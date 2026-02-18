/* ------------------------------------------------------------
   V58__mv_latest_grades_use_sentiment_proxy.sql
   - Recreate mv_latest_grades to source Sentiment from mv_sentiment_proxy
     and AI latest from vw_ai_analysis_latest for a single source of truth.
   - Uses fn_model_weights_as_of for weights at the latest available date.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_latest_grades;

CREATE MATERIALIZED VIEW rankalpha.mv_latest_grades AS
WITH latest AS (
  SELECT d.date_key, d.full_date
  FROM   dim_date d
  JOIN   fact_score_history f ON f.date_key = d.date_key
  ORDER  BY d.full_date DESC
  LIMIT 1
),
weights AS (
  SELECT w_m, w_v, w_s
  FROM   rankalpha.fn_model_weights_as_of('default', (SELECT full_date FROM latest))
),
-- Momentum from fact_score_history (new 1..100), fallback to legacy LR200 scaled
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
    FROM   fact_score_history f
    JOIN   dim_score_type t ON t.score_type_key = f.score_type_key
    WHERE  t.score_type_name = 'momentum score'
  ) r
  JOIN dim_stock s ON s.stock_key = r.stock_key
  WHERE r.rn = 1
),
momentum_legacy AS (
  SELECT s.symbol,
         MAX(f.score)::numeric(14,2) AS momentum_raw
  FROM   fact_score_history f
  JOIN   latest l ON f.date_key = l.date_key
  JOIN   dim_score_type t ON t.score_type_key = f.score_type_key
  JOIN   dim_stock s ON s.stock_key = f.stock_key
  WHERE  t.score_type_name = 'linear regression 200'
  GROUP  BY s.symbol
),
pcts AS (
  SELECT
    percentile_cont(0.05) WITHIN GROUP (ORDER BY momentum_raw) AS p05,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY momentum_raw) AS p95
  FROM momentum_legacy
),
-- AI latest via consolidated latest view
ai_latest AS (
  SELECT symbol, value_score AS ai_value_score
  FROM   vw_ai_analysis_latest
),
-- Fundamentals-based value score from fact_score_history
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
    FROM   fact_score_history f
    JOIN   dim_score_type t ON t.score_type_key = f.score_type_key
    WHERE  t.score_type_name = 'value score'
  ) r
  JOIN dim_stock s ON s.stock_key = r.stock_key
  WHERE r.rn = 1
),
-- Sentiment proxy (single source of truth)
sentiment_proxy AS (
  SELECT symbol, sentiment_proxy_score
  FROM   mv_sentiment_proxy
),
base AS (
  SELECT
    l.full_date                              AS as_of_date,
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
  FROM dim_stock st
  JOIN latest l ON TRUE
  LEFT JOIN momentum_new mn    ON mn.symbol = st.symbol
  LEFT JOIN momentum_legacy ml ON ml.symbol = st.symbol
  CROSS JOIN pcts p
  LEFT JOIN ai_latest ai ON ai.symbol = st.symbol
  LEFT JOIN value_fund vf ON vf.symbol = st.symbol
  LEFT JOIN sentiment_proxy sp ON sp.symbol = st.symbol
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
FROM ranked;

CREATE UNIQUE INDEX IF NOT EXISTS mv_latest_grades_symbol_uidx
  ON rankalpha.mv_latest_grades (symbol);

CREATE INDEX IF NOT EXISTS mv_latest_grades_grade_order_idx
  ON rankalpha.mv_latest_grades (grade_order DESC, symbol);

CREATE INDEX IF NOT EXISTS mv_latest_grades_sector_idx
  ON rankalpha.mv_latest_grades (sector);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

