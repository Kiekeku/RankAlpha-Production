/* ------------------------------------------------------------
   V118__fix_grades_percentiles_and_sentiment_proxy.sql
   - Fix grade percentiles to rank only symbols with a non-NULL composite
     (Momentum + Value required; Sentiment optional with re-normalization).
   - Treat missing AI scenarios as missing sentiment (NULL), not neutral 0% ER.
   - Restrict sentiment proxy computation to symbols with AI coverage to reduce cost.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

/* ------------------------------------------------------------
   1) As-of sentiment proxy: latest AI per stock as-of p_asof,
      expected_return NULL when no scenario targets are present.
   ------------------------------------------------------------ */
CREATE OR REPLACE FUNCTION rankalpha.fn_sentiment_proxy_as_of(p_asof DATE)
RETURNS TABLE (
  symbol                 TEXT,
  px_date_key            INT,
  expected_return        NUMERIC,
  sentiment_proxy_score  NUMERIC(14,2)
) LANGUAGE sql STABLE AS $$
  WITH ranked_ai AS (
    SELECT a.*,
           ROW_NUMBER() OVER (
             PARTITION BY a.stock_key
             ORDER BY a.date_key DESC, a.load_ts DESC, a.analysis_id DESC
           ) AS rn
    FROM   rankalpha.fact_ai_stock_analysis a
    JOIN   rankalpha.dim_date d ON d.date_key = a.date_key
    WHERE  d.full_date <= p_asof
  ),
  latest_ai AS (
    SELECT analysis_id, stock_key
    FROM ranked_ai
    WHERE rn = 1
  ),
  scen AS (
    SELECT la.stock_key,
           MAX(CASE WHEN ps.scenario_type = 'bull' THEN ps.price_target END)       AS bull_target,
           MAX(CASE WHEN ps.scenario_type = 'base' THEN ps.price_target END)       AS base_target,
           MAX(CASE WHEN ps.scenario_type = 'bear' THEN ps.price_target END)       AS bear_target,
           MAX(CASE WHEN ps.scenario_type = 'bull' THEN ps.probability_pct END)   AS bull_prob,
           MAX(CASE WHEN ps.scenario_type = 'base' THEN ps.probability_pct END)   AS base_prob,
           MAX(CASE WHEN ps.scenario_type = 'bear' THEN ps.probability_pct END)   AS bear_prob
    FROM   latest_ai la
    JOIN   rankalpha.fact_ai_price_scenario ps ON ps.analysis_id = la.analysis_id
    GROUP  BY la.stock_key
  ),
  latest_px AS (
    SELECT sp.stock_key, MAX(sp.date_key) AS date_key
    FROM   rankalpha.fact_security_price sp
    JOIN   latest_ai la ON la.stock_key = sp.stock_key
    JOIN   rankalpha.dim_date d ON d.date_key = sp.date_key
    WHERE  d.full_date <= p_asof
    GROUP  BY sp.stock_key
  ),
  px AS (
    SELECT lp.stock_key, sp.date_key AS px_date_key, sp.close_px
    FROM   latest_px lp
    JOIN   rankalpha.fact_security_price sp
      ON   sp.stock_key = lp.stock_key
     AND   sp.date_key  = lp.date_key
  ),
  base AS (
    SELECT s.symbol,
           px.px_date_key,
           px.close_px,
           sc.bull_target, sc.base_target, sc.bear_target,
           sc.bull_prob, sc.base_prob, sc.bear_prob
    FROM   px
    JOIN   rankalpha.dim_stock s ON s.stock_key = px.stock_key
    LEFT   JOIN scen sc ON sc.stock_key = px.stock_key
  ),
  prob AS (
    SELECT symbol, px_date_key, close_px,
           bull_target, base_target, bear_target,
           (COALESCE(bull_prob,0) + COALESCE(base_prob,0) + COALESCE(bear_prob,0)) AS tot_prob,
           bull_prob, base_prob, bear_prob
    FROM base
  ),
  weights AS (
    SELECT symbol, px_date_key, close_px,
           bull_target, base_target, bear_target,
           CASE WHEN bull_target IS NOT NULL
                THEN CASE WHEN tot_prob > 0 THEN COALESCE(bull_prob,0)/tot_prob ELSE 0.2 END
                ELSE NULL END AS p_bull_raw,
           CASE WHEN base_target IS NOT NULL
                THEN CASE WHEN tot_prob > 0 THEN COALESCE(base_prob,0)/tot_prob ELSE 0.6 END
                ELSE NULL END AS p_base_raw,
           CASE WHEN bear_target IS NOT NULL
                THEN CASE WHEN tot_prob > 0 THEN COALESCE(bear_prob,0)/tot_prob ELSE 0.2 END
                ELSE NULL END AS p_bear_raw
    FROM prob
  ),
  weights2 AS (
    SELECT symbol, px_date_key, close_px,
           bull_target, base_target, bear_target,
           p_bull_raw, p_base_raw, p_bear_raw,
           (COALESCE(p_bull_raw,0) + COALESCE(p_base_raw,0) + COALESCE(p_bear_raw,0)) AS sum_raw
    FROM weights
  ),
  er AS (
    SELECT symbol, px_date_key,
           CASE
             WHEN close_px IS NULL OR close_px <= 0 THEN NULL
             WHEN sum_raw IS NULL OR sum_raw <= 0 THEN NULL
             ELSE
               (COALESCE((CASE WHEN p_bull_raw IS NOT NULL THEN (p_bull_raw/NULLIF(sum_raw,0)) * ((bull_target/close_px) - 1) END), 0.0)
              + COALESCE((CASE WHEN p_base_raw IS NOT NULL THEN (p_base_raw/NULLIF(sum_raw,0)) * ((base_target/close_px) - 1) END), 0.0)
              + COALESCE((CASE WHEN p_bear_raw IS NOT NULL THEN (p_bear_raw/NULLIF(sum_raw,0)) * ((bear_target/close_px) - 1) END), 0.0))
           END AS expected_return
    FROM weights2
  ),
  pcts AS (
    SELECT
      percentile_cont(0.05) WITHIN GROUP (ORDER BY expected_return) AS p05,
      percentile_cont(0.95) WITHIN GROUP (ORDER BY expected_return) AS p95
    FROM er
    WHERE expected_return IS NOT NULL
  )
  SELECT e.symbol,
         e.px_date_key,
         e.expected_return,
         CASE
           WHEN e.expected_return IS NULL THEN NULL
           WHEN (SELECT p95 FROM pcts) IS NULL OR (SELECT p05 FROM pcts) IS NULL OR (SELECT p95 FROM pcts) = (SELECT p05 FROM pcts)
             THEN 50.0::numeric(14,2)
           ELSE LEAST(100.0, GREATEST(0.0, ((e.expected_return - (SELECT p05 FROM pcts)) / NULLIF((SELECT p95 FROM pcts) - (SELECT p05 FROM pcts), 0)) * 100.0))::numeric(14,2)
         END AS sentiment_proxy_score
  FROM er e
$$;

/* ------------------------------------------------------------
   2) Latest sentiment proxy MV: restrict to AI-covered symbols and
      keep missing scenarios as NULL.
   ------------------------------------------------------------ */
-- mv_latest_grades depends on mv_sentiment_proxy; drop it first to avoid DROP errors.
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_latest_grades;

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_sentiment_proxy;
CREATE MATERIALIZED VIEW rankalpha.mv_sentiment_proxy AS
WITH ranked_ai AS (
  SELECT a.*,
         ROW_NUMBER() OVER (
           PARTITION BY a.stock_key
           ORDER BY a.date_key DESC, a.load_ts DESC, a.analysis_id DESC
         ) AS rn
  FROM rankalpha.fact_ai_stock_analysis a
),
latest_ai AS (
  SELECT analysis_id, stock_key
  FROM ranked_ai
  WHERE rn = 1
),
scen AS (
  SELECT la.stock_key,
         MAX(CASE WHEN ps.scenario_type = 'bull' THEN ps.price_target END)       AS bull_target,
         MAX(CASE WHEN ps.scenario_type = 'base' THEN ps.price_target END)       AS base_target,
         MAX(CASE WHEN ps.scenario_type = 'bear' THEN ps.price_target END)       AS bear_target,
         MAX(CASE WHEN ps.scenario_type = 'bull' THEN ps.probability_pct END)   AS bull_prob,
         MAX(CASE WHEN ps.scenario_type = 'base' THEN ps.probability_pct END)   AS base_prob,
         MAX(CASE WHEN ps.scenario_type = 'bear' THEN ps.probability_pct END)   AS bear_prob
  FROM latest_ai la
  JOIN rankalpha.fact_ai_price_scenario ps ON ps.analysis_id = la.analysis_id
  GROUP BY la.stock_key
),
latest_px AS (
  SELECT sp.stock_key, MAX(sp.date_key) AS px_date_key
  FROM rankalpha.fact_security_price sp
  JOIN latest_ai la ON la.stock_key = sp.stock_key
  GROUP BY sp.stock_key
),
px AS (
  SELECT lp.stock_key, sp.date_key AS px_date_key, sp.close_px
  FROM latest_px lp
  JOIN rankalpha.fact_security_price sp
    ON sp.stock_key = lp.stock_key AND sp.date_key = lp.px_date_key
),
base AS (
  SELECT s.symbol,
         px.px_date_key,
         px.close_px,
         sc.bull_target, sc.base_target, sc.bear_target,
         sc.bull_prob, sc.base_prob, sc.bear_prob
  FROM px
  JOIN rankalpha.dim_stock s ON s.stock_key = px.stock_key
  LEFT JOIN scen sc ON sc.stock_key = px.stock_key
),
prob AS (
  SELECT symbol, px_date_key, close_px,
         bull_target, base_target, bear_target,
         (COALESCE(bull_prob,0) + COALESCE(base_prob,0) + COALESCE(bear_prob,0)) AS tot_prob,
         bull_prob, base_prob, bear_prob
  FROM base
),
weights AS (
  SELECT symbol, px_date_key, close_px,
         bull_target, base_target, bear_target,
         CASE WHEN bull_target IS NOT NULL
              THEN CASE WHEN tot_prob > 0 THEN COALESCE(bull_prob,0)/tot_prob ELSE 0.2 END
              ELSE NULL END AS p_bull_raw,
         CASE WHEN base_target IS NOT NULL
              THEN CASE WHEN tot_prob > 0 THEN COALESCE(base_prob,0)/tot_prob ELSE 0.6 END
              ELSE NULL END AS p_base_raw,
         CASE WHEN bear_target IS NOT NULL
              THEN CASE WHEN tot_prob > 0 THEN COALESCE(bear_prob,0)/tot_prob ELSE 0.2 END
              ELSE NULL END AS p_bear_raw
  FROM prob
),
weights2 AS (
  SELECT symbol, px_date_key, close_px,
         bull_target, base_target, bear_target,
         p_bull_raw, p_base_raw, p_bear_raw,
         (COALESCE(p_bull_raw,0) + COALESCE(p_base_raw,0) + COALESCE(p_bear_raw,0)) AS sum_raw
  FROM weights
),
er AS (
  SELECT symbol, px_date_key,
         CASE
           WHEN close_px IS NULL OR close_px <= 0 THEN NULL
           WHEN sum_raw IS NULL OR sum_raw <= 0 THEN NULL
           ELSE
             (COALESCE((CASE WHEN p_bull_raw IS NOT NULL THEN (p_bull_raw/NULLIF(sum_raw,0)) * ((bull_target/close_px) - 1) END), 0.0)
            + COALESCE((CASE WHEN p_base_raw IS NOT NULL THEN (p_base_raw/NULLIF(sum_raw,0)) * ((base_target/close_px) - 1) END), 0.0)
            + COALESCE((CASE WHEN p_bear_raw IS NOT NULL THEN (p_bear_raw/NULLIF(sum_raw,0)) * ((bear_target/close_px) - 1) END), 0.0))
         END AS expected_return
  FROM weights2
),
pcts AS (
  SELECT
    percentile_cont(0.05) WITHIN GROUP (ORDER BY expected_return) AS p05,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY expected_return) AS p95
  FROM er
  WHERE expected_return IS NOT NULL
)
SELECT e.symbol,
       e.px_date_key,
       e.expected_return,
       CASE
         WHEN e.expected_return IS NULL THEN NULL
         WHEN (SELECT p95 FROM pcts) IS NULL OR (SELECT p05 FROM pcts) IS NULL OR (SELECT p95 FROM pcts) = (SELECT p05 FROM pcts)
           THEN 50.0
         ELSE LEAST(100.0, GREATEST(0.0, ((e.expected_return - (SELECT p05 FROM pcts)) / NULLIF((SELECT p95 FROM pcts) - (SELECT p05 FROM pcts), 0)) * 100.0))
       END::numeric(14,2) AS sentiment_proxy_score
FROM er e;

CREATE UNIQUE INDEX IF NOT EXISTS mv_sentiment_proxy_symbol_uidx
  ON rankalpha.mv_sentiment_proxy (symbol);

/* ------------------------------------------------------------
   3) Grades as-of: compute percentiles over eligible (non-NULL composite) only.
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
  ),
  scored AS (
    SELECT
      symbol,
      ROUND((CUME_DIST() OVER (ORDER BY composite_raw ASC) * 99.0 + 1.0)::numeric, 2)::numeric(14,2) AS avg_score
    FROM ranked
    WHERE composite_raw IS NOT NULL
  )
  SELECT
    r.as_of_date,
    r.symbol,
    r.company_name,
    r.sector,
    r.exchange,
    r.momentum_score,
    r.value_score,
    r.sentiment_score,
    s.avg_score,
    CASE
      WHEN s.avg_score >= 90 THEN 'A'
      WHEN s.avg_score >= 70 THEN 'B'
      WHEN s.avg_score >= 45 THEN 'C'
      WHEN s.avg_score >= 20 THEN 'D'
      WHEN s.avg_score IS NOT NULL THEN 'F'
      ELSE 'N/A'
    END AS grade,
    CASE
      WHEN s.avg_score >= 90 THEN 5
      WHEN s.avg_score >= 70 THEN 4
      WHEN s.avg_score >= 45 THEN 3
      WHEN s.avg_score >= 20 THEN 2
      WHEN s.avg_score IS NOT NULL THEN 1
      ELSE 0
    END AS grade_order
  FROM ranked r
  LEFT JOIN scored s USING (symbol)
$$;

/* ------------------------------------------------------------
   4) Latest grades MV: same percentile fix (exclude NULL composites).
   ------------------------------------------------------------ */
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_latest_grades;

CREATE MATERIALIZED VIEW rankalpha.mv_latest_grades AS
WITH latest AS (
  SELECT MAX(d.full_date) AS full_date
  FROM   rankalpha.dim_date d
  JOIN   rankalpha.fact_score_history f ON f.date_key = d.date_key
),
weights AS (
  SELECT w_m, w_v, w_s
  FROM   rankalpha.fn_model_weights_as_of('default', (SELECT full_date FROM latest))
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
    WHERE  t.score_type_name = 'momentum score'
  ) r
  JOIN rankalpha.dim_stock s ON s.stock_key = r.stock_key
  WHERE r.rn = 1
),
momentum_legacy AS (
  SELECT s.symbol,
         MAX(f.score)::numeric(14,2) AS momentum_raw
  FROM   rankalpha.fact_score_history f
  JOIN   latest l ON TRUE
  JOIN   rankalpha.dim_score_type t ON t.score_type_key = f.score_type_key
  JOIN   rankalpha.dim_date d ON d.date_key = f.date_key
  JOIN   rankalpha.dim_stock s ON s.stock_key = f.stock_key
  WHERE  t.score_type_name = 'linear regression 200'
     AND d.full_date = l.full_date
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
  FROM   rankalpha.vw_ai_analysis_latest
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
    WHERE  t.score_type_name = 'value score'
  ) r
  JOIN rankalpha.dim_stock s ON s.stock_key = r.stock_key
  WHERE r.rn = 1
),
sentiment_proxy AS (
  SELECT symbol, sentiment_proxy_score
  FROM   rankalpha.mv_sentiment_proxy
),
base AS (
  SELECT
    (SELECT full_date FROM latest) AS as_of_date,
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
),
scored AS (
  SELECT
    symbol,
    ROUND((CUME_DIST() OVER (ORDER BY composite_raw ASC) * 99.0 + 1.0)::numeric, 2)::numeric(14,2) AS avg_score
  FROM ranked
  WHERE composite_raw IS NOT NULL
)
SELECT
  r.as_of_date,
  r.symbol,
  r.company_name,
  r.sector,
  r.exchange,
  r.momentum_score,
  r.value_score,
  r.sentiment_score,
  s.avg_score,
  CASE
    WHEN s.avg_score >= 90 THEN 'A'
    WHEN s.avg_score >= 70 THEN 'B'
    WHEN s.avg_score >= 45 THEN 'C'
    WHEN s.avg_score >= 20 THEN 'D'
    WHEN s.avg_score IS NOT NULL THEN 'F'
    ELSE 'N/A'
  END AS grade,
  CASE
    WHEN s.avg_score >= 90 THEN 5
    WHEN s.avg_score >= 70 THEN 4
    WHEN s.avg_score >= 45 THEN 3
    WHEN s.avg_score >= 20 THEN 2
    WHEN s.avg_score IS NOT NULL THEN 1
    ELSE 0
  END AS grade_order
FROM ranked r
LEFT JOIN scored s USING (symbol);

CREATE UNIQUE INDEX IF NOT EXISTS mv_latest_grades_symbol_uidx
  ON rankalpha.mv_latest_grades (symbol);

CREATE INDEX IF NOT EXISTS mv_latest_grades_grade_order_idx
  ON rankalpha.mv_latest_grades (grade_order DESC, symbol);

CREATE INDEX IF NOT EXISTS mv_latest_grades_sector_idx
  ON rankalpha.mv_latest_grades (sector);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
