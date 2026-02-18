from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd

from apps.ingestion.src.universe_maintainer import UniverseMaintainer


class _DummyPriceStore:
    def __init__(self, ref_df: pd.DataFrame | None) -> None:
        self._ref_df = ref_df

    def load(self, symbol: str):  # type: ignore[no-untyped-def]
        return self._ref_df

    def list_existing(self) -> set[str]:  # pragma: no cover
        return set()

    def delete(self, _symbol: str) -> bool:  # pragma: no cover
        return False


class _DummyConn:
    def cursor(self):  # type: ignore[no-untyped-def]  # pragma: no cover
        raise AssertionError("DB should not be used by anchor selection tests")

    def close(self) -> None:  # pragma: no cover
        return None


class _RecordingCursor:
    def __init__(self, fetchone_values=None, fetchall_values=None) -> None:
        self.queries: list[tuple[str, tuple | None]] = []
        self._fetchone_values = list(fetchone_values or [])
        self._fetchall_values = list(fetchall_values or [])

    def execute(self, sql: str, params=None) -> None:  # type: ignore[no-untyped-def]
        self.queries.append((sql, params))

    def fetchone(self):  # type: ignore[no-untyped-def]
        if self._fetchone_values:
            return self._fetchone_values.pop(0)
        return None

    def fetchall(self):  # type: ignore[no-untyped-def]
        if self._fetchall_values:
            return self._fetchall_values.pop(0)
        return []

    def close(self) -> None:
        return None


class _RecordingConn:
    def __init__(self, cursor: _RecordingCursor) -> None:
        self._cursor = cursor
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self) -> _RecordingCursor:  # type: ignore[no-untyped-def]
        return self._cursor

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        return None


def _db_factory() -> _DummyConn:  # pragma: no cover
    return _DummyConn()


def test_choose_anchor_prefers_reference_symbol_when_available():
    ref_idx = pd.date_range("2025-01-01", periods=3, freq="D")
    ref_df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]}, index=ref_idx)
    settings = SimpleNamespace(
        ingestion_reference_symbol="SPY",
        ingestion_anchor_min_share=0.5,
        ingestion_inactive_after_missing_bdays=30,
        ingestion_reactivate_if_within_bdays=1,
        ingestion_prune_after_missing_bdays=0,
    )
    um = UniverseMaintainer(settings, _DummyPriceStore(ref_df), _db_factory, logger=None)
    assert um._choose_anchor_date({"AAPL": date(2025, 1, 1)}) == ref_idx[-1].date()


def test_choose_anchor_uses_majority_date_when_share_high_enough():
    settings = SimpleNamespace(
        ingestion_reference_symbol="SPY",
        ingestion_anchor_min_share=0.6,
        ingestion_inactive_after_missing_bdays=30,
        ingestion_reactivate_if_within_bdays=1,
        ingestion_prune_after_missing_bdays=0,
    )
    um = UniverseMaintainer(settings, _DummyPriceStore(None), _db_factory, logger=None)
    last_dates = {
        "AAPL": date(2025, 1, 2),
        "MSFT": date(2025, 1, 2),
        "NVDA": date(2025, 1, 1),
    }
    assert um._choose_anchor_date(last_dates) == date(2025, 1, 2)


def test_choose_anchor_falls_back_to_max_date_when_share_too_low():
    settings = SimpleNamespace(
        ingestion_reference_symbol="SPY",
        ingestion_anchor_min_share=0.9,
        ingestion_inactive_after_missing_bdays=30,
        ingestion_reactivate_if_within_bdays=1,
        ingestion_prune_after_missing_bdays=0,
    )
    um = UniverseMaintainer(settings, _DummyPriceStore(None), _db_factory, logger=None)
    last_dates = {
        "AAPL": date(2025, 1, 1),
        "MSFT": date(2025, 1, 2),
        "NVDA": date(2025, 1, 3),
    }
    assert um._choose_anchor_date(last_dates) == date(2025, 1, 3)


def test_looks_delisted():
    settings = SimpleNamespace(
        ingestion_reference_symbol="SPY",
        ingestion_anchor_min_share=0.5,
        ingestion_inactive_after_missing_bdays=30,
        ingestion_reactivate_if_within_bdays=1,
        ingestion_prune_after_missing_bdays=0,
    )
    um = UniverseMaintainer(settings, _DummyPriceStore(None), _db_factory, logger=None)
    assert um._looks_delisted("ABC-202501") is True
    assert um._looks_delisted("ABC") is False


def test_apply_db_updates_uses_set_based_queries():
    settings = SimpleNamespace(
        ingestion_reference_symbol="SPY",
        ingestion_anchor_min_share=0.5,
        ingestion_inactive_after_missing_bdays=30,
        ingestion_reactivate_if_within_bdays=1,
        ingestion_prune_after_missing_bdays=0,
    )
    cur = _RecordingCursor(fetchone_values=[(2, 5), (1,)])
    conn = _RecordingConn(cur)
    um = UniverseMaintainer(
        settings,
        _DummyPriceStore(None),
        lambda: conn,
        logger=SimpleNamespace(info=lambda *_a, **_k: None),
    )

    um._apply_db_updates(["AAPL", "MSFT"], ["NVDA"])

    assert conn.commit_count == 1
    assert conn.rollback_count == 0
    assert len(cur.queries) == 2
    assert "symbol = ANY" in cur.queries[0][0]
    assert "DELETE FROM rankalpha.fact_security_price" in cur.queries[0][0]
    assert "symbol = ANY" in cur.queries[1][0]


def test_prune_parquet_files_fetches_status_in_one_query():
    deleted: list[str] = []
    price_store = _DummyPriceStore(None)
    price_store.delete = lambda sym: deleted.append(sym) or True  # type: ignore[method-assign]

    settings = SimpleNamespace(
        ingestion_reference_symbol="SPY",
        ingestion_anchor_min_share=0.5,
        ingestion_inactive_after_missing_bdays=30,
        ingestion_reactivate_if_within_bdays=1,
        ingestion_prune_after_missing_bdays=5,
    )
    cur = _RecordingCursor(fetchall_values=[[("AAPL", False), ("MSFT", True)]])
    conn = _RecordingConn(cur)
    um = UniverseMaintainer(
        settings,
        price_store,
        lambda: conn,
        logger=SimpleNamespace(info=lambda *_a, **_k: None),
    )
    um._trading_day_gaps = lambda *_a, **_k: {"AAPL": 6, "MSFT": 6}  # type: ignore[method-assign]

    um._prune_parquet_files(
        {"SPY": date(2025, 1, 10), "AAPL": date(2025, 1, 1), "MSFT": date(2025, 1, 1)},
        date(2025, 1, 10),
    )

    assert len(cur.queries) == 1
    assert "symbol = ANY" in cur.queries[0][0]
    assert deleted == ["AAPL"]
