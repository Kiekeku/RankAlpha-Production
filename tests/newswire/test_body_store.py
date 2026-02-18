from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


pytest.importorskip("tldextract")
pytest.importorskip("trafilatura")

from newswire import body_store  # noqa: E402


class _DB:
    def __init__(self, row):
        self.row = row
        self.flushed = 0

    def get(self, _model, _id):  # type: ignore[no-untyped-def]
        return self.row

    def flush(self) -> None:
        self.flushed += 1


def test_allowed_domain_allows_all_when_allowlist_empty():
    assert body_store._allowed_domain("https://example.com/a", "") is True


def test_allowed_domain_matches_registered_domain_and_host():
    assert body_store._allowed_domain("https://www.sec.gov/Archives", "sec.gov") is True
    assert body_store._allowed_domain("https://sub.example.co.uk/a", "example.co.uk") is True
    assert body_store._allowed_domain("https://bad.example.com/a", "foo.com") is False


def test_store_body_missing_raw_returns_missing_raw():
    db = _DB(row=None)
    out = body_store.store_body_if_needed(db, raw_id=1, url="u", prefilter_score=1.0)
    assert out.status == "missing_raw"
    assert out.stored is False


def test_store_body_short_circuits_when_already_present():
    row = SimpleNamespace(
        url_canonical="https://example.com",
        body_text="x",
        body_fetch_status=None,
        body_fetch_error="err",
    )
    db = _DB(row=row)
    out = body_store.store_body_if_needed(db, raw_id=1, url=row.url_canonical, prefilter_score=1.0)
    assert out.status == "already_present"
    assert row.body_fetch_status == "present"
    assert row.body_fetch_error is None


def test_store_body_skips_low_score(monkeypatch):
    monkeypatch.setenv("NEWS_BODY_PREFILTER_MIN", "0.90")
    row = SimpleNamespace(url_canonical="https://example.com", body_text=None, body_fetch_status=None, body_fetch_error=None)
    db = _DB(row=row)
    out = body_store.store_body_if_needed(db, raw_id=1, url=row.url_canonical, prefilter_score=0.1)
    assert out.status == "skipped_low_score"
    assert row.body_fetch_status == "skipped_low_score"


def test_store_body_skips_domain(monkeypatch):
    monkeypatch.setattr(body_store, "_allowed_domain", lambda _u, _a: False)
    row = SimpleNamespace(url_canonical="https://example.com", body_text=None, body_fetch_status=None, body_fetch_error=None)
    db = _DB(row=row)
    out = body_store.store_body_if_needed(db, raw_id=1, url=row.url_canonical, prefilter_score=1.0)
    assert out.status == "skipped_domain"
    assert row.body_fetch_status == "skipped_domain"


def test_store_body_sets_empty_body_status(monkeypatch):
    monkeypatch.setattr(body_store, "_allowed_domain", lambda _u, _a: True)
    monkeypatch.setattr(body_store, "_extract_body", lambda _u, timeout=10: ("", "boom"))
    row = SimpleNamespace(url_canonical="https://example.com", body_text=None, body_fetch_status=None, body_fetch_error=None)
    db = _DB(row=row)
    out = body_store.store_body_if_needed(db, raw_id=1, url=row.url_canonical, prefilter_score=1.0)
    assert out.status == "empty_body"
    assert out.error == "boom"
    assert row.body_fetch_status == "empty_body"


def test_store_body_truncates_and_persists(monkeypatch):
    monkeypatch.setenv("NEWS_BODY_MAX_CHARS", "3")
    monkeypatch.setattr(body_store, "_allowed_domain", lambda _u, _a: True)
    monkeypatch.setattr(body_store, "_extract_body", lambda _u, timeout=10: ("abcdef", None))
    row = SimpleNamespace(
        url_canonical="https://example.com",
        body_text=None,
        body_fetch_status=None,
        body_fetch_error=None,
        body_fingerprint=None,
        body_bytes=None,
        body_truncated=None,
        body_fetch_ts=None,
        body_source=None,
    )
    db = _DB(row=row)
    out = body_store.store_body_if_needed(db, raw_id=1, url=row.url_canonical, prefilter_score=1.0)
    assert out.status == "stored_truncated"
    assert out.stored is True
    assert row.body_text == "abc"
    assert isinstance(row.body_fingerprint, int)
    assert row.body_bytes == 3
    assert row.body_truncated is True
    assert isinstance(row.body_fetch_ts, datetime)
    assert row.body_fetch_ts.tzinfo == timezone.utc
