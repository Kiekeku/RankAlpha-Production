from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from apps.common.src.models import DimStock

STOP_SUFFIX = re.compile(
    r"\b(inc|inc\.|incorporated|corp|corp\.|corporation|ltd|ltd\.|plc|co|co\.|company)\b\.?",
    re.I,
)


def _normalize_name(name: str) -> str:
    n = (name or "").lower()
    n = STOP_SUFFIX.sub("", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def load_universe(db: Session) -> List[Tuple[int, str, str]]:
    rows = (
        db.query(DimStock.stock_key, DimStock.symbol, DimStock.company_name)
        .filter(DimStock.is_active == True)  # noqa: E712
        .all()
    )
    return [(r[0], (r[1] or "").upper(), _normalize_name(r[2] or "")) for r in rows]


def map_entities_to_symbols(db: Session, title: str, snippet: str = "") -> List[Dict[str, Any]]:
    """Very simple resolver:
    - Match ticker symbols in title/snippet as standalone words
    - Match normalized company names as substrings
    Returns list of impacts: {stock_key, role, confidence}
    """
    text = (title or "") + "\n" + (snippet or "")
    text_low = text.lower()
    impacts: List[Dict[str, Any]] = []
    universe = load_universe(db)

    # Exact ticker matches first
    matched_keys = set()
    for stock_key, sym, norm_name in universe:
        if not sym:
            continue
        if re.search(rf"\b{re.escape(sym)}\b", text):
            impacts.append({"stock_key": stock_key, "role": "issuer", "confidence": 0.8})
            matched_keys.add(stock_key)

    # Company name substring matches
    for stock_key, sym, norm_name in universe:
        if not norm_name or stock_key in matched_keys:
            continue
        if norm_name and norm_name in _normalize_name(text_low):
            impacts.append({"stock_key": stock_key, "role": "issuer", "confidence": 0.6})
            matched_keys.add(stock_key)

    return impacts[:5]
