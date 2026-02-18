/* ------------------------------------------------------------
   V82__mv_ai_analysis_latest_list.sql
   - Materialized view for frontend AI Analysis list pagination.
   - Precomputes lightweight fields from vw_ai_analysis_latest plus
     proximity metrics to avoid recomputing wide JSON aggregates.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_ai_analysis_latest_list;
CREATE MATERIALIZED VIEW rankalpha.mv_ai_analysis_latest_list AS
SELECT
    v.analysis_id,
    v.date_key,
    v.as_of_date,
    v.symbol,
    v.company_name,
    v.asset_type,
    v.overall_rating,
    v.confidence,
    v.commentary,
    v.bull_price_target,
    v.bull_probability_pct,
    v.base_price_target,
    v.base_probability_pct,
    v.bear_price_target,
    v.bear_probability_pct,
    prox.price_date,
    prox.close_px,
    prox.delta_bull_pct,
    prox.delta_base_pct,
    prox.delta_bear_pct,
    prox.nearest_scenario,
    prox.nearest_distance_pct,
    v.load_ts
FROM rankalpha.vw_ai_analysis_latest v
LEFT JOIN rankalpha.mv_ai_scenario_proximity prox
       ON prox.analysis_id = v.analysis_id
WITH NO DATA;

-- Indexes to support CONCURRENT refresh + common sort orders.
CREATE UNIQUE INDEX IF NOT EXISTS mv_ai_analysis_latest_list_pk
  ON rankalpha.mv_ai_analysis_latest_list (analysis_id);

CREATE INDEX IF NOT EXISTS mv_ai_analysis_latest_list_date_idx
  ON rankalpha.mv_ai_analysis_latest_list (as_of_date DESC, analysis_id);

CREATE INDEX IF NOT EXISTS mv_ai_analysis_latest_list_symbol_idx
  ON rankalpha.mv_ai_analysis_latest_list (symbol, as_of_date DESC);

-- Initial population
REFRESH MATERIALIZED VIEW rankalpha.mv_ai_analysis_latest_list;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
