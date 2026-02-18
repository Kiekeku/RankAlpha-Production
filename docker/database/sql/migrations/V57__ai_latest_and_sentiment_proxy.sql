/* ------------------------------------------------------------
   V57__ai_latest_and_sentiment_proxy.sql
   - View: vw_ai_analysis_latest  → latest AI analysis per symbol
   - Materialized View: mv_sentiment_proxy → scenario-based ER → 0..100 sentiment proxy
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- 1) Latest AI analysis per symbol (stable tie-breaks)
DROP VIEW IF EXISTS rankalpha.vw_ai_analysis_latest;
CREATE OR REPLACE VIEW rankalpha.vw_ai_analysis_latest AS
WITH ranked AS (
  SELECT
    v.analysis_id,
    ROW_NUMBER() OVER (
      PARTITION BY v.symbol
      ORDER BY v.date_key DESC, v.load_ts DESC, v.analysis_id DESC
    ) AS rn
  FROM rankalpha.vw_ai_analysis_full v
)
SELECT v.*
FROM rankalpha.vw_ai_analysis_full v
JOIN ranked r ON r.analysis_id = v.analysis_id
WHERE r.rn = 1;

-- 2) Scenario-based sentiment proxy (materialized)
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_sentiment_proxy;
CREATE MATERIALIZED VIEW rankalpha.mv_sentiment_proxy AS
WITH ranked_ai AS (
  SELECT a.*, ROW_NUMBER() OVER (
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
         MAX(CASE WHEN ps.scenario_type = 'bull' THEN ps.price_target END) AS bull_target,
         MAX(CASE WHEN ps.scenario_type = 'base' THEN ps.price_target END) AS base_target,
         MAX(CASE WHEN ps.scenario_type = 'bear' THEN ps.price_target END) AS bear_target,
         MAX(CASE WHEN ps.scenario_type = 'bull' THEN ps.probability_pct END) AS bull_prob,
         MAX(CASE WHEN ps.scenario_type = 'base' THEN ps.probability_pct END) AS base_prob,
         MAX(CASE WHEN ps.scenario_type = 'bear' THEN ps.probability_pct END) AS bear_prob
  FROM latest_ai la
  JOIN rankalpha.fact_ai_price_scenario ps ON ps.analysis_id = la.analysis_id
  GROUP BY la.stock_key
),
latest_px AS (
  SELECT sp.stock_key, MAX(sp.date_key) AS px_date_key
  FROM rankalpha.fact_security_price sp
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
         CASE WHEN close_px IS NULL OR close_px <= 0 THEN NULL ELSE
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
   END OF FILE
   ------------------------------------------------------------ */
