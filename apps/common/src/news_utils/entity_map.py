from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Tuple

from sqlalchemy import and_
from sqlalchemy.orm import Session

from apps.common.src.company_utils import clean_company_name
from apps.common.src.models import DimStock, MvUniverseEligible

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    cleaned = clean_company_name(name or "") or ""
    n = cleaned.lower()
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


_UNIVERSE_CACHE: tuple[float, List[Tuple[int, str, str]]] | None = None
_UNIVERSE_CACHE_LOCK = threading.Lock()


def load_universe(db: Session) -> List[Tuple[int, str, str]]:
    global _UNIVERSE_CACHE
    try:
        ttl_sec = int(os.environ.get("NEWS_ENTITY_UNIVERSE_CACHE_SEC", "600"))
    except Exception:
        ttl_sec = 600
    try:
        max_stale_sec = int(os.environ.get("NEWS_ENTITY_UNIVERSE_CACHE_MAX_STALE_SEC", "3600"))
    except Exception:
        max_stale_sec = 3600

    now = time.monotonic()
    with _UNIVERSE_CACHE_LOCK:
        cached = _UNIVERSE_CACHE
        if ttl_sec > 0 and cached is not None:
            ts, data = cached
            if (now - ts) <= ttl_sec:
                return data

    try:
        rows = (
            db.query(DimStock.stock_key, DimStock.symbol, DimStock.company_name)
            .join(MvUniverseEligible, MvUniverseEligible.symbol == DimStock.symbol)
            .filter(and_(DimStock.is_active == True, MvUniverseEligible.eligible == True))  # noqa: E712
            .all()
        )
        universe = [(r[0], (r[1] or "").upper(), _normalize_name(r[2] or "")) for r in rows]
        if ttl_sec > 0:
            with _UNIVERSE_CACHE_LOCK:
                _UNIVERSE_CACHE = (time.monotonic(), universe)
        return universe
    except Exception:
        # If the universe view is temporarily unavailable, optionally degrade gracefully using a cached snapshot.
        # Cap the maximum cache age to avoid silently masking long-lived DB/view issues.
        now = time.monotonic()
        with _UNIVERSE_CACHE_LOCK:
            cached = _UNIVERSE_CACHE
        if cached is not None and max_stale_sec > 0:
            ts, data = cached
            age = now - ts
            if age <= max_stale_sec:
                logger.warning(
                    "Universe load failed; using cached snapshot (age=%.1fs <= %ss)",
                    age,
                    max_stale_sec,
                    exc_info=True,
                )
                return data
        raise


def map_entities_to_symbols(db: Session, title: str, snippet: str = "") -> List[Dict[str, Any]]:
    text = (title or "") + "\n" + (snippet or "")
    normalized_text = _normalize_name(text)
    impacts: List[Dict[str, Any]] = []
    universe = load_universe(db)
    try:
        min_ticker_len = int(os.environ.get("NEWS_ENTITY_MIN_TICKER_LEN", "3"))
    except Exception:
        min_ticker_len = 3
    stopwords = {
        w.strip().upper()
        for w in os.environ.get("NEWS_ENTITY_TICKER_STOPLIST", "").split(",")
        if w.strip()
    }
    # Exact ticker matches first
    matched_keys = set()
    for stock_key, sym, norm_name in universe:
        if not sym:
            continue
        if re.search(rf"\${re.escape(sym)}\b", text):
            impacts.append({"stock_key": stock_key, "role": "issuer", "confidence": 0.8})
            matched_keys.add(stock_key)
            continue
        if len(sym) < max(1, min_ticker_len):
            continue
        if sym in stopwords:
            continue
        if re.search(rf"\b{re.escape(sym)}\b", text):
            impacts.append({"stock_key": stock_key, "role": "issuer", "confidence": 0.8})
            matched_keys.add(stock_key)
    # Company name substring matches
    for stock_key, sym, norm_name in universe:
        if not norm_name or stock_key in matched_keys:
            continue
        words = norm_name.split()
        if len(words) == 1 and len(norm_name) <= 3:
            continue
        if re.search(rf"(?<!\w){re.escape(norm_name)}(?!\w)", normalized_text):
            impacts.append({"stock_key": stock_key, "role": "issuer", "confidence": 0.6})
            matched_keys.add(stock_key)
    return impacts[:5]
