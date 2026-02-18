from __future__ import annotations

import pytest

from apps.common.src.portfolio.construction import _parse_model_strategy_blend


def test_parse_model_strategy_blend_valid():
    cfg = {
        "strategy_blend": {
            "strategies": [
                {"source_name": "S1", "strategy_name": "A", "weight_pct": 40},
                {"source_name": "S1", "strategy_name": "B", "weight_pct": 30},
                {"source_name": "S1", "strategy_name": "D", "weight_pct": 30},
            ]
        }
    }
    items = _parse_model_strategy_blend(cfg)
    assert len(items) == 3
    assert sum(x["weight_pct"] for x in items if x["enabled"]) == 100


def test_parse_model_strategy_blend_rejects_duplicate_pairs():
    cfg = {
        "strategy_blend": {
            "strategies": [
                {"source_name": "S1", "strategy_name": "A", "weight_pct": 50},
                {"source_name": "S1", "strategy_name": "A", "weight_pct": 50},
            ]
        }
    }
    with pytest.raises(ValueError, match="Duplicate strategy entry"):
        _parse_model_strategy_blend(cfg)


def test_parse_model_strategy_blend_rejects_non_100_sum():
    cfg = {
        "strategy_blend": {
            "strategies": [
                {"source_name": "S1", "strategy_name": "A", "weight_pct": 60},
                {"source_name": "S1", "strategy_name": "B", "weight_pct": 30},
            ]
        }
    }
    with pytest.raises(ValueError, match="must sum to 100"):
        _parse_model_strategy_blend(cfg)

