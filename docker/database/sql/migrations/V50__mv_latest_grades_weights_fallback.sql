/* ------------------------------------------------------------
   V50__mv_latest_grades_weights_fallback.sql
   Recreate mv_latest_grades so weights always exist (fallback to 0.40/0.40/0.20
   when dim_model_weight is empty). This prevents grade = 'N/A' when M/V exist.
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
weights_raw AS (
  SELECT
    COALESCE(w.w_momentum, 0.4)::numeric(6,4)  AS w_m,
    COALESCE(w.w_value, 0.4)::numeric(6,4)     AS w_v,
    COALESCE(w.w_sentiment, 0.2)::numeric(6,4) AS w_s
  FROM rankalpha.dim_model_weight w
  ORDER BY w.as_of_date DESC
  LIMIT 1
),
weights AS (
  /* Ensure exactly one row even when the table is empty */
  SELECT
    COALESCE((SELECT w_m FROM weights_raw), 0.4)::numeric(6,4) AS w_m,
    COALESCE((SELECT w_v FROM weights_raw), 0.4)::numeric(6,4) AS w_v,
    COALESCE((SELECT w_s FROM weights_raw), 0.2)::numeric(6,4) AS w_s
),
-- Momentum from fact_score_history (new 1..100), fallback to legacy LR200 scaled
momentum_new AS (
  SELECT s.symbol,
         r.momentum_score
  FROM (
    SELECT f.stock_key,
           f.score::numeric(10,2) AS momentum_score,
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
         MAX(f.score)::numeric(10,2) AS momentum_raw
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
ai_latest AS (
  SELECT symbol, value_score AS ai_value_score, news_sentiment_30d
  FROM (
    SELECT a.symbol,
           a.value_score,
           a.news_sentiment_30d,
           ROW_NUMBER() OVER (PARTITION BY a.symbol ORDER BY a.as_of_date DESC) AS rn
    FROM   vw_ai_analysis_full a
  ) x WHERE rn = 1
),
value_fund AS (
  SELECT s.symbol,
         r.value_score
  FROM (
    SELECT f.stock_key,
           f.score::numeric(10,2) AS value_score,
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
news AS (
  SELECT na.stock_key,
         AVG(ns.sentiment_score)::numeric(5,3) AS news_avg
  FROM   fact_news_articles na
  JOIN   fact_news_sentiment ns ON ns.article_id = na.article_id
  JOIN   dim_date d ON d.date_key = na.article_date
  JOIN   latest l ON d.full_date >= l.full_date - interval '30 days'
  GROUP  BY na.stock_key
),
sentiment_latest AS (
  SELECT s.symbol,
         r.sentiment_score
  FROM (
    SELECT f.stock_key,
           f.score::numeric(10,2) AS sentiment_score,
           ROW_NUMBER() OVER (
             PARTITION BY f.stock_key
             ORDER BY f.date_key DESC, f.load_ts DESC, f.fact_id DESC
           ) AS rn
    FROM   fact_score_history f
    JOIN   dim_score_type t ON t.score_type_key = f.score_type_key
    WHERE  t.score_type_name = 'sentiment score'
  ) r
  JOIN dim_stock s ON s.stock_key = r.stock_key
  WHERE r.rn = 1
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
    COALESCE(sl.sentiment_score, (COALESCE(ai.news_sentiment_30d, n.news_avg) + 1.0) * 50.0) AS s_eff,
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
  LEFT JOIN news n ON n.stock_key = st.stock_key
  LEFT JOIN sentiment_latest sl ON sl.symbol = st.symbol
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

