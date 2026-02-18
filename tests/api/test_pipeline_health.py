from datetime import date, datetime, timezone

from apps.api.src.routers import pipeline as pipeline_router


class DummyDb:
    pass


def test_health_reference_day_uses_previous_trading_day_before_ingestion(monkeypatch):
    market_today = date(2026, 1, 16)
    ingestion_last_run = datetime(2026, 1, 15, 10, 49, 15, tzinfo=timezone.utc)
    captured = {}

    def _fake_ref_trading_date(_db, cap_date=None):
        captured["cap_date"] = cap_date
        return cap_date or market_today

    monkeypatch.setattr(pipeline_router, "_market_today", lambda: market_today)
    monkeypatch.setattr(pipeline_router, "_ref_trading_date", _fake_ref_trading_date)

    ref_day = pipeline_router._health_reference_day(DummyDb(), ingestion_last_run)

    assert ref_day == date(2026, 1, 15)
    assert captured["cap_date"] == date(2026, 1, 15)


def test_health_reference_day_stays_on_today_after_ingestion(monkeypatch):
    market_today = date(2026, 1, 16)
    ingestion_last_run = datetime(2026, 1, 16, 5, 0, 0, tzinfo=timezone.utc)
    captured = {}

    def _fake_ref_trading_date(_db, cap_date=None):
        captured["cap_date"] = cap_date
        return cap_date or market_today

    monkeypatch.setattr(pipeline_router, "_market_today", lambda: market_today)
    monkeypatch.setattr(pipeline_router, "_ref_trading_date", _fake_ref_trading_date)

    ref_day = pipeline_router._health_reference_day(DummyDb(), ingestion_last_run)

    assert ref_day == market_today
    assert captured["cap_date"] == market_today
