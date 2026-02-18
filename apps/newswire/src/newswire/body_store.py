from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx
import tldextract
import trafilatura
from sqlalchemy.orm import Session

from apps.common.src.models import FactNewsRaw

from .dedup import simhash64


@dataclass
class BodyStoreResult:
    stored: bool
    status: str
    error: Optional[str] = None


_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())


def _allowed_domain(url: str, allowlist_csv: str) -> bool:
    try:
        ext = _TLD_EXTRACT(url or "")
        reg = ".".join(part for part in [ext.domain, ext.suffix] if part)
        host = ".".join(part for part in [ext.subdomain, ext.domain, ext.suffix] if part)
        allowed = [d.strip().lower() for d in (allowlist_csv or "").split(",") if d.strip()]
        if not allowed:
            return True  # no allowlist -> allow all
        reg_l = (reg or "").lower()
        host_l = (host or "").lower()
        return any(host_l.endswith(a) or reg_l == a for a in allowed)
    except Exception:
        return False


def _extract_body(url: str, timeout: int = 10) -> tuple[str, Optional[str]]:
    try:
        ua = os.environ.get("NEWS_BODY_USER_AGENT", "rankalpha-newswire/1.0")
        max_fetch_bytes = int(os.environ.get("NEWS_BODY_MAX_FETCH_BYTES", "800000"))
        if max_fetch_bytes <= 0:
            max_fetch_bytes = 800000
        with httpx.stream(
            "GET",
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": ua},
        ) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total >= max_fetch_bytes:
                    break
            content = b"".join(chunks)
        html = content.decode("utf-8", errors="ignore")
        text = (
            trafilatura.extract(
                html, include_comments=False, include_tables=False, favor_precision=True
            )
            or ""
        )
        return text.strip(), None
    except Exception as exc:
        return "", str(exc)[:500]


def store_body_if_needed(
    db: Session,
    raw_id,
    url: str,
    prefilter_score: float,
) -> BodyStoreResult:
    """Fetch and persist article body into fact_news_raw when gating passes.

    Gating:
      - prefilter_score >= NEWS_BODY_PREFILTER_MIN (default 0.50)
      - domain in NEWS_BODY_ALLOWLIST (comma-separated; empty => allow all)
      - truncate to NEWS_BODY_MAX_CHARS (default 120000)
    Returns a BodyStoreResult describing whether a body was stored and the decision status.
    """
    row: Optional[FactNewsRaw] = None
    try:
        row = db.get(FactNewsRaw, raw_id)
        if not row:
            return BodyStoreResult(False, "missing_raw")
        if row.body_text:
            # Body already stored, ensure status reflects it
            if not row.body_fetch_status:
                row.body_fetch_status = "present"
            row.body_fetch_error = None
            db.flush()
            return BodyStoreResult(False, "already_present")
        min_score = float(os.environ.get("NEWS_BODY_PREFILTER_MIN", "0.50"))
        if prefilter_score < min_score:
            row.body_fetch_status = "skipped_low_score"
            row.body_fetch_error = None
            db.flush()
            return BodyStoreResult(False, "skipped_low_score")
        allow = os.environ.get(
            "NEWS_BODY_ALLOWLIST",
            "businesswire.com,globenewswire.com,prnewswire.com,sec.gov,fda.gov",
        )
        if not _allowed_domain(url or row.url_canonical, allow):
            row.body_fetch_status = "skipped_domain"
            row.body_fetch_error = None
            db.flush()
            return BodyStoreResult(False, "skipped_domain")
        timeout = int(os.environ.get("NEWS_BODY_FETCH_TIMEOUT_SEC", "10"))
        text, err = _extract_body(url or row.url_canonical, timeout=timeout)
        if not text:
            row.body_fetch_status = "empty_body"
            row.body_fetch_error = err or "extraction_empty"
            db.flush()
            return BodyStoreResult(False, "empty_body", error=row.body_fetch_error)
        max_chars = int(os.environ.get("NEWS_BODY_MAX_CHARS", "120000"))
        trunc = False
        if len(text) > max_chars:
            text = text[:max_chars]
            trunc = True
        fp = int(simhash64(text))
        row.body_text = text
        row.body_fingerprint = fp
        row.body_bytes = len(text.encode("utf-8", errors="ignore"))
        row.body_truncated = trunc
        row.body_fetch_ts = datetime.now(tz=timezone.utc)
        row.body_source = "httpx+trafilatura"
        row.body_fetch_status = "stored_truncated" if trunc else "stored"
        row.body_fetch_error = None
        db.flush()
        return BodyStoreResult(True, "stored_truncated" if trunc else "stored")
    except Exception as exc:
        if row:
            row.body_fetch_status = "error"
            row.body_fetch_error = str(exc)[:500]
            db.flush()
        return BodyStoreResult(False, "error", error=str(exc))
