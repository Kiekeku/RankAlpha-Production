"""Maintains symbol activity flags based on ingestion results."""

from __future__ import annotations

import re
from bisect import bisect_right
from datetime import date, datetime, timedelta
from typing import Callable, Dict, Optional

import pandas as pd
import psycopg2

from apps.ingestion.src.price_store import PriceStore
from apps.ingestion.src.settings import Settings


class UniverseMaintainer:
    """Maintains dim_stock.is_active based on peer activity."""

    def __init__(
        self,
        settings: Settings,
        price_store: PriceStore,
        db_factory: Callable[[], psycopg2.extensions.connection],
        logger,
    ) -> None:
        self._settings = settings
        self._price_store = price_store
        self._db_factory = db_factory
        self._logger = logger
        try:
            self._inact_bdays = int(settings.ingestion_inactive_after_missing_bdays or 30)
        except Exception:
            self._inact_bdays = 30
        try:
            self._react_bdays = int(settings.ingestion_reactivate_if_within_bdays or 1)
        except Exception:
            self._react_bdays = 1
        try:
            self._ref_sym = (settings.ingestion_reference_symbol or "SPY").upper()
        except Exception:
            self._ref_sym = "SPY"
        try:
            self._min_share = float(settings.ingestion_anchor_min_share or 0.5)
        except Exception:
            self._min_share = 0.5
        try:
            self._prune_bdays = int(
                getattr(settings, "ingestion_prune_after_missing_bdays", None) or self._inact_bdays
            )
        except Exception:
            self._prune_bdays = self._inact_bdays

    def apply(self, last_dates: Dict[str, date]) -> None:
        anchor = self._choose_anchor_date(last_dates)
        if anchor is None:
            self._logger.info(
                "Inactive/reactivation check skipped: could not determine anchor date"
            )
            return

        processed_symbols = set(last_dates.keys())
        parquet_last_dates: Dict[str, date] = dict(last_dates)
        gaps = self._trading_day_gaps(parquet_last_dates, anchor)
        to_inactivate = [
            sym
            for sym, last_dt in last_dates.items()
            if gaps.get(sym, self._fallback_business_day_gap(last_dt, anchor)) >= self._inact_bdays
        ]

        all_parquets = self._price_store.list_existing()
        inactive_candidates = sorted(all_parquets - processed_symbols)
        to_reactivate: list[str] = []
        for sym in inactive_candidates:
            df = self._price_store.load(sym)
            if df is None or df.empty:
                continue
            last_dt = df.index[-1].date()
            parquet_last_dates[sym] = last_dt
            sym_gap = gaps.get(sym, self._fallback_business_day_gap(last_dt, anchor))
            if sym_gap <= self._react_bdays and not self._looks_delisted(sym):
                to_reactivate.append(sym)

        self._apply_db_updates(to_inactivate, to_reactivate)
        self._prune_parquet_files(parquet_last_dates, anchor)

    def evaluate_staleness(
        self, last_dates: Dict[str, date], *, stale_after_missing_bdays: int
    ) -> tuple[Optional[date], list[str]]:
        """Return anchor date and list of symbols that are stale vs the anchor."""
        anchor = self._choose_anchor_date(last_dates)
        if anchor is None or stale_after_missing_bdays <= 0:
            return anchor, []
        gaps = self._trading_day_gaps(last_dates, anchor)
        stale: list[str] = []
        for sym, last_dt in last_dates.items():
            gap = gaps.get(sym, self._fallback_business_day_gap(last_dt, anchor))
            if gap >= stale_after_missing_bdays:
                stale.append(sym)
        return anchor, stale

    def _choose_anchor_date(self, last_dates: Dict[str, date]) -> Optional[date]:
        df_ref = self._price_store.load(self._ref_sym)
        if df_ref is not None and not df_ref.empty:
            return df_ref.index[-1].date()
        if not last_dates:
            return None
        vals = list(last_dates.values())
        vc = pd.Series(vals, dtype="datetime64[ns]").dt.date.value_counts(dropna=True)
        if vc.empty:
            return max(vals)
        top_date = vc.idxmax()
        share = float(vc.max()) / max(1.0, float(vc.sum()))
        if share >= self._min_share:
            return top_date
        return max(vals)

    def _looks_delisted(self, symbol: str) -> bool:
        return bool(re.search(r"-[0-9]{6}$", symbol))

    def _fallback_business_day_gap(self, a: date, b: date) -> int:
        if a is None or b is None or a >= b:
            return 0
        start = pd.Timestamp(a) + pd.Timedelta(days=1)
        end = pd.Timestamp(b)
        rng = pd.bdate_range(start=start, end=end)
        return int(len(rng))

    def _load_trading_calendar(self, start: date, end: date) -> list[date]:
        """Fetch trading days from rankalpha.dim_date to account for market holidays.

        Falls back silently (returns empty) when the DB is unavailable.
        """
        try:
            conn = self._db_factory()
        except Exception:
            return []
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT full_date
                FROM rankalpha.dim_date
                WHERE is_trading_day IS TRUE
                  AND full_date BETWEEN %s AND %s
                ORDER BY full_date
                """,
                (start, end),
            )
            rows = cur.fetchall() or []
        except Exception:
            rows = []
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        out: list[date] = []
        for (dval,) in rows:
            try:
                if isinstance(dval, date) and not isinstance(dval, datetime):
                    out.append(dval)
                elif isinstance(dval, datetime):
                    out.append(dval.date())
                else:
                    out.append(pd.to_datetime(dval).date())
            except Exception:
                continue
        return out

    def _trading_day_gaps(self, last_dates: Dict[str, date], anchor: date) -> Dict[str, int]:
        """Compute per-symbol trading-day gaps vs anchor using dim_date when possible."""
        if not last_dates or anchor is None:
            return {}
        try:
            min_dt = min(last_dates.values())
        except Exception:
            return {}
        # Pad the window so we can map weekend/holiday last_dt to the prior trading day.
        start = min_dt - timedelta(days=14)
        end = anchor
        trade_days = self._load_trading_calendar(start, end)
        if not trade_days:
            return {}

        # Compute anchor index as the last trading day <= anchor.
        aidx = bisect_right(trade_days, anchor) - 1
        if aidx < 0:
            return {}

        gaps: Dict[str, int] = {}
        for sym, last_dt in last_dates.items():
            try:
                if last_dt is None or last_dt >= anchor:
                    gaps[sym] = 0
                    continue
                idx = bisect_right(trade_days, last_dt) - 1
                if idx < 0:
                    gaps[sym] = self._fallback_business_day_gap(last_dt, anchor)
                    continue
                gaps[sym] = max(int(aidx - idx), 0)
            except Exception:
                gaps[sym] = self._fallback_business_day_gap(last_dt, anchor)
        return gaps

    def _apply_db_updates(self, to_inactivate: list[str], to_reactivate: list[str]) -> None:
        if not to_inactivate and not to_reactivate:
            return
        conn = self._db_factory()
        cur = conn.cursor()
        inact_count = 0
        react_count = 0
        purged_price_rows = 0
        try:
            if to_inactivate:
                cur.execute(
                    """
                    WITH updated AS (
                        UPDATE dim_stock
                        SET is_active = FALSE
                        WHERE symbol = ANY(%s) AND is_active IS TRUE
                        RETURNING stock_key
                    ),
                    deleted AS (
                        DELETE FROM rankalpha.fact_security_price p
                        USING updated u
                        WHERE p.stock_key = u.stock_key
                        RETURNING 1
                    )
                    SELECT
                        COALESCE((SELECT COUNT(*) FROM updated), 0) AS inact_count,
                        COALESCE((SELECT COUNT(*) FROM deleted), 0) AS purged_count
                    """,
                    (to_inactivate,),
                )
                row = cur.fetchone()
                if row:
                    inact_count += int(row[0] or 0)
                    purged_price_rows += int(row[1] or 0)

            if to_reactivate:
                cur.execute(
                    """
                    WITH updated AS (
                        UPDATE dim_stock
                        SET is_active = TRUE
                        WHERE symbol = ANY(%s) AND is_active IS FALSE
                        RETURNING 1
                    )
                    SELECT COALESCE(COUNT(*), 0)::int AS react_count FROM updated
                    """,
                    (to_reactivate,),
                )
                row = cur.fetchone()
                if row:
                    react_count += int(row[0] or 0)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()
        self._logger.info(
            "Peer-activity check: anchor updates inactivated=%d reactivated=%d purged_price_rows=%d",
            inact_count,
            react_count,
            purged_price_rows,
        )

    def _prune_parquet_files(self, last_dates: Dict[str, date], anchor: date) -> None:
        if self._prune_bdays <= 0 or not last_dates:
            return
        gaps = self._trading_day_gaps(last_dates, anchor)
        prune_candidates = [
            sym
            for sym, last_dt in last_dates.items()
            if sym != self._ref_sym
            and gaps.get(sym, self._fallback_business_day_gap(last_dt, anchor)) >= self._prune_bdays
        ]
        if not prune_candidates:
            return
        pruned = 0
        conn = self._db_factory()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT symbol, is_active
                FROM dim_stock
                WHERE symbol = ANY(%s)
                """,
                (prune_candidates,),
            )
            rows = cur.fetchall() or []
            is_active_by_symbol = {str(sym).upper(): bool(is_active) for sym, is_active in rows}
            for sym in prune_candidates:
                if is_active_by_symbol.get(sym.upper(), False):
                    continue
                if self._price_store.delete(sym):
                    pruned += 1
        finally:
            cur.close()
            conn.close()
        if pruned:
            self._logger.info(
                "Pruned %d inactive parquet files (cutoff=%d business days)",
                pruned,
                self._prune_bdays,
            )
