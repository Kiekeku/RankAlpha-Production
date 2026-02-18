from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import psycopg2
import requests  # type: ignore[import-untyped]
from mcp_agent.agents.agent import Agent
from mcp_agent.workflows.evaluator_optimizer.evaluator_optimizer import (
    QualityRating,
)
from mcp_agent.workflows.llm.augmented_llm import RequestParams
from mcp_agent.workflows.llm.augmented_llm_openai import OpenAIAugmentedLLM
from mcp_agent.workflows.orchestrator.orchestrator import Orchestrator

from apps.common.src.logging import get_logger
from apps.common.src.observability import capture_message
from apps.sentiment.src.settings import Settings as Settings

try:
    from prometheus_client import Counter  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Counter = None  # type: ignore

try:
    from .metrics import record_symbol_processed
except Exception:  # pragma: no cover - optional dependency / direct execution fallback
    try:
        from metrics import record_symbol_processed  # type: ignore
    except Exception:
        record_symbol_processed = None  # type: ignore

try:
    from . import paths as sentiment_paths
    from .persistence import extract_json_block, load_json_and_insert
except ImportError:  # pragma: no cover - direct execution fallback
    import paths as sentiment_paths
    from persistence import extract_json_block, load_json_and_insert

try:
    from llm.prompt_loader import load_prompt  # when working dir is sentiment package root
except ModuleNotFoundError:
    try:
        from apps.sentiment.llm.prompt_loader import load_prompt
    except ModuleNotFoundError:
        from apps.sentiment.src.llm.prompt_loader import load_prompt

try:
    from llm.gpt5_responses_planner_llm import Gpt5ResponsesPlannerLLM
except ModuleNotFoundError:
    try:
        from apps.sentiment.llm.gpt5_responses_planner_llm import Gpt5ResponsesPlannerLLM
    except ModuleNotFoundError:
        from apps.sentiment.src.llm.gpt5_responses_planner_llm import (
            Gpt5ResponsesPlannerLLM,
        )

try:
    from llm.evaluator_optimizer_llm import EvaluatorOptimizerLLMNoDup
except ModuleNotFoundError:
    try:
        from apps.sentiment.llm.evaluator_optimizer_llm import (
            EvaluatorOptimizerLLMNoDup,
        )
    except ModuleNotFoundError:
        from apps.sentiment.src.llm.evaluator_optimizer_llm import (
            EvaluatorOptimizerLLMNoDup,
        )


SENTIMENT_REPORTS = (
    Counter(
        "rankalpha_sentiment_reports_total",
        "Sentiment analysis reports grouped by status.",
        ["status"],
    )
    if Counter is not None
    else None
)
SENTIMENT_TOOL_CALLS = (
    Counter(
        "rankalpha_sentiment_tool_calls_total",
        "Sentiment MCP tool calls grouped by tool name and outcome.",
        ["tool", "outcome"],
    )
    if Counter is not None
    else None
)


def _emit_tool_usage_metrics(logger: logging.Logger) -> None:
    if SENTIMENT_TOOL_CALLS is None:
        return
    try:
        delta = Gpt5ResponsesPlannerLLM.consume_tool_usage_delta() or {}
    except Exception:
        return
    by_tool = delta.get("by_tool", {}) or {}
    by_tool_err = delta.get("by_tool_errors", {}) or {}
    for tool, cnt in by_tool.items():
        try:
            total = int(cnt or 0)
        except Exception:
            continue
        try:
            err = int(by_tool_err.get(tool, 0) or 0)
        except Exception:
            err = 0
        ok = max(total - err, 0)
        try:
            if ok:
                SENTIMENT_TOOL_CALLS.labels(tool=str(tool), outcome="ok").inc(ok)
            if err:
                SENTIMENT_TOOL_CALLS.labels(tool=str(tool), outcome="error").inc(err)
        except Exception:
            pass


def _is_valid_price(value: Any) -> bool:
    try:
        if value is None:
            return False
        if isinstance(value, str):
            s = value.strip().lower()
            if not s or s in {"na", "n/a", "nan", "null", "none", "0", "0.0"}:
                return False
            value = float(s)
        f = float(value)
        # Filter NaN/inf and non-positive values
        if not (f > 0.0):
            return False
        if f != f:  # NaN
            return False
        if f == float("inf") or f == float("-inf"):
            return False
        return True
    except Exception:
        return False


def _fmt_price(px: float) -> str:
    try:
        s = f"{float(px):.6f}".rstrip("0").rstrip(".")
        return s if s else str(px)
    except Exception:
        return str(px)


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _build_output_filename(company_name: str, symbol: str) -> str:
    """Build a collision-resistant report filename."""
    try:
        base = (company_name or "").strip().lower().replace(" ", "_")
        base = re.sub(r"[^a-z0-9_]+", "", base) or (symbol or "symbol").strip().lower()
    except Exception:
        base = (symbol or "symbol").strip().lower()
    sym_slug = re.sub(r"[^a-z0-9_]+", "", (symbol or "").strip().lower()) or "symbol"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    nonce = uuid.uuid4().hex[:8]
    return f"{base}_{sym_slug}_report_{timestamp}_{nonce}.md"


def _dedupe_bases(bases: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for b in bases:
        if not isinstance(b, str):
            continue
        bb = b.strip().rstrip("/")
        if not bb or bb in seen:
            continue
        seen.add(bb)
        out.append(bb)
    return out


def _broker_bases(settings: Settings) -> list[str]:
    bases: list[str] = []
    try:
        if getattr(settings, "sentiment_broker_base", None):
            bases.append(str(settings.sentiment_broker_base))
    except Exception:
        pass
    for env_key in ("SENTIMENT_BROKER_BASE", "BROKER_BASE_URL"):
        v = os.getenv(env_key)
        if v:
            bases.append(v)
    # Compose / local defaults
    bases.extend(
        ["http://broker:8000", "http://localhost:8000", "http://host.docker.internal:8000"]
    )
    return _dedupe_bases(bases)


def _api_bases(settings: Settings) -> list[str]:
    bases: list[str] = []
    try:
        if getattr(settings, "sentiment_api_base", None):
            bases.append(str(settings.sentiment_api_base))
    except Exception:
        pass
    v = os.getenv("SENTIMENT_API_BASE")
    if v:
        bases.append(v)
    # Compose / local defaults
    bases.extend(["http://api:6080", "http://localhost:6080", "http://host.docker.internal:6080"])
    return _dedupe_bases(bases)


def _lookup_company_name(symbol: str, settings: Settings) -> str | None:
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    conn = None
    cur = None
    try:
        conn = psycopg2.connect(
            database=settings.database_name,
            user=settings.db_username,
            password=settings.password,
            host=settings.host,
            port=settings.port,
            connect_timeout=10,
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT company_name FROM rankalpha.dim_stock WHERE symbol = %s AND is_active IS TRUE",
            (sym,),
        )
        row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
        return None
    except Exception:
        return None
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _serper_api_key(settings: Settings) -> str | None:
    try:
        key = (
            os.getenv("SERPER_API_KEY") or getattr(settings, "serper_api_key", None) or ""
        ).strip()
        return key or None
    except Exception:
        return None


def _analyst_targets_query(*, ticker: str, company_name: str) -> str:
    sym = (ticker or "").strip().upper()
    name = (company_name or "").strip()
    return f"{name} ({sym}) analyst consensus price target high low average"


def _serper_search_organic(
    query: str,
    *,
    api_key: str,
    logger: logging.Logger,
    timeout: tuple[float, float] = (2.0, 6.0),
) -> list[dict[str, Any]]:
    """Call Serper Search API and return only the 'organic' results array."""
    q = (query or "").strip()
    if not q:
        return []
    try:
        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        payload = {"q": q}
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code >= 400:
            logger.debug(
                "Serper analyst-target search failed: status=%s q=%s",
                resp.status_code,
                q[:200],
            )
            return []
        data = resp.json() if resp.content else {}
        organic = data.get("organic")
        if isinstance(organic, list):
            out: list[dict[str, Any]] = []
            for item in organic:
                if isinstance(item, dict):
                    out.append(item)
            return out
        return []
    except Exception as e:
        logger.debug("Serper analyst-target search error: %s", type(e).__name__)
        return []


def _looks_like_prompt_injection(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    needles = (
        "ignore previous",
        "disregard previous",
        "system prompt",
        "developer message",
        "you are chatgpt",
        "role:",
        "assistant:",
        "developer:",
        "system:",
        "user:",
        "tool:",
        "function call",
        "execute",
        "override",
        "jailbreak",
        "prompt injection",
    )
    return any(n in t for n in needles)


def _sanitize_untrusted_text(text: Any, *, max_len: int) -> str:
    """Sanitize untrusted web text to reduce prompt-injection surface area."""
    try:
        s = str(text or "")
    except Exception:
        return ""
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("```", "").replace("'''", "")
    s = re.sub(r"(?i)^(system|developer|assistant|user)\s*:\s*", "", s).strip()
    if _looks_like_prompt_injection(s):
        return "[redacted: untrusted content contained instruction-like text]"
    if max_len > 0 and len(s) > max_len:
        s = s[:max_len].rstrip() + "…"
    return s


def _extract_usd_amounts(text: str) -> list[float]:
    """Extract USD-ish amounts from text (best-effort) for numeric comparison."""
    t = text or ""
    if not t:
        return []
    # Prefer explicit currency markers to avoid capturing things like "5 years" or "10 analysts".
    matches: list[str] = []
    try:
        matches.extend(re.findall(r"(?i)\$\s*(\d{1,4}(?:,\d{3})*(?:\.\d+)?)", t))
        matches.extend(re.findall(r"(?i)usd\s*\$?\s*(\d{1,4}(?:,\d{3})*(?:\.\d+)?)", t))
        matches.extend(re.findall(r"(?i)(\d{1,4}(?:,\d{3})*(?:\.\d+)?)\s*usd\b", t))
        matches.extend(re.findall(r"(?i)us\$\s*(\d{1,4}(?:,\d{3})*(?:\.\d+)?)", t))
    except Exception:
        matches = []
    out: list[float] = []
    for m in matches:
        try:
            v = float(str(m).replace(",", ""))
            if v <= 1.0 or v >= 200_000.0:
                continue
            out.append(v)
        except Exception:
            continue
    deduped: list[float] = []
    seen: set[str] = set()
    for v in out:
        k = f"{v:.6f}"
        if k in seen:
            continue
        seen.add(k)
        deduped.append(v)
    return deduped[:12]


def _fetch_human_analyst_targets_context(
    *,
    ticker: str,
    company_name: str,
    settings: Settings,
    logger: logging.Logger,
    limit: int = 10,
) -> str:
    """Return a compact JSON array string of Serper 'organic' results for analyst targets."""
    api_key = _serper_api_key(settings)
    if not api_key:
        return "[]"
    sym = (ticker or "").strip().upper()
    name = (company_name or "").strip()
    q = _analyst_targets_query(ticker=sym, company_name=name)
    organic = _serper_search_organic(q, api_key=api_key, logger=logger)
    if limit and limit > 0:
        organic = organic[: int(limit)]
    # Keep only fields we use to reduce prompt length.
    slim: list[dict[str, Any]] = []
    for item in organic:
        try:
            pos = item.get("position")
            link_s = _sanitize_untrusted_text(item.get("link"), max_len=360)
            if link_s and not (link_s.startswith("http://") or link_s.startswith("https://")):
                link_s = ""
            title_s = _sanitize_untrusted_text(item.get("title"), max_len=220)
            snippet_s = _sanitize_untrusted_text(item.get("snippet"), max_len=520)
            date_s = _sanitize_untrusted_text(item.get("date"), max_len=64)
            amounts = _extract_usd_amounts(snippet_s)
            slim.append(
                {
                    "position": pos,
                    "title": title_s,
                    "link": link_s,
                    "snippet": snippet_s,
                    "date": date_s,
                    "amounts_usd": amounts,
                }
            )
        except Exception:
            continue
    try:
        if slim:
            preview = "; ".join(
                f"{(it.get('position') or '?')}: {(it.get('title') or '')[:60]}"
                for it in slim[:3]
                if isinstance(it, dict)
            )
            logger.debug("Serper analyst targets: organic_kept=%d preview=%s", len(slim), preview)
    except Exception:
        pass
    try:
        return json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "[]"


def _summarize_human_analyst_targets(
    organic_json: str, *, anchor_price: Any
) -> dict[str, Any] | None:
    """Compute simple stats from extracted `amounts_usd` for UI display."""
    anchor_f: float | None = None
    try:
        anchor_f = float(anchor_price) if anchor_price is not None else None
        if anchor_f is not None and not (anchor_f > 0.0):
            anchor_f = None
    except Exception:
        anchor_f = None
    try:
        parsed = json.loads(organic_json or "[]")
    except Exception:
        return None
    if not isinstance(parsed, list):
        return None
    amounts: list[float] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        vals = item.get("amounts_usd")
        if not isinstance(vals, list):
            continue
        for v in vals:
            try:
                amounts.append(float(v))
            except Exception:
                continue
    if not amounts:
        return None
    filtered = amounts
    if anchor_f is not None:
        lo_bound = anchor_f * 0.25
        hi_bound = anchor_f * 4.0
        candidate = [v for v in amounts if v >= lo_bound and v <= hi_bound]
        filtered = candidate if candidate else amounts
    if not filtered:
        return None
    uniq = sorted({round(v, 6) for v in filtered})
    n = len(uniq)
    if n <= 0:
        return None
    low = float(uniq[0])
    high = float(uniq[-1])
    mid = float(uniq[n // 2]) if (n % 2 == 1) else float((uniq[n // 2 - 1] + uniq[n // 2]) / 2.0)
    mean = float(sum(uniq) / n)
    return {
        "human_analyst_target_count": n,
        "human_analyst_target_low_usd": low,
        "human_analyst_target_high_usd": high,
        "human_analyst_target_median_usd": mid,
        "human_analyst_target_mean_usd": mean,
    }


def _prefetch_rankalpha_target_price(
    symbol: str,
    settings: Settings,
    *,
    logger: logging.Logger,
) -> float | None:
    """Fetch RankAlpha fundamentals target price via the API (best-effort).

    This is a fallback when Serper-derived analyst target parsing fails.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    api_timeout = float(getattr(settings, "sentiment_anchor_api_timeout_seconds", 12.0) or 12.0)
    api_timeout = max(api_timeout, 3.0)
    connect_timeout = min(2.0, api_timeout)
    for base in _api_bases(settings):
        url = f"{base}/api/v1/grading/asset/{sym}?days=1"
        try:
            resp = requests.get(
                url,
                timeout=(connect_timeout, api_timeout),
                headers={"Accept": "application/json"},
            )
            if resp.status_code >= 400:
                continue
            data = resp.json() if resp.content else {}
            if not isinstance(data, dict):
                continue
            tp = data.get("target_price")
            if _is_valid_price(tp):
                tp_f = float(tp)
                try:
                    logger.info(
                        "Prefetched target_price from RankAlpha API: symbol=%s target_price=%s base=%s",
                        sym,
                        tp_f,
                        base,
                    )
                except Exception:
                    pass
                return tp_f
        except Exception:
            continue
    return None


def _prefetch_anchor(
    symbol: str,
    settings: Settings,
    *,
    logger: logging.Logger,
) -> tuple[float, str, str, str] | None:
    """Return (anchor_price, anchor_timestamp_utc, anchor_source, anchor_price_date).

    Strategy:
    1) Broker live price (last) via /price/{symbol}
    2) RankAlpha API previous close via /api/v1/prices/latest (adj_close_px preferred)

    Returns None when no usable price was found.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return None

    # 1) Broker (live)
    broker_token = (
        os.getenv("BROKER_SERVICE_TOKEN") or os.getenv("AUTH_SERVICE_TOKEN") or ""
    ).strip()
    broker_headers = {"X-RA-Service-Token": broker_token} if broker_token else None
    for base in _broker_bases(settings):
        url = f"{base}/price/{sym}"
        try:
            resp = requests.get(url, timeout=(1.5, 3.0), headers=broker_headers)
            if resp.status_code >= 400:
                continue
            data = resp.json() if resp.content else {}
            last = data.get("last")
            if _is_valid_price(last):
                last_f = float(last)
                ts = _iso_utc_now()
                price_date = ts.split("T", 1)[0]
                logger.info(
                    "Prefetched live price from broker: symbol=%s price=%s base=%s",
                    sym,
                    last_f,
                    base,
                )
                return last_f, ts, "broker_last", price_date
        except Exception:
            continue

    # 2) yfinance (live-ish fallback) - best-effort and optional dependency.
    try:
        import yfinance as yf  # type: ignore

        try:
            t = yf.Ticker(sym)
            # Try fast_info first (less heavy), then info.
            px_val = None
            try:
                fi = getattr(t, "fast_info", None) or {}
                if isinstance(fi, dict):
                    px_val = (
                        fi.get("lastPrice") or fi.get("last_price") or fi.get("regularMarketPrice")
                    )
            except Exception:
                px_val = None
            if px_val is None:
                try:
                    inf = getattr(t, "info", None) or {}
                    if isinstance(inf, dict):
                        px_val = inf.get("regularMarketPrice") or inf.get("currentPrice")
                except Exception:
                    px_val = None
            if _is_valid_price(px_val):
                px = float(px_val)
                ts = _iso_utc_now()
                price_date = ts.split("T", 1)[0]
                logger.info("Prefetched price from yfinance: symbol=%s price=%s", sym, px)
                return px, ts, "yfinance_last", price_date
        except Exception:
            pass
    except Exception:
        # yfinance is optional; ignore if missing or broken
        pass

    # 2) RankAlpha API (previous close)
    api_timeout = float(getattr(settings, "sentiment_anchor_api_timeout_seconds", 12.0) or 12.0)
    api_timeout = max(api_timeout, 3.0)
    connect_timeout = min(2.0, api_timeout)
    for base in _api_bases(settings):
        url = f"{base}/api/v1/prices/latest?symbol={sym}"
        try:
            resp = requests.get(
                url,
                timeout=(connect_timeout, api_timeout),
                headers={"Accept": "application/json"},
            )
            if resp.status_code >= 400:
                continue
            data = resp.json() if resp.content else {}
            items = data.get("items")
            if not isinstance(items, list) or not items:
                continue
            it0 = items[0] if isinstance(items[0], dict) else {}
            if not isinstance(it0, dict):
                continue
            price_date = str(it0.get("price_date") or "").strip()
            adj = it0.get("adj_close_px")
            close = it0.get("close_px")
            px = None
            src = None
            if _is_valid_price(adj):
                px = float(adj)
                src = "rankalpha_api_adj_close"
            elif _is_valid_price(close):
                px = float(close)
                src = "rankalpha_api_close"
            if px is None or src is None:
                continue
            # Use a date-only timestamp when we only have an EOD date.
            ts = f"{price_date}T00:00:00Z" if price_date else _iso_utc_now()
            price_date_out = price_date or ts.split("T", 1)[0]
            logger.info(
                "Prefetched close price from RankAlpha API: symbol=%s price=%s price_date=%s base=%s",
                sym,
                px,
                price_date_out,
                base,
            )
            return px, ts, src, price_date_out
        except Exception:
            continue

    return None


def build_request_params(model_choice: str, settings: Settings) -> RequestParams:
    """Build RequestParams for mcp-agent with the selected model.

    Notes:
    - mcp-agent's `RequestParams` uses camelCase fields (e.g., `maxTokens`).
    - The OpenAI adapter maps `maxTokens` to `max_completion_tokens` for reasoning
      models (o1/o3/o4/gpt-5) and to `max_tokens` for others.
    - We always set `model` explicitly so the planner and workers don't fallback
      to a provider-selected default (which can be `o3`).
    """

    # Decide an optional token limit in the unified `maxTokens` field.
    max_tokens_unified: int | None = None
    if model_choice.lower().startswith("gpt-5"):
        if settings.openai_max_completion_tokens is not None:
            max_tokens_unified = int(settings.openai_max_completion_tokens)
    else:
        if settings.openai_max_tokens is not None:
            max_tokens_unified = int(settings.openai_max_tokens)

    if max_tokens_unified is not None:
        return RequestParams(model=model_choice, maxTokens=max_tokens_unified)
    else:
        # At minimum, set the model so selection never falls back to o3.
        return RequestParams(model=model_choice)


async def _monitor_report_and_cancel(
    *,
    output_path: str,
    timeout_seconds: int,
    orchestrator_task: asyncio.Task,
    logger: logging.Logger,
) -> bool:
    """Watch for a valid fenced-JSON report, then cancel the orchestrator.

    Returns True if a valid report was detected within the timeout; False otherwise.
    """
    start = time.monotonic()
    last_error: str | None = None
    while (time.monotonic() - start) < max(1, int(timeout_seconds)):
        if orchestrator_task.done():
            return False
        try:
            if os.path.exists(output_path) and os.path.isfile(output_path):
                try:
                    if os.path.getsize(output_path) < 1000:
                        await asyncio.sleep(0.5)
                        continue
                except Exception:
                    pass
                try:
                    with open(output_path, "r", encoding="utf-8") as f:
                        raw = f.read()
                    json_str = extract_json_block(raw)
                    _ = json.loads(json_str)
                    logger.info(
                        f"Detected valid report at {output_path}; cancelling orchestrator early"
                    )
                    with contextlib.suppress(Exception):
                        orchestrator_task.cancel()
                    return True
                except Exception as e:
                    last_error = str(e)
        except Exception:
            pass
        await asyncio.sleep(0.5)
    if last_error:
        logger.debug(f"Report monitor timed out; last validation error: {last_error}")
    return False


async def ai_analysis(
    company_name,
    analyzer_app,
    symbol: str | None = None,
    *,
    news_title: str | None = None,
    news_url: str | None = None,
    trigger: str = "schedule",
):
    """Run a full AI analysis workflow for a given company/symbol.

    Optional keyword arguments `news_title` and `news_url` are accepted when the
    analysis is triggered from a news-driven queue. They are currently used for
    logging/traceability and are otherwise non-functional hints. The parameters
    are keyword-only to avoid accidental positional misuse.
    """
    logger = get_logger(__name__)
    settings = Settings()

    sym = (symbol or "").strip().upper()
    if not sym:
        logger.warning("Skipping analysis: symbol is required to prefetch an anchor price")
        if record_symbol_processed is not None:
            record_symbol_processed(outcome="skipped", trigger=trigger)
        return False

    # Resolve company name from DB for consistent prompt context.
    company_name_db = (company_name or "").strip() if isinstance(company_name, str) else ""
    if not company_name_db:
        company_name_db = (await asyncio.to_thread(_lookup_company_name, sym, settings)) or sym

    # Prefetch anchor price (broker live last -> RankAlpha API close). If missing, skip analysis.
    anchor = await asyncio.to_thread(_prefetch_anchor, sym, settings, logger=logger)
    if not anchor:
        logger.warning("Skipping analysis: could not prefetch anchor price for %s", sym)
        if record_symbol_processed is not None:
            record_symbol_processed(outcome="skipped", trigger=trigger)
        return False
    anchor_price, anchor_ts_utc, anchor_source, anchor_price_date = anchor

    os.makedirs(sentiment_paths.OUTPUT_DIR, exist_ok=True, mode=0o777)
    safe_company_name = company_name_db.strip() or sym
    output_file = _build_output_filename(safe_company_name, sym)
    output_path = os.path.join(sentiment_paths.OUTPUT_DIR, output_file)

    # Include originating news context if provided for traceability in logs
    if news_title or news_url:
        get_logger(__name__).info(
            "News-triggered analysis: title=%r url=%s", news_title, (news_url or "")
        )
    logger.info(
        "Preparing analysis for %s (%s) anchor=%s source=%s ts=%s → output: %s",
        safe_company_name,
        sym,
        _fmt_price(anchor_price),
        anchor_source,
        anchor_ts_utc,
        output_path,
    )

    analyst_targets_organic_json = "[]"
    analyst_targets_query_text: str | None = None
    analyst_targets_summary: dict[str, Any] | None = None
    try:
        if bool(getattr(settings, "sentiment_use_serper_analyst_targets", False)):
            limit = int(getattr(settings, "sentiment_serper_analyst_targets_limit", 10) or 10)
            analyst_targets_organic_json = await asyncio.to_thread(
                _fetch_human_analyst_targets_context,
                ticker=sym,
                company_name=safe_company_name,
                settings=settings,
                logger=logger,
                limit=limit,
            )
            analyst_targets_query_text = _analyst_targets_query(
                ticker=sym, company_name=safe_company_name
            )
            analyst_targets_summary = _summarize_human_analyst_targets(
                analyst_targets_organic_json, anchor_price=anchor_price
            )
    except Exception:
        analyst_targets_organic_json = "[]"
    try:
        if analyst_targets_organic_json and analyst_targets_organic_json != "[]":
            logger.debug("Serper analyst targets: injected organic results into prompt context")
    except Exception:
        pass

    prompt_analyst_targets_summary = analyst_targets_summary

    # Fallback: if Serper enrichment is enabled but parsing failed, use RankAlpha DB-backed target_price.
    try:
        if bool(getattr(settings, "sentiment_use_serper_analyst_targets", False)) and (
            not prompt_analyst_targets_summary
        ):
            tp_fallback = await asyncio.to_thread(
                _prefetch_rankalpha_target_price,
                sym,
                settings,
                logger=logger,
            )
            if tp_fallback is not None:
                prompt_analyst_targets_summary = {
                    "human_analyst_target_count": None,
                    "human_analyst_target_low_usd": None,
                    "human_analyst_target_high_usd": None,
                    "human_analyst_target_median_usd": float(tp_fallback),
                    "human_analyst_target_mean_usd": float(tp_fallback),
                }
                logger.info(
                    "Using RankAlpha target_price fallback for analyst targets: symbol=%s target_price=%s",
                    sym,
                    tp_fallback,
                )
    except Exception:
        pass

    analyst_targets_summary_json = "null"
    analyst_target_count_s = "null"
    analyst_target_low_s = "null"
    analyst_target_median_s = "null"
    analyst_target_high_s = "null"
    analyst_target_mean_s = "null"
    try:
        if isinstance(prompt_analyst_targets_summary, dict) and prompt_analyst_targets_summary:
            count_raw = prompt_analyst_targets_summary.get("human_analyst_target_count")
            count_i = int(count_raw) if count_raw is not None else None
            low_f = (
                float(prompt_analyst_targets_summary["human_analyst_target_low_usd"])
                if prompt_analyst_targets_summary.get("human_analyst_target_low_usd") is not None
                else None
            )
            median_f = (
                float(prompt_analyst_targets_summary["human_analyst_target_median_usd"])
                if prompt_analyst_targets_summary.get("human_analyst_target_median_usd") is not None
                else None
            )
            high_f = (
                float(prompt_analyst_targets_summary["human_analyst_target_high_usd"])
                if prompt_analyst_targets_summary.get("human_analyst_target_high_usd") is not None
                else None
            )
            mean_f = (
                float(prompt_analyst_targets_summary["human_analyst_target_mean_usd"])
                if prompt_analyst_targets_summary.get("human_analyst_target_mean_usd") is not None
                else None
            )

            analyst_target_count_s = (
                str(count_i) if (count_i is not None and count_i > 0) else "null"
            )
            analyst_target_low_s = _fmt_price(low_f) if low_f is not None else "null"
            analyst_target_median_s = _fmt_price(median_f) if median_f is not None else "null"
            analyst_target_high_s = _fmt_price(high_f) if high_f is not None else "null"
            analyst_target_mean_s = _fmt_price(mean_f) if mean_f is not None else "null"

            analyst_targets_summary_json = json.dumps(
                {
                    "count": count_i,
                    "low_usd": low_f,
                    "median_usd": median_f,
                    "high_usd": high_f,
                    "mean_usd": mean_f,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
    except Exception:
        analyst_targets_summary_json = "null"

    # Use the shared analyzer_app instance passed from the main function
    try:
        context = analyzer_app.context
        # Load settings to source env-backed values
        openai_key = settings.openai_api_key
        if openai_key:
            try:
                # Preserve existing OpenAI config (e.g., default_model) and just set api_key
                if isinstance(context.config.openai, dict):
                    context.config.openai["api_key"] = openai_key
                else:
                    setattr(context.config.openai, "api_key", openai_key)
            except Exception:
                # Fallback to dict if structure isn't present
                context.config.openai = {"api_key": openai_key}
        else:
            logger.warning("OPENAI_API_KEY not found in environment.")

        # Ensure model override from environment is reflected in the MCP context config
        env_model = settings.openai_model
        try:
            current_default = (
                context.config.openai.get("default_model")
                if isinstance(context.config.openai, dict)
                else getattr(context.config.openai, "default_model", None)
            )
        except Exception:
            current_default = None

        if env_model and env_model != current_default:
            try:
                if isinstance(context.config.openai, dict):
                    context.config.openai["default_model"] = env_model
                else:
                    setattr(context.config.openai, "default_model", env_model)
                logger.info(f"Overriding config default model to '{env_model}' from OPENAI_MODEL")
            except Exception as e:
                logger.warning(f"Could not set default model in context: {e}")

        # Optionally disable or override reasoning effort to avoid fallback to o3
        disable_reasoning = bool(settings.openai_disable_reasoning)
        override_effort = settings.openai_reasoning_effort  # low | medium | high
        try:
            if disable_reasoning:
                # Remove the reasoning_effort field entirely to avoid client fallback to reasoning models
                if isinstance(context.config.openai, dict):
                    context.config.openai.pop("reasoning_effort", None)
                else:
                    try:
                        delattr(context.config.openai, "reasoning_effort")
                    except Exception:
                        pass
                logger.info(
                    "Reasoning disabled via OPENAI_DISABLE_REASONING=1 (removed reasoning_effort from config)"
                )
            elif override_effort:
                if override_effort not in {"low", "medium", "high"}:
                    logger.warning(
                        f"Ignoring invalid OPENAI_REASONING_EFFORT='{override_effort}'. Use low|medium|high."
                    )
                else:
                    if isinstance(context.config.openai, dict):
                        context.config.openai["reasoning_effort"] = override_effort
                    else:
                        setattr(context.config.openai, "reasoning_effort", override_effort)
                    logger.info(
                        f"Reasoning effort set to '{override_effort}' via OPENAI_REASONING_EFFORT"
                    )
        except Exception as e:
            logger.warning(f"Could not adjust reasoning settings: {e}")
        # Log the effective default after any override
        try:
            effective_default = (
                context.config.openai.get("default_model")
                if isinstance(context.config.openai, dict)
                else getattr(context.config.openai, "default_model", None)
            )
            logger.info(f"Effective default model in context: '{effective_default}'")
            try:
                effective_effort = (
                    context.config.openai.get("reasoning_effort")
                    if isinstance(context.config.openai, dict)
                    else getattr(context.config.openai, "reasoning_effort", None)
                )
                logger.info(f"Effective reasoning_effort in context: '{effective_effort}'")
            except Exception:
                pass
        except Exception:
            pass

        if "filesystem" in context.config.mcp.servers:
            # Ensure the filesystem server has access to the OUTPUT_DIR
            try:
                context.config.mcp.servers["filesystem"].args.extend(
                    [sentiment_paths.OUTPUT_DIR, os.getcwd()]
                )
                logger.info(
                    "Filesystem server configured with access to %s",
                    sentiment_paths.OUTPUT_DIR,
                )
            except Exception:
                pass
        else:
            # Fallback: dynamically register filesystem server with safe roots
            try:
                context.config.mcp.servers["filesystem"] = {  # type: ignore[index]
                    "command": "npx",
                    "args": [
                        "-y",
                        "@modelcontextprotocol/server-filesystem",
                        sentiment_paths.OUTPUT_DIR,
                        os.getcwd(),
                    ],
                }
                logger.info("Dynamically registered filesystem MCP with OUTPUT_DIR and CWD roots")
            except Exception:
                logger.warning("Filesystem server not configured - report saving may fail")

        # Prefer 'serper' search provider if configured; fall back to 'g-search'
        servers_cfg = getattr(context.config.mcp, "servers", {})
        has_serper = "serper" in servers_cfg
        has_gsearch = "g-search" in servers_cfg
        if not (has_serper or has_gsearch):
            # Dynamically register a search MCP if config isn't discovered
            serper_key = os.getenv("SERPER_API_KEY") or str(
                getattr(Settings(), "serper_api_key", "") or ""
            )
            if serper_key:
                try:
                    context.config.mcp.servers["serper"] = {  # type: ignore[index]
                        "command": "uvx",
                        "args": ["serper-mcp-server"],
                        "env": {"SERPER_API_KEY": serper_key},
                    }
                    has_serper = True
                    logger.info("Dynamically registered Serper MCP via uvx serper-mcp-server")
                    try:
                        logger.info(
                            "Serper MCP (dynamic): key present=%s length=%d",
                            "yes" if len(serper_key) > 0 else "no",
                            len(serper_key),
                        )
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning(f"Could not register Serper MCP dynamically: {e}")
            if not has_serper:
                try:
                    context.config.mcp.servers["g-search"] = {  # type: ignore[index]
                        "command": "npx",
                        "args": ["-y", "g-search-mcp"],
                    }
                    has_gsearch = True
                    logger.info("Dynamically registered g-search MCP via npx g-search-mcp")
                except Exception as e:
                    logger.warning(f"Could not register g-search MCP dynamically: {e}")

            servers_cfg = getattr(context.config.mcp, "servers", {})

        logger.info(
            f"Search MCP discovery: serper={'yes' if has_serper else 'no'}, g-search={'yes' if has_gsearch else 'no'}"
        )
        if not (has_serper or has_gsearch):
            logger.warning(
                "No search MCP found. Configure 'serper' (preferred) or 'g-search' in mcp_agent.config.yaml"
            )
            logger.info("Examples: serper via uvx serper-mcp-server; g-search via npx g-search-mcp")
            return False

        # Ensure core servers exist
        for srv in ("fetch", "yfinance", "edgar"):
            if srv not in servers_cfg:
                context.config.mcp.servers[srv] = SimpleNamespace(args=[])
                logger.info(f"Registered missing MCP server '{srv}'")

        # Determine search server order: serper first if present, then g-search
        search_servers = [s for s in (["serper", "g-search"]) if s in servers_cfg]
        try:
            logger.info(f"Search order for research_agent: {search_servers}")
        except Exception:
            pass

        replacements_base: dict[str, str] = {
            "COMPANY_NAME": safe_company_name,
            "OUTPUT_PATH": output_path,
            "TICKER": sym,
            "ANCHOR_PRICE": _fmt_price(anchor_price),
            "ANCHOR_TIMESTAMP_UTC": anchor_ts_utc,
            "ANCHOR_SOURCE": anchor_source,
            "ANCHOR_PRICE_DATE": anchor_price_date,
            "ANALYST_TARGETS_ORGANIC": analyst_targets_organic_json,
            "ANALYST_TARGETS_SUMMARY_JSON": analyst_targets_summary_json,
            "ANALYST_TARGET_COUNT": analyst_target_count_s,
            "ANALYST_TARGET_LOW_USD": analyst_target_low_s,
            "ANALYST_TARGET_MEDIAN_USD": analyst_target_median_s,
            "ANALYST_TARGET_HIGH_USD": analyst_target_high_s,
            "ANALYST_TARGET_MEAN_USD": analyst_target_mean_s,
        }

        # Lean schema is the standard output format for this service.
        finder_prompt = "search_finder_lean"
        research_agent = Agent(
            name="search_finder",
            instruction=load_prompt(finder_prompt, replacements_base),
            server_names=search_servers + ["fetch", "yfinance", "edgar"],
        )

        # Log Serper tool discovery and planned allowlist (general + news) before orchestration
        try:
            if "serper" in search_servers:
                tools_result = await research_agent.list_tools(server_name="serper")
                serper_tool_names = sorted(
                    [getattr(t, "name", "") for t in getattr(tools_result, "tools", []) or []]
                )
                logger.info(
                    "Serper MCP tools discovered (%d): %s",
                    len(serper_tool_names),
                    ", ".join(serper_tool_names),
                )
                allow_suffixes = {"google_search", "google_search_news"}
                allowed = sorted(
                    [n for n in serper_tool_names if any(n.endswith(suf) for suf in allow_suffixes)]
                )
                pruned = sorted(set(serper_tool_names) - set(allowed))
                logger.info(
                    "Serper MCP tools allowed (%d): %s",
                    len(allowed),
                    ", ".join(allowed) if allowed else "(none)",
                )
                if pruned:
                    logger.info(
                        "Serper MCP tools pruned (%d): %s",
                        len(pruned),
                        ", ".join(pruned),
                    )
        except Exception as e:
            logger.warning(f"Serper tool discovery/logging failed: {e}")

        # Log yfinance (Yahoo Finance MCP) tool discovery for visibility
        try:
            if "yfinance" in servers_cfg:
                yf_tools = await research_agent.list_tools(server_name="yfinance")
                yf_tool_names = sorted(
                    [getattr(t, "name", "") for t in getattr(yf_tools, "tools", []) or []]
                )
                logger.info(
                    "yfinance MCP tools discovered (%d): %s",
                    len(yf_tool_names),
                    ", ".join(yf_tool_names),
                )
                logger.info(
                    "Guidance: use yfinance for quotes/OHLCV only; EDGAR remains authoritative for statements."
                )
        except Exception as e:
            logger.warning(f"yfinance tool discovery/logging failed: {e}")

        # Research evaluator: Evaluates the quality of Lean JSON
        evaluator_prompt = "research_evaluator_lean"
        research_evaluator = Agent(
            name="research_evaluator",
            instruction=load_prompt(evaluator_prompt, replacements_base),
        )

        # Resolve model preference early: ENV overrides config
        configured_model = None
        try:
            if isinstance(context.config.openai, dict):
                configured_model = context.config.openai.get("default_model")
            else:
                configured_model = getattr(context.config.openai, "default_model", None)
        except Exception:
            configured_model = None

        model_choice = settings.openai_model or configured_model
        if not model_choice:
            logger.error(
                "No OpenAI model configured. Set OPENAI_MODEL or openai.default_model in apps/sentiment/src/mcp_agent.config.yaml"
            )
            return False

        # Custom factory to ensure 'gpt-5*' is treated as reasoning in older mcp-agent versions
        def llm_factory(agent: Agent) -> OpenAIAugmentedLLM:
            # For GPT‑5 family, prefer a hybrid approach: use a stable planner model while keeping GPT‑5 for workers
            is_gpt5 = str(model_choice).lower().startswith("gpt-5")
            name_val = getattr(agent, "name", "") or ""
            is_planner = bool(
                agent and (name_val == "LLM Orchestration Planner" or "planner" in name_val.lower())
            )

            # Strengthen planner instruction regardless of model to avoid human-ask tasks
            if agent and is_planner:
                planner_instruction = """
                    You are an expert planner. Given an objective task and a list of available Agents and MCP servers,
                    break the objective into strictly actionable steps and parallelizable subtasks. Never ask the user
                    for input and never include tasks that request human guidance. Only use the provided Agents and their
                    servers to accomplish the goal. Do not restate or copy any agent's instruction text (e.g., data
                    collection checklists or rating criteria) into task descriptions; keep tasks concise and refer only
                    to the agent names.

                    PLANNING RULES:
                    - Always produce exactly three steps in this order: (1) research_quality_controller, (2) financial_analyst, (3) report_writer.
                    - In your first plan output, set is_complete=false so the orchestrator executes these steps.
                    - On subsequent planning iterations, inspect the provided plan_result and step_results. If all three steps have already been executed and the report_writer step returned a confirmation line that begins with 'SAVED:', then return steps=[] and set is_complete=true. Do not repeat previously executed steps.
                    - Do not add any extra steps, loops, or ask for human input.

                    Produce valid JSON as specified by the schema without any extra text.
                    """
                agent = Agent(name=agent.name, instruction=planner_instruction)

            if is_gpt5:
                # Use Responses API with tool bridging for all GPT‑5 agents (planner and workers)
                chosen_model = (
                    settings.openai_planner_model
                    if is_planner and settings.openai_planner_model
                    else model_choice
                )
                llm = Gpt5ResponsesPlannerLLM(agent=agent)
                if llm.default_request_params:
                    llm.default_request_params.model = chosen_model
                else:
                    llm.default_request_params = RequestParams(model=chosen_model)
                try:
                    logging.getLogger(__name__).info(
                        f"LLM selection: agent={getattr(agent, 'name', 'unknown')} model={chosen_model} wrapper=Gpt5ResponsesPlannerLLM"
                    )
                except Exception:
                    pass
            else:
                llm = OpenAIAugmentedLLM(agent=agent)
                try:
                    logging.getLogger(__name__).info(
                        f"LLM selection: agent={getattr(agent, 'name', 'unknown')} model={model_choice} wrapper=OpenAIAugmentedLLM"
                    )
                except Exception:
                    pass
            # Force recognition of gpt-5* as reasoning models if the installed mcp-agent is older
            try:
                llm._reasoning = lambda m: bool(
                    m
                    and (
                        str(m).startswith(("o1", "o3", "o4")) or str(m).lower().startswith("gpt-5")
                    )
                )
            except Exception:
                pass
            # Ensure default model matches the env/config so components that don't get explicit
            # RequestParams still use the correct model
            try:
                if llm.default_request_params:
                    # Preserve planner model override when configured.
                    if not is_gpt5:
                        llm.default_request_params.model = model_choice
                    # For GPT‑5, avoid sending systemPrompt entirely; we use a developer message instead
                    if is_gpt5 and hasattr(llm.default_request_params, "systemPrompt"):
                        llm.default_request_params.systemPrompt = None  # type: ignore[attr-defined]
                else:
                    llm.default_request_params = RequestParams(model=model_choice)
            except Exception:
                pass
            return llm

        # Create the research EvaluatorOptimizerLLM component (no duplicate criteria in user prompts)
        research_quality_controller = EvaluatorOptimizerLLMNoDup(
            optimizer=research_agent,
            evaluator=research_evaluator,
            llm_factory=llm_factory,
            min_rating=QualityRating.EXCELLENT,
        )
        # Ensure a stable, schema-friendly name (no hyphens) for planner validation
        try:
            setattr(research_quality_controller, "name", "research_quality_controller")
        except Exception:
            pass

        # Analyst/Writer agents: lean prompts only
        try:
            logger.info("Using LEAN prompts for analyst and report writer")
        except Exception:
            pass
        analyst_prompt = "financial_analyst_lean"
        writer_prompt = "report_writer_lean"

        analyst_agent = Agent(
            name="financial_analyst",
            instruction=load_prompt(analyst_prompt, replacements_base),
            # Include filesystem to allow direct save in fallback flows if the model chooses
            server_names=["fetch", "yfinance", "edgar", "filesystem"],
        )

        report_writer = Agent(
            name="report_writer",
            instruction=load_prompt(writer_prompt, replacements_base),
            server_names=["filesystem"],
        )

        # --- CREATE THE ORCHESTRATOR ---
        logger.info(f"Initializing stock analysis workflow for {safe_company_name}")

        orchestrator = Orchestrator(
            llm_factory=llm_factory,
            available_agents=[
                research_quality_controller,
                analyst_agent,
                report_writer,
            ],
            plan_type="full",
        )

        # Define the task for the orchestrator (lean only)
        task_prompt = "orchestrator_task_lean"
        task = load_prompt(task_prompt, replacements_base)
        source = "env" if settings.openai_model else "config"
        logger.info(f"Using LLM model '{model_choice}' (source: {source})")
        if symbol:
            logger.info(f"Processing symbol {symbol} using model '{model_choice}'")
        else:
            logger.info(f"Processing company {safe_company_name} using model '{model_choice}'")

        # Run the orchestrator
        logger.info(f"Starting analysis workflow for {safe_company_name}")

        # Build request params with correct token field based on model
        req_params = build_request_params(model_choice, settings)
        # Add a small debug log of token field if set
        token_field = (
            "max_completion_tokens" if model_choice.lower().startswith("gpt-5") else "max_tokens"
        )
        token_val = (
            settings.openai_max_completion_tokens
            if model_choice.lower().startswith("gpt-5")
            else settings.openai_max_tokens
        )
        if token_val is not None:
            logger.info(f"Token limit: {token_field}={token_val}")

        orchestrator_timeout = int(getattr(settings, "sentiment_orchestrator_timeout_seconds", 600))
        orc_text: str | None = None
        # Run orchestrator + monitor concurrently, allowing early stop when the report is saved
        orch_task = asyncio.create_task(
            orchestrator.generate_str(message=task, request_params=req_params)
        )
        monitor_task = asyncio.create_task(
            _monitor_report_and_cancel(
                output_path=output_path,
                timeout_seconds=orchestrator_timeout,
                orchestrator_task=orch_task,
                logger=logger,
            )
        )
        try:
            orc_text = await asyncio.wait_for(orch_task, timeout=orchestrator_timeout)
        except asyncio.CancelledError:
            # Likely cancelled by the monitor after a valid report write
            try:
                if not monitor_task.done():
                    await monitor_task
            except Exception:
                pass
            orc_text = None
        except asyncio.TimeoutError:
            # Do not retry here; propagate timeout so callers can decide policy
            logger.warning(
                f"Orchestrator timed out after {orchestrator_timeout}s; aborting analysis without retry."
            )
            with contextlib.suppress(Exception):
                monitor_task.cancel()
            raise
        finally:
            # Ensure the monitor task is cleaned up
            if not monitor_task.done():
                with contextlib.suppress(Exception):
                    monitor_task.cancel()
                    await monitor_task

        # Check if report was successfully created
        # Best-effort fallback: only write if the orchestrator returned a valid fenced JSON block
        if (not os.path.exists(output_path)) and isinstance(orc_text, str) and orc_text.strip():
            try:
                _ = extract_json_block(orc_text)
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(orc_text)
                logger.info(f"Report created via fallback write from fenced JSON: {output_path}")
            except Exception:
                # No valid JSON block -> skip fallback to avoid empty files
                pass

        if os.path.exists(output_path):
            logger.info(f"Report successfully generated: {output_path}")
            extra: dict[str, Any] = {}
            try:
                if analyst_targets_organic_json and analyst_targets_organic_json != "[]":
                    extra["human_analyst_targets_provider"] = "serper"
                    extra["human_analyst_targets_query"] = analyst_targets_query_text
                    extra["human_analyst_targets_organic"] = analyst_targets_organic_json
                    if isinstance(analyst_targets_summary, dict):
                        extra.update(analyst_targets_summary)
            except Exception:
                extra = {}
            load_json_and_insert(output_path, extra=extra or None)
            # Log tool usage summary (GPT‑5 Responses wrapper aggregates counts per process)
            try:
                Gpt5ResponsesPlannerLLM.log_tool_usage_summary(logger=logger, reset=False)
            except Exception:
                pass
            try:
                _emit_tool_usage_metrics(logger)
            except Exception:
                pass
            if SENTIMENT_REPORTS is not None:
                try:
                    SENTIMENT_REPORTS.labels(status="success").inc()
                except Exception:
                    pass
            if record_symbol_processed is not None:
                record_symbol_processed(outcome="success", trigger=trigger)
            logger.info("Finished analysis")
            return True
        else:
            logger.error(f"Failed to create report at {output_path}")
            # Emit tool-usage summary even on failure for observability
            try:
                Gpt5ResponsesPlannerLLM.log_tool_usage_summary(logger=logger, reset=False)
            except Exception:
                pass
            try:
                _emit_tool_usage_metrics(logger)
            except Exception:
                pass
            if SENTIMENT_REPORTS is not None:
                try:
                    SENTIMENT_REPORTS.labels(status="error").inc()
                except Exception:
                    pass
            if record_symbol_processed is not None:
                record_symbol_processed(outcome="error", trigger=trigger)
            capture_message(
                "rankalpha-sentiment: report generation failed",
                level="error",
                tags={"service": "rankalpha-sentiment", "symbol": sym},
                extra={
                    "symbol": sym,
                    "output_path": output_path,
                    "news_title": news_title,
                    "news_url": news_url,
                },
            )
            logger.info("Not retrying this analysis attempt")
            return False

    except asyncio.TimeoutError:
        # Propagate to caller; upstream will avoid retrying on timeouts
        raise
    except Exception as e:
        logger.error(f"Error during workflow execution: {str(e)}")
        if SENTIMENT_REPORTS is not None:
            try:
                SENTIMENT_REPORTS.labels(status="error").inc()
            except Exception:
                pass
        if record_symbol_processed is not None:
            record_symbol_processed(outcome="error", trigger=trigger)
        capture_message(
            "rankalpha-sentiment: workflow execution error",
            level="error",
            tags={"service": "rankalpha-sentiment", "symbol": sym},
            extra={
                "symbol": sym,
                "news_title": news_title,
                "news_url": news_url,
            },
        )
        logger.info("Not retrying this analysis attempt")
        return False


__all__ = ["build_request_params", "ai_analysis"]
