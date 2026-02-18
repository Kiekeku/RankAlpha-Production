/* ------------------------------------------------------------
   V55__versioned_model_weights_and_asof_grades.sql
   - Introduce time-versioned model weights (SCD-2 style)
   - Add helper functions to fetch weights as-of a date
   - Add fn_grades_as_of(date) returning the same shape as mv_latest_grades
   - Recreate mv_latest_grades to delegate to fn_grades_as_of(latest_date)
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- Required for range exclusion
CREATE EXTENSION IF NOT EXISTS btree_gist;

/* ------------------------------------------------------------
   1) Versioned weights tables
   ------------------------------------------------------------ */

CREATE TABLE IF NOT EXISTS rankalpha.dim_model_weight_version (
  id                BIGSERIAL PRIMARY KEY,
  model_code        TEXT NOT NULL DEFAULT 'default',
  effective_from    DATE NOT NULL,
  effective_to      DATE,
  train_start_date  DATE NOT NULL,
  train_end_date    DATE NOT NULL,
  window_days       INT  NOT NULL,
  horizon_days      INT  NOT NULL,
  lambda_rp         NUMERIC(6,4) NOT NULL,
  alpha_shrink      NUMERIC(6,4) NOT NULL DEFAULT 0.5,
  sentiment_coverage NUMERIC(6,4),
  computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  computed_by       TEXT,
  validity          DATERANGE GENERATED ALWAYS AS
                    (daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[)')) STORED,
  CONSTRAINT uq_weight_version UNIQUE (model_code, effective_from),
  CONSTRAINT ck_train_before_effective CHECK (train_end_date < effective_from)
);

-- Prevent overlapping validity ranges per model
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ex_model_weight_validity'
  ) THEN
    ALTER TABLE rankalpha.dim_model_weight_version
      ADD CONSTRAINT ex_model_weight_validity
      EXCLUDE USING gist (model_code WITH =, validity WITH &&);
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS rankalpha.dim_model_weight_item (
  version_id  BIGINT NOT NULL REFERENCES rankalpha.dim_model_weight_version(id) ON DELETE CASCADE,
  factor_code TEXT   NOT NULL,
  weight      NUMERIC(8,6) NOT NULL CHECK (weight >= 0 AND weight <= 1),
  CONSTRAINT uq_weight_item UNIQUE (version_id, factor_code)
);

CREATE INDEX IF NOT EXISTS ix_weight_version_model_from
  ON rankalpha.dim_model_weight_version(model_code, effective_from DESC);

CREATE INDEX IF NOT EXISTS ix_weight_item_version
  ON rankalpha.dim_model_weight_item(version_id);

/* ------------------------------------------------------------
   2) Bootstrap a baseline version so historical queries never fail
   ------------------------------------------------------------ */
DO $$
DECLARE
  v_id BIGINT;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM rankalpha.dim_model_weight_version) THEN
    INSERT INTO rankalpha.dim_model_weight_version (
      model_code, effective_from, effective_to,
      train_start_date, train_end_date,
      window_days, horizon_days, lambda_rp, alpha_shrink, sentiment_coverage, computed_by
    ) VALUES (
      'default', DATE '1970-01-01', NULL,
      DATE '1969-01-01', DATE '1969-12-31',
      504, 21, 0.4, 0.5, NULL, 'migration V55'
    ) RETURNING id INTO v_id;

    INSERT INTO rankalpha.dim_model_weight_item (version_id, factor_code, weight)
    VALUES
      (v_id, 'Momentum',  0.40),
      (v_id, 'Value',     0.40),
      (v_id, 'Sentiment', 0.20);
  END IF;
END$$;

/* ------------------------------------------------------------
   3) Helper: pick version id as-of a date
   ------------------------------------------------------------ */
CREATE OR REPLACE FUNCTION rankalpha.fn_model_weight_version_id_as_of(p_model TEXT, p_asof DATE)
RETURNS BIGINT
LANGUAGE sql STABLE AS $$
  SELECT id
  FROM   rankalpha.dim_model_weight_version
  WHERE  model_code = COALESCE(p_model, 'default')
    AND  p_asof <@ validity
  ORDER  BY effective_from DESC
  LIMIT 1
$$;

/* ------------------------------------------------------------
   4) Helper: return M/V/S weights as-of a date with fallback defaults
   ------------------------------------------------------------ */
CREATE OR REPLACE FUNCTION rankalpha.fn_model_weights_as_of(
  p_model TEXT,
  p_asof  DATE
) RETURNS TABLE (
  w_m numeric(6,4),
  w_v numeric(6,4),
  w_s numeric(6,4)
) LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_id BIGINT;
BEGIN
  v_id := rankalpha.fn_model_weight_version_id_as_of(p_model, p_asof);
  IF v_id IS NULL THEN
    -- Fallback default
    RETURN QUERY SELECT 0.4::numeric(6,4), 0.4::numeric(6,4), 0.2::numeric(6,4);
    RETURN;
  END IF;
  RETURN QUERY
  SELECT
    COALESCE(MAX(CASE WHEN i.factor_code ILIKE 'Momentum'  THEN i.weight END), 0.4)::numeric(6,4) AS w_m,
    COALESCE(MAX(CASE WHEN i.factor_code ILIKE 'Value'     THEN i.weight END), 0.4)::numeric(6,4) AS w_v,
    COALESCE(MAX(CASE WHEN i.factor_code ILIKE 'Sentiment' THEN i.weight END), 0.2)::numeric(6,4) AS w_s
  FROM rankalpha.dim_model_weight_item i
  WHERE i.version_id = v_id;
END$$;

/* ------------------------------------------------------------
   5) Grades as-of a date (set-returning function)
   Returns the same columns as mv_latest_grades for a given p_asof date.
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
  SELECT COALESCE(p_asof, CURRENT_DATE)::date AS as_of_date
),
weights AS (
  SELECT w_m, w_v, w_s
  FROM   rankalpha.fn_model_weights_as_of('default', (SELECT as_of_date FROM params))
),
-- Momentum from fact_score_history (new 1..100), as-of p_asof
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
  SELECT symbol, value_score AS ai_value_score, news_sentiment_30d
  FROM (
    SELECT a.symbol,
           a.value_score,
           a.news_sentiment_30d,
           ROW_NUMBER() OVER (PARTITION BY a.symbol ORDER BY a.as_of_date DESC) AS rn
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
news AS (
  SELECT na.stock_key,
         AVG(ns.sentiment_score)::numeric(5,3) AS news_avg
  FROM   rankalpha.fact_news_articles na
  JOIN   rankalpha.fact_news_sentiment ns ON ns.article_id = na.article_id
  JOIN   rankalpha.dim_date d ON d.date_key = na.article_date
  WHERE  d.full_date >= (SELECT as_of_date FROM params) - interval '30 days'
     AND d.full_date <= (SELECT as_of_date FROM params)
  GROUP  BY na.stock_key
),
sentiment_latest AS (
  SELECT s.symbol,
         r.sentiment_score
  FROM (
    SELECT f.stock_key,
           f.score::numeric(14,2) AS sentiment_score,
           ROW_NUMBER() OVER (
             PARTITION BY f.stock_key
             ORDER BY f.date_key DESC, f.load_ts DESC, f.fact_id DESC
           ) AS rn
    FROM   rankalpha.fact_score_history f
    JOIN   rankalpha.dim_score_type t ON t.score_type_key = f.score_type_key
    JOIN   rankalpha.dim_date d ON d.date_key = f.date_key
    WHERE  t.score_type_name = 'sentiment score'
       AND d.full_date <= (SELECT as_of_date FROM params)
  ) r
  JOIN rankalpha.dim_stock s ON s.stock_key = r.stock_key
  WHERE r.rn = 1
),
base AS (
  SELECT
    (SELECT as_of_date FROM params)            AS as_of_date,
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
  FROM rankalpha.dim_stock st
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
FROM ranked
$$;

/* ------------------------------------------------------------
   6) Recreate mv_latest_grades to use fn_grades_as_of(latest_date)
   ------------------------------------------------------------ */
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_latest_grades;

CREATE MATERIALIZED VIEW rankalpha.mv_latest_grades AS
SELECT g.*
FROM rankalpha.fn_grades_as_of(
  (
    SELECT MAX(d.full_date)
    FROM   rankalpha.dim_date d
    JOIN   rankalpha.fact_score_history f ON f.date_key = d.date_key
  )
) AS g;

-- Indexes for the materialized view
CREATE UNIQUE INDEX IF NOT EXISTS mv_latest_grades_symbol_uidx
  ON rankalpha.mv_latest_grades (symbol);

CREATE INDEX IF NOT EXISTS mv_latest_grades_grade_order_idx
  ON rankalpha.mv_latest_grades (grade_order DESC, symbol);

CREATE INDEX IF NOT EXISTS mv_latest_grades_sector_idx
  ON rankalpha.mv_latest_grades (sector);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

