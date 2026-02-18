from __future__ import annotations

import contextlib
import time
from decimal import Decimal
from typing import Any, Optional

from psycopg2 import sql
from psycopg2.extras import execute_values
from sqlalchemy import text

from apps.common.src.db import BatchWriter, get_engine


class ScoreRepository:
    def __init__(self, dsn: str, logger) -> None:
        self.dsn = dsn
        self.logger = logger
        self.conn: Optional[Any] = None
        self._conn_ctx = None
        # Shared SQLAlchemy engine for non-batch work; BatchWriter for bulk paths
        self.engine = get_engine(url_override=dsn)
        self.batch = BatchWriter(dsn=dsn)

    # Connection lifecycle
    def connect(self, attempts: int = 10, delay_seconds: float = 3.0):
        last_exc: Exception | None = None
        for i in range(1, attempts + 1):
            try:
                # Explicit autocommit=False so callers control commit/rollback
                ctx = self.batch.connect(autocommit=False)
                self._conn_ctx = ctx
                self.conn = ctx.__enter__()
                return self.conn
            except Exception as exc:  # pragma: no cover
                last_exc = exc
                self.logger.warning(f"DB connect attempt {i}/{attempts} failed: {exc}")
                time.sleep(delay_seconds)
        if last_exc:
            raise last_exc

    def dispose(self):
        try:
            if self._conn_ctx is not None:
                # Close without committing to avoid implicit persistence; rollback to be safe.
                self.conn.rollback()
                self._conn_ctx.__exit__(None, None, None)
            elif self.conn is not None:
                self.conn.rollback()
                self.conn.close()
        except Exception:
            pass
        try:
            self.engine.dispose()
        except Exception:
            pass

    # Dim/Fact helpers
    def ensure_score_types(self, cursor):
        names = [
            "SMA 200",
            "linear regression 200",
            "linear regression 90",
            "linear regression 50",
            "linear regression 30",
            "quality score",
            "ai momentum score",
            "low volatility score",
            "sentiment score",
            "value score",
            "momentum score",
            "momentum raw score",
            "momentum residual score",
            "money flow score",
        ]
        for name in names:
            cursor.execute(
                "INSERT INTO dim_score_type (score_type_name) VALUES (%s) ON CONFLICT (score_type_name) DO NOTHING",
                (name,),
            )

    def fetch_score_type_keys(self, cursor) -> dict[str, int]:
        cursor.execute("SELECT score_type_key, score_type_name FROM dim_score_type")
        return {name.lower(): key for key, name in cursor.fetchall()}

    def upsert_dim_stock(self, cursor, ticker: str) -> int | None:
        t = str(ticker).upper()
        cursor.execute(
            """
            INSERT INTO dim_stock (symbol, company_name, sector, exchange)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (symbol) DO NOTHING
            RETURNING stock_key
            """,
            (t, t, "Unknown", "Unknown"),
        )
        row = cursor.fetchone()
        if row:
            return int(row[0])
        cursor.execute("SELECT stock_key FROM dim_stock WHERE symbol = %s", (t,))
        row = cursor.fetchone()
        return int(row[0]) if row else None

    def fetch_stock_key(self, cursor, ticker: str) -> int | None:
        cursor.execute(
            "SELECT stock_key FROM dim_stock WHERE symbol = %s AND is_active IS TRUE", (ticker,)
        )
        result = cursor.fetchone()
        if result:
            return int(result[0])
        return self.upsert_dim_stock(cursor, ticker)

    def insert_score(
        self, cursor, date_key: int, stock_key: int, score_type_key: int, value: float
    ) -> None:
        cursor.execute(
            """
            INSERT INTO fact_score_history (
                date_key, stock_key, source_key, score_type_key, score
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (date_key, stock_key, 1, score_type_key, value),
        )

    def insert_scores(
        self, cursor, rows: list[tuple[int, int, int, float]], *, page_size: int = 1000
    ) -> int:
        """Bulk-insert fact_score_history rows.

        Rows are tuples of: (date_key, stock_key, score_type_key, score).
        Uses a savepoint-scoped bulk insert and falls back to row-wise inserts if the
        batch fails so the scorer can continue past isolated bad rows.
        """
        if not rows:
            return 0

        values = [(int(dk), int(sk), 1, int(stk), float(val)) for dk, sk, stk, val in rows]
        insert_sql = """
            INSERT INTO fact_score_history (
                date_key, stock_key, source_key, score_type_key, score
            ) VALUES %s
        """

        # Fast path: one bulk statement.
        try:
            cursor.execute("SAVEPOINT scorer_bulk_insert")
            execute_values(
                cursor,
                insert_sql,
                values,
                template="(%s, %s, %s, %s, %s)",
                page_size=page_size,
            )
            cursor.execute("RELEASE SAVEPOINT scorer_bulk_insert")
            return len(values)
        except Exception as exc:
            with contextlib.suppress(Exception):
                cursor.execute("ROLLBACK TO SAVEPOINT scorer_bulk_insert")
                cursor.execute("RELEASE SAVEPOINT scorer_bulk_insert")
            self.logger.warning(f"Bulk insert fallback to row-wise for {len(values)} rows: {exc}")

        # Fallback: isolate each row with a savepoint.
        inserted = 0
        for dk, sk, source_key, stk, val in values:
            try:
                cursor.execute("SAVEPOINT scorer_row_insert")
                cursor.execute(
                    """
                    INSERT INTO fact_score_history (
                        date_key, stock_key, source_key, score_type_key, score
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (dk, sk, source_key, stk, val),
                )
                cursor.execute("RELEASE SAVEPOINT scorer_row_insert")
                inserted += 1
            except Exception:
                with contextlib.suppress(Exception):
                    cursor.execute("ROLLBACK TO SAVEPOINT scorer_row_insert")
                    cursor.execute("RELEASE SAVEPOINT scorer_row_insert")
                continue
        return inserted

    def insert_score_if_absent(
        self, cursor, date_key: int, stock_key: int, score_type_key: int, value: float
    ) -> None:
        cursor.execute(
            """
            INSERT INTO fact_score_history (date_key, stock_key, source_key, score_type_key, score)
            SELECT %s, %s, %s, %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM fact_score_history f
                WHERE f.date_key = %s AND f.stock_key = %s AND f.score_type_key = %s
                LIMIT 1
            )
            """,
            (date_key, stock_key, 1, score_type_key, value, date_key, stock_key, score_type_key),
        )

    # Maintenance
    def refresh_materialized_views(self) -> None:
        views: list[tuple[str, str]] = []
        try:
            with self.batch.connect(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT schemaname, matviewname
                        FROM pg_matviews
                        WHERE schemaname = %s AND matviewname LIKE %s
                        """,
                        ("rankalpha", "mv_%"),
                    )
                    views = cur.fetchall()
        except Exception as exc:  # pragma: no cover
            self.logger.warning(f"Could not enumerate materialized views: {exc}")

        if not views:
            return

        try:
            with self.batch.connect(autocommit=True) as conn:
                for schemaname, matviewname in views:
                    qualified = sql.Identifier(schemaname, matviewname)
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                sql.SQL("REFRESH MATERIALIZED VIEW CONCURRENTLY {}").format(
                                    qualified
                                )
                            )
                        self.logger.info(
                            f"Refreshed materialized view {schemaname}.{matviewname} concurrently"
                        )
                    except Exception as exc:  # pragma: no cover
                        self.logger.warning(
                            f"Concurrent refresh failed for {schemaname}.{matviewname}: {exc}; retrying non-concurrent"
                        )
                        try:
                            with conn.cursor() as cur:
                                cur.execute(
                                    sql.SQL("REFRESH MATERIALIZED VIEW {}").format(qualified)
                                )
                            self.logger.info(
                                f"Refreshed materialized view {schemaname}.{matviewname}"
                            )
                        except Exception as exc2:
                            self.logger.error(
                                f"Could not refresh {schemaname}.{matviewname}: {exc2}"
                            )
        except Exception as exc:  # pragma: no cover
            self.logger.error(f"Failed to refresh materialized views: {exc}")

    def capture_screener_changes(self) -> None:
        # Refresh mv_screener_changes
        try:
            with self.batch.connect(autocommit=True) as conn:
                with conn.cursor() as cur:
                    try:
                        cur.execute(
                            "REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_screener_changes"
                        )
                        self.logger.info("Refreshed mv_screener_changes concurrently")
                    except Exception as exc:
                        self.logger.warning(
                            f"Concurrent refresh failed for mv_screener_changes: {exc}; retrying non-concurrent"
                        )
                        cur.execute("REFRESH MATERIALIZED VIEW rankalpha.mv_screener_changes")
                        self.logger.info("Refreshed mv_screener_changes")
        except Exception as exc:
            self.logger.error(f"Failed to refresh mv_screener_changes: {exc}")

        # Persist new events
        inserted = 0
        try:
            with self.batch.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO rankalpha.fact_screener_rank_change (
                            change_date_key, stock_key, source_key, style_key, change_type,
                            current_rank, previous_rank, rank_delta,
                            last_seen_date_key, days_since_last_seen, absent_trading_days
                        )
                        SELECT v.change_date_key, v.stock_key, v.source_key, v.style_key, v.change_type,
                               v.current_rank, v.previous_rank, v.rank_delta,
                               v.last_seen_date_key, v.days_since_last_seen, v.absent_trading_days
                        FROM rankalpha.mv_screener_changes v
                        WHERE NOT EXISTS (
                            SELECT 1 FROM rankalpha.fact_screener_rank_change f
                            WHERE f.change_date_key = v.change_date_key
                              AND f.stock_key = v.stock_key
                              AND f.source_key = v.source_key
                              AND ((f.style_key IS NULL AND v.style_key IS NULL) OR f.style_key = v.style_key)
                              AND f.change_type = v.change_type
                        )
                          AND EXISTS (
                              SELECT 1 FROM rankalpha.dim_source src
                              WHERE src.source_key = v.source_key
                                AND src.exclude_from_screener IS NOT TRUE
                          )
                        """
                    )
                    inserted = cur.rowcount or 0
            if inserted:
                self.logger.info(f"Recorded {inserted} new screener change event(s)")
            else:
                self.logger.info("No new screener change events detected")
        except Exception as exc:
            self.logger.error(f"Failed to record screener change events: {exc}")

    def update_screener_presence(self) -> None:
        """Upsert daily presence streaks per family and per side (long/short).

        - Uses latest trading day from fact_screener_rank
        - Respects excluded sources via dim_source.exclude_from_screener
        - Idempotent: ON CONFLICT upserts for the day
        """
        try:
            with self.batch.connect() as conn:
                with conn.cursor() as cur:
                    # Discover latest date_key present in screener facts
                    cur.execute("SELECT max(date_key) FROM rankalpha.fact_screener_rank")
                    row = cur.fetchone()
                    if not row or row[0] is None:
                        return
                    d0 = int(row[0])

                    # Upsert per-family presence with consecutive counters
                    cur.execute(
                        """
                        WITH present AS (
                            SELECT f.stock_key, f.style_key
                            FROM rankalpha.fact_screener_rank f
                            JOIN rankalpha.dim_source src ON src.source_key = f.source_key
                            WHERE f.date_key = %s AND src.exclude_from_screener IS NOT TRUE
                            GROUP BY f.stock_key, f.style_key
                        ), prev AS (
                            SELECT DISTINCT ON (p.stock_key, p.style_key)
                                   p.stock_key, p.style_key, p.consec_days_family
                            FROM rankalpha.fact_screener_presence p
                            WHERE p.date_key < %s
                            ORDER BY p.stock_key, p.style_key, p.date_key DESC
                        )
                        INSERT INTO rankalpha.fact_screener_presence (
                            date_key, stock_key, style_key, present_today, consec_days_family
                        )
                        SELECT %s AS date_key,
                               pr.stock_key,
                               pr.style_key,
                               TRUE AS present_today,
                               COALESCE(prev.consec_days_family, 0) + 1 AS consec_days_family
                        FROM present pr
                        LEFT JOIN prev ON prev.stock_key = pr.stock_key AND prev.style_key = pr.style_key
                        ON CONFLICT (date_key, stock_key, style_key) DO UPDATE
                        SET present_today = EXCLUDED.present_today,
                            consec_days_family = EXCLUDED.consec_days_family
                        """,
                        (d0, d0, d0),
                    )

                    # Insert reset rows for families that were previously present but are missing today
                    cur.execute(
                        """
                        WITH present AS (
                            SELECT f.stock_key, f.style_key
                            FROM rankalpha.fact_screener_rank f
                            JOIN rankalpha.dim_source src ON src.source_key = f.source_key
                            WHERE f.date_key = %s AND src.exclude_from_screener IS NOT TRUE
                            GROUP BY f.stock_key, f.style_key
                        ), prev_keys AS (
                            SELECT DISTINCT ON (p.stock_key, p.style_key)
                                   p.stock_key, p.style_key
                            FROM rankalpha.fact_screener_presence p
                            WHERE p.date_key < %s
                            ORDER BY p.stock_key, p.style_key, p.date_key DESC
                        ), missing AS (
                            SELECT pk.stock_key, pk.style_key
                            FROM prev_keys pk
                            LEFT JOIN present pr
                              ON pr.stock_key = pk.stock_key AND pr.style_key = pk.style_key
                            WHERE pr.stock_key IS NULL
                        )
                        INSERT INTO rankalpha.fact_screener_presence (
                            date_key, stock_key, style_key, present_today, consec_days_family
                        )
                        SELECT %s AS date_key, m.stock_key, m.style_key, FALSE, 0
                        FROM missing m
                        ON CONFLICT (date_key, stock_key, style_key) DO UPDATE
                        SET present_today = FALSE,
                            consec_days_family = 0
                        """,
                        (d0, d0, d0),
                    )

                    # Upsert per-side (long/short) presence with consecutive counters
                    cur.execute(
                        """
                        WITH present_long AS (
                            SELECT fr.stock_key, 'long'::text AS side
                            FROM rankalpha.fact_screener_rank fr
                            JOIN rankalpha.dim_source src ON src.source_key = fr.source_key AND src.exclude_from_screener IS NOT TRUE
                            JOIN rankalpha.dim_style sty ON sty.style_key = fr.style_key AND sty.position_side = 'long'
                            WHERE fr.date_key = %s
                            GROUP BY fr.stock_key
                        ), present_short AS (
                            SELECT fr.stock_key, 'short'::text AS side
                            FROM rankalpha.fact_screener_rank fr
                            JOIN rankalpha.dim_source src ON src.source_key = fr.source_key AND src.exclude_from_screener IS NOT TRUE
                            JOIN rankalpha.dim_style sty ON sty.style_key = fr.style_key AND sty.position_side = 'short'
                            WHERE fr.date_key = %s
                            GROUP BY fr.stock_key
                        ), present AS (
                            SELECT * FROM present_long
                            UNION ALL
                            SELECT * FROM present_short
                        ), prev AS (
                            SELECT DISTINCT ON (ps.stock_key, ps.position_side)
                                   ps.stock_key, ps.position_side, ps.consec_days_any_side
                            FROM rankalpha.fact_screener_presence_side ps
                            WHERE ps.date_key < %s
                            ORDER BY ps.stock_key, ps.position_side, ps.date_key DESC
                        )
                        INSERT INTO rankalpha.fact_screener_presence_side (
                            date_key, stock_key, position_side, present_any_side, consec_days_any_side
                        )
                        SELECT %s AS date_key,
                               p.stock_key,
                               p.side AS position_side,
                               TRUE AS present_any_side,
                               COALESCE(prev.consec_days_any_side, 0) + 1 AS consec_days_any_side
                        FROM present p
                        LEFT JOIN prev ON prev.stock_key = p.stock_key AND prev.position_side = p.side
                        ON CONFLICT (date_key, stock_key, position_side) DO UPDATE
                        SET present_any_side = EXCLUDED.present_any_side,
                            consec_days_any_side = EXCLUDED.consec_days_any_side
                        """,
                        (d0, d0, d0, d0),
                    )

                    # Insert reset rows for sides that were previously present but are missing today
                    cur.execute(
                        """
                        WITH present_long AS (
                            SELECT fr.stock_key, 'long'::text AS side
                            FROM rankalpha.fact_screener_rank fr
                            JOIN rankalpha.dim_source src ON src.source_key = fr.source_key AND src.exclude_from_screener IS NOT TRUE
                            JOIN rankalpha.dim_style sty ON sty.style_key = fr.style_key AND sty.position_side = 'long'
                            WHERE fr.date_key = %s
                            GROUP BY fr.stock_key
                        ), present_short AS (
                            SELECT fr.stock_key, 'short'::text AS side
                            FROM rankalpha.fact_screener_rank fr
                            JOIN rankalpha.dim_source src ON src.source_key = fr.source_key AND src.exclude_from_screener IS NOT TRUE
                            JOIN rankalpha.dim_style sty ON sty.style_key = fr.style_key AND sty.position_side = 'short'
                            WHERE fr.date_key = %s
                            GROUP BY fr.stock_key
                        ), present AS (
                            SELECT * FROM present_long
                            UNION ALL
                            SELECT * FROM present_short
                        ), prev_keys AS (
                            SELECT DISTINCT ON (ps.stock_key, ps.position_side)
                                   ps.stock_key, ps.position_side
                            FROM rankalpha.fact_screener_presence_side ps
                            WHERE ps.date_key < %s
                            ORDER BY ps.stock_key, ps.position_side, ps.date_key DESC
                        ), missing AS (
                            SELECT pk.stock_key, pk.position_side
                            FROM prev_keys pk
                            LEFT JOIN present p ON p.stock_key = pk.stock_key AND p.side = pk.position_side
                            WHERE p.stock_key IS NULL
                        )
                        INSERT INTO rankalpha.fact_screener_presence_side (
                            date_key, stock_key, position_side, present_any_side, consec_days_any_side
                        )
                        SELECT %s AS date_key, m.stock_key, m.position_side, FALSE, 0
                        FROM missing m
                        ON CONFLICT (date_key, stock_key, position_side) DO UPDATE
                        SET present_any_side = FALSE,
                            consec_days_any_side = 0
                        """,
                        (d0, d0, d0, d0),
                    )

                    # Note: Do NOT refresh concurrently inside this transaction block.
                    # We'll refresh scores MV on a separate autocommit connection below.
        except Exception as exc:
            self.logger.error(f"Failed to update screener presence / scores: {exc}")

        # Refresh scores MV on a fresh autocommit connection (avoid TX abort on CONCURRENTLY)
        try:
            with self.batch.connect(autocommit=True) as conn:
                with conn.cursor() as cur:
                    try:
                        cur.execute(
                            "REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_screener_scores_latest"
                        )
                        self.logger.info("Refreshed mv_screener_scores_latest concurrently")
                    except Exception as exc:
                        self.logger.warning(
                            f"Concurrent refresh failed for mv_screener_scores_latest: {exc}; retrying non-concurrent"
                        )
                        cur.execute("REFRESH MATERIALIZED VIEW rankalpha.mv_screener_scores_latest")
                        self.logger.info("Refreshed mv_screener_scores_latest")
        except Exception as exc:
            self.logger.error(f"Failed to refresh mv_screener_scores_latest: {exc}")

    # ---------------- Regime (US) -----------------------------
    def update_regime_series_us(self) -> None:
        """Compute US-only regime series for the latest trading day.

        Steps:
        - Refresh universe + intensity MVs
        - For latest date_key, compute robust Z per canonical style using last 252d history
        - Compose RiskOnCore/RiskOffCore/RegimeRaw, EMAs, label, index
        - Persist to fact_style_z_us, fact_regime_series, and fact_regime_effective_weight
        """
        import numpy as _np
        import pandas as _pd

        # 1) Refresh MVs
        # Refresh required MVs in dependency order: universe first, then style intensity
        try:
            with self.batch.connect(autocommit=True) as conn:
                with conn.cursor() as cur:
                    # 1) Universe
                    try:
                        cur.execute(
                            "REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_universe_regime_us"
                        )
                        self.logger.info("Refreshed mv_universe_regime_us concurrently")
                    except Exception as exc:
                        self.logger.warning(
                            f"Concurrent refresh failed for mv_universe_regime_us: {exc}; retrying non-concurrent"
                        )
                        cur.execute("REFRESH MATERIALIZED VIEW rankalpha.mv_universe_regime_us")
                        self.logger.info("Refreshed mv_universe_regime_us")
                    # 2) Style intensity (depends on universe)
                    try:
                        cur.execute(
                            "REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_style_intensity_us"
                        )
                        self.logger.info("Refreshed mv_style_intensity_us concurrently")
                    except Exception as exc:
                        self.logger.warning(
                            f"Concurrent refresh failed for mv_style_intensity_us: {exc}; retrying non-concurrent"
                        )
                        cur.execute("REFRESH MATERIALIZED VIEW rankalpha.mv_style_intensity_us")
                        self.logger.info("Refreshed mv_style_intensity_us")
        except Exception as exc:
            self.logger.error(f"Failed to refresh regime MVs: {exc}")

        # 2) Load recent intensity history (default ~400 trading days)
        max_days = 400
        try:
            query = text(
                """
                WITH recent AS (
                  SELECT DISTINCT date_key
                  FROM rankalpha.mv_style_intensity_us
                  ORDER BY date_key DESC
                  LIMIT :limit
                )
                SELECT d.full_date, i.date_key, i.style_name, i.intensity_raw
                FROM rankalpha.mv_style_intensity_us i
                JOIN rankalpha.dim_date d ON d.date_key = i.date_key
                WHERE i.date_key IN (SELECT date_key FROM recent)
                ORDER BY i.date_key ASC, i.style_name ASC
                """
            )
            df = _pd.read_sql_query(
                query, self.engine, params={"limit": max_days}, parse_dates=["full_date"]
            )
        except Exception as exc:
            self.logger.error(f"Failed to load style intensity history: {exc}")
            return

        if df.empty:
            self.logger.info("No style intensity rows available; skipping regime update")
            return

        # Canonical style ordering (fallback to observed styles)
        try:
            canon_df = _pd.read_sql(
                "SELECT DISTINCT canonical_name FROM rankalpha.dim_style_regime_map ORDER BY 1",
                self.engine,
            )
            canon_styles = [
                str(x) for x in canon_df["canonical_name"].tolist() if isinstance(x, str)
            ]
        except Exception:
            canon_styles = []
        if not canon_styles:
            canon_styles = sorted(set(str(s) for s in df["style_name"].unique()))

        wide = (
            df.pivot_table(
                index="full_date", columns="style_name", values="intensity_raw", aggfunc="first"
            )
            .sort_index()
            .fillna(0.0)
        )
        for style in canon_styles:
            if style not in wide.columns:
                wide[style] = 0.0
        wide = wide[canon_styles]

        if wide.empty:
            self.logger.info("Style intensity pivot is empty; skipping regime update")
            return

        def _robust_z(series: _pd.Series, win: int = 252) -> _pd.Series:
            series = series.astype(float)
            median = series.rolling(win, min_periods=90).median()

            def _mad(window: _pd.Series) -> float:
                arr = window.values.astype(float)
                if arr.size == 0:
                    return 0.0
                med = _np.median(arr)
                return float(_np.median(_np.abs(arr - med)))

            mad = series.rolling(win, min_periods=90).apply(_mad, raw=False)
            scale = 1.4826 * mad
            iqr = series.rolling(win, min_periods=90).quantile(0.75) - series.rolling(
                win, min_periods=90
            ).quantile(0.25)
            scale = scale.where((scale > 1e-8) & _np.isfinite(scale), 0.7413 * iqr)
            std = series.rolling(win, min_periods=2).std()
            scale = scale.where((scale > 1e-8) & _np.isfinite(scale), std.clip(lower=1e-6))
            z = (series - median) / scale
            return z.replace([_np.inf, -_np.inf], 0.0).fillna(0.0).clip(-4, 4)

        zwide = wide.apply(_robust_z)
        zwide = zwide.replace([_np.inf, -_np.inf], 0.0).fillna(0.0)

        # Map dates to date_keys
        date_lookup = {
            _pd.Timestamp(row.full_date).date(): int(row.date_key)
            for row in df[["full_date", "date_key"]].drop_duplicates().itertuples(index=False)
        }

        if not date_lookup:
            self.logger.warning("Could not map dates to date_keys; skipping regime update")
            return

        # Risk-on/off core construction
        risk_on = {
            "Momentum": 1.0,
            "Pullback": 0.6,
            "QualityGrowth": 0.9,
            "ValueGARP": 0.4,
            "IPO": 0.5,
            "EarningsPost": 0.6,
            "Squeeze": 0.3,
        }
        risk_off = {
            "Short": 1.0,
            "MeanRev": 0.6,
            "Defensive": 0.5,
            "EarningsPre": 0.3,
        }

        try:
            weights_df = _pd.read_sql(
                """
                SELECT canonical_name, MAX(regime_weight) AS regime_weight
                FROM rankalpha.dim_style_regime_map
                GROUP BY canonical_name
                """,
                self.engine,
            )
            weight_map = {
                str(r.canonical_name): float(r.regime_weight or 0.0)
                for r in weights_df.itertuples(index=False)
            }
        except Exception:
            weight_map = {}

        def _sum_weighted(styles: dict[str, float]) -> _pd.Series:
            total = _pd.Series(0.0, index=zwide.index)
            for style, default_w in styles.items():
                weight = float(weight_map.get(style, default_w))
                series = zwide.get(style)
                if series is None:
                    series = _pd.Series(0.0, index=zwide.index)
                total = total.add(series * weight, fill_value=0.0)
            return total

        risk_on_core = _sum_weighted(risk_on)
        risk_off_core = _sum_weighted(risk_off)
        regime_raw = risk_on_core - risk_off_core

        ema10 = regime_raw.ewm(span=10, adjust=False).mean()
        ema50 = regime_raw.ewm(span=50, adjust=False).mean()

        last3_up = ema10.rolling(3, min_periods=3).apply(
            lambda vals: 1.0 if _np.all(vals > 0.5) else 0.0, raw=True
        )
        last3_dn = ema10.rolling(3, min_periods=3).apply(
            lambda vals: 1.0 if _np.all(vals < -0.5) else 0.0, raw=True
        )
        labels = _np.where(
            last3_up == 1.0, "Risk-On", _np.where(last3_dn == 1.0, "Risk-Off", "Neutral")
        )
        label_series = _pd.Series(labels, index=ema10.index).fillna("Neutral")

        mu = ema10.rolling(252, min_periods=20).mean()
        sigma = ema10.rolling(252, min_periods=20).std().replace(0.0, 1.0).fillna(1.0)
        zidx = (ema10 - mu) / sigma
        zidx = zidx.replace([_np.inf, -_np.inf], 0.0).fillna(0.0)
        regime_index = (50 + 10 * zidx).clip(0, 100)

        # Prepare upsert rows
        style_rows: list[tuple[int, str, float]] = []
        for as_of, row in zwide.iterrows():
            dk = date_lookup.get(_pd.Timestamp(as_of).date())
            if dk is None:
                continue
            for style, zval in row.items():
                style_rows.append((int(dk), str(style), float(_np.nan_to_num(zval))))

        regime_rows: list[tuple[int, float, float, float, float, float, str, float]] = []
        for as_of in regime_raw.index:
            dk = date_lookup.get(_pd.Timestamp(as_of).date())
            if dk is None:
                continue
            regime_rows.append(
                (
                    int(dk),
                    float(risk_on_core.loc[as_of]),
                    float(risk_off_core.loc[as_of]),
                    float(regime_raw.loc[as_of]),
                    float(ema10.loc[as_of]),
                    float(ema50.loc[as_of]),
                    str(label_series.loc[as_of]),
                    float(regime_index.loc[as_of]),
                )
            )

        # Effective weights (dynamic Pullback g-factor, base weights elsewhere)
        pull_series = zwide.get("Pullback", _pd.Series(0.0, index=zwide.index))
        momo_series = zwide.get("Momentum", _pd.Series(0.0, index=zwide.index))
        mr_series = zwide.get("MeanRev", _pd.Series(0.0, index=zwide.index))
        short_series = zwide.get("Short", _pd.Series(0.0, index=zwide.index))

        for style in canon_styles:
            weight_map.setdefault(style, 0.0)

        g_factor = ((momo_series - pull_series) / 0.75).fillna(0.0)
        g_factor = _pd.Series(_np.tanh(g_factor.to_numpy()), index=g_factor.index)
        drag = (0.5 * mr_series + 0.5 * short_series).fillna(0.0) - 0.25
        drag = drag.clip(lower=0.0)
        g_factor = (g_factor - 0.3 * drag).clip(-1.0, 1.0)

        pull_base = float(weight_map.get("Pullback", 0.0))
        eff_rows: list[tuple[int, str, float, float, float]] = []
        for as_of in zwide.index:
            dk = date_lookup.get(_pd.Timestamp(as_of).date())
            if dk is None:
                continue
            pull_g = float(g_factor.loc[as_of])
            eff_rows.append((int(dk), "Pullback", pull_base * pull_g, pull_g, pull_base))
            for name, base_weight in weight_map.items():
                if name == "Pullback":
                    continue
                eff_rows.append((int(dk), str(name), float(base_weight), 1.0, float(base_weight)))

        # Upsert into targets
        if not style_rows and not regime_rows and not eff_rows:
            self.logger.info("No regime rows to upsert")
            return

        try:
            with self.batch.connect() as conn:
                with conn.cursor() as cur:
                    if style_rows:
                        execute_values(
                            cur,
                            """
                            INSERT INTO rankalpha.fact_style_z_us (date_key, style_name, z_value)
                            VALUES %s
                            ON CONFLICT (date_key, style_name)
                            DO UPDATE SET z_value = EXCLUDED.z_value, load_ts = now()
                            """,
                            style_rows,
                            page_size=1000,
                        )
                    if regime_rows:
                        execute_values(
                            cur,
                            """
                            INSERT INTO rankalpha.fact_regime_series (
                                date_key, risk_on_core, risk_off_core, regime_raw, ema10, ema50, regime_label, regime_index
                            ) VALUES %s
                            ON CONFLICT (date_key) DO UPDATE SET
                                risk_on_core = EXCLUDED.risk_on_core,
                                risk_off_core = EXCLUDED.risk_off_core,
                                regime_raw = EXCLUDED.regime_raw,
                                ema10 = EXCLUDED.ema10,
                                ema50 = EXCLUDED.ema50,
                                regime_label = EXCLUDED.regime_label,
                                regime_index = EXCLUDED.regime_index,
                                load_ts = now()
                            """,
                            regime_rows,
                            page_size=500,
                        )
                    if eff_rows:
                        execute_values(
                            cur,
                            """
                            INSERT INTO rankalpha.fact_regime_effective_weight (
                                date_key, canonical_name, effective_weight, g_factor, base_weight
                            ) VALUES %s
                            ON CONFLICT (date_key, canonical_name) DO UPDATE SET
                                effective_weight = EXCLUDED.effective_weight,
                                g_factor = EXCLUDED.g_factor,
                                base_weight = EXCLUDED.base_weight,
                                load_ts = now()
                            """,
                            eff_rows,
                            page_size=500,
                        )
            self.logger.info(
                "Regime series updated: %d style rows, %d regime rows, %d effective weight rows",
                len(style_rows),
                len(regime_rows),
                len(eff_rows),
            )
        except Exception as exc:
            if conn:
                conn.rollback()
            self.logger.error(f"Failed to upsert regime series: {exc}")
        finally:
            with contextlib.suppress(Exception):
                if conn is not None:
                    conn.close()

    def update_regime_rules_us(self) -> None:
        """Compute flow-based regime rules for the latest trading day (no HMM)."""
        import numpy as _np
        import pandas as _pd

        config_defaults = {
            "config_key": "default",
            "z_window_days": 252,
            "rs_window_days": 126,
            "rs_weight_mb": 1.0,
            "rs_weight_bb": -0.9,
            "rs_weight_mri": -0.4,
            "rs_weight_db": -0.5,
            "rs_trend_threshold": 0.5,
            "rs_riskoff_threshold": -0.5,
            "defensive_pct_threshold": 0.8,
            "mania_pct_threshold": 0.9,
            "ps_veto_threshold": 0.0,
            "hysteresis_days": 3,
            "config_version": "default",
        }
        try:
            with self.batch.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT config_key, z_window_days, rs_window_days,
                               rs_weight_mb, rs_weight_bb, rs_weight_mri, rs_weight_db,
                               rs_trend_threshold, rs_riskoff_threshold,
                               defensive_pct_threshold, mania_pct_threshold,
                               ps_veto_threshold, hysteresis_days, updated_at
                        FROM rankalpha.regime_rules_config
                        WHERE is_active IS TRUE
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """
                    )
                    row = cur.fetchone()
                    if row:
                        (
                            config_defaults["config_key"],
                            config_defaults["z_window_days"],
                            config_defaults["rs_window_days"],
                            config_defaults["rs_weight_mb"],
                            config_defaults["rs_weight_bb"],
                            config_defaults["rs_weight_mri"],
                            config_defaults["rs_weight_db"],
                            config_defaults["rs_trend_threshold"],
                            config_defaults["rs_riskoff_threshold"],
                            config_defaults["defensive_pct_threshold"],
                            config_defaults["mania_pct_threshold"],
                            config_defaults["ps_veto_threshold"],
                            config_defaults["hysteresis_days"],
                            updated_at,
                        ) = row
                        config_defaults["config_version"] = (
                            f"{config_defaults['config_key']}@{updated_at.isoformat() if hasattr(updated_at, 'isoformat') else updated_at}"
                        )
                        numeric_keys = [
                            "z_window_days",
                            "rs_window_days",
                            "rs_weight_mb",
                            "rs_weight_bb",
                            "rs_weight_mri",
                            "rs_weight_db",
                            "rs_trend_threshold",
                            "rs_riskoff_threshold",
                            "defensive_pct_threshold",
                            "mania_pct_threshold",
                            "ps_veto_threshold",
                            "hysteresis_days",
                        ]
                        for key in numeric_keys:
                            val = config_defaults.get(key)
                            if isinstance(val, Decimal):
                                config_defaults[key] = float(val)
        except Exception as exc:
            self.logger.warning(f"Failed to load regime rules config, using defaults: {exc}")
        # Use loaded config
        z_window = int(config_defaults["z_window_days"])
        rs_window = int(config_defaults["rs_window_days"])
        hyst = max(1, int(config_defaults["hysteresis_days"]))

        # Refresh supporting MVs (universe + flow views)
        try:
            with self.batch.connect(autocommit=True) as conn:
                with conn.cursor() as cur:
                    for mv in (
                        "rankalpha.mv_universe_regime_us",
                        "rankalpha.mv_screener_flow_us",
                        "rankalpha.mv_screener_breadth_flow",
                        "rankalpha.mv_style_transition_us",
                        "rankalpha.mv_screener_breadth",
                    ):
                        try:
                            cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv}")
                            self.logger.info(f"Refreshed {mv} concurrently")
                        except Exception as exc:
                            self.logger.warning(
                                f"Concurrent refresh failed for {mv}: {exc}; retrying non-concurrent"
                            )
                            cur.execute(f"REFRESH MATERIALIZED VIEW {mv}")
                            self.logger.info(f"Refreshed {mv}")
        except Exception as exc:
            self.logger.error(f"Failed to refresh regime flow MVs: {exc}")
            return

        # Pull flow history
        max_window = max(z_window, rs_window) + hyst + 30
        flow_rows = []
        latest_dk = None
        try:
            with self.batch.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT max(date_key) FROM rankalpha.mv_screener_flow_us")
                    latest = cur.fetchone()
                    latest_dk = int(latest[0]) if latest and latest[0] is not None else None
                    if latest_dk is None:
                        return
                    cur.execute(
                        """
                        SELECT date_key, style_name, entered_count, dropped_count, continuers_count, eligible_count
                        FROM rankalpha.mv_screener_flow_us
                        WHERE date_key <= %s
                          AND date_key >= (
                            SELECT COALESCE(MIN(date_key), %s) FROM (
                                SELECT DISTINCT date_key
                                FROM rankalpha.mv_screener_flow_us
                                WHERE date_key <= %s
                                ORDER BY date_key DESC
                                LIMIT %s
                            ) t
                          )
                        ORDER BY date_key ASC, style_name ASC
                        """,
                        (latest_dk, latest_dk, latest_dk, max_window),
                    )
                    flow_rows = cur.fetchall()
                    cur.execute(
                        """
                        SELECT date_key, pullback_count, pull_to_momentum, pull_to_short
                        FROM rankalpha.mv_style_transition_us
                        WHERE date_key <= %s
                          AND date_key >= (
                            SELECT COALESCE(MIN(date_key), %s) FROM (
                                SELECT DISTINCT date_key
                                FROM rankalpha.mv_style_transition_us
                                WHERE date_key <= %s
                                ORDER BY date_key DESC
                                LIMIT %s
                            ) t
                          )
                        ORDER BY date_key ASC
                        """,
                        (latest_dk, latest_dk, latest_dk, max_window),
                    )
                    transitions_rows = cur.fetchall()
        except Exception as exc:
            self.logger.error(f"Failed to fetch screener flow history: {exc}")
            return

        if not flow_rows:
            return

        df = _pd.DataFrame(
            flow_rows,
            columns=["date_key", "style", "entered", "dropped", "continuers", "eligible"],
        )
        df = df.sort_values("date_key")
        df["eligible"] = df["eligible"].astype(float).replace({0.0: _np.nan})
        for col in ("entered", "dropped", "continuers"):
            df[col] = df[col].astype(float)

        def _ratio(num_col):
            return _np.where(
                df["eligible"].notna() & (df["eligible"] > 0), df[num_col] / df["eligible"], 0.0
            )

        df["entered_pct"] = _ratio("entered")
        df["dropped_pct"] = _ratio("dropped")
        df["continuers_pct"] = _ratio("continuers")
        df["churn_pct"] = _np.where(
            df["eligible"].notna() & (df["eligible"] > 0),
            (df["entered"] + df["dropped"]) / df["eligible"],
            0.0,
        )

        def _pivot(metric):
            return (
                df.pivot(index="date_key", columns="style", values=metric).sort_index().fillna(0.0)
            )

        entered_pct = _pivot("entered_pct")
        dropped_pct = _pivot("dropped_pct")
        continuers_pct = _pivot("continuers_pct")
        churn_pct = _pivot("churn_pct")

        if entered_pct.empty:
            return

        dates = entered_pct.index
        if dates.size < max(rs_window, hyst) or latest_dk not in dates:
            return

        style_cols = ["Momentum", "Pullback", "MeanRev", "Short", "Defensive", "Squeeze", "IPO"]
        for frame in (entered_pct, dropped_pct, continuers_pct, churn_pct):
            for col in style_cols:
                if col not in frame.columns:
                    frame[col] = 0.0
            frame.sort_index(axis=1, inplace=True)

        def _rolling_robust_z(series: _pd.Series, window: int, min_points: int = 60) -> _pd.Series:
            values = series.astype(float).values
            idx = series.index
            out = _pd.Series(_np.nan, index=idx, dtype=float)
            n = len(values)
            for i in range(n):
                end = i + 1
                start = max(0, end - window)
                window_vals = values[start:end]
                valid = window_vals[_np.isfinite(window_vals)]
                if valid.size < min_points:
                    continue
                med = float(_np.median(valid))
                mad = float(_np.median(_np.abs(valid - med)))
                if mad > 1e-9:
                    scale = 1.4826 * mad
                else:
                    iqr = float(_np.percentile(valid, 75) - _np.percentile(valid, 25))
                    if iqr > 1e-9:
                        scale = 0.7413 * iqr
                    else:
                        std = float(valid.std(ddof=1)) if valid.size > 1 else 0.0
                        scale = std if std > 1e-9 else 1.0
                out.iat[i] = max(min((float(window_vals[-1]) - med) / scale, 4.0), -4.0)
            return out

        def _series(frame: _pd.DataFrame, name: str) -> _pd.Series:
            if name in frame.columns:
                return frame[name].astype(float)
            return _pd.Series(0.0, index=frame.index, dtype=float)

        momentum_enter = _series(entered_pct, "Momentum")
        squeeze_enter = _series(entered_pct, "Squeeze")
        short_enter = _series(entered_pct, "Short")
        pullback_enter = _series(entered_pct, "Pullback")
        defensive_enter = _series(entered_pct, "Defensive")
        meanrev_churn = _series(churn_pct, "MeanRev")
        pullback_churn = _series(churn_pct, "Pullback")
        momentum_cont = _series(continuers_pct, "Momentum")
        pullback_cont = _series(continuers_pct, "Pullback")
        short_cont = _series(continuers_pct, "Short")
        meanrev_cont = _series(continuers_pct, "MeanRev")
        ipo_enter = _series(entered_pct, "IPO")

        mri_base = (pullback_churn + meanrev_churn) / 2.0

        mb_z = _rolling_robust_z(momentum_enter, rs_window)
        squeeze_z = _rolling_robust_z(squeeze_enter, rs_window)
        bb_z = _rolling_robust_z(short_enter, rs_window)
        mri_z = _rolling_robust_z(mri_base, rs_window)
        db_z = _rolling_robust_z(defensive_enter, rs_window)

        mb_series = mb_z.fillna(0.0) + 0.3 * squeeze_z.fillna(0.0)
        bb_series = bb_z.fillna(0.0)
        mri_series = mri_z.fillna(0.0)
        db_series = db_z.fillna(0.0)

        # Long-window components
        mri_long = _rolling_robust_z(mri_base, z_window)
        pull_enter_long = _rolling_robust_z(pullback_enter, z_window)
        defensive_long = _rolling_robust_z(defensive_enter, z_window)
        momentum_cont_long = _rolling_robust_z(momentum_cont, z_window)
        anti_cont_long = _rolling_robust_z(
            (pullback_cont + short_cont + meanrev_cont) / 3.0, z_window
        )

        ps_series = momentum_cont_long.fillna(0.0) - anti_cont_long.fillna(0.0)
        mrp_series = mri_long.fillna(0.0) + 0.3 * pull_enter_long.fillna(0.0)
        rop_series = bb_series - 0.3 * mb_series
        dt_series = defensive_long.fillna(0.0) - 0.2 * mb_series
        tt_series = mb_series - 0.6 * bb_series

        # Transition bias
        trans_df = (
            _pd.DataFrame(
                transitions_rows,
                columns=["date_key", "pullback_count", "pull_to_momentum", "pull_to_short"],
            ).set_index("date_key")
            if transitions_rows
            else _pd.DataFrame(columns=["pullback_count", "pull_to_momentum", "pull_to_short"])
        )
        if not trans_df.empty:
            trans_df = trans_df.sort_index()
            trans_df["pullback_count"] = (
                trans_df["pullback_count"].astype(float).replace({0.0: _np.nan})
            )
            trans_df["share_m"] = (
                trans_df["pull_to_momentum"].astype(float) / trans_df["pullback_count"]
            )
            trans_df["share_s"] = (
                trans_df["pull_to_short"].astype(float) / trans_df["pullback_count"]
            )
            trans_df = trans_df.fillna(0.0)
        else:
            trans_df = _pd.DataFrame(0.0, index=dates, columns=["share_m", "share_s"])
        trans_df = trans_df.reindex(dates, fill_value=0.0)
        tb_raw = trans_df["share_m"] - trans_df["share_s"]
        tb_series = _rolling_robust_z(tb_raw, z_window).fillna(0.0)

        rs_series = (
            config_defaults["rs_weight_mb"] * mb_series
            + config_defaults["rs_weight_bb"] * bb_series
            + config_defaults["rs_weight_mri"] * mri_series
            + config_defaults["rs_weight_db"] * db_series
        )

        veto_mask = ps_series < config_defaults["ps_veto_threshold"]
        if veto_mask.any():
            rs_series = rs_series.where(~veto_mask, rs_series.clip(upper=0.25))

        rs_smooth = rs_series.rolling(window=hyst, min_periods=1).mean()

        if rs_series.isna().all():
            return

        def _consecutive(mask: _pd.Series) -> _pd.Series:
            window = mask.astype(float).rolling(window=hyst, min_periods=hyst).sum()
            return window == hyst

        trend_confirm = _consecutive(
            (rs_smooth > config_defaults["rs_trend_threshold"]).fillna(False)
        )
        riskoff_confirm = _consecutive(
            (rs_smooth < config_defaults["rs_riskoff_threshold"]).fillna(False)
        )

        latest_idx = int(dates[-1])
        mb_val = float(mb_series.loc[latest_idx])
        bb_val = float(bb_series.loc[latest_idx])
        mri_val = float(mri_series.loc[latest_idx])
        db_val = float(db_series.loc[latest_idx])
        tt_val = float(tt_series.loc[latest_idx])
        mrp_val = float(mrp_series.loc[latest_idx])
        rop_val = float(rop_series.loc[latest_idx])
        dt_val = float(dt_series.loc[latest_idx])
        ps_val = float(ps_series.loc[latest_idx])
        tb_val = float(tb_series.loc[latest_idx])
        rs_val = float(rs_series.loc[latest_idx])
        rs_smooth_val = float(rs_smooth.loc[latest_idx])

        is_trend = bool(trend_confirm.loc[latest_idx])
        is_riskoff = bool(riskoff_confirm.loc[latest_idx]) if not is_trend else False

        label = "Trend" if is_trend else ("Risk-Off" if is_riskoff else "Chop")
        tags: list[str] = []
        if label == "Chop" and mri_val > 0.0:
            tags.append("MeanReversionFavored")

        # Defensive drift tag (entered pct percentile)
        def _window_percentile(series: _pd.Series, threshold: float) -> float | None:
            arr = series.dropna().to_numpy(dtype=float)
            if arr.size == 0:
                return None
            window_size = min(arr.size, z_window)
            subset = arr[-window_size:]
            return float(_np.nanpercentile(subset, threshold * 100.0))

        defensive_threshold = _window_percentile(
            defensive_enter, config_defaults["defensive_pct_threshold"]
        )
        if defensive_threshold is not None:
            current_defensive = float(defensive_enter.loc[latest_idx])
            if current_defensive >= defensive_threshold and mb_val < 0.0:
                tags.append("DefensiveDrift")

        mania_threshold = _window_percentile(squeeze_enter, config_defaults["mania_pct_threshold"])
        if mania_threshold is not None:
            squeeze_today = float(squeeze_enter.loc[latest_idx])
            ipo_today = float(ipo_enter.loc[latest_idx])
            if squeeze_today >= mania_threshold and ipo_today >= mania_threshold * 0.5:
                tags.append("SpeculativeMania")

        payload = (
            latest_idx,
            mb_val,
            bb_val,
            mri_val,
            db_val,
            tt_val,
            mrp_val,
            rop_val,
            dt_val,
            ps_val,
            tb_val,
            rs_val,
            rs_smooth_val,
            label,
            tags,
            config_defaults["config_version"],
        )

        try:
            with self.batch.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO rankalpha.fact_regime_rules (
                            date_key, mb, bb, mri, db, tt, mrp, rop, dt, ps, tb, rs, rs_smooth, label, tags, config_version
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (date_key) DO UPDATE SET
                            mb = EXCLUDED.mb,
                            bb = EXCLUDED.bb,
                            mri = EXCLUDED.mri,
                            db = EXCLUDED.db,
                            tt = EXCLUDED.tt,
                            mrp = EXCLUDED.mrp,
                            rop = EXCLUDED.rop,
                            dt = EXCLUDED.dt,
                            ps = EXCLUDED.ps,
                            tb = EXCLUDED.tb,
                            rs = EXCLUDED.rs,
                            rs_smooth = EXCLUDED.rs_smooth,
                            label = EXCLUDED.label,
                            tags = EXCLUDED.tags,
                            config_version = EXCLUDED.config_version,
                            load_ts = now()
                        """,
                        payload,
                    )
        except Exception as exc:
            self.logger.error(f"Failed to upsert fact_regime_rules: {exc}")

    # ---------------- Rank Regime (Momentum↔Value) -------------------
    def refresh_rank_regime_daily(self) -> None:
        """Refresh the rank-based Momentum↔Value regime MV after scorer completes.

        Order dependencies:
        - mv_universe_regime_us (daily eligible universe)
        - mv_rank_regime_daily (this view depends on universe + fact_score_history)
        """
        try:
            with self.batch.connect(autocommit=True) as conn:
                with conn.cursor() as cur:
                    try:
                        cur.execute(
                            "REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_universe_regime_us"
                        )
                        self.logger.info("Refreshed mv_universe_regime_us concurrently")
                    except Exception as exc:
                        self.logger.warning(
                            f"Concurrent refresh failed for mv_universe_regime_us: {exc}; retrying non-concurrent"
                        )
                        cur.execute("REFRESH MATERIALIZED VIEW rankalpha.mv_universe_regime_us")
                        self.logger.info("Refreshed mv_universe_regime_us")
                    try:
                        cur.execute(
                            "REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_rank_regime_daily"
                        )
                        self.logger.info("Refreshed mv_rank_regime_daily concurrently")
                    except Exception as exc:
                        self.logger.warning(
                            f"Concurrent refresh failed for mv_rank_regime_daily: {exc}; retrying non-concurrent"
                        )
                        cur.execute("REFRESH MATERIALIZED VIEW rankalpha.mv_rank_regime_daily")
                        self.logger.info("Refreshed mv_rank_regime_daily")
        except Exception as exc:
            self.logger.error(f"Failed to refresh rank regime MV: {exc}")

    # ---------------- Market Structure (CVD-style) -------------------
    def update_market_structure_us(
        self,
        lookback_days: int = 320,  # covers z-window (252) + buffers
        trend_window: int = 50,
        rv_window: int = 20,
        corr_window: int = 20,
        z_window: int = 252,
        trend_up_z: float = 0.5,
        trend_down_z: float = -0.5,
        vol_threshold: float = 0.0,
        corr_threshold: float = 0.0,
        disp_threshold: float = 0.0,
    ) -> None:
        """Compute Market Structure regime components and persist.

        Components per latest day:
          - Trend: EW index return t-stat over `trend_window` days
          - RV20: annualized 20d realized vol of EW index
          - Corr (PC1 share): PC1 explained variance share from cross-sectional returns (corr_window days)
          - Dispersion: robust MAD (×1.4826) of today’s cross-sectional returns

        Standardize each via robust rolling z over `z_window`. Label using rule grid:
          - Calm Uptrend: Trend_z > +0.5 and RV_z < 0 and Corr_z < 0
          - Fragile Uptrend: Trend_z > +0.5 and (Corr_z > 0 or RV_z > 0)
          - Choppy: |Trend_z| ≤ 0.5 and Disp_z > 0
          - Risk-Off: Trend_z < −0.5 and (RV_z > 0 or Corr_z > 0)
          - Else Neutral
        """
        import numpy as _np
        import pandas as _pd

        # 1) Pull recent trading days
        try:
            days_df = _pd.read_sql(
                text(
                    """
                    WITH recent_dates AS (
                        SELECT DISTINCT date_key
                        FROM rankalpha.mv_universe_regime_us
                        ORDER BY date_key DESC
                        LIMIT :lim
                    )
                    SELECT d.date_key, d.full_date
                    FROM recent_dates r
                    JOIN rankalpha.dim_date d ON d.date_key = r.date_key
                    ORDER BY d.full_date ASC
                    """
                ),
                self.engine,
                params={"lim": max(lookback_days + corr_window + 5, z_window + corr_window + 5)},
                parse_dates=["full_date"],
            )
        except Exception as exc:
            self.logger.error(f"MarketStructure: failed to load trading days: {exc}")
            return
        if days_df.empty:
            return
        date_keys = days_df["date_key"].tolist()

        # 2) Eligible universe per day
        min_dk = int(min(date_keys))
        max_dk = int(max(date_keys))
        try:
            elig_df = _pd.read_sql(
                text(
                    """
                    SELECT date_key, stock_key
                    FROM rankalpha.mv_universe_regime_us
                    WHERE date_key BETWEEN :min_dk AND :max_dk
                      AND eligible IS TRUE
                    """
                ),
                self.engine,
                params={"min_dk": min_dk, "max_dk": max_dk},
            )
            if not elig_df.empty:
                elig_df = elig_df[elig_df["date_key"].isin(date_keys)]
        except Exception as exc:
            self.logger.error(f"MarketStructure: failed to load eligible universe: {exc}")
            return
        if elig_df.empty:
            self.logger.info("MarketStructure: empty eligible universe window; skipping")
            return

        # 3) Load prices for these stocks over the window (include one lag day for returns)
        try:
            first_dk = int(min(date_keys))
            # include one prior day to compute returns for the first date
            price_df = _pd.read_sql(
                text(
                    """
                    SELECT sp.date_key, sp.stock_key, sp.close_px
                    FROM rankalpha.fact_security_price sp
                    WHERE sp.date_key >= :first
                      AND sp.stock_key = ANY(:sks)
                    ORDER BY sp.stock_key, sp.date_key
                    """
                ),
                self.engine,
                params={
                    "first": first_dk - 1,
                    "sks": sorted(elig_df["stock_key"].unique().tolist()),
                },
            )
        except Exception as exc:
            self.logger.error(f"MarketStructure: failed to load prices: {exc}")
            return
        if price_df.empty:
            self.logger.info("MarketStructure: no prices; skipping")
            return

        # 4) Build returns pivot (dates × stocks)
        price_df = price_df.sort_values(["stock_key", "date_key"]).assign(
            close_px=lambda x: x["close_px"].astype(float)
        )
        price_df["ret"] = price_df.groupby("stock_key")["close_px"].pct_change(fill_method=None)
        ret_pivot = price_df.pivot_table(
            index="date_key", columns="stock_key", values="ret", aggfunc="first"
        ).sort_index()
        ret_pivot = ret_pivot.loc[ret_pivot.index.isin(date_keys)]
        if ret_pivot.empty:
            self.logger.info("MarketStructure: no returns after pivot; skipping")
            return

        # 5) Eligibility mask pivot (dates × stocks)
        elig_pivot = (
            elig_df.assign(val=1.0)
            .pivot_table(index="date_key", columns="stock_key", values="val", aggfunc="first")
            .reindex(index=ret_pivot.index, fill_value=_np.nan)
        )

        # Helper: robust z from rolling window ending at each t
        def _rolling_robust_z(series: _pd.Series, win: int = z_window) -> _pd.Series:
            series = series.astype(float)
            med = series.rolling(win, min_periods=max(30, win // 3)).median()

            def _mad(window: _pd.Series) -> float:
                arr = window.values.astype(float)
                if arr.size == 0:
                    return 0.0
                m = _np.median(arr)
                return float(_np.median(_np.abs(arr - m)))

            mad = series.rolling(win, min_periods=max(30, win // 3)).apply(_mad, raw=False)
            scale = 1.4826 * mad
            iqr = series.rolling(win, min_periods=max(30, win // 3)).quantile(
                0.75
            ) - series.rolling(win, min_periods=max(30, win // 3)).quantile(0.25)
            scale = scale.where((scale > 1e-8) & _np.isfinite(scale), 0.7413 * iqr)
            std = series.rolling(win, min_periods=5).std()
            scale = scale.where((scale > 1e-8) & _np.isfinite(scale), std.clip(lower=1e-6))
            z = (series - med) / scale
            return z.replace([_np.inf, -_np.inf], 0.0).fillna(0.0).clip(-4, 4)

        # 6) EW index returns per day over eligible names
        masked = ret_pivot.where(elig_pivot.notna())
        ew_ret = masked.mean(axis=1, skipna=True).astype(float).fillna(0.0)

        # Trend: t-stat of ew_ret over trend_window
        def _tstat(window: _pd.Series) -> float:
            arr = window.values.astype(float)
            if arr.size < 5:
                return _np.nan
            mu = _np.nanmean(arr)
            sd = _np.nanstd(arr, ddof=1)
            if sd <= 1e-12:
                return 0.0
            return float(mu / sd * _np.sqrt(arr.size))

        trend_raw = ew_ret.rolling(trend_window, min_periods=trend_window // 2).apply(
            _tstat, raw=False
        )
        rv20_ann = ew_ret.rolling(rv_window, min_periods=rv_window // 2).std() * _np.sqrt(252.0)

        # Corr (PC1 share) and Dispersion (MAD) per day
        corr_vals: list[tuple[int, float]] = []  # (date_key, pc1_share)
        disp_vals: list[tuple[int, float]] = []  # (date_key, mad)

        ret_idx = ret_pivot.index.to_list()
        for i, dk in enumerate(ret_idx):
            if i + 1 < corr_window:
                continue
            win_index = ret_idx[i - corr_window + 1 : i + 1]
            # Eligible at day dk (today)
            elig_today = elig_pivot.loc[dk].dropna().index.astype(int).tolist()
            if not elig_today:
                continue
            sub = ret_pivot.loc[win_index, elig_today]
            # Require complete observations across the window
            sub = sub.dropna(axis=1, how="any")
            n = sub.shape[1]
            if n < 5:
                continue
            # Center per day across stocks
            X = sub.values.astype(float)
            X = X - _np.nanmean(X, axis=1, keepdims=True)
            # Economy SVD on (corr_window × n) transposed to N×T
            # We want singular values of X (N×T); either X or X.T yields same Σ
            try:
                _, s, _ = _np.linalg.svd(X, full_matrices=False)
                s2 = s * s
                pc1_share = float(s2[0] / _np.sum(s2)) if _np.sum(s2) > 0 else 0.0
            except Exception:
                pc1_share = _np.nan
            corr_vals.append((int(dk), pc1_share))

            # Dispersion on today only (robust MAD across eligible stocks)
            todays = ret_pivot.loc[dk, elig_today].dropna().values.astype(float)
            if todays.size == 0:
                disp = _np.nan
            else:
                med = _np.median(todays)
                disp = 1.4826 * float(_np.median(_np.abs(todays - med)))
            disp_vals.append((int(dk), disp))

        corr_s = _pd.Series({dk: v for dk, v in corr_vals}).sort_index()
        disp_s = _pd.Series({dk: v for dk, v in disp_vals}).sort_index()

        # Align all series to the same index
        base_idx = _pd.Index(ret_idx, name="date_key")
        trend_raw = trend_raw.reindex(base_idx)
        rv20_ann = rv20_ann.reindex(base_idx)
        corr_s = corr_s.reindex(base_idx)
        disp_s = disp_s.reindex(base_idx)

        # Rolling robust z
        trend_z = _rolling_robust_z(trend_raw, z_window)
        rv_z = _rolling_robust_z(rv20_ann, z_window)
        corr_z = _rolling_robust_z(corr_s, z_window)
        disp_z = _rolling_robust_z(disp_s, z_window)

        # Build final frame for upsert (limit to last z_window days to keep runtime bounded)
        df = _pd.DataFrame(
            {
                "trend_raw": trend_raw,
                "rv20_ann": rv20_ann,
                "corr_pca1_share": corr_s,
                "disp_cs_mad": disp_s,
                "trend_z": trend_z,
                "rv20_z": rv_z,
                "corr_z": corr_z,
                "disp_z": disp_z,
            }
        )
        df.index.name = "date_key"
        df = df.dropna(
            subset=["trend_raw", "rv20_ann", "corr_pca1_share", "disp_cs_mad"], how="any"
        )
        if df.empty:
            self.logger.info("MarketStructure: insufficient data to compute metrics; skipping")
            return

        # Labeling function per-row
        chop_band = max(abs(trend_up_z), abs(trend_down_z)) or 0.5

        def _label_row(r) -> str:
            tz = float(r.get("trend_z", 0.0) or 0.0)
            rvz = float(r.get("rv20_z", 0.0) or 0.0)
            cz = float(r.get("corr_z", 0.0) or 0.0)
            dz = float(r.get("disp_z", 0.0) or 0.0)
            if tz > trend_up_z and rvz < vol_threshold and cz < corr_threshold:
                return "CalmUptrend"
            if tz > trend_up_z and (cz > corr_threshold or rvz > vol_threshold):
                return "FragileUptrend"
            if abs(tz) <= chop_band and dz > disp_threshold:
                return "Choppy"
            if tz < trend_down_z and (rvz > vol_threshold or cz > corr_threshold):
                return "Risk-Off"
            return "Neutral"

        df["label"] = [_label_row(df.loc[dk]) for dk in df.index]

        # Upsert (latest z_window rows to bound work)
        rows = []
        tail_idx = df.index.sort_values()[-min(len(df), z_window) :]
        for dk in tail_idx:
            r = df.loc[dk]
            rows.append(
                (
                    int(dk),
                    float(r["trend_raw"]),
                    float(r["rv20_ann"]),
                    float(r["corr_pca1_share"]),
                    float(r["disp_cs_mad"]),
                    float(r.get("trend_z", 0.0) or 0.0),
                    float(r.get("rv20_z", 0.0) or 0.0),
                    float(r.get("corr_z", 0.0) or 0.0),
                    float(r.get("disp_z", 0.0) or 0.0),
                    str(r["label"]),
                )
            )

        if not rows:
            return
        try:
            with self.batch.connect() as conn:
                with conn.cursor() as cur:
                    execute_values(
                        cur,
                        """
                        INSERT INTO rankalpha.fact_regime_market_structure (
                            date_key, trend_raw, rv20_ann, corr_pca1_share, disp_cs_mad,
                            trend_z, rv20_z, corr_z, disp_z, label
                        ) VALUES %s
                        ON CONFLICT (date_key) DO UPDATE SET
                            trend_raw = EXCLUDED.trend_raw,
                            rv20_ann = EXCLUDED.rv20_ann,
                            corr_pca1_share = EXCLUDED.corr_pca1_share,
                            disp_cs_mad = EXCLUDED.disp_cs_mad,
                            trend_z = EXCLUDED.trend_z,
                            rv20_z = EXCLUDED.rv20_z,
                            corr_z = EXCLUDED.corr_z,
                            disp_z = EXCLUDED.disp_z,
                            label = EXCLUDED.label,
                            load_ts = now()
                        """,
                        rows,
                    )
            self.logger.info(
                "MarketStructure: upserted %d day(s) ending dk=%s",
                len(rows),
                tail_idx.max() if len(tail_idx) else None,
            )
        except Exception as exc:
            self.logger.error(f"MarketStructure: upsert failed: {exc}")
