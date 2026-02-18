/* ------------------------------------------------------------
   V60__ai_scenario_proximity_view.sql
   View: vw_ai_scenario_proximity → nearest scenario vs latest close
   - Computes signed deltas to bull/base/bear targets for the latest AI analysis
   - Picks nearest scenario by absolute % delta; tie-break by higher probability, then base > bull > bear
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

DROP VIEW IF EXISTS rankalpha.vw_ai_scenario_proximity;
CREATE OR REPLACE VIEW rankalpha.vw_ai_scenario_proximity AS
WITH ranked AS (
  SELECT
    v.analysis_id,
    ROW_NUMBER() OVER (
      PARTITION BY v.symbol
      ORDER BY v.date_key DESC, v.load_ts DESC, v.analysis_id DESC
    ) AS rn
  FROM rankalpha.vw_ai_analysis_full v
), latest AS (
  SELECT v.*
  FROM rankalpha.vw_ai_analysis_full v
  JOIN ranked r ON r.analysis_id = v.analysis_id
  WHERE r.rn = 1
), scen AS (
  SELECT
    la.analysis_id,
    MAX(CASE WHEN ps.scenario_type = 'bull' THEN ps.price_target END) AS bull_target,
    MAX(CASE WHEN ps.scenario_type = 'base' THEN ps.price_target END) AS base_target,
    MAX(CASE WHEN ps.scenario_type = 'bear' THEN ps.price_target END) AS bear_target,
    MAX(CASE WHEN ps.scenario_type = 'bull' THEN ps.probability_pct END) AS bull_prob,
    MAX(CASE WHEN ps.scenario_type = 'base' THEN ps.probability_pct END) AS base_prob,
    MAX(CASE WHEN ps.scenario_type = 'bear' THEN ps.probability_pct END) AS bear_prob
  FROM latest la
  JOIN rankalpha.fact_ai_price_scenario ps ON ps.analysis_id = la.analysis_id
  GROUP BY la.analysis_id
), latest_px AS (
  SELECT sp.stock_key, MAX(sp.date_key) AS px_date_key
  FROM rankalpha.fact_security_price sp
  GROUP BY sp.stock_key
), px AS (
  SELECT s.symbol, lp.px_date_key, sp.close_px
  FROM latest_px lp
  JOIN rankalpha.fact_security_price sp
    ON sp.stock_key = lp.stock_key AND sp.date_key = lp.px_date_key
  JOIN rankalpha.dim_stock s ON s.stock_key = lp.stock_key
), base AS (
  SELECT la.analysis_id, la.symbol, la.date_key AS analysis_date_key,
         px.px_date_key, px.close_px,
         sc.bull_target, sc.base_target, sc.bear_target,
         sc.bull_prob, sc.base_prob, sc.bear_prob
  FROM latest la
  LEFT JOIN px ON px.symbol = la.symbol
  LEFT JOIN scen sc ON sc.analysis_id = la.analysis_id
), deltas AS (
  SELECT
    b.*,
    CASE WHEN close_px IS NOT NULL AND close_px > 0 AND bull_target IS NOT NULL
         THEN ((bull_target/close_px) - 1) * 100 ELSE NULL END AS delta_bull_pct,
    CASE WHEN close_px IS NOT NULL AND close_px > 0 AND base_target IS NOT NULL
         THEN ((base_target/close_px) - 1) * 100 ELSE NULL END AS delta_base_pct,
    CASE WHEN close_px IS NOT NULL AND close_px > 0 AND bear_target IS NOT NULL
         THEN ((bear_target/close_px) - 1) * 100 ELSE NULL END AS delta_bear_pct
  FROM base b
)
SELECT
  d.analysis_id,
  d.symbol,
  d.px_date_key,
  dd.full_date AS price_date,
  d.close_px,
  d.delta_bull_pct,
  d.delta_base_pct,
  d.delta_bear_pct,
  near.scenario AS nearest_scenario,
  near.abs_delta AS nearest_distance_pct
FROM deltas d
LEFT JOIN rankalpha.dim_date dd ON dd.date_key = d.px_date_key
LEFT JOIN LATERAL (
  SELECT s.scenario, ABS(s.delta) AS abs_delta
  FROM (
    VALUES
      ('bull', d.delta_bull_pct, d.bull_prob),
      ('base', d.delta_base_pct, d.base_prob),
      ('bear', d.delta_bear_pct, d.bear_prob)
  ) AS s(scenario, delta, prob)
  WHERE s.delta IS NOT NULL
  ORDER BY ABS(s.delta) ASC, COALESCE(s.prob, 0) DESC,
           CASE WHEN s.scenario = 'base' THEN 0 WHEN s.scenario = 'bull' THEN 1 ELSE 2 END
  LIMIT 1
) near ON TRUE;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

