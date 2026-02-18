from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from apps.common.src.portfolio.construction import (
    _require_broker_run_execution_day,
    _require_fresh_risk_report,
)


def test_require_broker_run_execution_day_rejects_wrong_day(monkeypatch):
    run = SimpleNamespace(run_id=uuid.uuid4(), as_of_date=date(2026, 1, 15))

    class FakeSession:
        def scalar(self, *_args, **_kwargs):
            return date(2026, 1, 16)  # next trading day after as_of_date

    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._eastern_today",
        lambda: date(2026, 1, 17),
    )

    with pytest.raises(ValueError, match="create a new run"):
        _require_broker_run_execution_day(FakeSession(), run=run)


def test_require_broker_run_execution_day_accepts_on_execution_day(monkeypatch):
    run = SimpleNamespace(run_id=uuid.uuid4(), as_of_date=date(2026, 1, 15))

    class FakeSession:
        def scalar(self, *_args, **_kwargs):
            return date(2026, 1, 16)

    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._eastern_today",
        lambda: date(2026, 1, 16),
    )

    exec_day = _require_broker_run_execution_day(FakeSession(), run=run)
    assert exec_day == date(2026, 1, 16)


def test_require_fresh_risk_report_requires_report():
    run = SimpleNamespace(run_id=uuid.uuid4(), updated_at=datetime(2026, 1, 16, tzinfo=UTC))

    class FakeSession:
        def get(self, *_args, **_kwargs):
            return None

    with pytest.raises(ValueError, match="risk report missing"):
        _require_fresh_risk_report(FakeSession(), run=run)


def test_require_fresh_risk_report_rejects_fail_status():
    report = SimpleNamespace(
        evaluated_at=datetime(2026, 1, 16, 12, 0, tzinfo=UTC),
        status="FAIL",
    )
    run = SimpleNamespace(run_id=uuid.uuid4(), updated_at=datetime(2026, 1, 16, tzinfo=UTC))

    class FakeSession:
        def get(self, *_args, **_kwargs):
            return report

        def scalar(self, *_args, **_kwargs):
            return None

    with pytest.raises(ValueError, match="risk status FAIL"):
        _require_fresh_risk_report(FakeSession(), run=run)


def test_require_fresh_risk_report_rejects_stale_report():
    report = SimpleNamespace(
        evaluated_at=datetime(2026, 1, 16, 12, 0, tzinfo=UTC),
        status="PASS",
    )
    run = SimpleNamespace(run_id=uuid.uuid4(), updated_at=datetime(2026, 1, 16, 12, 30, tzinfo=UTC))

    class FakeSession:
        def __init__(self):
            self._scalar_values = [
                datetime(2026, 1, 16, 12, 45, tzinfo=UTC),  # max order update
                None,  # max position update
            ]

        def get(self, *_args, **_kwargs):
            return report

        def scalar(self, *_args, **_kwargs):
            return self._scalar_values.pop(0)

    with pytest.raises(ValueError, match="risk report is stale"):
        _require_fresh_risk_report(FakeSession(), run=run)


def test_require_fresh_risk_report_accepts_fresh_report():
    report = SimpleNamespace(
        evaluated_at=datetime(2026, 1, 16, 13, 0, tzinfo=UTC),
        status="PASS",
    )
    run = SimpleNamespace(run_id=uuid.uuid4(), updated_at=datetime(2026, 1, 16, 12, 30, tzinfo=UTC))

    class FakeSession:
        def __init__(self):
            self._scalar_values = [
                datetime(2026, 1, 16, 12, 45, tzinfo=UTC),
                None,
            ]

        def get(self, *_args, **_kwargs):
            return report

        def scalar(self, *_args, **_kwargs):
            return self._scalar_values.pop(0)

    _require_fresh_risk_report(FakeSession(), run=run)
