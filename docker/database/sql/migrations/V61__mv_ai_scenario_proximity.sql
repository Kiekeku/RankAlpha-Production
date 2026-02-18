/* ------------------------------------------------------------
   V61__mv_ai_scenario_proximity.sql
   Materialize proximity for latest AI analysis per symbol.

   - Creates rankalpha.mv_ai_scenario_proximity as a cached snapshot of
     rankalpha.vw_ai_scenario_proximity.
   - Adds a UNIQUE index on (analysis_id) so we can REFRESH CONCURRENTLY.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_ai_scenario_proximity;
CREATE MATERIALIZED VIEW rankalpha.mv_ai_scenario_proximity AS
SELECT * FROM rankalpha.vw_ai_scenario_proximity;

-- Unique index required for CONCURRENT refreshes
CREATE UNIQUE INDEX IF NOT EXISTS mv_ai_scenario_proximity_pk
  ON rankalpha.mv_ai_scenario_proximity (analysis_id);

-- Helpful secondary index for symbol lookups (optional)
CREATE INDEX IF NOT EXISTS mv_ai_scenario_proximity_symbol_idx
  ON rankalpha.mv_ai_scenario_proximity (symbol);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

