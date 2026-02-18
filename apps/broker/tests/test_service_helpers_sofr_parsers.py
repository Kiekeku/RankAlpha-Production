from __future__ import annotations

import re
import sys
from datetime import date, datetime, timezone


def _import_service(monkeypatch):
    import apps.common.src.observability as obs

    monkeypatch.setattr(obs, "instrument_fastapi_app", lambda *_a, **_k: None)
    sys.modules.pop("tradeexec.reports.daily", None)

    import types

    daily_mod = types.ModuleType("tradeexec.reports.daily")

    class DailyReport:  # type: ignore
        def __init__(self, *args, **kwargs) -> None:  # pragma: no cover
            return

        def email_report(self) -> None:  # pragma: no cover
            return

    daily_mod.DailyReport = DailyReport
    sys.modules["tradeexec.reports.daily"] = daily_mod

    sys.modules.pop("tradeexec.service", None)
    from tradeexec import service  # noqa: WPS433 (import inside helper)

    return service


def test_parse_year_month_handles_common_formats(monkeypatch):
    service = _import_service(monkeypatch)

    assert service._parse_year_month("2025-01-02") == (2025, 1)
    assert service._parse_year_month("202501") == (2025, 1)
    assert service._parse_year_month("2025/12/31") == (2025, 12)
    assert service._parse_year_month("2025-13-01") == (None, None)
    assert service._parse_year_month(None) == (None, None)


def test_parse_bar_date_accepts_epoch_ms_and_iso(monkeypatch):
    service = _import_service(monkeypatch)

    # epoch milliseconds for 2025-01-02 UTC
    dt = datetime(2025, 1, 2, tzinfo=timezone.utc)
    ms = int(dt.timestamp() * 1000)
    assert service._parse_bar_date(ms) == date(2025, 1, 2)

    assert service._parse_bar_date("2025-01-02") == date(2025, 1, 2)
    assert service._parse_bar_date("not-a-date") is None


def test_generate_local_symbol_guesses_is_deterministic_for_horizon_one(monkeypatch):
    service = _import_service(monkeypatch)

    guesses = service._generate_local_symbol_guesses("sr3", horizon_months=1)
    assert guesses and len(guesses) == 2
    assert all(g.startswith("SR3") for g in guesses)
    assert all(re.match(r"^SR3[A-Z]\d{1,2}$", g) for g in guesses)


def test_secdef_search_futures_filters_non_fut_and_dedupes(monkeypatch):
    service = _import_service(monkeypatch)

    class _Client:
        def __init__(self):
            self.calls = []

        def get(self, path: str, params=None):  # type: ignore[no-untyped-def]
            self.calls.append((path, dict(params or {})))
            # Return a list like ibind would
            return [
                {
                    "secType": "FUT",
                    "listingExchange": "GLOBEX",
                    "expiry": "2025-03-20",
                    "conid": 101,
                    "localSymbol": "SR3H5",
                },
                {
                    "secType": "FUT",
                    "listingExchange": "NYSE",  # filtered out
                    "expiry": "2025-03-20",
                    "conid": 102,
                    "localSymbol": "BAD",
                },
                {"secType": "STK", "expiry": "2025-03-20", "conid": 103, "localSymbol": "STK"},
                {
                    "secType": "FUT",
                    "listingExchange": "GLOBEX",
                    "expiry": "2025-03-20",
                    "conid": 101,  # duplicate conid
                    "localSymbol": "SR3H5",
                },
            ]

    ib = type("IB", (), {"client": _Client()})()
    out = service._secdef_search_futures(ib, symbols=["SR3"])
    assert len(out) == 1
    assert out[0]["conid"] == 101
    assert out[0]["localSymbol"] == "SR3H5"
