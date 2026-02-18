from __future__ import annotations

import pytest
from apps.scorer.src.settings import Settings


@pytest.fixture(autouse=True)
def _base_env(monkeypatch):
    monkeypatch.setenv("DATABASE_NAME", "db")
    monkeypatch.setenv("DB_USERNAME", "user")
    monkeypatch.setenv("PASSWORD", "pass")
    monkeypatch.setenv("HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")


def test_scorer_settings_parses_types_and_defaults(monkeypatch):
    monkeypatch.setenv("SCORING_MOMENTUM_MIN_VALID_FRAC", "0.75")
    monkeypatch.setenv("SCORING_WEIGHT_FORCE", "true")
    monkeypatch.setenv("SCORING_VIX_FFILL_LIMIT", "3")

    s = Settings()
    assert s.scoring_momentum_min_valid_frac == 0.75
    assert s.scoring_weight_force is True
    assert s.scoring_vix_ffill_limit == 3
    assert s.scoring_momentum_composite_mode == "blend"
    assert s.scoring_asof_pass_min_ratio == 0.5
    assert s.scoring_momentum_valid_min_ratio == 0.5
