from __future__ import annotations

import time
from typing import Any

from opentelemetry.trace import Status, StatusCode
from prometheus_client import Counter, Gauge, Histogram

from apps.common.src.logging import setup_logging
from apps.common.src.observability import (
    init_service_observability,
    sleep_for_metrics_flush,
    start_span,
)
from apps.ingestion.src.ingestion_runner import IngestionRunner
from apps.ingestion.src.settings import Settings

INGESTION_RUNS = Counter(
    "rankalpha_ingestion_runs_total",
    "Total ingestion runs grouped by status.",
    ["status"],
)
INGESTION_DURATION = Histogram(
    "rankalpha_ingestion_run_seconds",
    "Wall clock duration of ingestion runs.",
    ["status"],
    buckets=(5, 10, 30, 60, 120, 300, 600, 1200, 3600),
)
INGESTION_SYMBOLS = Gauge(
    "rankalpha_ingestion_symbols_tracked",
    "Number of parquet files tracked during ingestion.",
)
DOWNLOAD_FAILURES = Counter(
    "rankalpha_ingestion_download_failures_total",
    "Count of individual ticker download failures.",
    ["ticker"],
)
EXPECTED_MISSING = Counter(
    "rankalpha_ingestion_expected_missing_total",
    "Count of expected missing downloads (e.g., delisted tickers) by provider/kind.",
    ["provider", "kind"],
)
STALE_SYMBOLS = Gauge(
    "rankalpha_ingestion_stale_symbols",
    "Number of symbols that appear stale vs the peer anchor date.",
)
STALE_SYMBOL_RATIO = Gauge(
    "rankalpha_ingestion_stale_symbol_ratio",
    "Share of symbols that appear stale vs the peer anchor date.",
)
EXPECTED_MISSING_SYMBOLS = Gauge(
    "rankalpha_ingestion_expected_missing_symbols",
    "Number of symbols treated as expected-missing in the most recent run.",
)
UNEXPECTED_STALE_SYMBOLS = Gauge(
    "rankalpha_ingestion_unexpected_stale_symbols",
    "Number of stale symbols excluding expected-missing symbols.",
)
UNEXPECTED_STALE_SYMBOL_RATIO = Gauge(
    "rankalpha_ingestion_unexpected_stale_symbol_ratio",
    "Share of stale symbols excluding expected-missing symbols.",
)
INGESTION_ACTIVE_SYMBOLS = Gauge(
    "rankalpha_ingestion_active_symbols",
    "Number of active symbols in the ingestion run universe.",
)
INGESTION_SYMBOLS_WITH_PRICE = Gauge(
    "rankalpha_ingestion_symbols_with_price",
    "Number of active symbols with a resolved last trade date in the run.",
)
INGESTION_SYMBOL_COVERAGE_RATIO = Gauge(
    "rankalpha_ingestion_symbol_coverage_ratio",
    "Share of active symbols covered by price output or expected-missing classification.",
)
INGESTION_SYMBOL_DRIFT_RATIO = Gauge(
    "rankalpha_ingestion_symbol_drift_ratio",
    "Drift ratio for ingestion symbol coverage (1 - coverage_ratio).",
)
INGESTION_DRIFT_VIOLATIONS = Counter(
    "rankalpha_ingestion_drift_violations_total",
    "Count of ingestion drift guard violations.",
    ["check"],
)


def _execute_ingestion(span: Any, settings: Settings) -> None:
    runner = IngestionRunner(
        settings,
        span,
        symbol_gauge=INGESTION_SYMBOLS,
        download_failures=DOWNLOAD_FAILURES,
        expected_missing_counter=EXPECTED_MISSING,
        expected_missing_symbols_gauge=EXPECTED_MISSING_SYMBOLS,
        stale_symbols_gauge=STALE_SYMBOLS,
        stale_ratio_gauge=STALE_SYMBOL_RATIO,
        unexpected_stale_symbols_gauge=UNEXPECTED_STALE_SYMBOLS,
        unexpected_stale_ratio_gauge=UNEXPECTED_STALE_SYMBOL_RATIO,
        active_symbols_gauge=INGESTION_ACTIVE_SYMBOLS,
        symbols_with_price_gauge=INGESTION_SYMBOLS_WITH_PRICE,
        symbol_coverage_ratio_gauge=INGESTION_SYMBOL_COVERAGE_RATIO,
        symbol_drift_ratio_gauge=INGESTION_SYMBOL_DRIFT_RATIO,
        drift_violations_counter=INGESTION_DRIFT_VIOLATIONS,
    )
    runner.run()


def main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    init_service_observability("rankalpha-ingestion")
    for run_status in ("success", "error"):
        INGESTION_DURATION.labels(status=run_status)
        INGESTION_RUNS.labels(status=run_status)
    status = "success"
    start_time = time.perf_counter()
    with start_span("ingestion.run") as span:
        try:
            _execute_ingestion(span, settings)
        except Exception as exc:  # pragma: no cover - defensive logging
            status = "error"
            try:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception:
                pass
            raise
        finally:
            duration = time.perf_counter() - start_time
            try:
                span.set_attribute("ingestion.duration_seconds", duration)
                span.set_attribute("ingestion.status", status)
            except Exception:
                pass
            INGESTION_DURATION.labels(status=status).observe(duration)
            INGESTION_RUNS.labels(status=status).inc()
            sleep_for_metrics_flush("rankalpha-ingestion")


if __name__ == "__main__":
    main()
