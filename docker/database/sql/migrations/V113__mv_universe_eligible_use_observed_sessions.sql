/* ------------------------------------------------------------
   V113__mv_universe_eligible_use_observed_sessions.sql
   - Fix mv_universe_eligible to use observed price sessions for:
     - med_addv_30_usd / med_vol_30_sh (last 30 trading days)
     - bars_22 (last 22 trading days)
   - This prevents min_bars_22 from inadvertently failing for every symbol
     when dim_date trading flags are unset/stale.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- mv_universe_eligible is referenced by other materialized views (e.g., mv_screener_scores_latest).
-- Preserve current definitions, drop dependents, rebuild mv_universe_eligible, then recreate dependents.
DROP TABLE IF EXISTS ra_tmp_viewdefs;
CREATE TEMP TABLE ra_tmp_viewdefs (
  name text PRIMARY KEY,
  def  text NOT NULL
);

INSERT INTO pg_temp.ra_tmp_viewdefs(name, def)
SELECT 'mv_screener_scores_latest', pg_get_viewdef('rankalpha.mv_screener_scores_latest'::regclass, true)
WHERE to_regclass('rankalpha.mv_screener_scores_latest') IS NOT NULL;

INSERT INTO pg_temp.ra_tmp_viewdefs(name, def)
SELECT 'v_latest_screener_consensus', pg_get_viewdef('rankalpha.v_latest_screener_consensus'::regclass, true)
WHERE to_regclass('rankalpha.v_latest_screener_consensus') IS NOT NULL;

-- Drop known dependents first to avoid DROP ... CASCADE (which can remove unrelated objects).
DROP VIEW IF EXISTS rankalpha.v_latest_screener_consensus;
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_screener_scores_latest;

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_universe_eligible;

CREATE MATERIALIZED VIEW rankalpha.mv_universe_eligible AS
WITH pol AS (
  SELECT * FROM rankalpha.universe_policy WHERE policy_code = 'default' LIMIT 1
), d30 AS (
  -- Use the last 30 observed price sessions (robust even if dim_date trading flags are stale).
  SELECT date_key
  FROM (
    SELECT DISTINCT s.date_key
    FROM   fact_security_price s
    ORDER  BY s.date_key DESC
    LIMIT  30
  ) x
), d22 AS (
  -- Use the last 22 observed price sessions (robust even if dim_date trading flags are stale).
  SELECT date_key
  FROM (
    SELECT DISTINCT s.date_key
    FROM   fact_security_price s
    ORDER  BY s.date_key DESC
    LIMIT  22
  ) x
), base30 AS (
  SELECT ds.stock_key,
         ds.symbol,
         ds.exchange,
         COALESCE(at.asset_type_name, 'equity') AS asset_type,
         (s.close_px)::numeric(20,4)                          AS close_px,
         (s.volume)::numeric                                   AS vol,
         ((s.close_px)::numeric(20,4) * (s.volume)::numeric)   AS dollar_vol
  FROM   dim_stock ds
  LEFT   JOIN dim_asset_type at ON at.asset_type_key = ds.asset_type_key
  JOIN   fact_security_price s ON s.stock_key = ds.stock_key
  JOIN   d30 ON d30.date_key = s.date_key
  WHERE  ds.is_active IS TRUE
), med AS (
  SELECT stock_key,
         symbol,
         exchange,
         asset_type,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY dollar_vol) AS med_addv_30_usd,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY vol)        AS med_vol_30_sh
  FROM   base30
  GROUP  BY stock_key, symbol, exchange, asset_type
), bars AS (
  SELECT ds.stock_key,
         COUNT(*) AS bars_22
  FROM   dim_stock ds
  JOIN   fact_security_price s ON s.stock_key = ds.stock_key
  JOIN   d22 ON d22.date_key = s.date_key
  WHERE  ds.is_active IS TRUE
  GROUP  BY ds.stock_key
), latest_px AS (
  SELECT ds.stock_key,
         ds.symbol,
         v.adj_close_px AS latest_adj_close
  FROM   vw_latest_adj_close v
  JOIN   dim_stock ds ON ds.symbol = v.symbol
)
SELECT
  m.symbol,
  m.stock_key,
  m.exchange,
  m.asset_type,
  lp.latest_adj_close,
  m.med_addv_30_usd,
  m.med_vol_30_sh,
  COALESCE(b.bars_22, 0) AS bars_22,
  CASE
    WHEN (SELECT EXISTS (SELECT 1 FROM pol)) IS NOT TRUE THEN FALSE
    WHEN EXISTS (
           SELECT 1
           FROM unnest((SELECT exclude_exchanges FROM pol)) AS pat(pattern)
           WHERE m.exchange ILIKE pat.pattern
         ) THEN FALSE
    WHEN NOT EXISTS (
           SELECT 1
           FROM unnest((SELECT allowed_asset_types FROM pol)) AS at(type)
           WHERE m.asset_type = at.type
         ) THEN FALSE
    WHEN lp.latest_adj_close IS NULL OR lp.latest_adj_close < (SELECT min_price FROM pol) THEN FALSE
    WHEN m.med_addv_30_usd IS NULL OR m.med_addv_30_usd < (SELECT min_addv30_usd FROM pol) THEN FALSE
    WHEN m.med_vol_30_sh IS NULL OR m.med_vol_30_sh < (SELECT min_vol30_sh FROM pol) THEN FALSE
    WHEN COALESCE(b.bars_22, 0) < (SELECT min_bars_22 FROM pol) THEN FALSE
    ELSE TRUE
  END AS eligible
FROM med m
LEFT JOIN bars b      ON b.stock_key = m.stock_key
LEFT JOIN latest_px lp ON lp.stock_key = m.stock_key;

CREATE UNIQUE INDEX IF NOT EXISTS mv_universe_eligible_symbol_uidx
  ON rankalpha.mv_universe_eligible (symbol);

CREATE INDEX IF NOT EXISTS mv_universe_eligible_eligible_idx
  ON rankalpha.mv_universe_eligible (eligible);

-- Recreate dependents from captured definitions.
DO $$
DECLARE
  mv_def text;
  view_def text;
BEGIN
  SELECT def INTO mv_def FROM pg_temp.ra_tmp_viewdefs WHERE name = 'mv_screener_scores_latest';
  IF mv_def IS NOT NULL THEN
    EXECUTE 'CREATE MATERIALIZED VIEW rankalpha.mv_screener_scores_latest AS ' || mv_def;
    EXECUTE 'CREATE UNIQUE INDEX mv_screener_scores_latest_pk ON rankalpha.mv_screener_scores_latest (as_of_date, symbol)';
  END IF;

  SELECT def INTO view_def FROM pg_temp.ra_tmp_viewdefs WHERE name = 'v_latest_screener_consensus';
  IF view_def IS NOT NULL THEN
    EXECUTE 'CREATE VIEW rankalpha.v_latest_screener_consensus AS ' || view_def;
  END IF;
END $$;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
