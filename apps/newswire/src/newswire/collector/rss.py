from __future__ import annotations

import calendar
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import feedparser  # type: ignore
import httpx

logger = logging.getLogger(__name__)


def _parse_feeds_env(value: Optional[str]) -> List[str]:
    if not value:
        return []
    s = value.strip()
    # JSON array or bar-separated
    if s.startswith("["):
        try:
            arr = json.loads(s)
            return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    return [x.strip() for x in s.split("|") if x.strip()]


def _to_dt_iso(entry: Dict[str, Any]) -> Optional[str]:
    # Prefer published, then updated
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st is not None:
            try:
                ts = datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)
                return ts.isoformat()
            except Exception:
                continue
    # Fallback to string fields; best-effort parse via feedparser already normalized
    for key in ("published", "updated", "created"):
        v = entry.get(key)
        if isinstance(v, str) and v:
            try:
                # Avoid heavy parsers; rely on published_parsed primarily
                return v
            except Exception:
                continue
    return None


def _source_domain(entry_url: Optional[str], feed_link: Optional[str]) -> str:
    url = entry_url or feed_link or ""
    try:
        netloc = urlparse(url).netloc or ""
        return netloc.lower()
    except Exception:
        return ""


async def poll_rss(
    session: Optional[httpx.AsyncClient] = None,
    feeds: Optional[List[str]] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    num_per_feed: int = 50,
) -> AsyncIterator[Dict[str, Any]]:
    """Yield recent items from configured RSS/Atom feeds.

    - Configure feeds via `NEWS_RSS_FEEDS` (bar-separated or JSON array).
    - Respects `since`/`until` windows; publishes ISO timestamps when available.
    """
    feed_list: List[str] = feeds or _parse_feeds_env(os.environ.get("NEWS_RSS_FEEDS"))
    if not feed_list:
        return

    close_client = False
    client = session
    if client is None:
        client = httpx.AsyncClient(timeout=20)
        close_client = True

    try:
        for url in feed_list:
            try:
                r = await client.get(url)
                r.raise_for_status()
            except Exception as e:
                logger.warning("RSS fetch failed: %s (%s)", url, e)
                continue

            parsed = feedparser.parse(r.content)
            entries: Iterable[Dict[str, Any]] = parsed.get("entries", [])  # type: ignore
            count = 0
            for e in entries:
                if count >= max(1, num_per_feed):
                    break
                ts_iso = _to_dt_iso(e)
                ts_dt: Optional[datetime] = None
                if ts_iso:
                    try:
                        # Common case: iso-8601; timezone-naive treated as UTC
                        ts_dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
                        if ts_dt.tzinfo is None:
                            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                    except Exception:
                        ts_dt = None
                # Filter by window if provided
                if since and ts_dt and ts_dt < since:
                    continue
                if until and ts_dt and ts_dt > until:
                    continue

                entry_url = e.get("link") or e.get("id") or ""
                title = e.get("title") or ""
                summary = e.get("summary") or e.get("description") or ""
                try:
                    from apps.common.src.news_utils.dedup import (
                        simhash64,
                    )  # local import to avoid heavy import when unused

                    text_fp = int(simhash64(f"{title} {summary}"))
                except Exception:
                    text_fp = None
                yield {
                    "url": entry_url,
                    "title": title,
                    "snippet": summary,
                    "published_at": ts_iso,
                    "source_domain": _source_domain(
                        entry_url,
                        parsed.get("feed", {}).get("link") if parsed.get("feed") else None,
                    ),
                    "language": (parsed.get("feed", {}) or {}).get("language") or "en",
                    "country": None,
                    "raw": e,
                    "text_fp": text_fp,
                }
                count += 1
    finally:
        if close_client:
            await client.aclose()
