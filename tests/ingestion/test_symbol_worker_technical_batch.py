from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
from apps.ingestion.src.symbol_worker import SymbolIngestionWorker, SymbolResult


class _DummyCounter:
    def labels(self, **_kwargs):  # type: ignore[no-untyped-def]
        return self

    def inc(self) -> None:
        return None


class _DummyCursor:
    def close(self) -> None:
        return None


class _DummyConn:
    def cursor(self) -> _DummyCursor:
        return _DummyCursor()

    def close(self) -> None:
        return None


class _DurationRecorder:
    def __init__(self) -> None:
        self.values: list[float] = []

    def observe(self, value: float) -> None:
        self.values.append(float(value))


class _DurationHistogram:
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.recorder = _DurationRecorder()

    def labels(self, *, status: str) -> _DurationRecorder:
        self.statuses.append(status)
        return self.recorder


def test_upsert_technicals_batches_rows_once(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_execute_values(cur, sql, values, template=None, page_size=100):  # type: ignore[no-untyped-def]
        captured["sql"] = sql
        captured["values"] = list(values)
        captured["template"] = template
        captured["page_size"] = page_size
        captured["calls"] = int(captured.get("calls", 0)) + 1

    monkeypatch.setattr("apps.ingestion.src.symbol_worker.execute_values", _fake_execute_values)

    settings = SimpleNamespace(ingestion_history_days=10, ingestion_yfinance_enabled=False)
    worker = SymbolIngestionWorker(
        settings,
        price_store=SimpleNamespace(),
        broker_client=SimpleNamespace(),
        db_factory=lambda: _DummyConn(),
        span=None,
        logger=SimpleNamespace(info=lambda *_a, **_k: None),
        download_failures=_DummyCounter(),
    )

    worker._upsert_technicals(
        _DummyConn(),
        date_key=20260116,
        stock_key=42,
        technicals={
            "sma20": 100.5,
            "macd": -0.7,
            "skip_none": None,
            "skip_nan": np.nan,
        },
    )

    assert captured.get("calls") == 1
    assert captured.get("template") == "(%s, %s, %s, %s)"
    rows = captured.get("values")
    assert rows == [
        (20260116, 42, "SMA20", 100.5),
        (20260116, 42, "MACD", -0.7),
    ]


def test_symbol_worker_run_records_duration_with_status(monkeypatch):
    hist = _DurationHistogram()
    monkeypatch.setattr("apps.ingestion.src.symbol_worker.SYMBOL_PROCESS_DURATION", hist)

    settings = SimpleNamespace(ingestion_history_days=10, ingestion_yfinance_enabled=False)
    worker = SymbolIngestionWorker(
        settings,
        price_store=SimpleNamespace(),
        broker_client=SimpleNamespace(),
        db_factory=lambda: _DummyConn(),
        span=None,
        logger=SimpleNamespace(info=lambda *_a, **_k: None),
        download_failures=_DummyCounter(),
    )
    monkeypatch.setattr(
        worker,
        "_process_symbol",
        lambda *_a, **_k: SymbolResult("AAPL", date(2026, 1, 16)),
    )

    out = worker.run("AAPL")

    assert out.last_trade_date == date(2026, 1, 16)
    assert hist.statuses == ["success"]
    assert len(hist.recorder.values) == 1


def test_symbol_worker_run_records_no_data_status(monkeypatch):
    hist = _DurationHistogram()
    monkeypatch.setattr("apps.ingestion.src.symbol_worker.SYMBOL_PROCESS_DURATION", hist)

    settings = SimpleNamespace(ingestion_history_days=10, ingestion_yfinance_enabled=False)
    worker = SymbolIngestionWorker(
        settings,
        price_store=SimpleNamespace(),
        broker_client=SimpleNamespace(),
        db_factory=lambda: _DummyConn(),
        span=None,
        logger=SimpleNamespace(info=lambda *_a, **_k: None),
        download_failures=_DummyCounter(),
    )
    monkeypatch.setattr(
        worker,
        "_process_symbol",
        lambda *_a, **_k: SymbolResult("AAPL", None),
    )

    out = worker.run("AAPL")

    assert out.last_trade_date is None
    assert hist.statuses == ["no_data"]
    assert len(hist.recorder.values) == 1
