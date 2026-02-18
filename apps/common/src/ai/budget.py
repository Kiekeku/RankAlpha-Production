from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from apps.common.src.ai.notifications import BudgetAlertEvent, send_budget_alert

try:  # pragma: no cover - optional dependency
    from apps.common.src.observability import get_or_create_gauge
except Exception:  # pragma: no cover - keep budget usable without prometheus
    get_or_create_gauge = None  # type: ignore[assignment]


@dataclass
class Budget:
    max_requests_per_min: int = int(os.getenv("AI_RPM", "120") or 120)
    max_tokens_per_day: int = int(os.getenv("AI_MAX_DAILY_TOKENS", "2000000") or 2_000_000)
    max_cost_usd_per_day: float = float(os.getenv("AI_MAX_DAILY_COST_USD", "25.0") or 25.0)


class InMemoryCounter:
    """Very small TTL counter store for per-process budgets.

    This is intentionally simple and sufficient for a single-process worker.
    """

    def __init__(self):
        self._c: dict[str, tuple[float, float]] = {}

    def incr(self, key: str, amount: float, ttl_s: int) -> float:
        now = time.time()
        val, exp = self._c.get(key, (0.0, now + ttl_s))
        if now > exp:
            val, exp = 0.0, now + ttl_s
        val += float(amount)
        self._c[key] = (val, exp)
        return val

    def get(self, key: str) -> float:
        now = time.time()
        val, exp = self._c.get(key, (0.0, now))
        if now > exp:
            return 0.0
        return float(val)


# Optional Redis-backed counter for cross-process budgets
class RedisCounter:
    def __init__(self, client: Any) -> None:
        self._client = client

    def incr(self, key: str, amount: float, ttl_s: int) -> float:
        p = self._client.pipeline(transaction=False)
        p.incrbyfloat(key, float(amount))
        # Always set/refresh TTL so inactive keys eventually expire
        p.expire(key, int(ttl_s))
        val, _ = p.execute()
        try:
            return float(val)
        except Exception:
            return 0.0

    def get(self, key: str) -> float:
        val = self._client.get(key)
        try:
            return float(val or 0.0)
        except Exception:
            return 0.0

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception:
            pass


def get_redis_counter_from_env() -> Optional[RedisCounter]:
    """Best-effort Redis counter constructor.

    Looks for REDIS_URL or (REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD) envs.
    Returns None if redis is not installed or connection fails.
    """
    try:
        import redis  # type: ignore
    except Exception:
        return None
    url = os.getenv("REDIS_URL") or os.getenv("CACHE_URL")
    common_kwargs = dict(decode_responses=True, socket_timeout=0.3, socket_connect_timeout=0.2)
    try:
        if url:
            client = redis.from_url(url, **common_kwargs)
        else:
            host = os.getenv("REDIS_HOST", "localhost")
            port = int(os.getenv("REDIS_PORT", "6379"))
            db = int(os.getenv("REDIS_DB", "0"))
            password = os.getenv("REDIS_PASSWORD") or None
            client = redis.Redis(host=host, port=port, db=db, password=password, **common_kwargs)
        # quick ping validation
        try:
            if not client.ping():
                return None
        except Exception:
            return None
        return RedisCounter(client)
    except Exception:
        return None


@dataclass
class CallReservation:
    tokens_est: int
    cost_est: float
    date_str: str  # date bucket when the reservation was made (UTC yyyymmdd)


logger = logging.getLogger(__name__)

_AI_BUDGET_USED_USD = None
_AI_BUDGET_LIMIT_USD = None
_AI_BUDGET_USAGE_RATIO = None
try:  # pragma: no cover - optional dependency / registry errors
    if get_or_create_gauge is not None:
        _AI_BUDGET_USED_USD = get_or_create_gauge(
            "rankalpha_ai_budget_used",
            "Current AI budget usage for the day (tokens or USD), by service and metric.",
            labelnames=("service", "metric"),
        )
        _AI_BUDGET_LIMIT_USD = get_or_create_gauge(
            "rankalpha_ai_budget_limit",
            "Current AI budget limit for the day (tokens or USD), by service and metric.",
            labelnames=("service", "metric"),
        )
        _AI_BUDGET_USAGE_RATIO = get_or_create_gauge(
            "rankalpha_ai_budget_usage_ratio",
            "Current AI budget usage ratio (used / limit) for the day, by service and metric.",
            labelnames=("service", "metric"),
        )
except Exception:  # pragma: no cover - keep budget ledger functional if metrics fail
    _AI_BUDGET_USED_USD = None
    _AI_BUDGET_LIMIT_USD = None
    _AI_BUDGET_USAGE_RATIO = None


class BudgetLedger:
    """Lightweight, synchronous budget ledger used by guards and wrappers.

    Tracks RPM, daily tokens, and daily cost; raises RuntimeError on limit breach.
    """

    def __init__(
        self,
        *,
        service: str,
        budget: Budget | None = None,
        counter: Optional[Any] = None,
        now: Callable[[], float] | None = None,
        alert_handler: Optional[Callable[[BudgetAlertEvent], None]] = None,
    ) -> None:
        self.service = service
        self.budget = budget or Budget()
        self.counter = counter or InMemoryCounter()
        self._now = now or time.time
        self._alert_handler = alert_handler or send_budget_alert
        self._alert_thresholds: Tuple[float, ...] = (0.80, 1.00)
        self._alert_cache: dict[tuple[str, float, str], bool] = {}

    def _k(self, *parts: str) -> str:
        return f"{self.service}:" + ":".join(parts)

    def _date_str(self) -> str:
        return time.strftime("%Y%m%d", time.gmtime(self._now()))

    def _usage_snapshot(self) -> dict[str, Any]:
        """Return a snapshot of current budget usage for logging/debugging."""
        date_str = self._date_str()
        snapshot: dict[str, Any] = {
            "usage_date_utc": date_str,
            "rpm_limit_per_minute": float(self.budget.max_requests_per_min or 0),
            "tokens_limit_per_day": float(self.budget.max_tokens_per_day or 0),
            "cost_limit_per_day": float(self.budget.max_cost_usd_per_day or 0.0),
        }
        try:
            snapshot["rpm_used_last_minute"] = self._get_counter_value(self._k("rpm"))
        except Exception:
            snapshot["rpm_used_last_minute"] = 0.0
        try:
            snapshot["tokens_used_today"] = self._get_counter_value(self._k("tokens", date_str))
        except Exception:
            snapshot["tokens_used_today"] = 0.0
        try:
            snapshot["cost_used_today"] = self._get_counter_value(self._k("cost", date_str))
        except Exception:
            snapshot["cost_used_today"] = 0.0
        return snapshot

    def _log_guardrail_hit(
        self,
        *,
        guard: str,
        message: str,
        limit: float,
        used_before: float,
        attempted_increment: float,
        used_after: float | None = None,
    ) -> None:
        try:
            snapshot = self._usage_snapshot()
        except Exception:
            snapshot = {}
        payload: dict[str, Any] = {
            "service": self.service,
            "guard": guard,
            "message": message,
            "limit": float(limit),
            "used_before_rollback": float(used_before),
            "attempt_increment": float(attempted_increment),
        }
        if used_after is not None:
            payload["used_after_rollback"] = float(used_after)
        if snapshot:
            payload.update(snapshot)
        try:
            logger.error(
                "Budget guard triggered",
                extra={"service": self.service, "guard": guard, "budget_usage": payload},
            )
        except Exception:
            logger.error(
                "Budget guard triggered (logging payload failed)",
                extra={"service": self.service, "guard": guard},
            )

    @staticmethod
    def _format_number(value: float | int | None) -> str:
        if value is None:
            return "0"
        try:
            return format(float(value), "g")
        except Exception:
            return str(value)

    def _build_guardrail_detail(
        self,
        *,
        limit: float,
        used_before: float,
        attempted_increment: float,
        used_after: float | None = None,
    ) -> str:
        parts = [
            f"limit={self._format_number(limit)}",
            f"used_before={self._format_number(used_before)}",
            f"attempt={self._format_number(attempted_increment)}",
        ]
        if used_after is not None:
            parts.append(f"used_after={self._format_number(used_after)}")
        try:
            snapshot = self._usage_snapshot()
        except Exception:
            snapshot = None
        if snapshot:
            subset_keys = (
                "usage_date_utc",
                "rpm_limit_per_minute",
                "rpm_used_last_minute",
                "tokens_limit_per_day",
                "tokens_used_today",
                "cost_limit_per_day",
                "cost_used_today",
            )
            compact_snapshot = {k: snapshot.get(k) for k in subset_keys if k in snapshot}
            try:
                parts.append(f"usage_snapshot={json.dumps(compact_snapshot, sort_keys=True)}")
            except Exception:
                parts.append(f"usage_snapshot={compact_snapshot}")
        return ", ".join(parts)

    def reserve_request(self) -> None:
        key = self._k("rpm")
        used = self.counter.incr(key, 1, 60)
        if used > self.budget.max_requests_per_min:
            # roll back the increment so smaller requests can still proceed
            rolled_back = None
            try:
                rolled_back = self.counter.incr(key, -1, 60)
            finally:
                pass
            try:
                self._log_guardrail_hit(
                    guard="requests_per_minute",
                    message="Rate limit exceeded for LLM/search",
                    limit=float(self.budget.max_requests_per_min or 0),
                    used_before=float(used),
                    attempted_increment=1.0,
                    used_after=float(rolled_back) if rolled_back is not None else None,
                )
            except Exception:
                logger.debug("Failed to log RPM guardrail event", extra={"service": self.service})
            detail = ""
            try:
                detail = self._build_guardrail_detail(
                    limit=float(self.budget.max_requests_per_min or 0),
                    used_before=float(used),
                    attempted_increment=1.0,
                    used_after=float(rolled_back) if rolled_back is not None else None,
                )
            except Exception:
                detail = ""
            message = "Rate limit exceeded for LLM/search"
            if detail:
                message = f"{message} ({detail})"
            raise RuntimeError(message)

    def reserve_tokens(self, tokens_estimate: int) -> None:
        key = self._k("tokens", self._date_str())
        amount = int(tokens_estimate)
        used = self.counter.incr(key, amount, 86400)
        if used > self.budget.max_tokens_per_day:
            # roll back over-reservation
            rolled_back = None
            try:
                rolled_back = self.counter.incr(key, -amount, 86400)
            finally:
                pass
            try:
                self._log_guardrail_hit(
                    guard="tokens_per_day",
                    message="Daily token budget exceeded",
                    limit=float(self.budget.max_tokens_per_day or 0),
                    used_before=float(used),
                    attempted_increment=float(amount),
                    used_after=float(rolled_back) if rolled_back is not None else None,
                )
            except Exception:
                logger.debug("Failed to log token guardrail event", extra={"service": self.service})
            detail = ""
            try:
                detail = self._build_guardrail_detail(
                    limit=float(self.budget.max_tokens_per_day or 0),
                    used_before=float(used),
                    attempted_increment=float(amount),
                    used_after=float(rolled_back) if rolled_back is not None else None,
                )
            except Exception:
                detail = ""
            message = "Daily token budget exceeded"
            if detail:
                message = f"{message} ({detail})"
            raise RuntimeError(message)

    def reserve_cost(self, cost_estimate_usd: float) -> None:
        key = self._k("cost", self._date_str())
        amount = float(cost_estimate_usd)
        used = self.counter.incr(key, amount, 86400)
        if used > self.budget.max_cost_usd_per_day:
            # roll back over-reservation
            rolled_back = None
            try:
                rolled_back = self.counter.incr(key, -amount, 86400)
            finally:
                pass
            try:
                self._log_guardrail_hit(
                    guard="cost_per_day",
                    message="Daily cost budget exceeded",
                    limit=float(self.budget.max_cost_usd_per_day or 0.0),
                    used_before=float(used),
                    attempted_increment=float(amount),
                    used_after=float(rolled_back) if rolled_back is not None else None,
                )
            except Exception:
                logger.debug("Failed to log cost guardrail event", extra={"service": self.service})
            detail = ""
            try:
                detail = self._build_guardrail_detail(
                    limit=float(self.budget.max_cost_usd_per_day or 0.0),
                    used_before=float(used),
                    attempted_increment=float(amount),
                    used_after=float(rolled_back) if rolled_back is not None else None,
                )
            except Exception:
                detail = ""
            message = "Daily cost budget exceeded"
            if detail:
                message = f"{message} ({detail})"
            raise RuntimeError(message)

    def begin_call(self, *, tokens_estimate: int, cost_estimate_usd: float) -> CallReservation:
        """Atomically reserve RPM + token/cost estimate and return a reservation handle.

        Use with commit(...) to replace the estimate with actuals (via delta increment),
        avoiding double counting.
        """
        # RPM is tracked per minute separately; call sites should also call reserve_request() for RPM
        # but we do it here for convenience so begin_call is a one-stop preflight.
        self.reserve_request()
        self.reserve_tokens(tokens_estimate)
        self.reserve_cost(cost_estimate_usd)
        return CallReservation(
            tokens_est=int(tokens_estimate),
            cost_est=float(cost_estimate_usd),
            date_str=self._date_str(),
        )

    def commit(
        self,
        tokens_in: int,
        tokens_out: int,
        actual_cost_usd: float,
        reservation: CallReservation | None = None,
    ) -> None:
        """Finalize accounting for a call.

        If a reservation is provided, only the positive delta (actual - estimate) is added.
        This prevents double counting; when actual < estimate we do not decrement below the
        reserved amount (conservative usage).
        """
        actual_tokens = max(0, int(tokens_in) + int(tokens_out))
        delta_tokens = actual_tokens
        delta_cost = max(0.0, float(actual_cost_usd))
        if reservation is not None:
            try:
                # If day changed between reservation and commit, do not subtract the previous day's estimate.
                if reservation.date_str != self._date_str():
                    delta_tokens = actual_tokens
                    delta_cost = max(0.0, float(actual_cost_usd))
                else:
                    delta_tokens = max(0, actual_tokens - int(reservation.tokens_est))
                    delta_cost = max(0.0, float(actual_cost_usd) - float(reservation.cost_est))
            except Exception:
                # Fallback to adding actuals if reservation corrupted
                delta_tokens = actual_tokens
                delta_cost = max(0.0, float(actual_cost_usd))
        tokens_key = self._k("tokens", self._date_str())
        cost_key = self._k("cost", self._date_str())
        self.counter.incr(tokens_key, delta_tokens, 86400)
        self.counter.incr(cost_key, delta_cost, 86400)
        try:
            self._evaluate_alerts(tokens_key=tokens_key, cost_key=cost_key)
        except Exception:
            logger.exception("Budget alert evaluation failed", extra={"service": self.service})

    # ------------------------------------------------------------------
    # Alert helpers
    def _evaluate_alerts(self, *, tokens_key: str, cost_key: str) -> None:
        date_str = self._date_str()
        tokens_limit = float(self.budget.max_tokens_per_day or 0)
        cost_limit = float(self.budget.max_cost_usd_per_day or 0.0)
        if tokens_limit > 0:
            tokens_used = self._get_counter_value(tokens_key)
            self._emit_budget_metrics(metric="tokens", used=tokens_used, limit=tokens_limit)
            self._check_metric_alert(
                metric="tokens", used=tokens_used, limit=tokens_limit, date_str=date_str
            )
        if cost_limit > 0:
            cost_used = self._get_counter_value(cost_key)
            self._emit_budget_metrics(metric="cost", used=cost_used, limit=cost_limit)
            self._check_metric_alert(
                metric="cost", used=cost_used, limit=cost_limit, date_str=date_str
            )

    def _emit_budget_metrics(self, *, metric: str, used: float, limit: float) -> None:
        if (
            _AI_BUDGET_USED_USD is None
            or _AI_BUDGET_LIMIT_USD is None
            or _AI_BUDGET_USAGE_RATIO is None
        ):
            return
        try:
            service = str(self.service or "unknown")
            metric_name = str(metric or "unknown")
            _AI_BUDGET_USED_USD.labels(service=service, metric=metric_name).set(float(used))
            _AI_BUDGET_LIMIT_USD.labels(service=service, metric=metric_name).set(float(limit))
            ratio = float(used) / float(limit) if float(limit) > 0 else 0.0
            _AI_BUDGET_USAGE_RATIO.labels(service=service, metric=metric_name).set(ratio)
        except Exception:
            return

    def _get_counter_value(self, key: str) -> float:
        try:
            val = self.counter.get(key)
        except Exception:
            return 0.0
        try:
            return float(val or 0.0)
        except Exception:
            return 0.0

    def _check_metric_alert(self, *, metric: str, used: float, limit: float, date_str: str) -> None:
        if not limit or limit <= 0:
            return
        percent = used / limit if limit else 0.0
        for threshold in self._alert_thresholds:
            if percent >= threshold and self._should_emit_alert(
                metric=metric, threshold=threshold, date_str=date_str
            ):
                if not self._alert_handler:
                    continue
                event = BudgetAlertEvent(
                    service=self.service,
                    metric=metric,
                    threshold=threshold,
                    percent=percent,
                    used=used,
                    limit=limit,
                    date_utc=date_str,
                )
                try:
                    self._alert_handler(event)
                except Exception:
                    logger.exception(
                        "Budget alert handler failed",
                        extra={"service": self.service, "metric": metric, "threshold": threshold},
                    )

    def _should_emit_alert(self, *, metric: str, threshold: float, date_str: str) -> bool:
        cache_key = (metric, threshold, date_str)
        if self._alert_cache.get(cache_key):
            return False

        alert_key = self._k("alert", metric, f"{threshold:.2f}", date_str)
        try:
            existing = self.counter.get(alert_key)
            if float(existing or 0.0) >= 1.0:
                self._alert_cache[cache_key] = True
                return False
        except Exception:
            pass

        self._alert_cache[cache_key] = True
        try:
            self.counter.incr(alert_key, 1, 86400)
        except Exception:
            pass
        return True
