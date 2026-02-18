from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from .pricing import load_pricing

SAFETY = float(os.getenv("COST_SAFETY_MARGIN", "1.25"))


def estimate_tokens(text: str, model_hint: str = "") -> int:
    """Estimate tokens using tokenizer if available; fallback to chars/4 heuristic.

    Clamp to a generous upper bound to avoid overflow during preflight.
    """
    try:  # optional tiktoken
        import tiktoken  # type: ignore

        # Use a common encoding; exact model encoding not critical for bounds checking
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text or ""))
    except Exception:
        s = text or ""
        return max(1, min(len(s) // 4, 200_000))


def extract_usage(result: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """Normalize usage fields from different providers to (tokens_in, tokens_out)."""
    u = result.get("usage") or {}
    ti = u.get("prompt_tokens") or u.get("input_tokens")
    to = u.get("completion_tokens") or u.get("output_tokens")
    ti = int(ti) if isinstance(ti, int) else None
    to = int(to) if isinstance(to, int) else None
    return ti, to


def calc_llm_cost_usd(tokens_in: int, tokens_out: int, model: str, apply_safety: bool) -> float:
    pricing = load_pricing().lookup(model) or load_pricing().lookup("fallback")
    base = 0.0
    if pricing:
        base = (
            (tokens_in / 1000.0) * pricing.input_per_1k
            + (tokens_out / 1000.0) * pricing.output_per_1k
            + pricing.request_fixed
        )
    return round(base * (SAFETY if apply_safety else 1.0), 6)


def preflight_estimate_cost(model: str, system_text: str, user_text: str) -> Tuple[int, float]:
    """Rough, fast preflight cost estimate used for gating.

    Returns (est_tokens_in, est_cost_usd_with_safety_factor)
    """
    est_in = estimate_tokens(system_text) + estimate_tokens(user_text)
    est_cost = calc_llm_cost_usd(est_in, 0, model, apply_safety=True)
    return est_in, est_cost


def reconcile_cost(model: str, result: Dict[str, Any], fallback_in: int) -> Tuple[int, int, float]:
    """Reconcile final cost using provider-reported usage; fallback to tokenizing output text.

    Returns (tokens_in, tokens_out, actual_cost_usd)
    """
    ti, to = extract_usage(result)
    if ti is None:
        ti = fallback_in
    if to is None:
        out_text = result.get("text") or result.get("output") or ""
        to = estimate_tokens(out_text)
    actual = calc_llm_cost_usd(int(ti), int(to), model, apply_safety=False)
    return int(ti), int(to), actual
