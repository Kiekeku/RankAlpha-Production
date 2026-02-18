from __future__ import annotations

import asyncio
import os
import time
from hashlib import sha256
from typing import Any, Callable, Dict, Optional, Tuple

from .budget import Budget, BudgetLedger
from .costing import preflight_estimate_cost, reconcile_cost


class _InMemoryCache:
    def __init__(self) -> None:
        self._s: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Tuple[Any, int]]:
        now = time.time()
        v = self._s.get(key)
        if not v:
            return None
        val, exp = v
        if now > exp:
            self._s.pop(key, None)
            return None
        return val, int(exp - now)

    def set(self, key: str, val: Any, ttl_s: int) -> None:
        self._s[key] = (val, time.time() + int(ttl_s))


class AIGateway:
    """Async guardrail gateway for LLM and search calls.

    Provides: RPM, daily token/cost budgets, optional in-memory caching, and simple circuit breakers.
    """

    def __init__(
        self,
        *,
        service: str,
        budget: Budget | None = None,
        rpm_concurrency: int | None = None,
        counter: Optional[Any] = None,
        cache: Optional[_InMemoryCache] = None,
    ) -> None:
        self.service = service
        self.ledger = BudgetLedger(service=service, budget=budget, counter=counter)
        self._sem = asyncio.Semaphore(
            int(os.getenv("AI_MAX_CONCURRENCY", str(rpm_concurrency or 4)))
        )
        self._circuit: Dict[str, Tuple[float, int]] = {}
        self._cache = cache or _InMemoryCache()

    def _circuit_open(self, name: str, cool_s: int = 120) -> bool:
        opened_at, _ = self._circuit.get(name, (0.0, 0))
        return (time.time() - opened_at) < cool_s

    def _record_failure(self, name: str, threshold: int = 5) -> None:
        opened_at, fails = self._circuit.get(name, (0.0, 0))
        fails += 1
        if fails >= threshold:
            self._circuit[name] = (time.time(), 0)
        else:
            self._circuit[name] = (opened_at, fails)

    async def call_llm(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        do_request: Callable[[str, str, str], Any],  # must be awaitable
        max_retries: int = 1,
        timeout_s: int = 30,
        cache_ttl_s: int = 24 * 3600,
    ) -> Dict[str, Any]:
        if os.getenv("AI_DISABLE", "0").lower() in {"1", "true", "yes"}:
            raise RuntimeError("AI disabled by AI_DISABLE=1")
        if os.getenv("AI_DRY_RUN", "0").lower() in {"1", "true", "yes"}:
            return {"dry_run": True}

        # Cache by model+system+prompt hash
        key = sha256(f"llm|{model}|{system}|{prompt}".encode("utf-8")).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            return cached[0]

        if self._circuit_open("llm"):
            raise RuntimeError("LLM circuit open; try later")

        # Preflight budget reservation (best-effort)
        est_in, est_cost = preflight_estimate_cost(model, system, prompt)
        reservation = self.ledger.begin_call(tokens_estimate=est_in, cost_estimate_usd=est_cost)

        last_err: Optional[Exception] = None
        async with self._sem:
            for attempt in range(max_retries + 1):
                try:
                    fut = asyncio.wait_for(do_request(model, system, prompt), timeout_s)
                    result = await fut
                    # Expect result to contain usage or text for reconciliation
                    ti, to, actual = reconcile_cost(
                        model, result if isinstance(result, dict) else {}, est_in
                    )
                    self.ledger.commit(ti, to, actual, reservation=reservation)
                    self._circuit["llm"] = (0.0, 0)
                    self._cache.set(key, result, cache_ttl_s)
                    return result
                except Exception as e:
                    last_err = e
                    self._record_failure("llm")
                    await asyncio.sleep(0.5 * (attempt + 1))
        # Propagate last error
        assert last_err is not None
        raise last_err

    async def call_search(
        self,
        *,
        provider: str,
        query: str,
        do_search: Callable[[str], Any],  # must be awaitable
        per_query_cap: int = 10,
        cache_ttl_s: int = 6 * 3600,
    ) -> Any:
        if os.getenv("SEARCH_DISABLE", "0").lower() in {"1", "true", "yes"}:
            return []
        qnorm = " ".join((query or "").lower().split())[:256]
        key = sha256(f"search|{provider}|{qnorm}".encode("utf-8")).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            return cached[0]
        if self._circuit_open("search"):
            raise RuntimeError("Search circuit open; try later")

        # Budget reservation: count 1 request, optionally apply per-query cost if configured
        self.ledger.reserve_request()
        # Per-query cost gating (if SEARCH_*_COST_USD provided, use it)
        # We reuse calc_llm_cost for ledger plumbing, but this is search cost only
        # so we just increment dollars; tokens remain unaffected here.
        cost_override = float(os.getenv("SEARCH_COST_USD", "0.0") or 0.0)
        if cost_override > 0:
            self.ledger.reserve_cost(cost_override)

        async with self._sem:
            try:
                res = await asyncio.wait_for(do_search(qnorm), 15)
                # Trim fan-out per query
                if isinstance(res, list):
                    res = res[:per_query_cap]
                self._circuit["search"] = (0.0, 0)
                self._cache.set(key, res, cache_ttl_s)
                return res
            except Exception as e:
                self._record_failure("search")
                raise e
