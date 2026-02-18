from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, Iterable, Optional

import httpx

from apps.common.src.news_utils.dedup import simhash64

logger = logging.getLogger(__name__)


def _fmt_gdelt_dt(dt: datetime) -> str:
    # GDELT expects UTC YYYYMMDDHHMMSS
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%d%H%M%S")


async def _fetch_window(
    client: httpx.AsyncClient,
    base_url: str,
    start: Optional[datetime],
    end: Optional[datetime],
    query: Optional[str],
    maxrecords: int,
) -> Iterable[Dict[str, Any]]:
    params = {
        "format": "json",
        "mode": os.environ.get("GDELT_MODE", "ArtList"),
        "sort": os.environ.get("GDELT_SORT", "DateDesc"),
        "maxrecords": str(maxrecords),
    }
    if query:
        q = query.strip()
        if q and " OR " in q and not (q.startswith("(") and q.endswith(")")):
            q = f"({q})"
        params["query"] = q
    if start and end:
        params["startdatetime"] = _fmt_gdelt_dt(start)
        params["enddatetime"] = _fmt_gdelt_dt(end)
    else:
        params["timespan"] = os.environ.get("GDELT_TIMESPAN", "15m")

    resp = await client.get(base_url, params=params)
    resp.raise_for_status()
    data = resp.json()
    # API returns non-200 on major failures; minor errors come back in response
    if isinstance(data, dict) and data.get("error"):
        logger.warning("GDELT responded with error: %s", data.get("error"))
        return
    rows = data.get("articles", []) or data.get("documents", []) or []
    for row in rows:
        title = row.get("title") or row.get("semtitle") or ""
        snippet = row.get("seendescription") or row.get("snippet") or ""
        try:
            text_fp = int(simhash64(f"{title} {snippet}"))
        except Exception:
            text_fp = None
        yield {
            "url": row.get("url"),
            "title": title,
            "snippet": snippet,
            "published_at": row.get("seendate") or row.get("date"),
            "source_domain": row.get("domain") or row.get("source"),
            "country": row.get("sourcecountry"),
            "language": row.get("language"),
            "raw": row,
            "text_fp": text_fp,
        }


async def poll_gdelt(
    session: Optional[httpx.AsyncClient] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    query: Optional[str] = None,
    maxrecords: int = 50,
) -> AsyncIterator[Dict[str, Any]]:
    """Yield recent documents from the GDELT 2.0 DOC API.

    - If since/until provided, iterate windows of 15m and fetch.
    - Else, fetch a single timespan (env GDELT_TIMESPAN, default 15m).
    """
    base_url = os.environ.get("GDELT_DOC_URL", "https://api.gdeltproject.org/api/v2/doc/doc")
    close_client = False
    client = session
    if client is None:
        client = httpx.AsyncClient(timeout=45)
        close_client = True
    try:
        if since and until:
            step_minutes = int(os.environ.get("GDELT_STEP_MIN", "15"))
            step = timedelta(minutes=step_minutes)
            if step <= timedelta(0):
                step = timedelta(minutes=15)
            cur = since
            while cur < until:
                end = min(cur + step, until)
                if (end - cur) <= timedelta(minutes=1):
                    end = cur + timedelta(minutes=1)
                logger.debug(
                    "GDELT window request: start=%s end=%s query=%s maxrecords=%s",
                    _fmt_gdelt_dt(cur),
                    _fmt_gdelt_dt(end),
                    query,
                    maxrecords,
                )
                async for item in _fetch_window(client, base_url, cur, end, query, maxrecords):
                    yield item
                logger.debug(
                    "GDELT poll window %s-%s yielded %s docs so far",
                    _fmt_gdelt_dt(cur),
                    _fmt_gdelt_dt(end),
                    maxrecords,
                )
                cur = end
        else:
            logger.debug(
                "GDELT timespan request: timespan=%s query=%s maxrecords=%s",
                os.environ.get("GDELT_TIMESPAN", "15m"),
                query,
                maxrecords,
            )
            async for item in _fetch_window(client, base_url, None, None, query, maxrecords):
                yield item
    finally:
        if close_client:
            await client.aclose()
