from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from apps.api.src.routers import signals


class _DummyScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._rows)


class _DummyResult:
    def __init__(
        self,
        *,
        scalar_value=None,
        scalar_one_or_none_value=None,
        all_rows=None,
        scalars_rows=None,
    ):
        self._scalar_value = scalar_value
        self._scalar_one_or_none_value = scalar_one_or_none_value
        self._all_rows = list(all_rows or [])
        self._scalars_rows = list(scalars_rows or [])

    def scalar(self):  # type: ignore[no-untyped-def]
        return self._scalar_value

    def scalar_one_or_none(self):  # type: ignore[no-untyped-def]
        return self._scalar_one_or_none_value

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._all_rows)

    def scalars(self):  # type: ignore[no-untyped-def]
        return _DummyScalars(self._scalars_rows)


class _QueueSession:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        if not self._results:
            raise AssertionError("No more queued DB results")
        self.calls += 1
        return self._results.pop(0)


def test_signals_leaderboard_uses_rank_window_percentiles():
    target_date = date(2025, 1, 2)
    db = _QueueSession(
        [
            _DummyResult(
                scalar_one_or_none_value=SimpleNamespace(score_type_key=42),
            ),
            _DummyResult(scalar_value=4),
            _DummyResult(scalar_value=4),
            _DummyResult(
                all_rows=[
                    ("AAPL", "Apple", "Tech", 90.0, target_date, 1),
                    ("MSFT", "Microsoft", "Tech", 80.0, target_date, 2),
                ]
            ),
        ]
    )

    out = signals.get_signals_leaderboard(
        db=db,  # type: ignore[arg-type]
        signal_type="momentum raw score",
        skip=0,
        limit=2,
        date_str="2025-01-02",
    )

    assert db.calls == 4
    assert out.total_count == 4
    assert len(out.signals) == 2
    assert out.signals[0].symbol == "AAPL"
    assert out.signals[0].percentile == pytest.approx(100.0)
    assert out.signals[1].symbol == "MSFT"
    assert out.signals[1].percentile == pytest.approx(75.0)


def test_signals_leaderboard_percentiles_stay_global_with_filters():
    target_date = date(2025, 1, 2)
    db = _QueueSession(
        [
            _DummyResult(
                scalar_one_or_none_value=SimpleNamespace(score_type_key=42),
            ),
            _DummyResult(scalar_value=10),  # global population
            _DummyResult(scalar_value=2),  # filtered population
            _DummyResult(
                all_rows=[
                    ("AAPL", "Apple", "Tech", 60.0, target_date, 6),
                    ("MSFT", "Microsoft", "Tech", 55.0, target_date, 7),
                ]
            ),
        ]
    )

    out = signals.get_signals_leaderboard(
        db=db,  # type: ignore[arg-type]
        signal_type="momentum raw score",
        skip=0,
        limit=2,
        sector="Tech",
        date_str="2025-01-02",
    )

    assert db.calls == 4
    assert out.total_count == 2
    assert out.signals[0].symbol == "AAPL"
    assert out.signals[0].percentile == pytest.approx(50.0)
    assert out.signals[1].symbol == "MSFT"
    assert out.signals[1].percentile == pytest.approx(40.0)


def test_compare_signals_batches_queries_and_keeps_zero_scores():
    latest_date = date(2025, 1, 3)
    db = _QueueSession(
        [
            _DummyResult(scalar_value=latest_date),
            _DummyResult(all_rows=[("AAPL", 1), ("MSFT", 2)]),
            _DummyResult(all_rows=[("S1", 11), ("S2", 12)]),
            _DummyResult(
                all_rows=[
                    (1, 11, 10.0),
                    (1, 12, 20.0),
                    (2, 11, 30.0),
                    (2, 12, 0.0),
                ]
            ),
        ]
    )

    out = signals.compare_signals(
        db=db,  # type: ignore[arg-type]
        symbols="AAPL,MSFT,UNKNOWN",
        signal_types="S1,S2",
    )

    assert db.calls == 4
    assert [row.symbol for row in out] == ["AAPL", "MSFT"]
    assert out[0].signals == {"S1": 10.0, "S2": 20.0}
    assert out[1].signals == {"S1": 30.0, "S2": 0.0}
