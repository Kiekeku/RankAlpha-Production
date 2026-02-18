from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openai import OpenAI
from rapidfuzz import fuzz as rf_fuzz
from rapidfuzz import process as rf_process
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.common.src.ai.budget import Budget, BudgetLedger, get_redis_counter_from_env
from apps.common.src.ai.costing import preflight_estimate_cost, reconcile_cost
from apps.common.src.models import (
    DimNewsCluster,
    DimStock,
    FactNewsEvent,
    FactNewsImpact,
    FactNewsRaw,
)
from apps.common.src.news_utils.entity_map import map_entities_to_symbols

from .body_store import store_body_if_needed


@dataclass
class ImpactOut:
    stock_key: int
    role: str
    direction: str
    magnitude_score: float
    expected_return_pct: Optional[float]
    rationale: str


def _build_prompt(title: str, snippet: str, body: str, candidates: List[Dict[str, Any]]) -> str:
    cand_json = [
        {"stock_key": c["stock_key"], "symbol": c.get("symbol"), "role": c.get("role", "issuer")}
        for c in candidates
    ]
    return f"""
You are a market news analyst. Read the news and determine event type and directional impact.

Return strict JSON with keys: event_type, overall_direction (positive|negative|mixed|unclear),
overall_magnitude (0-100), timescale (immediate|near-term|long), summary (<= 2 lines),
impacts: list of items each with:
  - stock_key (preferred when provided in candidates), OR symbol (ticker) if you can derive it from the company name,
  - if symbol is unknown, include company_name and exchange (e.g., NASDAQ/NYSE/TSX) to aid mapping,
  - role (issuer|competitor|supplier|customer|index|sector),
  - direction (positive|negative|mixed|unclear),
  - magnitude (0-100),
  - expected_return_pct (optional),
  - rationale (<= 1 line).

Candidates are provided; reuse them when appropriate. It is allowed to add new impacted entities by deriving the ticker symbol from the news context.

Title: {title}\nSnippet: {snippet}\nBody: {body[:4000]}

Candidates: {cand_json}
"""


# Module-level shared ledger to persist RPM/daily counters across calls
_NEWSWIRE_LLM_LEDGER = BudgetLedger(
    service="newswire_llm", budget=Budget(), counter=get_redis_counter_from_env()
)


def analyze_event_cluster(db: Session, event_id) -> Dict[str, Any]:
    # Load centroid
    ev = db.get(FactNewsEvent, event_id)
    if not ev:
        return {"ok": False, "error": "event not found"}
    force_reanalyze = os.environ.get("NEWS_LLM_FORCE_REANALYZE", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    llm_ran_at = getattr(ev, "llm_ran_at", None)
    llm_response = getattr(ev, "llm_response", None)
    llm_error = getattr(ev, "llm_error", None)
    if (
        not force_reanalyze
        and llm_ran_at is not None
        and llm_response is not None
        and not (str(llm_error or "").strip())
    ):
        return {"ok": True, "skipped": "already_analyzed"}
    cl = db.get(DimNewsCluster, ev.cluster_id)
    if not cl or not cl.centroid_raw_id:
        return {"ok": False, "error": "cluster/centroid not found"}
    raw = db.get(FactNewsRaw, cl.centroid_raw_id)
    if not raw:
        return {"ok": False, "error": "raw not found"}

    if os.environ.get("NEWS_LLM_ENABLED", "true").lower() != "true":
        ev.llm_error = "disabled"
        ev.llm_ran_at = datetime.now(timezone.utc)
        db.flush()
        return {"ok": False, "error": "newswire_llm_disabled"}

    title = raw.title or ""
    snippet = raw.snippet or ""
    # Prefer stored body; otherwise fetch with shared body-store guardrails.
    body = (raw.body_text or "").strip()
    if not body:
        try:
            score = float(ev.materiality_score or 0.0) / 100.0
        except Exception:
            score = 0.0
        try:
            store_body_if_needed(
                db,
                raw_id=cl.centroid_raw_id,
                url=raw.url_canonical,
                prefilter_score=score,
            )
        except Exception:
            pass
        body = (raw.body_text or "").strip()

    # Candidate entities via local mapper
    candidates = map_entities_to_symbols(db, title, snippet)
    # enrich with symbols for prompt clarity
    sk_to_sym = {
        r.stock_key: r.symbol
        for r in db.execute(
            select(DimStock.stock_key, DimStock.symbol).where(
                DimStock.stock_key.in_([c["stock_key"] for c in candidates])
            )
        )
    }
    for c in candidates:
        c["symbol"] = sk_to_sym.get(c["stock_key"]) or None

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        ev.llm_error = "api_key_missing"
        ev.llm_ran_at = datetime.now(timezone.utc)
        db.flush()
        return {"ok": False, "error": "OPENAI_API_KEY missing"}
    if os.getenv("AI_DISABLE", "0").lower() in {"1", "true", "yes"}:
        ev.llm_error = "ai_disabled"
        ev.llm_ran_at = datetime.now(timezone.utc)
        db.flush()
        return {"ok": False, "error": "ai_disabled"}
    model = os.environ.get("NEWS_LLM_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    client = OpenAI(api_key=api_key)
    ledger = _NEWSWIRE_LLM_LEDGER

    prompt = _build_prompt(title, snippet, body, candidates)
    system_text = "You extract structured market impact from news."
    max_prompt_chars = int(os.environ.get("NEWS_LLM_PROMPT_MAX_CHARS", "20000"))
    ev.llm_prompt = prompt[:max_prompt_chars]
    ev.llm_model = model
    ev.llm_ran_at = datetime.now(timezone.utc)
    ev.llm_error = None
    ev.llm_tokens_prompt = None
    ev.llm_tokens_completion = None
    ev.llm_response = None
    # Preflight budget check (estimate); if exceeded, short-circuit
    # Optional dry-run: short-circuit BEFORE any budget reservation
    if os.getenv("AI_DRY_RUN", "0").lower() in {"1", "true", "yes"}:
        ev.llm_error = "dry_run"
        db.flush()
        return {"ok": True, "dry_run": True}
    # Preflight estimate + reservation (only for real calls)
    try:
        est_in, est_cost = preflight_estimate_cost(model, system_text, prompt)
        reservation = ledger.begin_call(tokens_estimate=est_in, cost_estimate_usd=est_cost)
    except Exception as e:
        ev.llm_error = f"budget_block: {e}"[:500]
        db.flush()
        return {"ok": False, "error": f"budget_block: {e}"}

    prompt_tokens_used = 0
    completion_tokens_used = 0
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_text},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=800,
        )
        content = resp.choices[0].message.content or "{}"
        # Reconcile usage/cost and commit
        usage = getattr(resp, "usage", None)
        usage_dict = {}
        if usage is not None:
            try:
                usage_dict = {
                    "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                }
            except Exception:
                usage_dict = {}
        ti, to, actual = reconcile_cost(
            model, {"usage": usage_dict, "text": content}, fallback_in=est_in
        )
        prompt_tokens_used = ti
        completion_tokens_used = to
        try:
            ledger.commit(ti, to, actual, reservation=reservation)
        except Exception:
            # Non-fatal (we already reserved); continue
            pass
    except Exception as e:
        ev.llm_error = f"openai_error: {e}"[:500]
        db.flush()
        return {"ok": False, "error": f"openai_error: {e}"}

    import json

    try:
        data = json.loads(content)
    except Exception:
        ev.llm_error = "invalid_json"
        ev.llm_tokens_prompt = prompt_tokens_used or None
        ev.llm_tokens_completion = completion_tokens_used or None
        ev.llm_response = None
        db.flush()
        return {"ok": False, "error": "invalid_json"}

    ev.llm_response = data
    ev.llm_tokens_prompt = prompt_tokens_used or None
    ev.llm_tokens_completion = completion_tokens_used or None
    ev.llm_error = None

    # Update event
    ev.event_type = str(data.get("event_type") or ev.event_type or "") or None
    ev.direction = str(data.get("overall_direction") or ev.direction or "") or None
    ev.timescale = str(data.get("timescale") or ev.timescale or "") or None
    if isinstance(data.get("overall_magnitude"), (int, float)):
        # Optional: override with LLM magnitude if present
        try:
            mg = float(data.get("overall_magnitude"))
            ev.materiality_score = max(ev.materiality_score or 0, min(100.0, max(0.0, mg)))
        except Exception:
            pass
    if isinstance(data.get("summary"), str) and data.get("summary"):
        ev.summary = data.get("summary")[:500]

    # Map impacts
    llm_imps = data.get("impacts") or []
    updated = 0
    inserted = 0
    for imp in llm_imps:
        sk = None
        # Prefer stock_key when provided
        if imp.get("stock_key") is not None:
            try:
                sk = int(imp.get("stock_key"))
            except Exception:
                sk = None
        # Fallback: resolve by symbol when provided
        if sk is None and imp.get("symbol"):
            sym = str(imp.get("symbol")).upper()
            r = db.query(DimStock).filter(DimStock.symbol == sym).one_or_none()
            if r is not None:
                sk = int(r.stock_key)
        # Fuzzy fallback: resolve by company name (US/CA universe) when provided
        if sk is None:
            cand_name = None
            for k in ("name", "company", "company_name"):
                if isinstance(imp.get(k), str) and imp.get(k).strip():
                    cand_name = imp.get(k).strip()
                    break
            if cand_name:
                # Load active US/CA stocks
                allowed_ex = [
                    s.strip().upper()
                    for s in os.environ.get(
                        "NEWS_LLM_ALLOWED_EXCHANGES",
                        "NASDAQ,NYSE,NYSEARCA,NYSE AMERICAN,OTC,TSX,TSXV,CSE,NEO",
                    ).split(",")
                    if s.strip()
                ]
                ex_hint = str(imp.get("exchange") or "").upper().strip()
                rows = db.query(DimStock).filter(DimStock.is_active == True).all()  # noqa: E712

                def _norm(s: str) -> str:
                    s = (s or "").lower()
                    s = re.sub(
                        r"\b(inc\.|incorporated|corp\.|corporation|ltd\.|ltd|plc|co\.|company)\b",
                        "",
                        s,
                    )
                    s = re.sub(r"[^a-z0-9 ]+", " ", s)
                    s = re.sub(r"\s+", " ", s).strip()
                    return s

                choices = []
                meta = []
                for row in rows:
                    ex = (row.exchange or "").upper()
                    # Restrict to allowed exchanges and honor any explicit LLM exchange hint
                    if ex and allowed_ex and not any(ex.startswith(p) for p in allowed_ex):
                        continue
                    if ex_hint and ex and not ex.startswith(ex_hint):
                        continue
                    nm = _norm(row.company_name or "")
                    if not nm:
                        continue
                    choices.append(nm)
                    meta.append(row)
                target = _norm(cand_name)
                if target and choices:
                    thr = int(os.environ.get("NEWS_LLM_FUZZY_SCORE", "88"))
                    match = rf_process.extractOne(target, choices, scorer=rf_fuzz.token_set_ratio)
                    if match and match[1] >= thr:  # score, index
                        idx = match[2]
                        sk = int(meta[idx].stock_key)
        if sk is None:
            continue
        dirn = str(imp.get("direction") or "unclear")
        mag = imp.get("magnitude")
        er = imp.get("expected_return_pct")
        rationale = str(imp.get("rationale") or "")
        role = str(imp.get("role") or "issuer")
        row = (
            db.query(FactNewsImpact)
            .filter(FactNewsImpact.event_id == ev.event_id, FactNewsImpact.stock_key == sk)
            .one_or_none()
        )
        if row is None:
            # Insert a new impact row when LLM adds a valid entity
            row = FactNewsImpact(
                event_id=ev.event_id,
                stock_key=sk,
                role=role,
                confidence=0.6,
            )
            db.add(row)
            inserted += 1
        row.direction = dirn
        try:
            if isinstance(mag, (int, float)):
                row.magnitude_score = float(mag)
        except Exception:
            pass
        try:
            if isinstance(er, (int, float)):
                row.expected_return_pct = float(er)
        except Exception:
            pass
        if rationale:
            row.rationale = rationale[:350]
        updated += 1

    db.flush()
    return {"ok": True, "updated_impacts": updated, "inserted_impacts": inserted}


def analyze_recent_events(db: Session, hours: int = 12, limit: int = 20) -> Dict[str, Any]:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import desc, func

    since = datetime.now(tz=timezone.utc) - timedelta(hours=abs(int(hours)))
    q = (
        db.query(FactNewsEvent)
        .join(DimNewsCluster, DimNewsCluster.cluster_id == FactNewsEvent.cluster_id)
        .join(FactNewsRaw, FactNewsRaw.raw_id == DimNewsCluster.centroid_raw_id)
        .filter(func.coalesce(FactNewsRaw.published_at, FactNewsRaw.first_seen_ts) >= since)
        .order_by(desc(FactNewsEvent.decided_at))
        .limit(limit)
    )
    evs = q.all()
    out = []
    for ev in evs:
        out.append(analyze_event_cluster(db, ev.event_id))
    return {"ok": True, "count": len(evs), "results": out}
