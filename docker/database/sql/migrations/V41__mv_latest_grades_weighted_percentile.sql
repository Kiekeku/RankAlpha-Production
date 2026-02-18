/* ------------------------------------------------------------
   V41__mv_latest_grades_weighted_percentile.sql
   Recreate mv_latest_grades with:
   - Weighted composite (Momentum 40%, Value 40%, Sentiment 20%)
   - Dynamic reweighting when components are NULL (no penalty)
   - Final cross-sectional percentile mapped to 1..100 as avg_score
   - Percentile-based grade bands: A>=90, B>=70, C>=45, D>=20, else F
   Uses momentum and value from fact_score_history (latest per symbol),
   with legacy/AI fallbacks where needed.
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
-- Momentum from fact_score_history (new 1..100)
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
-- Legacy LR200 slope as fallback for momentum
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
-- AI snapshot (for value fallback + sentiment)
ai AS (
  SELECT a.symbol,
         MAX(a.value_score) AS ai_value_score,
         MAX(a.news_sentiment_30d) AS news_sentiment_30d
  FROM   vw_ai_analysis_full a
  JOIN   latest l ON a.as_of_date = l.full_date
  GROUP  BY a.symbol
),
-- Fundamentals-based value score (latest per symbol)
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
-- 30D news sentiment average as fallback for sentiment
news AS (
  SELECT na.stock_key,
         AVG(ns.sentiment_score)::numeric(5,3) AS news_avg
  FROM   fact_news_articles na
  JOIN   fact_news_sentiment ns ON ns.article_id = na.article_id
  JOIN   dim_date d ON d.date_key = na.article_date
  JOIN   latest l ON d.full_date >= l.full_date - interval '30 days'
  GROUP  BY na.stock_key
),
base AS (
  SELECT
    l.full_date                              AS as_of_date,
    st.symbol,
    st.company_name,
    st.sector,
    st.exchange,
    -- Momentum: prefer new 1..100; else legacy LR200 scaled 0..100
    COALESCE(mn.momentum_score,
             LEAST(100.0, GREATEST(0.0, ((ml.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0))) AS momentum_score,
    -- Value: fundamentals-based 0..100; fallback to AI value_score
    COALESCE(vf.value_score, a.ai_value_score) AS value_score,
    -- Sentiment: map [-1,1] to [0,100]
    (COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0        AS sentiment_score,
    -- Weighted composite with dynamic reweighting (M=0.4, V=0.4, S=0.2)
    CASE
      WHEN ((CASE WHEN COALESCE(mn.momentum_score,
                                 LEAST(100.0, GREATEST(0.0, ((ml.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0))) IS NOT NULL THEN 0.4 ELSE 0 END)
           + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 0.4 ELSE 0 END)
           + (CASE WHEN (COALESCE(a.news_sentiment_30d, n.news_avg)) IS NOT NULL THEN 0.2 ELSE 0 END)) > 0
      THEN (
        (COALESCE(mn.momentum_score,
                  LEAST(100.0, GREATEST(0.0, ((ml.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0))) * 0.4)
      + (COALESCE(vf.value_score, a.ai_value_score) * 0.4)
      + (((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0) * 0.2)
      ) /
      ((CASE WHEN COALESCE(mn.momentum_score,
                           LEAST(100.0, GREATEST(0.0, ((ml.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0))) IS NOT NULL THEN 0.4 ELSE 0 END)
     + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 0.4 ELSE 0 END)
     + (CASE WHEN (COALESCE(a.news_sentiment_30d, n.news_avg)) IS NOT NULL THEN 0.2 ELSE 0 END))
      ELSE NULL
    END AS composite_raw
  FROM dim_stock st
  JOIN latest l ON TRUE
  LEFT JOIN momentum_new mn   ON mn.symbol = st.symbol
  LEFT JOIN momentum_legacy ml ON ml.symbol = st.symbol
  CROSS JOIN pcts p
  LEFT JOIN ai a  ON a.symbol = st.symbol
  LEFT JOIN value_fund vf ON vf.symbol = st.symbol
  LEFT JOIN news n ON n.stock_key = st.stock_key
  WHERE st.is_active IS TRUE
),
ranked AS (
  SELECT
    b.*,
    -- Cross-sectional percentile across non-null composite_raw
    CASE WHEN b.composite_raw IS NOT NULL THEN
      CUME_DIST() OVER (ORDER BY b.composite_raw ASC NULLS LAST)
    ELSE NULL END AS composite_cume
  FROM base b
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
  -- Map percentile to 1..100 (keep two decimals)
  CASE WHEN composite_cume IS NOT NULL THEN ROUND(((composite_cume * 99.0) + 1.0)::numeric, 2) ELSE NULL END AS avg_score,
  CASE
    WHEN (CASE WHEN composite_cume IS NOT NULL THEN ((composite_cume * 99.0) + 1.0) ELSE NULL END) >= 90 THEN 'A'
    WHEN (CASE WHEN composite_cume IS NOT NULL THEN ((composite_cume * 99.0) + 1.0) ELSE NULL END) >= 70 THEN 'B'
    WHEN (CASE WHEN composite_cume IS NOT NULL THEN ((composite_cume * 99.0) + 1.0) ELSE NULL END) >= 45 THEN 'C'
    WHEN (CASE WHEN composite_cume IS NOT NULL THEN ((composite_cume * 99.0) + 1.0) ELSE NULL END) >= 20 THEN 'D'
    WHEN composite_cume IS NOT NULL THEN 'F'
    ELSE 'N/A'
  END AS grade,
  CASE
    WHEN (CASE WHEN composite_cume IS NOT NULL THEN ((composite_cume * 99.0) + 1.0) ELSE NULL END) >= 90 THEN 5
    WHEN (CASE WHEN composite_cume IS NOT NULL THEN ((composite_cume * 99.0) + 1.0) ELSE NULL END) >= 70 THEN 4
    WHEN (CASE WHEN composite_cume IS NOT NULL THEN ((composite_cume * 99.0) + 1.0) ELSE NULL END) >= 45 THEN 3
    WHEN (CASE WHEN composite_cume IS NOT NULL THEN ((composite_cume * 99.0) + 1.0) ELSE NULL END) >= 20 THEN 2
    WHEN composite_cume IS NOT NULL THEN 1
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

