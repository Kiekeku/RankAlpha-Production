from __future__ import annotations

import pytest
from apps.ingestion.src.ingestion_runner import IngestionRunner


class _DummySpan:
    def __init__(self) -> None:
        self.attrs: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attrs[key] = value


class _Recorder:
    def __init__(self) -> None:
        self.observed: list[float] = []

    def observe(self, value: float) -> None:
        self.observed.append(float(value))


class _HistogramSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.recorder = _Recorder()

    def labels(self, *, phase: str, status: str) -> _Recorder:
        self.calls.append((phase, status))
        return self.recorder


class _LoggerSpy:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, msg: str, *args) -> None:  # type: ignore[no-untyped-def]
        self.messages.append(msg % args if args else msg)


def test_record_phase_duration_observes_and_sets_span_attributes(monkeypatch):
    runner = IngestionRunner.__new__(IngestionRunner)
    runner._span = _DummySpan()  # type: ignore[attr-defined]
    hist = _HistogramSpy()
    monkeypatch.setattr("apps.ingestion.src.ingestion_runner.INGESTION_PHASE_DURATION", hist)
    monkeypatch.setattr("apps.ingestion.src.ingestion_runner.time.perf_counter", lambda: 10.0)

    runner._record_phase_duration(phase="symbol_pool", started_at=7.5, status="success")

    assert hist.calls == [("symbol_pool", "success")]
    assert hist.recorder.observed == [2.5]
    assert runner._span.attrs["ingestion.phase.symbol_pool.seconds"] == 2.5
    assert runner._span.attrs["ingestion.phase.symbol_pool.status"] == "success"


def test_run_timed_phase_records_error_status_on_exception():
    runner = IngestionRunner.__new__(IngestionRunner)
    recorded: list[tuple[str, str]] = []

    def _capture(*, phase: str, started_at: float, status: str) -> None:
        recorded.append((phase, status))

    runner._record_phase_duration = _capture  # type: ignore[method-assign]

    def _boom() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        runner._run_timed_phase("cache_refresh", _boom)

    assert recorded == [("cache_refresh", "error")]


def test_maybe_log_symbol_progress_logs_first_interval_and_last(monkeypatch):
    runner = IngestionRunner.__new__(IngestionRunner)
    logger = _LoggerSpy()
    runner._logger = logger  # type: ignore[attr-defined]
    monkeypatch.setattr("apps.ingestion.src.ingestion_runner.time.perf_counter", lambda: 20.0)

    runner._maybe_log_symbol_progress(processed=1, total=10, every=5, started_at=10.0)
    runner._maybe_log_symbol_progress(processed=3, total=10, every=5, started_at=10.0)
    runner._maybe_log_symbol_progress(processed=5, total=10, every=5, started_at=10.0)
    runner._maybe_log_symbol_progress(processed=10, total=10, every=5, started_at=10.0)

    assert len(logger.messages) == 3
    assert "1/10" in logger.messages[0]
    assert "5/10" in logger.messages[1]
    assert "10/10" in logger.messages[2]
