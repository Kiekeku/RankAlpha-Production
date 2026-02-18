"""Sentiment Signals Pipeline (scaffold).

High level stages:
- Resolve entities (mentions → tickers)
- Classify per-document sentiment and aspects
- Extract structured events
- Aggregate to daily ticker sentiment (S_t)

This module is a placeholder for wiring the prompts in
`apps/sentiment/src/prompts/signals/` into an executable path. The
existing orchestrated report flow remains unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from apps.common.src.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Document:
    doc_id: str
    publish_datetime: Optional[str] = None
    source_name: Optional[str] = None
    url: Optional[str] = None
    text: Optional[str] = None
    ticker_candidates: List[str] = field(default_factory=list)


def run_pipeline(
    documents: Iterable[Document],
    *,
    ticker: Optional[str] = None,
    trading_date: Optional[str] = None,
) -> None:
    """Entry point for the doc-centric sentiment pipeline.

    Parameters
    - documents: iterable of input documents
    - ticker: optional target ticker for aggregation
    - trading_date: optional YYYY-MM-DD for aggregation window

    This is a scaffold only; wiring to LLM prompts and persistence is left
    for a subsequent change.
    """
    docs = list(documents)
    logger.info(
        "Signals pipeline stub: %s document(s) queued for ticker=%s, trading_date=%s",
        len(docs),
        ticker or "N/A",
        trading_date or "N/A",
    )
    for doc in docs:
        preview = (doc.text or "").strip()
        if len(preview) > 500:
            preview = preview[:500].rstrip() + "…"
        logger.info(
            "Document %s source=%s published=%s url=%s body_preview=%r",
            doc.doc_id,
            doc.source_name or "unknown",
            doc.publish_datetime or "unknown",
            doc.url or "n/a",
            preview or "<empty>",
        )
