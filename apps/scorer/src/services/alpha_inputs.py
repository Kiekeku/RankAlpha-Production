from __future__ import annotations

import pandas as pd


class AlphaInputs:
    def __init__(self, engine, logger=None):
        self.engine = engine
        self.logger = logger

    def _normalize_series(self, values: pd.Series) -> pd.Series:
        if values.empty:
            return pd.Series([None] * len(values), index=values.index)
        numeric = pd.to_numeric(values, errors="coerce")
        data = numeric.dropna().astype(float)
        if data.empty:
            return pd.Series([None] * len(values), index=values.index)
        p05 = data.quantile(0.05)
        p95 = data.quantile(0.95)
        if pd.isna(p05) or pd.isna(p95) or abs(p95 - p05) < 1e-9:
            return pd.Series([50.0] * len(values), index=values.index)

        def _scale(x):
            if pd.isna(x):
                return None
            norm = (float(x) - p05) / (p95 - p05)
            return max(0.0, min(100.0, norm * 100.0))

        return numeric.apply(_scale)

    def load_ai_scores(self) -> dict[str, dict[str, float | None]]:
        query = """
            SELECT symbol,
                   date_key,
                   value_score,
                   quality_score,
                   momentum_score,
                   low_vol_score,
                   news_sentiment_30d,
                   social_sentiment_7d
            FROM rankalpha.vw_ai_analysis_latest
        """
        df = pd.read_sql_query(query, self.engine)
        if df.empty:
            return {}

        result: dict[str, dict[str, float | None]] = {}
        factor_columns = ["value_score", "quality_score", "momentum_score", "low_vol_score"]
        for col in factor_columns:
            df[f"{col}_norm"] = self._normalize_series(df[col])

        sentiment_inputs = df[["news_sentiment_30d", "social_sentiment_7d"]].apply(
            pd.to_numeric, errors="coerce"
        )
        df["sentiment_raw"] = sentiment_inputs.mean(axis=1)
        df["sentiment_norm"] = self._normalize_series(df["sentiment_raw"])

        # Prefer DB materialized proxy if available; fallback handled below
        scen_scores: dict[str, dict[str, float | None]] = {}
        try:
            scen_sql = """
                SELECT symbol, px_date_key, sentiment_proxy_score
                FROM rankalpha.mv_sentiment_proxy
            """
            df_s = pd.read_sql_query(scen_sql, self.engine)
            if not df_s.empty:
                for _, r in df_s.iterrows():
                    sym = str(r.get("symbol") or "").upper()
                    scen_scores[sym] = {
                        "sentiment_score": r.get("sentiment_proxy_score"),
                        "sentiment_date_key": int(r.get("px_date_key"))
                        if pd.notna(r.get("px_date_key"))
                        else None,
                    }
        except Exception:
            scen_scores = {}

        for _, row in df.iterrows():
            symbol = str(row["symbol"]).upper()
            try:
                date_key = int(row["date_key"])
            except Exception:
                date_key = None
            entry = {
                "date_key": date_key,
                "value_score": row.get("value_score_norm"),
                "quality_score": row.get("quality_score_norm"),
                "momentum_score": row.get("momentum_score_norm"),
                "low_vol_score": row.get("low_vol_score_norm"),
                "sentiment_score": (
                    scen_scores.get(symbol, {}).get("sentiment_score")
                    if scen_scores.get(symbol, {}).get("sentiment_score") is not None
                    else row.get("sentiment_norm")
                ),
                "sentiment_date_key": scen_scores.get(symbol, {}).get("sentiment_date_key"),
            }
            result[symbol] = entry

        return result

    # Valuation moved to ValuationService to keep responsibilities clean.
