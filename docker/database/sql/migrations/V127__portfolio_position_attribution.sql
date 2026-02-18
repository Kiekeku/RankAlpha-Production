/* ------------------------------------------------------------
   V127__portfolio_position_attribution.sql
   - Daily per-position attribution for BROKER portfolios
   - Close-to-close, using prior-day holdings snapshot and FX conversion
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE TABLE IF NOT EXISTS rankalpha.fact_portfolio_position_attribution (
  date_key int NOT NULL REFERENCES rankalpha.dim_date(date_key),
  portfolio_id uuid NOT NULL REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,
  stock_key int NOT NULL REFERENCES rankalpha.dim_stock(stock_key),

  qty_prev numeric(20,4) NOT NULL,
  qty_end numeric(20,4) NULL,

  close_prev_local numeric(20,4) NULL,
  close_local numeric(20,4) NULL,

  fx_prev numeric(18,8) NULL,
  fx numeric(18,8) NULL,

  close_prev_base numeric(20,4) NULL,
  close_base numeric(20,4) NULL,

  market_value_prev_base numeric(20,4) NULL,
  pnl_base numeric(20,4) NULL,

  return_base numeric(12,6) NULL,
  weight_prev_pct numeric(12,6) NULL,
  contribution_pct numeric(12,6) NULL,

  methodology text NOT NULL DEFAULT 'CLOSE_TO_CLOSE_QTY_PREV',
  load_ts timestamptz NOT NULL DEFAULT now(),

  PRIMARY KEY (date_key, portfolio_id, stock_key)
);

CREATE INDEX IF NOT EXISTS ix_pos_attrib_portfolio_date
  ON rankalpha.fact_portfolio_position_attribution (portfolio_id, date_key DESC);

CREATE OR REPLACE VIEW rankalpha.vw_portfolio_position_attribution AS
SELECT
  a.date_key,
  d.full_date,
  a.portfolio_id,
  p.portfolio_name,
  a.stock_key,
  s.symbol,
  s.company_name,
  a.qty_prev,
  a.qty_end,
  a.close_prev_local,
  a.close_local,
  a.close_prev_base,
  a.close_base,
  a.market_value_prev_base,
  a.pnl_base,
  a.return_base,
  a.weight_prev_pct,
  a.contribution_pct,
  a.methodology,
  a.load_ts
FROM rankalpha.fact_portfolio_position_attribution a
JOIN rankalpha.dim_date d ON d.date_key = a.date_key
JOIN rankalpha.portfolio p ON p.portfolio_id = a.portfolio_id
JOIN rankalpha.dim_stock s ON s.stock_key = a.stock_key;

