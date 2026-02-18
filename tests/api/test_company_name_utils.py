from __future__ import annotations

import pytest

from apps.api.src.utils import company


@pytest.fixture(autouse=True)
def _clear_cache():
    company._NAME_CACHE.clear()
    yield
    company._NAME_CACHE.clear()


def test_clean_company_name_strips_common_suffixes():
    assert company.clean_company_name("Acme, Inc.") == "Acme"
    assert company.clean_company_name("Foo Holdings PLC") == "Foo"
    assert company.clean_company_name("Bar Co.") == "Bar"


def test_clean_company_name_never_returns_empty_label():
    # Single token names are returned as-is (even if it's a suffix-ish token).
    assert company.clean_company_name("Inc") == "Inc"


def test_clean_company_name_caches_with_ttl(monkeypatch):
    now = 1000.0

    def fake_time() -> float:
        return now

    monkeypatch.setattr(company.time, "time", fake_time)

    first = company.clean_company_name("Acme, Inc.")
    assert first == "Acme"

    # Within TTL: returns cached value
    company._NAME_CACHE["Acme, Inc."] = (now, "CACHED")
    second = company.clean_company_name("Acme, Inc.")
    assert second == "CACHED"

    # Past TTL: recomputes and ignores stale cached value
    ttl = 60 * 60 * 24
    company._NAME_CACHE["Acme, Inc."] = (now - ttl - 1, "STALE")
    third = company.clean_company_name("Acme, Inc.")
    assert third == "Acme"
