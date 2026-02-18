from __future__ import annotations

import pandas as pd

from apps.ingestion.src.price_sync_service import PriceSyncService


class _DummyCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, query: str, params: tuple) -> None:
        self.executed.append((query, params))

    def fetchone(self):  # type: ignore[no-untyped-def]
        return self._rows[0] if self._rows else None

    def fetchall(self):  # type: ignore[no-untyped-def]
        return self._rows

    def close(self) -> None:
        return None


class _DummyConn:
    def __init__(self, rows):
        self._rows = rows
        self.cursors: list[_DummyCursor] = []

    def cursor(self) -> _DummyCursor:
        cur = _DummyCursor(self._rows)
        self.cursors.append(cur)
        return cur


def _make_df() -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=10, freq="D")
    df = pd.DataFrame(
        {
            "Open": [1.0] * 10,
            "High": [2.0] * 10,
            "Low": [0.5] * 10,
            "Close": [10.0 + i for i in range(10)],
            "Adj Close": [10.0 + i for i in range(10)],
            "Volume": [100.0] * 9 + [float("nan")],
        },
        index=idx,
    )
    return df


def test_price_sync_service_partial_sync_when_anchor_matches(monkeypatch):
    df = _make_df()
    # Matches are checked against the last 3 dates excluding the newest row.
    check_idx = df.index[:-1][-3:]
    rows = []
    for ts in check_idx:
        dk = int(pd.Timestamp(ts).strftime("%Y%m%d"))
        rows.append((dk, float(df.at[ts, "Adj Close"])))
    conn = _DummyConn(rows)
    svc = PriceSyncService(conn, history_days=999)

    captured: dict[str, object] = {}

    def _bulk(rows):  # type: ignore[no-untyped-def]
        captured["rows"] = rows

    def _prune(stock_key, df_in):  # type: ignore[no-untyped-def]
        captured["prune"] = (stock_key, int(pd.Timestamp(df_in.index[0]).strftime("%Y%m%d")))

    monkeypatch.setattr(svc, "_bulk_upsert", _bulk)
    monkeypatch.setattr(svc, "_prune_old_rows", _prune)

    svc.sync("AAPL", stock_key=123, df=df, force_full=False)

    rows = captured["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 5
    assert captured["prune"] == (123, 20250101)


def test_price_sync_service_full_sync_when_anchor_mismatch(monkeypatch):
    df = _make_df()
    check_idx = df.index[:-1][-3:]
    rows = []
    for ts in check_idx:
        dk = int(pd.Timestamp(ts).strftime("%Y%m%d"))
        rows.append((dk, 9999.0))
    conn = _DummyConn(rows)
    svc = PriceSyncService(conn, history_days=999)

    captured: dict[str, object] = {}

    monkeypatch.setattr(svc, "_bulk_upsert", lambda rows: captured.setdefault("rows", rows))
    monkeypatch.setattr(svc, "_prune_old_rows", lambda *_a, **_k: None)

    svc.sync("AAPL", stock_key=123, df=df, force_full=False)

    rows = captured["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 10
