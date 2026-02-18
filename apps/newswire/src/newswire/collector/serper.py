from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from apps.common.src.ai.budget import Budget, get_redis_counter_from_env
from apps.common.src.ai.guardrails import AIGateway
from apps.common.src.news_utils.dedup import simhash64

# Module-level shared gateway to preserve rate limits/cache across invocations
_SEARCH_GATEWAY = AIGateway(
    service="newswire_search", budget=Budget(), counter=get_redis_counter_from_env()
)
logger = logging.getLogger(__name__)


def _make_tbs(since: Optional[datetime], until: Optional[datetime]) -> Optional[str]:
    # Serper supports Google's tbs param like qdr:h (hour), qdr:d (day)
    if not since:
        return os.environ.get("SERPER_TBS")
    now = datetime.now(tz=timezone.utc)
    delta = (now - since).total_seconds() / 3600.0
    if delta <= 6:
        return "qdr:h"
    if delta <= 72:
        return "qdr:d"
    return "qdr:w"


async def poll_serper(
    session: Optional[httpx.AsyncClient] = None,
    queries: Optional[List[str]] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    num: int = 50,
) -> AsyncIterator[Dict[str, Any]]:
    """Yield recent results from Serper News API.

    - Provide SERPER_API_KEY in env.
    - queries: override env SERPER_NEWS_QUERIES (bar-separated: q1|q2|...)
    """
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        return

    base_url = os.environ.get("SERPER_NEWS_URL", "https://google.serper.dev/news")
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    gl = os.environ.get("SERPER_GL", "us")
    hl = os.environ.get("SERPER_HL", "en")

    q_list = queries
    if not q_list:
        raw = os.environ.get(
            "SERPER_NEWS_QUERIES",
            (
                "site:businesswire.com|site:globenewswire.com|site:prnewswire.com|"
                '("earnings" OR "guidance" OR "merger" OR "acquisition" OR "bankruptcy" OR "chapter 11" OR "dividend" OR "buyback" OR "layoffs")|'
                '(site:reuters.com OR site:bloomberg.com OR site:wsj.com OR site:ft.com) ("earnings" OR "guidance" OR "merger" OR "acquisition" OR "bankruptcy")|'
                "(site:sec.gov OR site:fda.gov OR site:justice.gov OR site:cftc.gov) (charges OR fines OR settles OR sues OR approves OR blocks OR warning OR recall)|"
                '(tariff OR sanctions OR "export controls" OR "entity list") ("company" OR "issuer" OR "stock")'
            ),
        )
        q_list = [q.strip() for q in raw.split("|") if q.strip()]

    tbs = _make_tbs(since, until)

    close_client = False
    client = session
    if client is None:
        client = httpx.AsyncClient(timeout=15)
        close_client = True

    try:
        for q in q_list:
            qnorm = q

            async def _do_search(qtxt: str):
                body = {"q": qtxt, "gl": gl, "hl": hl}
                if tbs:
                    body["tbs"] = tbs
                logger.debug(
                    "Serper request payload: q=%s gl=%s hl=%s tbs=%s url=%s",
                    qtxt,
                    gl,
                    hl,
                    tbs,
                    base_url,
                )
                r = await client.post(base_url, headers=headers, json=body)
                try:
                    r.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    content = (r.text or "").strip()
                    logger.warning(
                        "Serper HTTP error: status=%s query=%s body=%s",
                        r.status_code,
                        qtxt,
                        content[:500],
                        exc_info=(type(exc), exc, exc.__traceback__),
                    )
                    raise
                logger.debug("Serper request: q=%s gl=%s hl=%s tbs=%s", qtxt, gl, hl, tbs)
                return r.json() or {}

            try:
                # Use shared gateway to enforce RPM and caching; cap fan-out per query
                result = await _SEARCH_GATEWAY.call_search(
                    provider="serper",
                    query=qnorm,
                    do_search=_do_search,
                    per_query_cap=min(max(num, 1), 50),
                )
                rows = (result or {}).get("news", [])
            except Exception as exc:
                logger.warning(
                    "Serper query failed: %s",
                    qnorm,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                rows = []
            logger.debug("Serper results: query=%s rows=%s", qnorm, len(rows or []))
            for row in rows or []:
                try:
                    title = row.get("title") or ""
                    snippet = row.get("snippet") or ""
                    try:
                        text_fp = int(simhash64(f"{title} {snippet}"))
                    except Exception:
                        text_fp = None
                    yield {
                        "url": row.get("link"),
                        "title": title,
                        "snippet": snippet,
                        "published_at": row.get("date"),
                        "source_domain": row.get("source") or "",
                        "language": "en",
                        "country": gl.upper(),
                        "raw": row,
                        "text_fp": text_fp,
                    }
                except Exception:
                    continue
    finally:
        if close_client:
            await client.aclose()
