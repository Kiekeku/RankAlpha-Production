from __future__ import annotations

import logging
import time
from typing import Any, Optional

from apps.common.src.observability import get_or_create_counter, get_or_create_histogram

logger = logging.getLogger(__name__)


def _norm_label(value: Any, *, default: str = "unknown") -> str:
    raw = str(value or "").strip()
    return raw if raw else default


def normalize_action_label(value: Any) -> str:
    raw = _norm_label(value).upper()
    if raw in {"BUY", "BOT", "LONG"}:
        return "buy"
    if raw in {"SELL", "SLD", "SHORT"}:
        return "sell"
    if raw in {"EXIT"}:
        return "exit"
    return raw.lower()


def normalize_order_type_label(value: Any) -> str:
    raw = _norm_label(value).upper()
    return raw.replace(" ", "_")


def normalize_account_label(value: Optional[str]) -> str:
    return _norm_label(value, default="UNKNOWN")


def classify_error_kind(exc: BaseException) -> str:
    name = exc.__class__.__name__
    lowered = name.lower()
    if name == "ExternalBrokerError":
        return "external_broker_error"
    if "timeout" in lowered:
        return "timeout"
    msg = str(exc).lower()
    if "remote end closed connection without response" in msg or "remotedisconnected" in msg:
        return "remote_disconnected"
    if "protocolerror" in msg or "connection aborted" in msg:
        return "connection_aborted"
    if "reached max retries" in msg:
        return "retry_exhausted"
    if isinstance(exc, RuntimeError) and "no contracts found" in msg:
        return "no_contracts"
    if isinstance(exc, ValueError):
        return "validation"
    return "other"


try:
    BROKER_ORDERS_SUBMITTED = get_or_create_counter(
        "rankalpha_broker_orders_submitted_total",
        "Count of broker orders submitted to the IBKR client.",
        labelnames=("account", "action", "order_type"),
    )
except Exception:  # pragma: no cover
    BROKER_ORDERS_SUBMITTED = None

try:
    BROKER_ORDERS_ACCEPTED = get_or_create_counter(
        "rankalpha_broker_orders_accepted_total",
        "Count of broker orders accepted (order id returned) by the IBKR client.",
        labelnames=("account", "action", "order_type"),
    )
except Exception:  # pragma: no cover
    BROKER_ORDERS_ACCEPTED = None

try:
    BROKER_ORDERS_FAILED = get_or_create_counter(
        "rankalpha_broker_orders_failed_total",
        "Count of broker order submissions that failed.",
        labelnames=("account", "action", "order_type", "reason"),
    )
except Exception:  # pragma: no cover
    BROKER_ORDERS_FAILED = None

try:
    BROKER_ORDERS_CANCELED = get_or_create_counter(
        "rankalpha_broker_orders_canceled_total",
        "Count of broker order cancellations that succeeded.",
        labelnames=("account",),
    )
except Exception:  # pragma: no cover
    BROKER_ORDERS_CANCELED = None

try:
    BROKER_FILLS_INGESTED = get_or_create_counter(
        "rankalpha_broker_fills_ingested_total",
        "Count of execution fills ingested into the RankAlpha ledger.",
        labelnames=("account",),
    )
except Exception:  # pragma: no cover
    BROKER_FILLS_INGESTED = None

try:
    BROKER_ORDER_PLACE_SECONDS = get_or_create_histogram(
        "rankalpha_broker_order_place_seconds",
        "Time spent in the broker order placement call.",
        labelnames=("account", "order_type"),
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 60),
    )
except Exception:  # pragma: no cover
    BROKER_ORDER_PLACE_SECONDS = None

try:
    BROKER_TIME_TO_FILL_SECONDS = get_or_create_histogram(
        "rankalpha_broker_time_to_fill_seconds",
        "Time between recommendation creation and first fill update.",
        labelnames=("account", "action"),
        buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, 14400, 86400),
    )
except Exception:  # pragma: no cover
    BROKER_TIME_TO_FILL_SECONDS = None

try:
    BROKER_IBKR_REQUEST_SECONDS = get_or_create_histogram(
        "rankalpha_broker_ibkr_request_seconds",
        "Latency for outbound IBKR Web API requests (via ibind).",
        labelnames=("account", "operation"),
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 60),
    )
except Exception:  # pragma: no cover
    BROKER_IBKR_REQUEST_SECONDS = None

try:
    BROKER_IBKR_REQUEST_ERRORS = get_or_create_counter(
        "rankalpha_broker_ibkr_request_errors_total",
        "Count of outbound IBKR Web API request errors grouped by operation and kind.",
        labelnames=("account", "operation", "kind"),
    )
except Exception:  # pragma: no cover
    BROKER_IBKR_REQUEST_ERRORS = None

try:
    BROKER_EXECUTOR_CYCLES = get_or_create_counter(
        "rankalpha_broker_executor_cycles_total",
        "Count of broker executor cycles grouped by outcome.",
        labelnames=("account", "outcome"),
    )
    for outcome in ("success", "error"):
        BROKER_EXECUTOR_CYCLES.labels(account="UNKNOWN", outcome=outcome).inc(0)
except Exception:  # pragma: no cover
    BROKER_EXECUTOR_CYCLES = None

try:
    BROKER_EXECUTOR_CYCLE_SECONDS = get_or_create_histogram(
        "rankalpha_broker_executor_cycle_seconds",
        "Time spent per broker executor cycle (work only; excludes sleep).",
        labelnames=("account",),
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 60, 120),
    )
except Exception:  # pragma: no cover
    BROKER_EXECUTOR_CYCLE_SECONDS = None

try:
    BROKER_PREV_CLOSE_ERRORS = get_or_create_counter(
        "rankalpha_broker_prev_close_errors_total",
        "Count of /price/prev-close failures grouped by kind and suppression.",
        labelnames=("account", "kind", "suppressed"),
    )
except Exception:  # pragma: no cover
    BROKER_PREV_CLOSE_ERRORS = None

try:
    BROKER_PRICE_SNAPSHOT_ERRORS = get_or_create_counter(
        "rankalpha_broker_price_snapshot_errors_total",
        "Count of /price/{symbol} snapshot failures grouped by kind and suppression.",
        labelnames=("account", "kind", "suppressed"),
    )
except Exception:  # pragma: no cover
    BROKER_PRICE_SNAPSHOT_ERRORS = None


def record_order_submitted(*, account: Optional[str], action: Any, order_type: Any) -> None:
    if BROKER_ORDERS_SUBMITTED is None:
        return
    try:
        BROKER_ORDERS_SUBMITTED.labels(
            account=normalize_account_label(account),
            action=normalize_action_label(action),
            order_type=normalize_order_type_label(order_type),
        ).inc()
    except Exception:
        return


def record_prev_close_error(
    *, account: Optional[str], exc: BaseException, suppressed: bool
) -> None:
    if BROKER_PREV_CLOSE_ERRORS is None:
        return
    try:
        BROKER_PREV_CLOSE_ERRORS.labels(
            account=normalize_account_label(account),
            kind=classify_error_kind(exc),
            suppressed="true" if suppressed else "false",
        ).inc()
    except Exception:
        return


def record_price_snapshot_error(
    *, account: Optional[str], exc: BaseException, suppressed: bool
) -> None:
    if BROKER_PRICE_SNAPSHOT_ERRORS is None:
        return
    try:
        BROKER_PRICE_SNAPSHOT_ERRORS.labels(
            account=normalize_account_label(account),
            kind=classify_error_kind(exc),
            suppressed="true" if suppressed else "false",
        ).inc()
    except Exception:
        return


def record_order_accepted(*, account: Optional[str], action: Any, order_type: Any) -> None:
    if BROKER_ORDERS_ACCEPTED is None:
        return
    try:
        BROKER_ORDERS_ACCEPTED.labels(
            account=normalize_account_label(account),
            action=normalize_action_label(action),
            order_type=normalize_order_type_label(order_type),
        ).inc()
    except Exception:
        return


def record_order_failed(
    *, account: Optional[str], action: Any, order_type: Any, reason: str
) -> None:
    if BROKER_ORDERS_FAILED is None:
        return
    try:
        BROKER_ORDERS_FAILED.labels(
            account=normalize_account_label(account),
            action=normalize_action_label(action),
            order_type=normalize_order_type_label(order_type),
            reason=_norm_label(reason),
        ).inc()
    except Exception:
        return


def record_order_canceled(*, account: Optional[str]) -> None:
    if BROKER_ORDERS_CANCELED is None:
        return
    try:
        BROKER_ORDERS_CANCELED.labels(account=normalize_account_label(account)).inc()
    except Exception:
        return


def record_fill_ingested(*, account: Optional[str], count: int = 1) -> None:
    if BROKER_FILLS_INGESTED is None:
        return
    try:
        BROKER_FILLS_INGESTED.labels(account=normalize_account_label(account)).inc(
            max(int(count), 0)
        )
    except Exception:
        return


def observe_order_place_seconds(*, account: Optional[str], order_type: Any, seconds: float) -> None:
    if BROKER_ORDER_PLACE_SECONDS is None:
        return
    try:
        BROKER_ORDER_PLACE_SECONDS.labels(
            account=normalize_account_label(account),
            order_type=normalize_order_type_label(order_type),
        ).observe(max(float(seconds), 0.0))
    except Exception:
        return


def observe_time_to_fill_seconds(*, account: Optional[str], action: Any, seconds: float) -> None:
    if BROKER_TIME_TO_FILL_SECONDS is None:
        return
    try:
        BROKER_TIME_TO_FILL_SECONDS.labels(
            account=normalize_account_label(account),
            action=normalize_action_label(action),
        ).observe(max(float(seconds), 0.0))
    except Exception:
        return


def observe_ibkr_request_seconds(*, account: Optional[str], operation: str, seconds: float) -> None:
    if BROKER_IBKR_REQUEST_SECONDS is None:
        return
    try:
        BROKER_IBKR_REQUEST_SECONDS.labels(
            account=normalize_account_label(account),
            operation=_norm_label(operation),
        ).observe(max(float(seconds), 0.0))
    except Exception:
        return


def record_ibkr_request_error(
    *, account: Optional[str], operation: str, exc: BaseException
) -> None:
    if BROKER_IBKR_REQUEST_ERRORS is None:
        return
    try:
        BROKER_IBKR_REQUEST_ERRORS.labels(
            account=normalize_account_label(account),
            operation=_norm_label(operation),
            kind=classify_error_kind(exc),
        ).inc()
    except Exception:
        return


def record_executor_cycle(*, account: Optional[str], outcome: str) -> None:
    if BROKER_EXECUTOR_CYCLES is None:
        return
    try:
        BROKER_EXECUTOR_CYCLES.labels(
            account=normalize_account_label(account),
            outcome=_norm_label(outcome),
        ).inc()
    except Exception:
        return


def observe_executor_cycle_seconds(*, account: Optional[str], seconds: float) -> None:
    if BROKER_EXECUTOR_CYCLE_SECONDS is None:
        return
    try:
        BROKER_EXECUTOR_CYCLE_SECONDS.labels(
            account=normalize_account_label(account),
        ).observe(max(float(seconds), 0.0))
    except Exception:
        return


def prime_executor_cycle_metrics(*, account: Optional[str]) -> None:
    if BROKER_EXECUTOR_CYCLES is None:
        return
    acct = normalize_account_label(account)
    try:
        for outcome in ("success", "error"):
            BROKER_EXECUTOR_CYCLES.labels(account=acct, outcome=outcome).inc(0)
    except Exception:
        return


class Timer:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def seconds(self) -> float:
        return time.perf_counter() - self._start
