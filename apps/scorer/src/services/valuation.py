from __future__ import annotations

import numpy as np
import pandas as pd


class ValuationService:
    def __init__(self, engine, logger=None):
        self.engine = engine
        self.logger = logger

    def _has_industry_group(self) -> bool:
        """Detects whether dim_stock has an industry_group column."""
        try:
            q = """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'rankalpha'
                  AND table_name   = 'dim_stock'
                  AND column_name  = 'industry_group'
                LIMIT 1
            """
            df = pd.read_sql_query(q, self.engine)
            return not df.empty
        except Exception:
            return False

    # --- NEW: helper to synthesize EV/EBITDA (ev2ebitda_synth) ----------------
    @staticmethod
    def _attach_ev_ebitda(
        df: pd.DataFrame,
        *,
        global_as_of_key: int,
        global_as_of_ts: pd.Timestamp,
    ) -> pd.DataFrame:
        """
        Build a synthetic metric_code='ev2ebitda_synth' from mktcap + netdebt over ttmebitd.
        - Prefers interim net debt (netdebt_i) then annual (netdebt_a).
        - Drops rows where required components are missing or non-finite.
        - Uses the common global as-of for the synthetic rows.
        """
        need = {"mktcap", "netdebt_i", "netdebt_a", "ttmebitd"}
        sub = df[df["metric_code"].isin(need)][
            ["symbol", "sector", "peer_group", "metric_code", "metric_value"]
        ].copy()
        if sub.empty:
            return df

        # Pivot to have components as columns per symbol
        pv = sub.pivot_table(
            index=["symbol", "sector", "peer_group"],
            columns="metric_code",
            values="metric_value",
            aggfunc="last",
        )

        # Choose net debt: interim first, else annual
        netdebt = pv.get("netdebt_i")
        if netdebt is None:
            netdebt = pv.get("netdebt_a")
        else:
            netdebt = netdebt.fillna(pv.get("netdebt_a"))

        mktcap = pv.get("mktcap")
        ebitda = pv.get("ttmebitd")

        # If any component set is missing entirely, nothing to do
        if mktcap is None or ebitda is None or netdebt is None:
            return df

        with np.errstate(all="ignore"):
            ev = mktcap + netdebt  # EV ≈ Market Cap + Net Debt
            ratio = ev / ebitda  # EV/EBITDA

        synth = (
            ratio.to_frame("metric_value")
            .reset_index()
            .assign(
                metric_code="ev2ebitda_synth",
                date_key=int(global_as_of_key),
                as_of=global_as_of_ts,
            )
        )
        # Drop NaN/inf
        synth = synth[np.isfinite(synth["metric_value"].values)]
        if synth.empty:
            return df

        # Align columns to df and append
        keep_cols = [
            "date_key",
            "symbol",
            "sector",
            "peer_group",
            "metric_code",
            "metric_value",
            "as_of",
        ]
        return pd.concat([df, synth[keep_cols]], ignore_index=True)

    @staticmethod
    def _attach_pe(
        df: pd.DataFrame,
        *,
        global_as_of_key: int,
        global_as_of_ts: pd.Timestamp,
    ) -> pd.DataFrame:
        """
        Build a synthetic metric_code='pe_synth' from market-cap implied price / EPS.

        Price proxy: (mktcap * 1e6) / sharesoutstanding
        EPS preference: epsactual -> aepsxclxor -> aepsinclxo -> aepsnorm -> abepsxclxo

        Notes:
          - Negative EPS yields negative P/E, later penalized as worst (<=0).
          - Uses the common global as-of for the synthetic rows.
        """
        need = {
            "mktcap",
            "sharesoutstanding",
            "epsactual",
            "aepsxclxor",
            "aepsinclxo",
            "aepsnorm",
            "abepsxclxo",
        }
        sub = df[df["metric_code"].isin(need)][
            ["symbol", "sector", "peer_group", "metric_code", "metric_value"]
        ].copy()
        if sub.empty:
            return df

        pv = sub.pivot_table(
            index=["symbol", "sector", "peer_group"],
            columns="metric_code",
            values="metric_value",
            aggfunc="last",
        )

        mktcap = pv.get("mktcap")
        shares = pv.get("sharesoutstanding")
        if mktcap is None or shares is None:
            return df

        eps = pv.get("epsactual")
        for code in ["aepsxclxor", "aepsinclxo", "aepsnorm", "abepsxclxo"]:
            series = pv.get(code)
            if series is None:
                continue
            eps = series if eps is None else eps.fillna(series)
        if eps is None:
            return df

        with np.errstate(all="ignore"):
            price = (mktcap * 1_000_000.0) / shares
            ratio = price / eps

        synth = (
            ratio.to_frame("metric_value")
            .reset_index()
            .assign(
                metric_code="pe_synth",
                date_key=int(global_as_of_key),
                as_of=global_as_of_ts,
            )
        )
        synth = synth[np.isfinite(synth["metric_value"].values)]
        if synth.empty:
            return df

        keep_cols = [
            "date_key",
            "symbol",
            "sector",
            "peer_group",
            "metric_code",
            "metric_value",
            "as_of",
        ]
        return pd.concat([df, synth[keep_cols]], ignore_index=True)

    @staticmethod
    def _attach_pfcf(
        df: pd.DataFrame,
        *,
        global_as_of_key: int,
        global_as_of_ts: pd.Timestamp,
    ) -> pd.DataFrame:
        """
        Build a synthetic metric_code='pfcf_synth' using Market Cap and Free Cash Flow.

        Preference:
          - Price / FCF per share (ttmfcfshr), else
          - Market Cap / total FCF (ttmfcf), else
          - Market Cap / annual FCF (a1fcf)

        Notes:
          - Negative FCF yields negative P/FCF, later penalized as worst (<=0).
          - Uses the common global as-of for the synthetic rows.
        """
        need = {
            "mktcap",
            "sharesoutstanding",
            "ttmfcfshr",
            "ttmfcf",
            "a1fcf",
        }
        sub = df[df["metric_code"].isin(need)][
            ["symbol", "sector", "peer_group", "metric_code", "metric_value"]
        ].copy()
        if sub.empty:
            return df

        pv = sub.pivot_table(
            index=["symbol", "sector", "peer_group"],
            columns="metric_code",
            values="metric_value",
            aggfunc="last",
        )

        mktcap = pv.get("mktcap")
        if mktcap is None:
            return df

        shares = pv.get("sharesoutstanding")
        fcf_total = pv.get("ttmfcf")
        a1fcf = pv.get("a1fcf")
        if fcf_total is None:
            fcf_total = a1fcf
        elif a1fcf is not None:
            fcf_total = fcf_total.fillna(a1fcf)

        fcf_per_share = pv.get("ttmfcfshr")
        if fcf_per_share is None and shares is not None and fcf_total is not None:
            with np.errstate(all="ignore"):
                fcf_per_share = (fcf_total * 1_000_000.0) / shares

        ratio_per_share: pd.Series | None = None
        if shares is not None and fcf_per_share is not None:
            with np.errstate(all="ignore"):
                price = (mktcap * 1_000_000.0) / shares
                ratio_per_share = price / fcf_per_share

        ratio_total: pd.Series | None = None
        if fcf_total is not None:
            with np.errstate(all="ignore"):
                ratio_total = mktcap / fcf_total

        if ratio_per_share is None and ratio_total is None:
            return df
        ratio: pd.Series | None = ratio_total if ratio_per_share is None else ratio_per_share
        if ratio_per_share is not None and ratio_total is not None:
            ratio = ratio_per_share.fillna(ratio_total)
        if ratio is None:
            return df

        assert ratio is not None
        ratio_series = ratio
        synth = (
            ratio_series.to_frame("metric_value")
            .reset_index()
            .assign(
                metric_code="pfcf_synth",
                date_key=int(global_as_of_key),
                as_of=global_as_of_ts,
            )
        )
        synth = synth[np.isfinite(synth["metric_value"].values)]
        if synth.empty:
            return df

        keep_cols = [
            "date_key",
            "symbol",
            "sector",
            "peer_group",
            "metric_code",
            "metric_value",
            "as_of",
        ]
        return pd.concat([df, synth[keep_cols]], ignore_index=True)

    # -------------------------------------------------------------------------

    @staticmethod
    def _get_metric_groups_default() -> dict[str, dict]:
        return {
            # EV-based
            "ev_ebitda": {"codes": ["ev2ebitda_synth"], "weight": 0.25},
            "ev_fcf": {"codes": ["ev2fcf_curttm", "ev2fcf_cura"], "weight": 0.25},
            # Price-based
            "pfcf": {"codes": ["ttmprfcfps", "aprfcfps", "pfcf_synth"], "weight": 0.20},
            "ps": {"codes": ["ttmpr2rev", "apr2rev"], "weight": 0.15},
            "pb": {
                "codes": ["price2bk", "aprice2bk", "pr2tanbk", "apr2tanbk"],
                "weight": 0.10,
            },
            "pe": {"codes": ["peexclxor", "peinclxor", "pebexclxor", "pe_synth"], "weight": 0.05},
            # Optional direct yield
            "div": {"codes": ["divyield_curttm"], "weight": 0.00},
        }

    @staticmethod
    def _get_sector_overrides() -> dict[str, dict[str, dict]]:
        return {
            "Financials": {
                "pb": {
                    "codes": ["price2bk", "aprice2bk", "pr2tanbk", "apr2tanbk"],
                    "weight": 0.50,
                },
                "pe": {
                    "codes": ["peexclxor", "peinclxor", "pebexclxor", "pe_synth"],
                    "weight": 0.30,
                },
                "div": {"codes": ["divyield_curttm"], "weight": 0.20},
            },
            "Real Estate": {
                "pb": {
                    "codes": ["price2bk", "aprice2bk", "pr2tanbk", "apr2tanbk"],
                    "weight": 0.50,
                },
                "div": {"codes": ["divyield_curttm"], "weight": 0.30},
                "ps": {"codes": ["ttmpr2rev", "apr2rev"], "weight": 0.20},
            },
        }

    @staticmethod
    def _compute_value_scores_from_frame(
        df: pd.DataFrame,
        *,
        metric_groups_default: dict[str, dict],
        sector_overrides: dict[str, dict[str, dict]],
        direct_yield_codes: set[str],
        statement_metric_codes: set[str],
        sector_weight: float,
        market_weight: float,
        min_sector_size: int,
        recency_calendar_days: int,
        statement_recency_calendar_days: int,
        winsorize: bool,
        winsor_lo: float,
        winsor_hi: float,
        coverage_shrink: bool,
        coverage_shrink_center: float,
        coverage_shrink_power: float,
        logger=None,
    ) -> dict[str, dict[str, float | int | None]]:
        if df.empty:
            return {}

        required = {"date_key", "symbol", "sector", "peer_group", "metric_code", "metric_value"}
        missing = required.difference(df.columns)
        if missing:
            if logger:
                logger.info(f"Valuation v2.3: missing columns in frame: {sorted(missing)}")
            return {}

        df = df.copy()
        if "as_of" not in df.columns:
            df["as_of"] = pd.to_datetime(
                pd.to_numeric(df["date_key"], errors="coerce").astype("Int64").astype(str),
                format="%Y%m%d",
                errors="coerce",
            )

        global_as_of = pd.to_datetime(df["as_of"].max())
        if pd.isna(global_as_of):
            return {}

        cutoff_price = global_as_of - pd.Timedelta(days=int(recency_calendar_days))
        cutoff_statement = global_as_of - pd.Timedelta(days=int(statement_recency_calendar_days))
        is_statement = df["metric_code"].isin(statement_metric_codes)
        df = df[(df["as_of"] >= cutoff_price) | (is_statement & (df["as_of"] >= cutoff_statement))]
        if df.empty:
            if logger:
                logger.info("Valuation v2.3: all rows filtered by recency; aborting")
            return {}

        global_as_of = pd.to_datetime(df["as_of"].max())
        if pd.isna(global_as_of):
            return {}
        global_as_of_key = int(global_as_of.strftime("%Y%m%d"))

        df["metric_value"] = pd.to_numeric(df["metric_value"], errors="coerce")
        df = df[~pd.isna(df["metric_value"])]
        if df.empty:
            return {}

        _tmp_dates = df[["symbol", "date_key"]].copy()
        _tmp_dates["date_key"] = pd.to_numeric(_tmp_dates["date_key"], errors="coerce")
        sym_latest_date_key_map = (
            _tmp_dates.groupby("symbol")["date_key"].max().dropna().astype(int).to_dict()
        )

        df = ValuationService._attach_ev_ebitda(
            df, global_as_of_key=global_as_of_key, global_as_of_ts=global_as_of
        )
        df = ValuationService._attach_pe(
            df, global_as_of_key=global_as_of_key, global_as_of_ts=global_as_of
        )
        df = ValuationService._attach_pfcf(
            df, global_as_of_key=global_as_of_key, global_as_of_ts=global_as_of
        )

        is_direct = df["metric_code"].isin(direct_yield_codes)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv = 1.0 / df["metric_value"]
        df["_yield"] = np.where(is_direct, df["metric_value"], inv)
        df.loc[(~is_direct) & (df["metric_value"] <= 0), "_yield"] = -np.inf

        if winsorize:

            def _winsor_grp(s: pd.Series) -> pd.Series:
                finite = np.isfinite(s.values)
                if finite.sum() < 5:
                    return s
                lo, hi = np.quantile(s.values[finite], [winsor_lo, winsor_hi])
                out = s.copy()
                out.values[finite] = np.clip(s.values[finite], lo, hi)
                return out

            df["_yield"] = df.groupby(["metric_code", "peer_group"])["_yield"].transform(
                _winsor_grp
            )

        # ----- Percentiles: higher yield => cheaper -----
        df["_mkt_rank"] = df.groupby("metric_code")["_yield"].rank(
            method="average", ascending=True, pct=True
        )
        df["_mkt_cheap"] = df["_mkt_rank"] * 100.0

        grp = df.groupby(["metric_code", "peer_group"])
        df["_grp_size"] = grp["_yield"].transform(lambda s: int(np.isfinite(s).sum()))
        df["_grp_rank"] = grp["_yield"].rank(method="average", ascending=True, pct=True)
        df["_grp_cheap"] = df["_grp_rank"] * 100.0

        df["_metric_score"] = np.where(
            df["_grp_size"] >= float(min_sector_size),
            sector_weight * df["_grp_cheap"] + market_weight * df["_mkt_cheap"],
            df["_mkt_cheap"],
        )

        sym_sector = (
            df[["symbol", "sector"]].drop_duplicates().set_index("symbol")["sector"].to_dict()
        )
        wide = df.pivot_table(
            index="symbol", columns="metric_code", values="_metric_score", aggfunc="mean"
        )
        if wide.empty:
            if logger:
                logger.info("Valuation v2.3: pivot produced 0 rows")
            return {}

        def pick_first(row: pd.Series, codes: list[str]) -> float | None:
            for c in codes:
                v = row.get(c)
                if v is not None and not pd.isna(v):
                    return float(v)
            return None

        results: dict[str, dict[str, float | int | None]] = {}
        for symbol, row in wide.iterrows():
            sec = str(sym_sector.get(symbol, "") or "")
            groups = sector_overrides.get(sec, metric_groups_default)

            buckets: list[tuple[float, float]] = []
            for spec in groups.values():
                weight = float(spec["weight"])
                if weight <= 0:
                    continue
                score = pick_first(row, spec["codes"])
                if score is not None and np.isfinite(score):
                    buckets.append((score, weight))

            wsum = sum(w for _, w in buckets)
            if not buckets or wsum <= 0:
                continue

            value_score_raw = sum(s * w for s, w in buckets) / wsum
            value_score_raw = float(np.clip(value_score_raw, 0.0, 100.0))

            expected_wsum = sum(
                float(spec["weight"]) for spec in groups.values() if float(spec["weight"]) > 0
            )
            coverage = float(wsum / expected_wsum) if expected_wsum > 0 else 0.0
            coverage = float(np.clip(coverage, 0.0, 1.0))

            value_score = value_score_raw
            if coverage_shrink and expected_wsum > 0:
                alpha = float(np.clip(coverage, 0.0, 1.0)) ** float(coverage_shrink_power)
                value_score = (float(coverage_shrink_center) * (1.0 - alpha)) + (
                    value_score_raw * alpha
                )
            value_score = float(np.clip(value_score, 0.0, 100.0))

            results[str(symbol).upper()] = {
                "date_key": int(sym_latest_date_key_map.get(symbol, global_as_of_key)),
                "value_score": value_score,
                "value_score_raw": value_score_raw,
                "buckets_used": int(len(buckets)),
                "weight_sum": float(wsum),
                "coverage": coverage,
            }

        return results

    def compute_valuation_scores_from_frame(
        self,
        df: pd.DataFrame,
        *,
        sector_weight: float = 0.7,
        market_weight: float = 0.3,
        min_sector_size: int = 5,
        recency_calendar_days: int = 7,
        statement_recency_calendar_days: int = 400,
        winsorize: bool = True,
        winsor_lo: float = 0.01,
        winsor_hi: float = 0.99,
        coverage_shrink: bool = True,
        coverage_shrink_center: float = 50.0,
        coverage_shrink_power: float = 1.0,
    ) -> dict[str, dict[str, float | int | None]]:
        """
        Test/helper entrypoint: compute value scores from a pre-built (date_key,symbol,metric_code,metric_value,...) frame.

        Returns the same shape as `compute_valuation_scores`, including diagnostics fields.
        """
        metric_groups_default = self._get_metric_groups_default()
        sector_overrides = self._get_sector_overrides()
        direct_yield_codes = {"divyield_curttm"}
        statement_metric_codes = {
            "sharesoutstanding",
            "epsactual",
            "aepsxclxor",
            "aepsinclxo",
            "aepsnorm",
            "abepsxclxo",
            "netdebt_i",
            "netdebt_a",
            "ttmebitd",
            "ttmfcf",
            "ttmfcfshr",
            "a1fcf",
        }
        return self._compute_value_scores_from_frame(
            df,
            metric_groups_default=metric_groups_default,
            sector_overrides=sector_overrides,
            direct_yield_codes=direct_yield_codes,
            statement_metric_codes=statement_metric_codes,
            sector_weight=sector_weight,
            market_weight=market_weight,
            min_sector_size=min_sector_size,
            recency_calendar_days=recency_calendar_days,
            statement_recency_calendar_days=statement_recency_calendar_days,
            winsorize=winsorize,
            winsor_lo=winsor_lo,
            winsor_hi=winsor_hi,
            coverage_shrink=coverage_shrink,
            coverage_shrink_center=coverage_shrink_center,
            coverage_shrink_power=coverage_shrink_power,
            logger=self.logger,
        )

    def compute_valuation_scores(
        self,
        *,
        sector_weight: float = 0.7,
        market_weight: float = 0.3,
        min_sector_size: int = 5,  # min peer-group size
        recency_calendar_days: int = 7,  # ~5 trading days
        statement_recency_calendar_days: int = 400,
        prefer_industry_group: bool = True,
        winsorize: bool = True,
        winsor_lo: float = 0.01,
        winsor_hi: float = 0.99,
        coverage_shrink: bool = True,
        coverage_shrink_center: float = 50.0,
        coverage_shrink_power: float = 1.0,
    ) -> dict[str, dict[str, float | int | None]]:
        """
        Returns a per-symbol dict keyed by uppercase ticker.

        Always includes:
          - `date_key` (int): latest available fundamentals date_key for that symbol
          - `value_score` (float): final 0..100 valuation score (higher = cheaper)

        Also includes diagnostics (not persisted by default):
          - `value_score_raw` (float): score before coverage shrink-to-neutral
          - `buckets_used` (int): number of buckets contributing to the score
          - `weight_sum` (float): sum of bucket weights actually used
          - `coverage` (float): weight_sum / expected_weight_sum in [0,1]

        v2.2 changes:
          - Adds synthetic EV/EBITDA (ev2ebitda_synth) using mktcap + netdebt over ttmebitd.
          - Keeps EV/FCF (TTM/Annual) if available (Industrial/Utilities).
          - Maintains TTM preference, yield-based ranking, common as-of, and peer-group logic.

        v2.3 changes:
          - Fixes percentile direction so higher yield => higher score.
          - Adds synthetic P/E and P/FCF fallbacks (pe_synth, pfcf_synth).
          - Applies a coverage-aware shrink toward neutral when buckets are missing.
        """

        metric_groups_default = self._get_metric_groups_default()
        sector_overrides = self._get_sector_overrides()

        # Build raw code universe (exclude synthetic codes from SQL)
        synthetic_codes = {"ev2ebitda_synth", "pe_synth", "pfcf_synth"}  # computed in-memory

        def _collect_codes(groups: dict[str, dict]) -> set[str]:
            out: set[str] = set()
            for v in groups.values():
                out.update(v["codes"])
            return out

        all_codes = set(_collect_codes(metric_groups_default))
        for g in sector_overrides.values():
            all_codes.update(_collect_codes(g))

        # Add dependencies required to synthesize EV/EBITDA
        ev_ebitda_deps = {
            "mktcap",
            "netdebt_i",
            "netdebt_a",
            "ttmebitd",
        }  # EV ≈ mktcap + netdebt; EBITDA TTM
        all_codes.update(ev_ebitda_deps)

        pe_synth_deps = {
            "mktcap",
            "sharesoutstanding",
            "epsactual",
            "aepsxclxor",
            "aepsinclxo",
            "aepsnorm",
            "abepsxclxo",
        }
        all_codes.update(pe_synth_deps)

        pfcf_synth_deps = {
            "mktcap",
            "sharesoutstanding",
            "ttmfcfshr",
            "ttmfcf",
            "a1fcf",
        }
        all_codes.update(pfcf_synth_deps)

        raw_codes: list[str] = sorted(c for c in all_codes if c not in synthetic_codes)
        if not raw_codes:
            return {}

        # Identify direct-yield codes (do NOT invert these)
        direct_yield_codes = {"divyield_curttm"}
        statement_metric_codes = {
            "sharesoutstanding",
            "epsactual",
            "aepsxclxor",
            "aepsinclxo",
            "aepsnorm",
            "abepsxclxo",
            "netdebt_i",
            "netdebt_a",
            "ttmebitd",
            "ttmfcf",
            "ttmfcfshr",
            "a1fcf",
        }

        # Prefer industry_group as peer key when available
        use_industry = prefer_industry_group and self._has_industry_group()
        peer_sql = "COALESCE(s.industry_group, s.sector)" if use_industry else "s.sector"
        code_list_sql = ",".join([f"'{c}'" for c in raw_codes])

        query = f"""
            WITH latest AS (
                SELECT f.stock_key, f.metric_key, MAX(f.date_key) AS date_key
                FROM rankalpha.fact_fin_fundamentals f
                JOIN rankalpha.dim_fin_metric m ON m.metric_key = f.metric_key
                JOIN rankalpha.dim_stock s ON s.stock_key = f.stock_key
                WHERE s.is_active IS TRUE
                  AND m.metric_code IN ({code_list_sql})
                GROUP BY f.stock_key, f.metric_key
            )
            SELECT l.date_key,
                   s.symbol,
                   s.sector,
                   {peer_sql} AS peer_group,
                   m.metric_code,
                   f.metric_value
            FROM latest l
            JOIN rankalpha.fact_fin_fundamentals f
              ON f.stock_key = l.stock_key AND f.metric_key = l.metric_key AND f.date_key = l.date_key
            JOIN rankalpha.dim_stock s ON s.stock_key = l.stock_key
            JOIN rankalpha.dim_fin_metric m ON m.metric_key = l.metric_key
        """
        if self.logger:
            self.logger.info(
                f"Valuation v2.3: querying {len(raw_codes)} raw codes; peer_group={'industry_group' if use_industry else 'sector'}"
            )
        df = pd.read_sql_query(query, self.engine)
        if df.empty:
            if self.logger:
                self.logger.info("Valuation v2.3: fundamentals query returned 0 rows")
            return {}

        results = self._compute_value_scores_from_frame(
            df,
            metric_groups_default=metric_groups_default,
            sector_overrides=sector_overrides,
            direct_yield_codes=direct_yield_codes,
            statement_metric_codes=statement_metric_codes,
            sector_weight=sector_weight,
            market_weight=market_weight,
            min_sector_size=min_sector_size,
            recency_calendar_days=recency_calendar_days,
            statement_recency_calendar_days=statement_recency_calendar_days,
            winsorize=winsorize,
            winsor_lo=winsor_lo,
            winsor_hi=winsor_hi,
            coverage_shrink=coverage_shrink,
            coverage_shrink_center=coverage_shrink_center,
            coverage_shrink_power=coverage_shrink_power,
            logger=self.logger,
        )

        if self.logger and results:
            gran = "industry_group" if use_industry else "sector"
            # The helper stamps a common global as-of; use it for logging.
            as_of_key = int(pd.to_numeric(df["date_key"], errors="coerce").max() or 0)
            self.logger.info(
                f"Valuation v2.3: scores for {len(results)} symbols; as_of={as_of_key}; peer={gran}; recency<= {recency_calendar_days}d (stmt<= {statement_recency_calendar_days}d)"
            )

        return results
