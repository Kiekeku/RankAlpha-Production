"""Symbol-level ingestion worker."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from queue import Empty, Queue
from threading import Thread
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import psycopg2
from prometheus_client import Counter, Histogram
from psycopg2.extras import execute_values

from apps.ingestion.src.broker_client import BrokerClient
from apps.ingestion.src.price_store import PriceStore
from apps.ingestion.src.price_sync_service import PriceSyncService
from apps.ingestion.src.settings import Settings
from apps.ingestion.src.utils import canonicalize_ohlcv, history_days, to_naive_index, to_naive_ts


@dataclass(frozen=True)
class SymbolResult:
    symbol: str
    last_trade_date: Optional[date]
    expected_missing: bool = False
    expected_missing_kind: Optional[str] = None


SYMBOL_PROCESS_DURATION = Histogram(
    "rankalpha_ingestion_symbol_process_seconds",
    "Wall clock duration per symbol in ingestion worker.",
    ["status"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
)


class _NoopCounter:
    """Prometheus Counter stand-in for unit tests and non-metrics contexts."""

    def labels(self, **_labels):  # type: ignore[no-untyped-def]
        return self

    def inc(self, *_a, **_k):  # type: ignore[no-untyped-def]
        return None


class SymbolIngestionWorker:
    """Processes a single symbol end-to-end."""

    _INDEX_PREFIXES = ("$", "%", "#")

    def __init__(
        self,
        settings: Settings,
        price_store: PriceStore,
        broker_client: BrokerClient,
        db_factory: Callable[[], psycopg2.extensions.connection],
        span: Any,
        logger,
        download_failures: Counter,
        expected_missing_counter: Counter | None = None,
        stock_key_map: Dict[str, int] | None = None,
    ) -> None:
        self._settings = settings
        self._price_store = price_store
        self._broker = broker_client
        self._db_factory = db_factory
        self._span = span
        self._logger = logger
        self._history_days = history_days(settings)
        self._download_failures = download_failures
        self._expected_missing_counter = expected_missing_counter or _NoopCounter()
        self._stock_key_map = {str(k).upper(): int(v) for k, v in (stock_key_map or {}).items()}

    def run(self, symbol: str) -> SymbolResult:
        ticker = symbol.upper()
        conn = self._db_factory()
        started_at = time.perf_counter()
        status = "success"
        try:
            result = self._process_symbol(conn, ticker)
            status = "success" if result.last_trade_date is not None else "no_data"
            return result
        finally:
            try:
                duration = max(0.0, float(time.perf_counter() - started_at))
                SYMBOL_PROCESS_DURATION.labels(status=status).observe(duration)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def _process_symbol(self, conn, symbol: str) -> SymbolResult:
        dest_path = self._price_store.path(symbol)
        history_days = self._history_days
        end_bound = pd.Timestamp.now(tz="America/New_York").normalize()
        end_bound_naive = to_naive_ts(end_bound)
        # Weekly "full resync" to detect/repair back-adjustments even when prices
        # appear stable day-over-day. Sunday ET is the heaviest maintenance window.
        force_full_resync = bool(getattr(end_bound, "dayofweek", -1) == 6)

        expected_missing = False
        expected_missing_kind: Optional[str] = None
        latest_pdf: Optional[pd.DataFrame] = None

        try:
            # Index-prefixed symbols (e.g., "$SPX", "%SPX", "#SPX") are produced externally
            # (another worker writes the parquet). Never call yfinance (or broker prev-close)
            # for these symbols.
            if symbol.startswith(self._INDEX_PREFIXES):
                if os.path.exists(dest_path):
                    existing = self._price_store.load(symbol)
                    if existing is not None and not existing.empty:
                        latest_pdf = existing.tail(history_days)
                else:
                    self._logger.info(
                        "Index parquet missing for %s; skipping refresh (no yfinance)", symbol
                    )
            elif not os.path.exists(dest_path):
                start_hint = (end_bound - pd.Timedelta(days=max(history_days * 2, 400))).strftime(
                    "%Y-%m-%d"
                )
                df, missing_kind = self._download_prices(symbol, start_date=start_hint)
                if missing_kind and not expected_missing:
                    expected_missing = True
                    expected_missing_kind = missing_kind
                df = self._prepare_for_storage(df, end_bound_naive)
                if df is not None and not df.empty:
                    self._price_store.save(symbol, df)
                    latest_pdf = df
            else:
                existing = self._price_store.load(symbol)
                if existing is not None and not existing.empty:
                    last_dt = existing.index[-1].normalize()
                    last_in_file = existing.index[-1]
                    last_in_file_date = to_naive_ts(last_in_file).date()

                    expected_trade_date = self._prev_trading_day(end_bound.date())
                    adj_last_ok = False
                    try:
                        ac = float(existing.loc[last_in_file, "Adj Close"])
                        adj_last_ok = (ac == ac) and (not pd.isna(ac))
                    except Exception:
                        adj_last_ok = False

                    has_expected_trade = adj_last_ok and last_in_file_date >= expected_trade_date

                    if has_expected_trade:
                        latest_pdf = existing.tail(history_days)
                    else:
                        broker_ts, broker_px = self._broker.fetch_prev_close(symbol)
                        if (
                            broker_ts is not None
                            and broker_px is not None
                            and broker_ts < end_bound_naive
                            and broker_ts.date() >= last_in_file_date
                        ):
                            add = pd.DataFrame(
                                {
                                    "Open": [np.nan],
                                    "High": [np.nan],
                                    "Low": [np.nan],
                                    "Close": [float(broker_px)],
                                    "Adj Close": [float(broker_px)],
                                    "Volume": [np.nan],
                                },
                                index=[broker_ts],
                            )
                            combined = pd.concat([existing, add])
                            combined = combined[
                                ~combined.index.duplicated(keep="last")
                            ].sort_index()
                            combined = combined[to_naive_index(combined.index) < end_bound_naive]
                            combined = combined.tail(history_days)
                            self._price_store.save(symbol, combined)
                            latest_pdf = combined
                        else:
                            tail_bdays = max(history_days + 5, 30)
                            try:
                                tail_end = end_bound - pd.Timedelta(days=1)
                                tail_start = pd.bdate_range(
                                    end=tail_end, periods=max(tail_bdays, 2)
                                )[0]
                            except Exception:
                                tail_start = end_bound - pd.Timedelta(days=max(tail_bdays * 2, 400))
                            last_dt_n = to_naive_ts(last_dt)
                            tail_ts_n = to_naive_ts(pd.Timestamp(tail_start))
                            start_dt = min(last_dt_n, tail_ts_n)
                            if start_dt < end_bound_naive:
                                df_new, missing_kind = self._download_prices(
                                    symbol, start_date=start_dt.strftime("%Y-%m-%d")
                                )
                                if missing_kind and not expected_missing:
                                    expected_missing = True
                                    expected_missing_kind = missing_kind
                                df_new = self._prepare_for_storage(df_new, end_bound_naive)
                                if df_new is not None and not df_new.empty:
                                    combined = pd.concat([existing, df_new])
                                    combined = combined[
                                        ~combined.index.duplicated(keep="last")
                                    ].sort_index()
                                    combined = combined[
                                        to_naive_index(combined.index) < end_bound_naive
                                    ]
                                    combined = combined.tail(history_days)
                                    self._price_store.save(symbol, combined)
                                    latest_pdf = combined
                                else:
                                    latest_pdf = existing.tail(history_days)
                    if latest_pdf is None:
                        latest_pdf = existing.tail(history_days)
        except Exception as exc:
            self._download_failures.labels(ticker=symbol).inc()
            self._record_span_event(
                "ingestion.download_failure", {"symbol": symbol, "message": str(exc)}
            )
            self._logger.warning("Refresh failed for %s: %s", symbol, exc)

        try:
            pdf = latest_pdf if latest_pdf is not None else self._price_store.load(symbol)
            if pdf is None or pdf.empty:
                return SymbolResult(
                    symbol,
                    None,
                    expected_missing=expected_missing,
                    expected_missing_kind=expected_missing_kind,
                )
            pdf = pdf.tail(history_days)
            last_dt = pdf.index[-1].date()
            date_key = int(last_dt.strftime("%Y%m%d"))
            stock_key = self._fetch_stock_key(conn, symbol)
            if not stock_key:
                return SymbolResult(
                    symbol,
                    last_dt,
                    expected_missing=expected_missing,
                    expected_missing_kind=expected_missing_kind,
                )

            from apps.common.src.technicals import compute_technicals

            techs = compute_technicals(pdf)
            self._upsert_technicals(conn, date_key, stock_key, techs)

            price_sync = PriceSyncService(conn, history_days)
            price_sync.sync(symbol, stock_key, pdf, force_full=force_full_resync)

            conn.commit()
            self._record_span_event(
                "ingestion.symbol_processed",
                {"symbol": symbol, "last_trade_date": str(last_dt), "rows": int(len(pdf.index))},
            )
            return SymbolResult(
                symbol,
                last_dt,
                expected_missing=expected_missing,
                expected_missing_kind=expected_missing_kind,
            )
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            self._download_failures.labels(ticker=symbol).inc()
            self._record_span_event(
                "ingestion.symbol_failure", {"symbol": symbol, "message": str(exc)}
            )
            self._logger.error("Worker failed for %s: %s", symbol, exc)
            return SymbolResult(
                symbol,
                None,
                expected_missing=expected_missing,
                expected_missing_kind=expected_missing_kind,
            )

    def _prepare_for_storage(
        self, df: Optional[pd.DataFrame], end_bound_naive: pd.Timestamp
    ) -> Optional[pd.DataFrame]:
        if df is None or df.empty:
            return None
        df = canonicalize_ohlcv(df)
        df = df[to_naive_index(df.index) < end_bound_naive]
        return df.tail(self._history_days)

    def _fetch_stock_key(self, conn, symbol: str) -> Optional[int]:
        mapped = self._stock_key_map.get(symbol.upper())
        if mapped is not None:
            return int(mapped)
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT stock_key FROM dim_stock WHERE symbol = %s AND is_active IS TRUE",
                (symbol,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else None
        finally:
            cur.close()

    def _upsert_technicals(
        self, conn, date_key: int, stock_key: int, technicals: Dict[str, Any]
    ) -> None:
        if not technicals:
            return
        rows = []
        for code, value in technicals.items():
            if value is None or pd.isna(value):
                continue
            rows.append((date_key, stock_key, str(code).upper(), float(value)))
        if not rows:
            return
        cur = conn.cursor()
        try:
            execute_values(
                cur,
                """
                INSERT INTO rankalpha.fact_technical_indicator (date_key, stock_key, indicator_code, value)
                VALUES %s
                ON CONFLICT (date_key, stock_key, indicator_code)
                DO UPDATE SET value=EXCLUDED.value, load_ts=now()
                """,
                rows,
                template="(%s, %s, %s, %s)",
                page_size=100,
            )
        finally:
            cur.close()

    def _classify_yfinance_expected_missing(self, exc: BaseException) -> Optional[str]:
        msg = (str(exc) or "").lower()
        if not msg:
            return None
        candidates = (
            "no timezone found",
            "possibly delisted",
            "delisted",
            "no data found",
            "not found",
            "no price data found",
            "symbol may be delisted",
        )
        if any(token in msg for token in candidates):
            return "not_found"
        return None

    def _download_prices(
        self, symbol: str, start_date: str | None = None
    ) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        if not self._settings.ingestion_yfinance_enabled:
            self._logger.info("yfinance disabled; skipping download for %s", symbol)
            return None, "disabled"
        try:
            import yfinance as yf  # type: ignore
        except Exception as exc:
            self._logger.warning("yfinance unavailable; cannot download %s: %s", symbol, exc)
            return None, None
        kwargs = dict(auto_adjust=False, progress=False, interval="1d", prepost=False)
        y_sym = (symbol or "").replace(".", "-")
        timeout_seconds = self._float_setting("ingestion_yfinance_timeout_seconds", 20.0)
        max_retries = self._int_setting("ingestion_yfinance_max_retries", 2)
        retry_backoff_seconds = self._float_setting("ingestion_yfinance_retry_backoff_seconds", 0.5)
        total_attempts = max(1, max_retries + 1)

        def _invoke_download() -> pd.DataFrame:
            if start_date:
                return yf.download(y_sym, start=start_date, end=self._market_end_str(), **kwargs)
            return yf.download(y_sym, end=self._market_end_str(), **kwargs)

        last_error: Optional[BaseException] = None
        for attempt_idx in range(total_attempts):
            attempt_no = attempt_idx + 1
            try:
                df = self._execute_with_timeout(_invoke_download, timeout_seconds=timeout_seconds)
                if df is None or getattr(df, "empty", False):
                    # Common and expected for delisted symbols (audited via metrics + logs).
                    kind = "empty"
                    try:
                        self._expected_missing_counter.labels(provider="yfinance", kind=kind).inc()
                    except Exception:
                        pass
                    self._record_span_event(
                        "ingestion.yfinance_expected_missing",
                        {"symbol": symbol, "kind": kind},
                    )
                    self._logger.info(
                        "yfinance returned no data for %s; treating as expected-missing (kind=%s)",
                        symbol,
                        kind,
                    )
                    return None, kind
                return df, None
            except TimeoutError as exc:
                last_error = exc
                self._logger.warning(
                    "yfinance download timeout for %s (attempt %d/%d timeout=%.1fs)",
                    symbol,
                    attempt_no,
                    total_attempts,
                    timeout_seconds,
                )
            except Exception as exc:
                missing_kind = self._classify_yfinance_expected_missing(exc)
                if missing_kind:
                    try:
                        self._expected_missing_counter.labels(
                            provider="yfinance", kind=missing_kind
                        ).inc()
                    except Exception:
                        pass
                    self._record_span_event(
                        "ingestion.yfinance_expected_missing",
                        {"symbol": symbol, "kind": missing_kind, "message": str(exc)},
                    )
                    self._logger.info(
                        "yfinance missing data for %s; treating as expected-missing (kind=%s): %s",
                        symbol,
                        missing_kind,
                        exc,
                    )
                    return None, missing_kind

                last_error = exc
                self._logger.warning(
                    "yfinance download failed for %s (attempt %d/%d): %s",
                    symbol,
                    attempt_no,
                    total_attempts,
                    exc,
                )

            if attempt_no < total_attempts:
                self._sleep_before_retry(attempt_no, retry_backoff_seconds)

        if last_error is not None:
            self._logger.warning(
                "yfinance download exhausted retries for %s after %d attempt(s): %s",
                symbol,
                total_attempts,
                last_error,
            )
        return None, None

    def _sleep_before_retry(self, attempt_no: int, base_seconds: float) -> None:
        delay = max(0.0, float(base_seconds)) * float(2 ** max(0, attempt_no - 1))
        if delay <= 0:
            return
        time.sleep(delay)

    def _execute_with_timeout(
        self, fn: Callable[[], pd.DataFrame], *, timeout_seconds: float
    ) -> pd.DataFrame:
        timeout = max(0.1, float(timeout_seconds))
        result_queue: Queue[Tuple[bool, Any]] = Queue(maxsize=1)

        def _runner() -> None:
            try:
                result_queue.put((True, fn()))
            except Exception as exc:  # pragma: no cover - exercised via caller behavior
                result_queue.put((False, exc))

        # Use a daemon thread so a stuck download cannot block this worker's retry loop.
        worker = Thread(target=_runner, name="ingestion-yfinance-download", daemon=True)
        worker.start()
        worker.join(timeout=timeout)
        if worker.is_alive():
            raise TimeoutError("yfinance download timed out")

        try:
            ok, payload = result_queue.get_nowait()
        except Empty as exc:  # pragma: no cover - defensive
            raise RuntimeError("yfinance download worker exited without result") from exc

        if ok:
            return payload
        raise payload

    def _float_setting(self, key: str, default: float) -> float:
        try:
            value = getattr(self._settings, key, None)
            parsed = float(value) if value is not None else float(default)
        except Exception:
            parsed = float(default)
        return parsed if parsed > 0 else float(default)

    def _int_setting(self, key: str, default: int) -> int:
        try:
            value = getattr(self._settings, key, None)
            parsed = int(value) if value is not None else int(default)
        except Exception:
            parsed = int(default)
        return parsed if parsed >= 0 else int(default)

    def _market_end_str(self) -> str:
        now_et = pd.Timestamp.now(tz="America/New_York")
        return now_et.normalize().strftime("%Y-%m-%d")

    def _is_trading_day(self, d: date) -> bool:
        try:
            from apps.broker.tradeexec.utils.market_calendar import (
                is_trading_day as is_td,  # type: ignore
            )

            return bool(is_td(d))
        except Exception:
            return d.weekday() < 5

    def _prev_trading_day(self, d: date) -> date:
        candidate = d
        while True:
            candidate = candidate - timedelta(days=1)
            if self._is_trading_day(candidate):
                return candidate

    def _record_span_event(self, name: str, attributes: Dict[str, Any]) -> None:
        if not self._span:
            return
        try:
            self._span.add_event(name, attributes)
        except Exception:
            pass
