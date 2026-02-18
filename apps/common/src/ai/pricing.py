from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Optional

try:  # optional dependency
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


@dataclass
class ModelPricing:
    input_per_1k: float
    output_per_1k: float
    request_fixed: float = 0.0
    image_per_unit: float = 0.0
    audio_per_min: float = 0.0


class PricingCatalog:
    """Regex-based pricing lookup for model ids.

    Prices are loaded from a YAML/JSON data source to avoid hardcoding rates in code.
    """

    def __init__(self, entries: Dict[str, ModelPricing]):
        # keys are regex patterns for model ids
        self._entries = [(re.compile(p), v) for p, v in entries.items()]

    def lookup(self, model: str) -> Optional[ModelPricing]:
        for rx, val in self._entries:
            try:
                if rx.search(model):
                    return val
            except Exception:
                continue
        return None


@lru_cache(maxsize=1)
def load_pricing() -> PricingCatalog:
    """Load pricing from env JSON, YAML file, or conservative defaults.

    Precedence:
      - AI_PRICING_JSON (JSON string)
      - AI_PRICING_YAML path (YAML file)
      - apps/common/config/pricing.yaml if present
      - fallback placeholders (all zeros)
    """
    env_json = os.getenv("AI_PRICING_JSON")
    data: Dict[str, Any]
    if env_json:
        data = json.loads(env_json)
    else:
        path = os.getenv("AI_PRICING_YAML", "apps/common/config/pricing.yaml")
        data = {"models": {}}
        if yaml is not None:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    file_data = yaml.safe_load(f) or {}
                    if isinstance(file_data, dict):
                        data = file_data
            except FileNotFoundError:
                # leave data empty -> fallback below
                pass
        # If no yaml module, skip file loading silently

    # Fallback placeholders (do not error if missing)
    if not data.get("models"):
        data = {
            "models": {
                r"^gpt-4o.*": {"input_per_1k": 0.0, "output_per_1k": 0.0},
                r"^gpt-4o-mini.*": {"input_per_1k": 0.0, "output_per_1k": 0.0},
                r"^gpt-5.*": {"input_per_1k": 0.0, "output_per_1k": 0.0},
                r"^claude-3.*": {"input_per_1k": 0.0, "output_per_1k": 0.0},
                r"^text-embedding.*": {"input_per_1k": 0.0, "output_per_1k": 0.0},
                r"fallback": {"input_per_1k": 0.0, "output_per_1k": 0.0},
            }
        }

    entries: Dict[str, ModelPricing] = {}
    for pat, vals in (data.get("models") or {}).items():
        try:
            entries[str(pat)] = ModelPricing(**vals)
        except Exception:
            # ignore malformed entries
            continue
    return PricingCatalog(entries)


def search_cost(provider: str) -> float:
    """Return per-query cost for a given search provider.

    Override via env:
      - SEARCH_SERPAPI_COST_USD, SEARCH_GOOGLE_CSE_COST_USD, SEARCH_SERPER_COST_USD,
        SEARCH_DEFAULT_COST_USD
    """
    m = {
        "serpapi": float(
            os.getenv("SEARCH_SERPAPI_COST_USD", os.getenv("SEARCH_DEFAULT_COST_USD", "0.00"))
        ),
        "google_cse": float(
            os.getenv("SEARCH_GOOGLE_CSE_COST_USD", os.getenv("SEARCH_DEFAULT_COST_USD", "0.00"))
        ),
        "serper": float(
            os.getenv("SEARCH_SERPER_COST_USD", os.getenv("SEARCH_DEFAULT_COST_USD", "0.00"))
        ),
        "free": 0.0,
    }
    return m.get(provider, float(os.getenv("SEARCH_DEFAULT_COST_USD", "0.00")))
