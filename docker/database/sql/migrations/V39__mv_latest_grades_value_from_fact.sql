/* ------------------------------------------------------------
   V39__mv_latest_grades_value_from_fact.sql
   Update mv_latest_grades to source value_score from fact_score_history
   (latest per symbol) with AI value_score as a fallback.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- Drop and recreate the materialized view to change its definition
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_latest_grades;

CREATE MATERIALIZED VIEW rankalpha.mv_latest_grades AS
WITH latest AS (
  SELECT d.date_key, d.full_date
  FROM   dim_date d
  JOIN   fact_score_history f ON f.date_key = d.date_key
  ORDER  BY d.full_date DESC
  LIMIT 1
),
momentum AS (
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
  FROM momentum
),
-- AI snapshot (kept for sentiment); as_of aligned to latest day
ai AS (
  SELECT a.symbol,
         MAX(a.value_score) AS ai_value_score,
         MAX(a.news_sentiment_30d) AS news_sentiment_30d
  FROM   vw_ai_analysis_full a
  JOIN   latest l ON a.as_of_date = l.full_date
  GROUP  BY a.symbol
),
-- Fundamentals-based value score: latest per symbol from fact_score_history
value_fund AS (
  SELECT symbol, value_score
  FROM (
    SELECT
      s.symbol,
      f.score::numeric(10,2) AS value_score,
      ROW_NUMBER() OVER (
        PARTITION BY f.stock_key
        ORDER BY f.date_key DESC, f.load_ts DESC, f.fact_id DESC
      ) AS rn
    FROM   fact_score_history f
    JOIN   dim_score_type t ON t.score_type_key = f.score_type_key
    JOIN   dim_stock s ON s.stock_key = f.stock_key
    WHERE  t.score_type_name = 'value score'
  ) ranked
  WHERE rn = 1
),
news AS (
  SELECT na.stock_key,
         AVG(ns.sentiment_score)::numeric(5,3) AS news_avg
  FROM   fact_news_articles na
  JOIN   fact_news_sentiment ns ON ns.article_id = na.article_id
  JOIN   dim_date d ON d.date_key = na.article_date
  JOIN   latest l ON d.full_date >= l.full_date - interval '30 days'
  GROUP  BY na.stock_key
)
SELECT
  l.full_date                              AS as_of_date,
  st.symbol,
  st.company_name,
  st.sector,
  st.exchange,
  -- momentum 0-100 using winsorized p05/p95
  LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)) AS momentum_score,
  COALESCE(vf.value_score, a.ai_value_score) AS value_score,
  (COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0 AS sentiment_score,
  -- average of non-nulls
  (
    (COALESCE(LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)), 0)
     + COALESCE(COALESCE(vf.value_score, a.ai_value_score), 0)
     + COALESCE((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0, 0))
    / NULLIF(
        (CASE WHEN m.momentum_raw IS NOT NULL THEN 1 ELSE 0 END)
      + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 1 ELSE 0 END)
      + (CASE WHEN COALESCE(a.news_sentiment_30d, n.news_avg) IS NOT NULL THEN 1 ELSE 0 END),
      0
    )
  ) AS avg_score,
  CASE
    WHEN (
      (COALESCE(LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)), 0)
       + COALESCE(COALESCE(vf.value_score, a.ai_value_score), 0)
       + COALESCE((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0, 0))
      / NULLIF(
          (CASE WHEN m.momentum_raw IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(a.news_sentiment_30d, n.news_avg) IS NOT NULL THEN 1 ELSE 0 END),
        0
      )
    ) >= 85 THEN 'A'
    WHEN (
      (COALESCE(LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)), 0)
       + COALESCE(COALESCE(vf.value_score, a.ai_value_score), 0)
       + COALESCE((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0, 0))
      / NULLIF(
          (CASE WHEN m.momentum_raw IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(a.news_sentiment_30d, n.news_avg) IS NOT NULL THEN 1 ELSE 0 END),
        0
      )
    ) >= 70 THEN 'B'
    WHEN (
      (COALESCE(LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)), 0)
       + COALESCE(COALESCE(vf.value_score, a.ai_value_score), 0)
       + COALESCE((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0, 0))
      / NULLIF(
          (CASE WHEN m.momentum_raw IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(a.news_sentiment_30d, n.news_avg) IS NOT NULL THEN 1 ELSE 0 END),
        0
      )
    ) >= 55 THEN 'C'
    WHEN (
      (COALESCE(LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)), 0)
       + COALESCE(COALESCE(vf.value_score, a.ai_value_score), 0)
       + COALESCE((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0, 0))
      / NULLIF(
          (CASE WHEN m.momentum_raw IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(a.news_sentiment_30d, n.news_avg) IS NOT NULL THEN 1 ELSE 0 END),
        0
      )
    ) >= 40 THEN 'D'
    WHEN (
      (COALESCE(LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)), 0)
       + COALESCE(COALESCE(vf.value_score, a.ai_value_score), 0)
       + COALESCE((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0, 0))
      / NULLIF(
          (CASE WHEN m.momentum_raw IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(a.news_sentiment_30d, n.news_avg) IS NOT NULL THEN 1 ELSE 0 END),
        0
      )
    ) IS NOT NULL THEN 'F'
    ELSE 'N/A'
  END AS grade,
  CASE
    WHEN (
      (COALESCE(LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)), 0)
       + COALESCE(COALESCE(vf.value_score, a.ai_value_score), 0)
       + COALESCE((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0, 0))
      / NULLIF(
          (CASE WHEN m.momentum_raw IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(a.news_sentiment_30d, n.news_avg) IS NOT NULL THEN 1 ELSE 0 END),
        0
      )
    ) >= 85 THEN 5
    WHEN (
      (COALESCE(LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)), 0)
       + COALESCE(COALESCE(vf.value_score, a.ai_value_score), 0)
       + COALESCE((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0, 0))
      / NULLIF(
          (CASE WHEN m.momentum_raw IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(a.news_sentiment_30d, n.news_avg) IS NOT NULL THEN 1 ELSE 0 END),
        0
      )
    ) >= 70 THEN 4
    WHEN (
      (COALESCE(LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)), 0)
       + COALESCE(COALESCE(vf.value_score, a.ai_value_score), 0)
       + COALESCE((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0, 0))
      / NULLIF(
          (CASE WHEN m.momentum_raw IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(a.news_sentiment_30d, n.news_avg) IS NOT NULL THEN 1 ELSE 0 END),
        0
      )
    ) >= 55 THEN 3
    WHEN (
      (COALESCE(LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)), 0)
       + COALESCE(COALESCE(vf.value_score, a.ai_value_score), 0)
       + COALESCE((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0, 0))
      / NULLIF(
          (CASE WHEN m.momentum_raw IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(a.news_sentiment_30d, n.news_avg) IS NOT NULL THEN 1 ELSE 0 END),
        0
      )
    ) >= 40 THEN 2
    WHEN (
      (COALESCE(LEAST(100.0, GREATEST(0.0, ((m.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0)), 0)
       + COALESCE(COALESCE(vf.value_score, a.ai_value_score), 0)
       + COALESCE((COALESCE(a.news_sentiment_30d, n.news_avg) + 1.0) * 50.0, 0))
      / NULLIF(
          (CASE WHEN m.momentum_raw IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(vf.value_score, a.ai_value_score) IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(a.news_sentiment_30d, n.news_avg) IS NOT NULL THEN 1 ELSE 0 END),
        0
      )
    ) IS NOT NULL THEN 1
    ELSE 0
  END AS grade_order
FROM dim_stock st
JOIN latest l ON TRUE
LEFT JOIN momentum m ON m.symbol = st.symbol
CROSS JOIN pcts p
LEFT JOIN ai a ON a.symbol = st.symbol
LEFT JOIN value_fund vf ON vf.symbol = st.symbol
LEFT JOIN news n ON n.stock_key = st.stock_key
WHERE st.is_active IS TRUE;

-- Indexes for fast filters and sorting (recreate after drop)
CREATE UNIQUE INDEX IF NOT EXISTS mv_latest_grades_symbol_uidx
  ON rankalpha.mv_latest_grades (symbol);

CREATE INDEX IF NOT EXISTS mv_latest_grades_grade_order_idx
  ON rankalpha.mv_latest_grades (grade_order DESC, symbol);

CREATE INDEX IF NOT EXISTS mv_latest_grades_sector_idx
  ON rankalpha.mv_latest_grades (sector);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
