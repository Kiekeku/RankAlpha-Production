/* ------------------------------------------------------------
   V119__optimize_latest_adj_close_and_ai_proximity.sql
   - vw_latest_adj_close: remove unnecessary window computation (latest adj == close).
   - vw_ai_scenario_proximity: source latest analyses from vw_ai_analysis_latest and use
     per-symbol lateral price lookup to avoid rescanning full analysis/history tables.
   - Refresh dependent materialized views.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

/* ------------------------------------------------------------
   1) Latest adjusted close: latest row's adj_close == close by construction.
   ------------------------------------------------------------ */
CREATE OR REPLACE VIEW rankalpha.vw_latest_adj_close AS
SELECT DISTINCT ON (sp.stock_key)
  ds.symbol,
  ds.company_name,
  dd.full_date        AS price_date,
  sp.close_px         AS close_px,
  sp.close_px::numeric AS adj_close_px
FROM   rankalpha.fact_security_price sp
JOIN   rankalpha.dim_date  dd ON dd.date_key  = sp.date_key
JOIN   rankalpha.dim_stock ds ON ds.stock_key = sp.stock_key
ORDER  BY sp.stock_key, sp.date_key DESC;

/* ------------------------------------------------------------
   2) Scenario proximity: use vw_ai_analysis_latest + indexed LATERAL lookup for latest price.
   ------------------------------------------------------------ */
CREATE OR REPLACE VIEW rankalpha.vw_ai_scenario_proximity AS
WITH latest AS (
  SELECT
    v.analysis_id,
    v.symbol,
    v.date_key AS analysis_date_key
  FROM rankalpha.vw_ai_analysis_latest v
),
scen AS (
  SELECT
    la.analysis_id,
    MAX(CASE WHEN ps.scenario_type = 'bull' THEN ps.price_target END)       AS bull_target,
    MAX(CASE WHEN ps.scenario_type = 'base' THEN ps.price_target END)       AS base_target,
    MAX(CASE WHEN ps.scenario_type = 'bear' THEN ps.price_target END)       AS bear_target,
    MAX(CASE WHEN ps.scenario_type = 'bull' THEN ps.probability_pct END)   AS bull_prob,
    MAX(CASE WHEN ps.scenario_type = 'base' THEN ps.probability_pct END)   AS base_prob,
    MAX(CASE WHEN ps.scenario_type = 'bear' THEN ps.probability_pct END)   AS bear_prob
  FROM latest la
  JOIN rankalpha.fact_ai_price_scenario ps ON ps.analysis_id = la.analysis_id
  GROUP BY la.analysis_id
),
px AS (
  SELECT
    la.analysis_id,
    la.symbol,
    p.date_key AS px_date_key,
    p.close_px
  FROM latest la
  JOIN rankalpha.dim_stock s ON s.symbol = la.symbol
  JOIN LATERAL (
    SELECT sp.date_key, sp.close_px
    FROM rankalpha.fact_security_price sp
    WHERE sp.stock_key = s.stock_key
    ORDER BY sp.date_key DESC
    LIMIT 1
  ) p ON TRUE
),
base AS (
  SELECT
    la.analysis_id,
    la.symbol,
    la.analysis_date_key,
    px.px_date_key,
    px.close_px,
    sc.bull_target, sc.base_target, sc.bear_target,
    sc.bull_prob, sc.base_prob, sc.bear_prob
  FROM latest la
  LEFT JOIN px   ON px.analysis_id = la.analysis_id
  LEFT JOIN scen sc ON sc.analysis_id = la.analysis_id
),
deltas AS (
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
   3) Refresh dependent materialized views.
   ------------------------------------------------------------ */
REFRESH MATERIALIZED VIEW rankalpha.mv_ai_scenario_proximity;
REFRESH MATERIALIZED VIEW rankalpha.mv_ai_analysis_latest_list;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
