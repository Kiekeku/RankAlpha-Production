/* ------------------------------------------------------------
   V71__universe_policy_table_and_mv_update.sql
   - Add rankalpha.universe_policy table with tunable thresholds
   - Seed initial 'default' policy (include ETFs)
   - Recreate mv_universe_eligible to use the policy table (no hardcoded constants)
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE TABLE IF NOT EXISTS rankalpha.universe_policy (
  policy_code         text PRIMARY KEY,
  min_price           numeric(20,4) NOT NULL DEFAULT 3.0,
  min_addv30_usd      numeric(20,2) NOT NULL DEFAULT 1000000,
  min_vol30_sh        numeric(20,2) NOT NULL DEFAULT 50000,
  min_bars_22         integer       NOT NULL DEFAULT 15,
  allowed_asset_types text[]        NOT NULL DEFAULT ARRAY['equity','etf'],
  exclude_exchanges   text[]        NOT NULL DEFAULT ARRAY['OTC%','OTCQB%','OTCMKTS%','PINK%'],
  updated_at          timestamptz   NOT NULL DEFAULT now()
);

INSERT INTO rankalpha.universe_policy(policy_code)
VALUES ('default')
ON CONFLICT (policy_code) DO NOTHING;

-- Recreate MV to use policy
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_universe_eligible;

CREATE MATERIALIZED VIEW rankalpha.mv_universe_eligible AS
WITH pol AS (
  SELECT * FROM rankalpha.universe_policy WHERE policy_code = 'default' LIMIT 1
), latest AS (
  SELECT MAX(d.full_date) AS latest_date
  FROM   fact_security_price s
  JOIN   dim_date d ON d.date_key = s.date_key
), d30 AS (
  SELECT d.date_key
  FROM   dim_date d, latest l
  WHERE  d.full_date <= l.latest_date
  ORDER  BY d.full_date DESC
  LIMIT  30
), d22 AS (
  SELECT d.date_key
  FROM   dim_date d, latest l
  WHERE  d.full_date <= l.latest_date
  ORDER  BY d.full_date DESC
  LIMIT  22
), base30 AS (
  SELECT ds.stock_key,
         ds.symbol,
         ds.exchange,
         COALESCE(at.asset_type_name, 'equity') AS asset_type,
         (s.close_px)::numeric(20,4)                      AS close_px,
         (s.volume)::numeric                              AS vol,
         ((s.close_px)::numeric(20,4) * (s.volume)::numeric) AS dollar_vol
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
LEFT JOIN bars b   ON b.stock_key = m.stock_key
LEFT JOIN latest_px lp ON lp.stock_key = m.stock_key;

CREATE UNIQUE INDEX IF NOT EXISTS mv_universe_eligible_symbol_uidx
  ON rankalpha.mv_universe_eligible (symbol);

CREATE INDEX IF NOT EXISTS mv_universe_eligible_eligible_idx
  ON rankalpha.mv_universe_eligible (eligible);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
