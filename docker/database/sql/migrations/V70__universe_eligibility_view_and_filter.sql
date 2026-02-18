/* ------------------------------------------------------------
   V70__universe_eligibility_view_and_filter.sql
   - Create mv_universe_eligible (single source of truth for tradable universe)
   - Include ETFs (same price/liquidity rules as equities)
   - Filter out OTC symbols and low price/liquidity names
   - Update fn_grades_as_of to restrict to eligible universe
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_universe_eligible;

-- Materialized view computing eligibility metrics and a boolean flag
CREATE MATERIALIZED VIEW rankalpha.mv_universe_eligible AS
WITH latest AS (
  SELECT MAX(d.full_date) AS latest_date
  FROM   fact_security_price s
  JOIN   dim_date d ON d.date_key = s.date_key
), d30 AS (
  SELECT d.date_key
  FROM   dim_date d, latest l
  WHERE  d.full_date <= l.latest_date
  ORDER  BY d.full_date DESC
  LIMIT  30
), d22 AS (
  SELECT d.date_key
  FROM   dim_date d, latest l
  WHERE  d.full_date <= l.latest_date
  ORDER  BY d.full_date DESC
  LIMIT  22
), base30 AS (
  SELECT ds.stock_key,
         ds.symbol,
         ds.exchange,
         COALESCE(at.asset_type_name, 'equity') AS asset_type,
         (s.close_px)::numeric(20,4)                      AS close_px,
         (s.volume)::numeric                              AS vol,
         ((s.close_px)::numeric(20,4) * (s.volume)::numeric) AS dollar_vol
  FROM   dim_stock ds
  LEFT   JOIN dim_asset_type at ON at.asset_type_key = ds.asset_type_key
  JOIN   fact_security_price s ON s.stock_key = ds.stock_key
  JOIN   d30 ON d30.date_key = s.date_key
  WHERE  ds.is_active IS TRUE
), med AS (
  SELECT stock_key,
         symbol,
         exchange,
         asset_type,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY dollar_vol) AS med_addv_30_usd,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY vol)        AS med_vol_30_sh
  FROM   base30
  GROUP  BY stock_key, symbol, exchange, asset_type
), bars AS (
  SELECT ds.stock_key,
         COUNT(*) AS bars_22
  FROM   dim_stock ds
  JOIN   fact_security_price s ON s.stock_key = ds.stock_key
  JOIN   d22 ON d22.date_key = s.date_key
  WHERE  ds.is_active IS TRUE
  GROUP  BY ds.stock_key
), latest_px AS (
  -- Adjusted close on latest day equals close_px by construction, but we use the view for consistency
  SELECT ds.stock_key,
         ds.symbol,
         v.adj_close_px AS latest_adj_close
  FROM   vw_latest_adj_close v
  JOIN   dim_stock ds ON ds.symbol = v.symbol
)
SELECT
  m.symbol,
  m.stock_key,
  m.exchange,
  m.asset_type,
  lp.latest_adj_close,
  m.med_addv_30_usd,
  m.med_vol_30_sh,
  COALESCE(b.bars_22, 0) AS bars_22,
  CASE
    WHEN (m.exchange ILIKE 'OTC%' OR m.exchange ILIKE 'OTCQB%' OR m.exchange ILIKE 'OTCMKTS%' OR m.exchange ILIKE 'PINK%') THEN FALSE
    WHEN NOT (m.asset_type ILIKE 'equity' OR m.asset_type ILIKE 'etf') THEN FALSE
    WHEN lp.latest_adj_close IS NULL OR lp.latest_adj_close < 3 THEN FALSE                 -- price floor ($3)
    WHEN m.med_addv_30_usd IS NULL OR m.med_addv_30_usd < 1000000 THEN FALSE              -- 30d median ADDV >= $1M
    WHEN m.med_vol_30_sh IS NULL OR m.med_vol_30_sh < 50000 THEN FALSE                    -- 30d median shares >= 50k
    WHEN COALESCE(b.bars_22, 0) < 15 THEN FALSE                                           -- continuity >= 15 of 22 days
    ELSE TRUE
  END AS eligible
FROM med m
LEFT JOIN bars b   ON b.stock_key = m.stock_key
LEFT JOIN latest_px lp ON lp.stock_key = m.stock_key;

CREATE UNIQUE INDEX IF NOT EXISTS mv_universe_eligible_symbol_uidx
  ON rankalpha.mv_universe_eligible (symbol);

CREATE INDEX IF NOT EXISTS mv_universe_eligible_eligible_idx
  ON rankalpha.mv_universe_eligible (eligible);

/* ------------------------------------------------------------
   Update fn_grades_as_of to restrict universe to eligible symbols
   ------------------------------------------------------------ */
CREATE OR REPLACE FUNCTION rankalpha.fn_grades_as_of(p_asof DATE)
RETURNS TABLE (
  as_of_date      DATE,
  symbol          TEXT,
  company_name    TEXT,
  sector          TEXT,
  exchange        TEXT,
  momentum_score  NUMERIC(14,2),
  value_score     NUMERIC(14,2),
  sentiment_score NUMERIC(14,2),
  avg_score       NUMERIC(14,2),
  grade           TEXT,
  grade_order     INT
) LANGUAGE sql STABLE AS $$
  WITH params AS (
    SELECT p_asof::date AS as_of_date
  ),
  weights AS (
    SELECT w_m, w_v, w_s
    FROM   rankalpha.fn_model_weights_as_of('default', (SELECT as_of_date FROM params))
  ),
  momentum_new AS (
    SELECT s.symbol,
           r.momentum_score
    FROM (
      SELECT f.stock_key,
             f.score::numeric(14,2) AS momentum_score,
             ROW_NUMBER() OVER (
               PARTITION BY f.stock_key
               ORDER BY f.date_key DESC, f.load_ts DESC, f.fact_id DESC
             ) AS rn
      FROM   rankalpha.fact_score_history f
      JOIN   rankalpha.dim_score_type t ON t.score_type_key = f.score_type_key
      JOIN   rankalpha.dim_date d ON d.date_key = f.date_key
      WHERE  t.score_type_name = 'momentum score'
         AND d.full_date <= (SELECT as_of_date FROM params)
    ) r
    JOIN rankalpha.dim_stock s ON s.stock_key = r.stock_key
    WHERE r.rn = 1
  ),
  momentum_legacy AS (
    SELECT s.symbol,
           MAX(f.score)::numeric(14,2) AS momentum_raw
    FROM   rankalpha.fact_score_history f
    JOIN   rankalpha.dim_score_type t ON t.score_type_key = f.score_type_key
    JOIN   rankalpha.dim_date d ON d.date_key = f.date_key
    JOIN   rankalpha.dim_stock s ON s.stock_key = f.stock_key
    WHERE  t.score_type_name = 'linear regression 200'
       AND d.full_date = (SELECT as_of_date FROM params)
    GROUP  BY s.symbol
  ),
  pcts AS (
    SELECT
      percentile_cont(0.05) WITHIN GROUP (ORDER BY momentum_raw) AS p05,
      percentile_cont(0.95) WITHIN GROUP (ORDER BY momentum_raw) AS p95
    FROM momentum_legacy
  ),
  ai_latest AS (
    SELECT symbol, value_score AS ai_value_score
    FROM (
      SELECT a.symbol,
             a.value_score,
             ROW_NUMBER() OVER (
               PARTITION BY a.symbol
               ORDER BY a.date_key DESC, a.load_ts DESC, a.analysis_id DESC
             ) AS rn
      FROM   rankalpha.vw_ai_analysis_full a
      WHERE  a.as_of_date <= (SELECT as_of_date FROM params)
    ) x WHERE rn = 1
  ),
  value_fund AS (
    SELECT s.symbol,
           r.value_score
    FROM (
      SELECT f.stock_key,
             f.score::numeric(14,2) AS value_score,
             ROW_NUMBER() OVER (
               PARTITION BY f.stock_key
               ORDER BY f.date_key DESC, f.load_ts DESC, f.fact_id DESC
             ) AS rn
      FROM   rankalpha.fact_score_history f
      JOIN   rankalpha.dim_score_type t ON t.score_type_key = f.score_type_key
      JOIN   rankalpha.dim_date d ON d.date_key = f.date_key
      WHERE  t.score_type_name = 'value score'
         AND d.full_date <= (SELECT as_of_date FROM params)
    ) r
    JOIN rankalpha.dim_stock s ON s.stock_key = r.stock_key
    WHERE r.rn = 1
  ),
  sentiment_proxy AS (
    SELECT symbol, sentiment_proxy_score
    FROM   rankalpha.fn_sentiment_proxy_as_of((SELECT as_of_date FROM params))
  ),
  base AS (
    SELECT
      (SELECT as_of_date FROM params)  AS as_of_date,
      st.symbol,
      st.company_name,
      st.sector,
      st.exchange,
      COALESCE(mn.momentum_score,
               LEAST(100.0, GREATEST(0.0, ((ml.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0))) AS m_eff,
      COALESCE(vf.value_score, ai.ai_value_score) AS v_eff,
      sp.sentiment_proxy_score AS s_eff,
      (SELECT w_m FROM weights) AS w_m,
      (SELECT w_v FROM weights) AS w_v,
      (SELECT w_s FROM weights) AS w_s
    FROM rankalpha.dim_stock st
    LEFT JOIN momentum_new mn    ON mn.symbol = st.symbol
    LEFT JOIN momentum_legacy ml ON ml.symbol = st.symbol
    CROSS JOIN pcts p
    LEFT JOIN ai_latest ai ON ai.symbol = st.symbol
    LEFT JOIN value_fund vf ON vf.symbol = st.symbol
    LEFT JOIN sentiment_proxy sp ON sp.symbol = st.symbol
    JOIN rankalpha.mv_universe_eligible ue ON ue.symbol = st.symbol AND ue.eligible IS TRUE
    WHERE st.is_active IS TRUE
  ),
  ranked AS (
    SELECT
      as_of_date,
      symbol,
      company_name,
      sector,
      exchange,
      m_eff AS momentum_score,
      v_eff AS value_score,
      s_eff AS sentiment_score,
      CASE
        WHEN m_eff IS NOT NULL AND v_eff IS NOT NULL THEN (
          (COALESCE(m_eff, 0) * w_m)
        + (COALESCE(v_eff, 0) * w_v)
        + (COALESCE(s_eff, 0) * w_s)
        ) / NULLIF(
            (CASE WHEN m_eff IS NOT NULL THEN w_m ELSE 0 END)
          + (CASE WHEN v_eff IS NOT NULL THEN w_v ELSE 0 END)
          + (CASE WHEN s_eff IS NOT NULL THEN w_s ELSE 0 END), 0)
        ELSE NULL
      END AS composite_raw
    FROM base
  )
  SELECT
    as_of_date,
    symbol,
    company_name,
    sector,
    exchange,
    momentum_score,
    value_score,
    sentiment_score,
    CASE WHEN composite_raw IS NOT NULL THEN
      ROUND((CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0)::numeric, 2)
    ELSE NULL END AS avg_score,
    CASE
      WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 90 THEN 'A'
      WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 70 THEN 'B'
      WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 45 THEN 'C'
      WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 20 THEN 'D'
      WHEN composite_raw IS NOT NULL THEN 'F'
      ELSE 'N/A'
    END AS grade,
    CASE
      WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 90 THEN 5
      WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 70 THEN 4
      WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 45 THEN 3
      WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 20 THEN 2
      WHEN composite_raw IS NOT NULL THEN 1
      ELSE 0
    END AS grade_order
  FROM ranked
$$;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

