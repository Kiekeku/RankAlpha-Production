from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.scorer.src.main import evaluate_stage_drift
from apps.scorer.src.main import _enforce_stage_drift_guard


def test_evaluate_stage_drift_detects_eligible_to_asof_violation():
    summary, violations = evaluate_stage_drift(
        {"eligible": 100, "asof_pass": 30, "momentum_valid": 25},
        min_asof_ratio=0.5,
        min_momentum_ratio=0.5,
    )

    assert summary["asof_ratio"] == 0.3
    assert summary["momentum_ratio"] == (25.0 / 30.0)
    assert any(v.startswith("eligible_to_asof") for v in violations)
    assert not any(v.startswith("asof_to_momentum") for v in violations)


def test_evaluate_stage_drift_detects_asof_to_momentum_violation():
    summary, violations = evaluate_stage_drift(
        {"eligible": 100, "asof_pass": 80, "momentum_valid": 20},
        min_asof_ratio=0.5,
        min_momentum_ratio=0.5,
    )

    assert summary["asof_ratio"] == 0.8
    assert summary["momentum_ratio"] == 0.25
    assert any(v.startswith("asof_to_momentum") for v in violations)
    assert not any(v.startswith("eligible_to_asof") for v in violations)


def test_evaluate_stage_drift_no_violation_when_ratios_healthy():
    _summary, violations = evaluate_stage_drift(
        {"eligible": 200, "asof_pass": 150, "momentum_valid": 120},
        min_asof_ratio=0.5,
        min_momentum_ratio=0.5,
    )
    assert violations == []


def test_enforce_stage_drift_guard_raises_on_violation():
    settings = SimpleNamespace(
        scoring_asof_pass_min_ratio=0.5,
        scoring_momentum_valid_min_ratio=0.5,
    )

    class _Span:
        def set_attribute(self, *_a, **_k):  # pragma: no cover - no-op
            return None

    with pytest.raises(RuntimeError, match="Scorer drift guard triggered"):
        _enforce_stage_drift_guard(
            {"eligible": 100, "asof_pass": 30, "momentum_valid": 20},
            settings=settings,
            logger=SimpleNamespace(info=lambda *_a, **_k: None),
            span=_Span(),
        )


def test_enforce_stage_drift_guard_returns_summary_when_healthy():
    settings = SimpleNamespace(
        scoring_asof_pass_min_ratio=0.5,
        scoring_momentum_valid_min_ratio=0.5,
    )

    class _Span:
        def set_attribute(self, *_a, **_k):  # pragma: no cover - no-op
            return None

    summary = _enforce_stage_drift_guard(
        {"eligible": 200, "asof_pass": 150, "momentum_valid": 120},
        settings=settings,
        logger=SimpleNamespace(info=lambda *_a, **_k: None),
        span=_Span(),
    )
    assert summary["eligible"] == 200
    assert summary["asof_pass"] == 150
    assert summary["momentum_valid"] == 120
