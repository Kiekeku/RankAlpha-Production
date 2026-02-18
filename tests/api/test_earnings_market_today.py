from datetime import date, datetime as real_datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest


def test_earnings_market_today_uses_eastern(monkeypatch):
    from apps.api.src.routers import earnings as earnings_router

    try:
        eastern = ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        pytest.skip("tzdata not available")
    captured = {}

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            captured["tz"] = tz
            return real_datetime(2026, 1, 15, 20, 0, tzinfo=tz)

    monkeypatch.setattr(earnings_router, "_MARKET_TZ", eastern)
    monkeypatch.setattr(earnings_router, "datetime", FakeDateTime)

    assert earnings_router._market_today() == date(2026, 1, 15)
    assert captured["tz"] is eastern


def test_grading_market_today_uses_eastern(monkeypatch):
    from apps.api.src.routers import grading as grading_router

    try:
        eastern = ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        pytest.skip("tzdata not available")
    captured = {}

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            captured["tz"] = tz
            return real_datetime(2026, 1, 15, 20, 0, tzinfo=tz)

    monkeypatch.setattr(grading_router, "_MARKET_TZ", eastern)
    monkeypatch.setattr(grading_router, "datetime", FakeDateTime)

    assert grading_router._market_today() == date(2026, 1, 15)
    assert captured["tz"] is eastern
