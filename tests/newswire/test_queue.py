from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from apps.common.src.news_utils.queue import enqueue_sentiment_analysis


class _FakeQuery:
    def __init__(self, *, one=None, first=None):
        self._one = one
        self._first = first

    def filter(self, *_a, **_k):  # pragma: no cover
        return self

    def one_or_none(self):
        return self._one

    def first(self):
        return self._first


class _FakeDB:
    def __init__(self, *, symbol_row=None, existing_queue=None, execute_rowcount=1, raise_execute=False):
        self.symbol_row = symbol_row
        self.existing_queue = existing_queue
        self.execute_rowcount = execute_rowcount
        self.raise_execute = raise_execute
        self.execute_calls = 0

    def query(self, model_or_col):  # type: ignore[no-untyped-def]
        # DimStock.symbol lookup -> returns tuple like ("AAPL",)
        name = getattr(model_or_col, "__name__", None) or str(model_or_col)
        if "DimStock" in name or "DimStock.symbol" in name:
            return _FakeQuery(one=self.symbol_row)
        # SentimentAnalysisQueue guard query -> .first()
        return _FakeQuery(first=self.existing_queue)

    def execute(self, _stmt):  # type: ignore[no-untyped-def]
        self.execute_calls += 1
        if self.raise_execute:
            raise RuntimeError("boom")
        return SimpleNamespace(rowcount=self.execute_rowcount)


def test_enqueue_sentiment_analysis_resolves_symbol_and_inserts():
    db = _FakeDB(symbol_row=("aapl",), existing_queue=None, execute_rowcount=1)
    ok = enqueue_sentiment_analysis(db, stock_key=1, title="t", url="u")
    assert ok is True
    assert db.execute_calls == 1


def test_enqueue_sentiment_analysis_skips_when_guard_finds_existing():
    db = _FakeDB(symbol_row=("AAPL",), existing_queue=("existing",), execute_rowcount=1)
    ok = enqueue_sentiment_analysis(db, stock_key=1)
    assert ok is False
    assert db.execute_calls == 0


def test_enqueue_sentiment_analysis_returns_false_when_symbol_missing():
    db = _FakeDB(symbol_row=None, existing_queue=None)
    ok = enqueue_sentiment_analysis(db, stock_key=1)
    assert ok is False


def test_enqueue_sentiment_analysis_handles_execute_errors():
    db = _FakeDB(symbol_row=("AAPL",), existing_queue=None, raise_execute=True)
    ok = enqueue_sentiment_analysis(db, stock_key=1, run_after_ts=datetime.now(timezone.utc))
    assert ok is False

