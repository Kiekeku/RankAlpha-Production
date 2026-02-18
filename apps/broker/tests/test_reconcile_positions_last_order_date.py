from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from tradeexec.order import reconcile_positions as rp


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_a, **_k):  # pragma: no cover
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_a, **_k):  # pragma: no cover
        return _FakeQuery(self._rows)


def test_compute_last_order_placed_date_applies_friday_bump(monkeypatch):
    # today is Tuesday; earliest recent run is Friday => bump +1 day to Saturday.
    class _FixedDate:
        @classmethod
        def today(cls):  # type: ignore[no-untyped-def]
            return date(2025, 1, 7)  # Tuesday

    monkeypatch.setattr(rp, "date", _FixedDate)
    statuses = [
        SimpleNamespace(System="SYS_A", LastSuccessfulRun=datetime(2025, 1, 3, 12, 0, 0)),
        SimpleNamespace(System="SYS_A", LastSuccessfulRun=datetime(2025, 1, 6, 12, 0, 0)),
    ]
    session = _FakeSession(statuses)
    rec = rp.ReconcilePosition(
        ib_interface=SimpleNamespace(),
        program_name="p",
        system_prefixes=["SYS"],
    )

    out = rec._compute_last_order_placed_date(session)
    assert out == date(2025, 1, 4)  # Saturday (Friday + 1 day)


def test_compute_last_order_placed_date_ignores_too_old_runs(monkeypatch):
    class _FixedDate:
        @classmethod
        def today(cls):  # type: ignore[no-untyped-def]
            return date(2025, 1, 7)

    monkeypatch.setattr(rp, "date", _FixedDate)
    # Older than 7 days relative to today -> ignored, so return today.
    statuses = [SimpleNamespace(System="SYS_A", LastSuccessfulRun=datetime(2024, 12, 1, 12, 0, 0))]
    session = _FakeSession(statuses)
    rec = rp.ReconcilePosition(
        ib_interface=SimpleNamespace(),
        program_name="p",
        system_prefixes=["SYS"],
    )

    out = rec._compute_last_order_placed_date(session)
    assert out == date(2025, 1, 7)


def test_normalise_order_list_keeps_only_dicts():
    out = rp.ReconcilePosition._normalise_order_list([{"a": 1}, None, 123, {"b": 2}])
    assert out == [{"a": 1}, {"b": 2}]


def test_prefetch_existing_exit_keys_maps_reconcile_exit_to_both_sides():
    session = _FakeSession(
        [
            ("AAPL", "Sell", ""),
            ("MSFT", "Exit", "Reconcile Systems with IB"),
            ("TSLA", "Exit", "Other"),
        ]
    )
    rec = rp.ReconcilePosition(
        ib_interface=SimpleNamespace(),
        program_name="p",
        system_prefixes=["SYS"],
    )

    out = rec._prefetch_existing_exit_keys(session, date(2025, 1, 1))
    assert out is not None
    assert ("AAPL", "Sell") in out
    assert ("MSFT", "Buy") in out
    assert ("MSFT", "Sell") in out
    assert ("TSLA", "Buy") not in out
    assert ("TSLA", "Sell") not in out
