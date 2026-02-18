/* ------------------------------------------------------------
   V62__price_history_views.sql
   Views over fact_security_price for human‑readable history and
   latest adjusted closes (DB source of truth; no Parquet).
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- Drop if exist to make migration idempotent
DROP VIEW IF EXISTS rankalpha.vw_stock_price_history;
DROP VIEW IF EXISTS rankalpha.vw_latest_adj_close;

/*
  Human‑readable per‑day price history with adjusted close.
  - Uses total_return_factor to scale each row so the series matches
    “adjusted close” semantics (latest day equals close_px).
  - Default ordering is symbol, date DESC for readability when selected directly.
*/
CREATE OR REPLACE VIEW rankalpha.vw_stock_price_history AS
SELECT
  ds.symbol,
  ds.company_name,
  dd.full_date        AS price_date,
  sp.open_px          AS open_px,
  sp.high_px          AS high_px,
  sp.low_px           AS low_px,
  sp.close_px         AS close_px,
  CASE
    WHEN sp.total_return_factor IS NOT NULL AND sp.total_return_factor > 0
    THEN ROUND(sp.close_px * (
           FIRST_VALUE(sp.total_return_factor) OVER (
             PARTITION BY sp.stock_key
             ORDER BY sp.date_key DESC
             ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
           ) / sp.total_return_factor
         ), 4)
    ELSE sp.close_px
  END                 AS adj_close_px,
  sp.volume           AS volume
FROM   rankalpha.fact_security_price sp
JOIN   rankalpha.dim_date  dd ON dd.date_key  = sp.date_key
JOIN   rankalpha.dim_stock ds ON ds.stock_key = sp.stock_key
ORDER  BY ds.symbol, dd.full_date DESC;

/*
  Latest adjusted close per symbol (one row per active stock).
  - Uses DISTINCT ON with index (stock_key, date_key DESC) for efficiency.
  - Adjusted close at the latest date equals close_px by construction.
*/
CREATE OR REPLACE VIEW rankalpha.vw_latest_adj_close AS
SELECT DISTINCT ON (sp.stock_key)
  ds.symbol,
  ds.company_name,
  dd.full_date        AS price_date,
  sp.close_px         AS close_px,
  -- adj close equals close on the latest row, but compute consistently
  CASE
    WHEN sp.total_return_factor IS NOT NULL AND sp.total_return_factor > 0
    THEN ROUND(sp.close_px * (
           FIRST_VALUE(sp.total_return_factor) OVER (
             PARTITION BY sp.stock_key
             ORDER BY sp.date_key DESC
             ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
           ) / sp.total_return_factor
         ), 4)
    ELSE sp.close_px
  END                 AS adj_close_px
FROM   rankalpha.fact_security_price sp
JOIN   rankalpha.dim_date  dd ON dd.date_key  = sp.date_key
JOIN   rankalpha.dim_stock ds ON ds.stock_key = sp.stock_key
ORDER  BY sp.stock_key, sp.date_key DESC;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

