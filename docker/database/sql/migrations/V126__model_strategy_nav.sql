/* ------------------------------------------------------------
   V126__model_strategy_nav.sql
   - Daily NAV time series per (MODEL portfolio, source, strategy)
   - Supports strategy-level performance attribution for model portfolios
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE TABLE IF NOT EXISTS rankalpha.fact_model_strategy_nav (
  date_key int NOT NULL REFERENCES rankalpha.dim_date(date_key),
  model_portfolio_id uuid NOT NULL
    REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,
  source_key int4 NOT NULL
    REFERENCES rankalpha.dim_source(source_key),
  strategy_name varchar(50) NOT NULL,
  nav_base_ccy numeric(20,4) NOT NULL,
  load_ts timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (date_key, model_portfolio_id, source_key, strategy_name)
);

CREATE INDEX IF NOT EXISTS ix_model_strategy_nav_portfolio_date
  ON rankalpha.fact_model_strategy_nav (model_portfolio_id, date_key DESC);

CREATE OR REPLACE VIEW rankalpha.vw_model_strategy_performance AS
SELECT
  nav.date_key,
  d.full_date,
  nav.model_portfolio_id AS portfolio_id,
  p.portfolio_name,
  nav.source_key,
  src.source_name,
  nav.strategy_name,
  nav.nav_base_ccy,
  LAG(nav.nav_base_ccy) OVER (
    PARTITION BY nav.model_portfolio_id, nav.source_key, nav.strategy_name
    ORDER BY nav.date_key
  ) AS nav_prev,
  (nav.nav_base_ccy /
   LAG(nav.nav_base_ccy) OVER (
     PARTITION BY nav.model_portfolio_id, nav.source_key, nav.strategy_name
     ORDER BY nav.date_key
   ) - 1) AS daily_return
FROM rankalpha.fact_model_strategy_nav nav
JOIN rankalpha.portfolio p
  ON p.portfolio_id = nav.model_portfolio_id
JOIN rankalpha.dim_date d
  ON d.date_key = nav.date_key
JOIN rankalpha.dim_source src
  ON src.source_key = nav.source_key;

