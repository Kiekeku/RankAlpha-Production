"""Coordinates the ingestion run."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, TypeVar
from zoneinfo import ZoneInfo

import psycopg2
from prometheus_client import Counter, Gauge, Histogram

from apps.common.src.logging import get_logger
from apps.common.src.observability import report_ratio_threshold
from apps.ingestion.src.breadth_job import BreadthJob
from apps.ingestion.src.broker_client import BrokerClient
from apps.ingestion.src.dxy_regime import DxyRegimeJob
from apps.ingestion.src.earnings import EarningsCalendarUpdater
from apps.ingestion.src.fed_balance_sheet_job import FedBalanceSheetJob
from apps.ingestion.src.hy_stress import HyStressJob
from apps.ingestion.src.price_cache_refresher import PriceCacheRefresher
from apps.ingestion.src.price_store import PriceStore
from apps.ingestion.src.rrp_tga_job import RrpTgaJob
from apps.ingestion.src.settings import Settings
from apps.ingestion.src.sofr_rates_job import run_sofr_rates_job
from apps.ingestion.src.symbol_worker import SymbolIngestionWorker
from apps.ingestion.src.tips_real_yield_job import TipsRealYieldJob
from apps.ingestion.src.trading_calendar_job import TradingCalendarJob
from apps.ingestion.src.universe_maintainer import UniverseMaintainer

T = TypeVar("T")

INGESTION_PHASE_DURATION = Histogram(
    "rankalpha_ingestion_phase_seconds",
    "Wall clock duration of ingestion phases.",
    ["phase", "status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600),
)


def _safe_ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(max(int(denominator), 1))


def evaluate_symbol_coverage(
    symbols: list[str], last_dates: Dict[str, date], expected_missing: set[str]
) -> tuple[int, int, int, int, float, float, list[str]]:
    """Return coverage/drift summary for the active symbol universe."""
    symbol_set = {str(sym).upper() for sym in (symbols or []) if sym}
    with_price = {str(sym).upper() for sym in (last_dates or {}).keys() if sym}
    expected_set = {str(sym).upper() for sym in (expected_missing or set()) if sym}
    covered = symbol_set.intersection(with_price.union(expected_set))
    uncovered = sorted(symbol_set - covered)
    total = len(symbol_set)
    with_price_count = len(symbol_set.intersection(with_price))
    expected_count = len(symbol_set.intersection(expected_set))
    covered_count = len(covered)
    coverage_ratio = _safe_ratio(covered_count, total)
    drift_ratio = max(0.0, 1.0 - coverage_ratio)
    return (
        total,
        with_price_count,
        expected_count,
        covered_count,
        coverage_ratio,
        drift_ratio,
        uncovered,
    )


class IngestionRunner:
    """Coordinates the ingestion process."""

    def __init__(
        self,
        settings: Settings,
        span: Any,
        *,
        symbol_gauge: Gauge,
        download_failures: Counter,
        expected_missing_counter: Counter,
        expected_missing_symbols_gauge: Gauge | None = None,
        stale_symbols_gauge: Gauge | None = None,
        stale_ratio_gauge: Gauge | None = None,
        unexpected_stale_symbols_gauge: Gauge | None = None,
        unexpected_stale_ratio_gauge: Gauge | None = None,
        active_symbols_gauge: Gauge | None = None,
        symbols_with_price_gauge: Gauge | None = None,
        symbol_coverage_ratio_gauge: Gauge | None = None,
        symbol_drift_ratio_gauge: Gauge | None = None,
        drift_violations_counter: Counter | None = None,
    ) -> None:
        self._settings = settings
        self._span = span
        self._logger = get_logger(__name__)
        self._price_store = PriceStore(settings, self._logger)
        self._broker_client = BrokerClient(settings, self._logger)
        self._db_factory = self._build_db_factory()
        self._cache_refresher = PriceCacheRefresher(settings, self._logger)
        self._universe = UniverseMaintainer(
            settings, self._price_store, self._db_factory, self._logger
        )
        self._earnings = EarningsCalendarUpdater(settings, self._db_factory, self._logger)
        self._hy_stress = HyStressJob(settings, self._logger, self._db_factory)
        self._breadth = BreadthJob(settings, self._logger, self._db_factory)
        self._rrp_tga = RrpTgaJob(settings, self._logger, self._db_factory)
        self._fed_balance_sheet = FedBalanceSheetJob(settings, self._logger, self._db_factory)
        self._tips_real_yield = TipsRealYieldJob(settings, self._logger, self._db_factory)
        self._dxy_regime = DxyRegimeJob(settings, self._logger, self._db_factory)
        self._trading_calendar = TradingCalendarJob(self._db_factory, self._logger)
        self._symbol_gauge = symbol_gauge
        self._download_failures = download_failures
        self._expected_missing_counter = expected_missing_counter
        self._expected_missing_symbols_gauge = expected_missing_symbols_gauge
        self._stale_symbols_gauge = stale_symbols_gauge
        self._stale_ratio_gauge = stale_ratio_gauge
        self._unexpected_stale_symbols_gauge = unexpected_stale_symbols_gauge
        self._unexpected_stale_ratio_gauge = unexpected_stale_ratio_gauge
        self._active_symbols_gauge = active_symbols_gauge
        self._symbols_with_price_gauge = symbols_with_price_gauge
        self._symbol_coverage_ratio_gauge = symbol_coverage_ratio_gauge
        self._symbol_drift_ratio_gauge = symbol_drift_ratio_gauge
        self._drift_violations_counter = drift_violations_counter

    def run(self) -> None:
        self._run_timed_phase("price_store_prepare", self._price_store.prepare)
        self._set_span_attribute("ingestion.output_dir", self._price_store.output_dir)

        # Parquet repair can be extremely expensive when upstream drops full-history files.
        # Run it only on Sunday ET as a weekly hygiene window.
        try:
            is_sunday_et = datetime.now(tz=ZoneInfo("America/New_York")).weekday() == 6
        except Exception:
            is_sunday_et = False
        if is_sunday_et:
            self._run_timed_phase("parquet_repair", self._price_store.repair_if_available)

        self._run_timed_phase("trading_calendar_refresh", self._refresh_trading_calendar)

        existing = self._run_timed_phase("list_existing_parquets", self._price_store.list_existing)
        self._logger.info(
            "Found %d existing parquet files in %s", len(existing), self._price_store.output_dir
        )
        self._set_span_attribute("ingestion.existing_parquet_count", len(existing))

        symbols: list[str] = []
        stock_key_map: Dict[str, int] = {}

        def _load_universe_from_db() -> None:
            nonlocal symbols, stock_key_map
            conn = self._db_factory()
            try:
                self._register_index_parquet_symbols(conn, existing)
                self._mark_delisted(conn)
                symbols = self._fetch_active_symbols(conn)
                stock_key_map = self._fetch_stock_keys(conn, symbols)
            finally:
                conn.close()

        self._run_timed_phase("load_universe_from_db", _load_universe_from_db)

        if not symbols:
            self._logger.info("No active symbols found for ingestion run")
            return

        self._symbol_gauge.set(len(symbols))
        if self._active_symbols_gauge is not None:
            try:
                self._active_symbols_gauge.set(len(symbols))
            except Exception:
                pass
        try:
            self._set_span_attribute("ingestion.symbol_count", len(symbols))
            self._span.add_event("ingestion.symbols.selected", {"count": len(symbols)})
        except Exception:
            pass

        worker = SymbolIngestionWorker(
            self._settings,
            self._price_store,
            self._broker_client,
            self._db_factory,
            self._span,
            self._logger,
            self._download_failures,
            self._expected_missing_counter,
            stock_key_map=stock_key_map,
        )

        last_dates: Dict[str, date] = {}
        expected_missing: set[str] = set()
        try:
            max_workers = int(getattr(self._settings, "ingestion_workers", 4) or 4)
        except Exception:
            max_workers = 4

        def _process_symbols_parallel() -> None:
            progress_every = self._progress_log_every()
            started_at = time.perf_counter()
            processed = 0
            total = len(symbols)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(worker.run, sym): sym for sym in symbols}
                for fut in as_completed(futures):
                    result = fut.result()
                    processed += 1
                    if result.last_trade_date is not None:
                        last_dates[result.symbol] = result.last_trade_date
                    if getattr(result, "expected_missing", False):
                        expected_missing.add(result.symbol)
                    self._maybe_log_symbol_progress(
                        processed=processed,
                        total=total,
                        every=progress_every,
                        started_at=started_at,
                    )

        self._run_timed_phase("symbol_pool", _process_symbols_parallel)

        if self._expected_missing_symbols_gauge is not None:
            try:
                self._expected_missing_symbols_gauge.set(len(expected_missing))
            except Exception:
                pass

        self._run_timed_phase(
            "stale_metrics",
            lambda: self._emit_stale_metrics(
                symbols, last_dates, expected_missing=expected_missing
            ),
        )
        self._run_timed_phase(
            "coverage_drift_guard",
            lambda: self._emit_symbol_coverage_metrics(
                symbols, last_dates, expected_missing=expected_missing
            ),
        )
        self._run_timed_phase("cache_refresh", lambda: self._cache_refresher.refresh(last_dates))
        self._run_timed_phase("universe_apply", lambda: self._universe.apply(last_dates))
        self._run_timed_phase("tail_jobs_parallel", self._run_tail_jobs_parallel)
        self._logger.info("Ingestion completed. processed=%d", len(symbols))

    def _set_span_attribute(self, key: str, value: Any) -> None:
        try:
            if self._span:
                self._span.set_attribute(key, value)
        except Exception:
            pass

    def _record_phase_duration(self, *, phase: str, started_at: float, status: str) -> None:
        duration = max(0.0, float(time.perf_counter() - started_at))
        INGESTION_PHASE_DURATION.labels(phase=phase, status=status).observe(duration)
        self._set_span_attribute(f"ingestion.phase.{phase}.seconds", duration)
        self._set_span_attribute(f"ingestion.phase.{phase}.status", status)

    def _run_timed_phase(self, phase: str, fn: Callable[[], T]) -> T:
        started_at = time.perf_counter()
        status = "success"
        try:
            return fn()
        except Exception:
            status = "error"
            raise
        finally:
            self._record_phase_duration(phase=phase, started_at=started_at, status=status)

    def _progress_log_every(self) -> int:
        try:
            every = int(getattr(self._settings, "ingestion_progress_log_every", 100) or 100)
        except Exception:
            every = 100
        return max(1, every)

    def _maybe_log_symbol_progress(
        self, *, processed: int, total: int, every: int, started_at: float
    ) -> None:
        if processed <= 0 or total <= 0:
            return
        if processed != 1 and processed != total and processed % max(1, every) != 0:
            return
        elapsed = max(float(time.perf_counter() - started_at), 1e-6)
        rate = float(processed) / elapsed
        pct = (float(processed) * 100.0) / float(total)
        self._logger.info(
            "Symbol refresh progress: %d/%d (%.1f%%, %.2f sym/s)",
            processed,
            total,
            pct,
            rate,
        )

    def _emit_stale_metrics(
        self, symbols: list[str], last_dates: Dict[str, date], *, expected_missing: set[str]
    ) -> None:
        if not symbols:
            return
        total = len(symbols)
        # Treat missing last_trade_date as stale: the worker did not return a usable update.
        processed = {s.upper() for s in last_dates.keys()}
        missing = {sym.upper() for sym in symbols if sym.upper() not in processed}

        try:
            stale_bdays = int(
                getattr(self._settings, "ingestion_stale_after_missing_bdays", 1) or 1
            )
        except Exception:
            stale_bdays = 1
        anchor, stale = self._universe.evaluate_staleness(
            last_dates, stale_after_missing_bdays=stale_bdays
        )
        stale_set = {s.upper() for s in stale} | missing
        stale_count = len(stale_set)
        ratio = float(stale_count) / float(max(total, 1))
        expected_missing_set = {s.upper() for s in (expected_missing or set())}
        unexpected_stale_set = stale_set - expected_missing_set
        unexpected_stale_count = len(unexpected_stale_set)
        unexpected_ratio = float(unexpected_stale_count) / float(max(total, 1))

        if self._stale_symbols_gauge is not None:
            try:
                self._stale_symbols_gauge.set(stale_count)
            except Exception:
                pass
        if self._stale_ratio_gauge is not None:
            try:
                self._stale_ratio_gauge.set(ratio)
            except Exception:
                pass
        if self._unexpected_stale_symbols_gauge is not None:
            try:
                self._unexpected_stale_symbols_gauge.set(unexpected_stale_count)
            except Exception:
                pass
        if self._unexpected_stale_ratio_gauge is not None:
            try:
                self._unexpected_stale_ratio_gauge.set(unexpected_ratio)
            except Exception:
                pass

        try:
            if anchor is not None:
                self._span.set_attribute("ingestion.anchor_date", str(anchor))
            self._span.set_attribute("ingestion.stale.symbols", stale_count)
            self._span.set_attribute("ingestion.stale.ratio", ratio)
            self._span.set_attribute(
                "ingestion.expected_missing.symbols", len(expected_missing_set)
            )
            self._span.set_attribute("ingestion.unexpected_stale.symbols", unexpected_stale_count)
            self._span.set_attribute("ingestion.unexpected_stale.ratio", unexpected_ratio)
        except Exception:
            pass

        try:
            threshold = float(
                getattr(self._settings, "ingestion_stale_price_alert_ratio_threshold", 0.05) or 0.05
            )
        except Exception:
            threshold = 0.05

        # Only notify when the run looks meaningfully degraded (avoid Sentry quota burn).
        report_ratio_threshold(
            service="rankalpha-ingestion",
            check="stale_prices_unexpected",
            ratio=unexpected_ratio,
            threshold=threshold,
            total=total,
            affected=unexpected_stale_count,
            sample=sorted(list(unexpected_stale_set))[:25] if unexpected_stale_set else None,
            level="error",
        )

    def _emit_symbol_coverage_metrics(
        self, symbols: list[str], last_dates: Dict[str, date], *, expected_missing: set[str]
    ) -> None:
        (
            total,
            with_price_count,
            expected_count,
            covered_count,
            coverage_ratio,
            drift_ratio,
            uncovered,
        ) = evaluate_symbol_coverage(symbols, last_dates, expected_missing)
        if total <= 0:
            return

        if self._symbols_with_price_gauge is not None:
            try:
                self._symbols_with_price_gauge.set(with_price_count)
            except Exception:
                pass
        if self._symbol_coverage_ratio_gauge is not None:
            try:
                self._symbol_coverage_ratio_gauge.set(coverage_ratio)
            except Exception:
                pass
        if self._symbol_drift_ratio_gauge is not None:
            try:
                self._symbol_drift_ratio_gauge.set(drift_ratio)
            except Exception:
                pass

        try:
            self._span.set_attribute("ingestion.coverage.total_symbols", total)
            self._span.set_attribute("ingestion.coverage.with_price", with_price_count)
            self._span.set_attribute("ingestion.coverage.expected_missing", expected_count)
            self._span.set_attribute("ingestion.coverage.covered", covered_count)
            self._span.set_attribute("ingestion.coverage.ratio", coverage_ratio)
            self._span.set_attribute("ingestion.coverage.drift_ratio", drift_ratio)
        except Exception:
            pass

        self._logger.info(
            "Ingestion coverage: total=%d with_price=%d expected_missing=%d covered=%d coverage=%.4f drift=%.4f",
            total,
            with_price_count,
            expected_count,
            covered_count,
            coverage_ratio,
            drift_ratio,
        )

        try:
            min_ratio = float(getattr(self._settings, "ingestion_symbol_success_min_ratio", 0.85))
        except Exception:
            min_ratio = 0.85
        min_ratio = min(max(min_ratio, 0.0), 1.0)
        drift_threshold = max(0.0, 1.0 - min_ratio)

        report_ratio_threshold(
            service="rankalpha-ingestion",
            check="symbol_coverage_drift",
            ratio=drift_ratio,
            threshold=drift_threshold,
            total=total,
            affected=(total - covered_count),
            sample=uncovered[:25] if uncovered else None,
            level="error",
        )

        if coverage_ratio < min_ratio:
            if self._drift_violations_counter is not None:
                try:
                    self._drift_violations_counter.labels(check="symbol_coverage").inc()
                except Exception:
                    pass
            raise RuntimeError(
                "Ingestion coverage drift guard triggered: "
                f"coverage_ratio={coverage_ratio:.4f} < min_ratio={min_ratio:.4f} "
                f"(covered={covered_count}, total={total})"
            )

    def _run_tail_jobs_parallel(self) -> None:
        """Run post-price side jobs in parallel to shorten wall clock."""
        jobs = [
            ("earnings", self._refresh_earnings),
            ("rates", self._refresh_rates),
            ("hy_stress", self._refresh_hy_stress),
            ("breadth", self._refresh_breadth),
            ("rrp_tga", self._refresh_rrp_tga),
            ("fed_balance_sheet", self._refresh_fed_balance_sheet),
            ("tips_real_yield", self._refresh_tips_real_yield),
            ("dxy_regime", self._refresh_dxy_regime),
        ]
        # Use a small pool to avoid DB connection storms
        max_workers = min(4, len(jobs))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futs = {executor.submit(fn): name for name, fn in jobs}
            for fut in as_completed(futs):
                name = futs[fut]
                try:
                    fut.result()
                except Exception as exc:  # pragma: no cover - double guard
                    self._logger.warning("Tail job %s raised: %s", name, exc, exc_info=True)

    def _refresh_trading_calendar(self) -> None:
        try:
            if self._span:
                self._span.add_event("ingestion.trading_calendar.start")
        except Exception:
            pass
        try:
            lookback_days = getattr(
                self._settings, "ingestion_trading_calendar_lookback_days", None
            )
            lookahead_days = getattr(
                self._settings, "ingestion_trading_calendar_lookahead_days", None
            )
            try:
                today = datetime.now(tz=ZoneInfo("America/New_York")).date()
            except Exception:
                today = date.today()
            start_date = (
                today - timedelta(days=int(lookback_days)) if lookback_days is not None else None
            )
            end_date = (
                today + timedelta(days=int(lookahead_days)) if lookahead_days is not None else None
            )
            self._trading_calendar.refresh(start_date=start_date, end_date=end_date)
        except Exception:
            self._logger.warning("Trading calendar refresh failed", exc_info=True)
        finally:
            try:
                if self._span:
                    self._span.add_event("ingestion.trading_calendar.end")
            except Exception:
                pass

    def _build_db_factory(self) -> Callable[[], psycopg2.extensions.connection]:
        def factory() -> psycopg2.extensions.connection:
            return psycopg2.connect(
                database=self._settings.database_name,
                user=self._settings.db_username,
                password=self._settings.password,
                host=self._settings.host,
                port=self._settings.port,
            )

        return factory

    def _register_index_parquet_symbols(self, conn, existing_parquets: set[str]) -> None:
        """Auto-register index parquet files (e.g., $SPX.parquet, %SPX.parquet) into dim_stock.

        These symbols are produced externally and already contain valid prices, so
        we simply upsert them as asset_type "index" and mark them active. No
        attempt is made to validate via yfinance.
        """

        index_prefixes = ("$", "%", "#")
        index_symbols = sorted(
            {sym.upper() for sym in existing_parquets if sym.startswith(index_prefixes)}
        )
        if not index_symbols:
            return

        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO rankalpha.dim_asset_type(asset_type_name) VALUES (%s) ON CONFLICT DO NOTHING",
                ("index",),
            )
            cur.execute(
                "SELECT asset_type_key FROM rankalpha.dim_asset_type WHERE asset_type_name = %s",
                ("index",),
            )
            row = cur.fetchone()
            if not row:
                self._logger.warning(
                    "Could not resolve asset_type_key for 'index'; skipping index parquet registration"
                )
                conn.rollback()
                return
            asset_type_key = int(row[0])

            cur.execute("SELECT symbol FROM dim_stock WHERE symbol = ANY(%s)", (index_symbols,))
            existing_in_db = {str(r[0]).upper() for r in cur.fetchall()}
            to_insert = [sym for sym in index_symbols if sym not in existing_in_db]
            if not to_insert:
                conn.commit()
                return

            for sym in to_insert:
                cur.execute(
                    """
                    INSERT INTO dim_stock(symbol, company_name, exchange, is_active, asset_type_key)
                    VALUES (%s, %s, %s, TRUE, %s)
                    ON CONFLICT (symbol) DO NOTHING
                    """,
                    (sym, sym.lstrip("$%#"), "INDEX", asset_type_key),
                )

            conn.commit()
            self._logger.info(
                "Registered %d index parquet symbol(s) into dim_stock: %s",
                len(to_insert),
                ",".join(to_insert),
            )
        except Exception:
            conn.rollback()
            self._logger.warning("Index parquet registration failed", exc_info=True)
        finally:
            cur.close()

    def _mark_delisted(self, conn) -> None:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE dim_stock SET is_active = FALSE WHERE symbol ~ '-[0-9]{6}$' AND is_active = TRUE"
            )
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            cur.close()

    def _fetch_active_symbols(self, conn) -> list[str]:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT symbol
                FROM dim_stock
                WHERE is_active IS TRUE
                ORDER BY symbol ASC
                """
            )
            rows = cur.fetchall()
            return [str(r[0]).upper() for r in rows]
        finally:
            cur.close()

    def _fetch_stock_keys(self, conn, symbols: list[str]) -> Dict[str, int]:
        if not symbols:
            return {}
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT symbol, stock_key
                FROM dim_stock
                WHERE is_active IS TRUE
                  AND symbol = ANY(%s)
                """,
                (symbols,),
            )
            rows = cur.fetchall()
            return {str(sym).upper(): int(sk) for sym, sk in rows if sym is not None}
        finally:
            cur.close()

    def _refresh_earnings(self) -> None:
        try:
            if self._span:
                self._span.add_event("ingestion.earnings.refresh.start")
        except Exception:
            pass
        try:
            self._earnings.refresh()
        except Exception:
            self._logger.warning("Earnings refresh failed", exc_info=True)
        finally:
            try:
                if self._span:
                    self._span.add_event("ingestion.earnings.refresh.end")
            except Exception:
                pass

    def _refresh_rates(self) -> None:
        # Never allow rates job to crash ingestion; log warnings only
        try:
            if self._span:
                self._span.add_event("ingestion.sofr_rates.start")
        except Exception:
            pass
        try:
            run_sofr_rates_job(self._settings, self._logger)
        except Exception:
            # Extra guard: swallow any unhandled exception
            self._logger.warning("SOFR rates job failed (guarded)", exc_info=True)
        finally:
            try:
                if self._span:
                    self._span.add_event("ingestion.sofr_rates.end")
            except Exception:
                pass

    def _refresh_hy_stress(self) -> None:
        # Guarded to avoid crashing ingestion on errors
        try:
            if self._span:
                self._span.add_event("ingestion.hy_stress.start")
        except Exception:
            pass
        try:
            self._hy_stress.refresh()
        except Exception:
            self._logger.warning("HY stress job failed (guarded)", exc_info=True)
        finally:
            try:
                if self._span:
                    self._span.add_event("ingestion.hy_stress.end")
            except Exception:
                pass

    def _refresh_breadth(self) -> None:
        # Guarded to avoid crashing ingestion on errors
        try:
            if self._span:
                self._span.add_event("ingestion.breadth.start")
        except Exception:
            pass
        try:
            self._breadth.refresh()
        except Exception:
            self._logger.warning("Breadth job failed (guarded)", exc_info=True)
        finally:
            try:
                if self._span:
                    self._span.add_event("ingestion.breadth.end")
            except Exception:
                pass

    def _refresh_rrp_tga(self) -> None:
        # Guarded to avoid crashing ingestion on errors
        try:
            if self._span:
                self._span.add_event("ingestion.rrp_tga.start")
        except Exception:
            pass
        try:
            self._rrp_tga.refresh()
        except Exception:
            self._logger.warning("RRP/TGA job failed (guarded)", exc_info=True)
        finally:
            try:
                if self._span:
                    self._span.add_event("ingestion.rrp_tga.end")
            except Exception:
                pass

    def _refresh_fed_balance_sheet(self) -> None:
        # Guarded to avoid crashing ingestion on errors
        try:
            if self._span:
                self._span.add_event("ingestion.fed_balance_sheet.start")
        except Exception:
            pass
        try:
            self._fed_balance_sheet.refresh()
        except Exception:
            self._logger.warning("Fed balance sheet job failed (guarded)", exc_info=True)
        finally:
            try:
                if self._span:
                    self._span.add_event("ingestion.fed_balance_sheet.end")
            except Exception:
                pass

    def _refresh_tips_real_yield(self) -> None:
        # Guarded to avoid crashing ingestion on errors
        try:
            if self._span:
                self._span.add_event("ingestion.tips_real_yield.start")
        except Exception:
            pass
        try:
            self._tips_real_yield.refresh()
        except Exception:
            self._logger.warning("TIPS real yield job failed (guarded)", exc_info=True)
        finally:
            try:
                if self._span:
                    self._span.add_event("ingestion.tips_real_yield.end")
            except Exception:
                pass

    def _refresh_dxy_regime(self) -> None:
        # Guarded to avoid crashing ingestion on errors
        try:
            if self._span:
                self._span.add_event("ingestion.dxy_regime.start")
        except Exception:
            pass
        try:
            self._dxy_regime.refresh()
        except Exception:
            self._logger.warning("DXY regime job failed (guarded)", exc_info=True)
        finally:
            try:
                if self._span:
                    self._span.add_event("ingestion.dxy_regime.end")
            except Exception:
                pass
