/* ------------------------------------------------------------
   V125__portfolio_broker_nlv.sql
   - Store broker-reported Net Liquidation Value (NLV) snapshots.
   - This is separate from fact_portfolio_nav (which may be reconstructed).
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE TABLE IF NOT EXISTS rankalpha.fact_portfolio_broker_nlv (
  date_key        INT  NOT NULL REFERENCES rankalpha.dim_date(date_key),
  portfolio_id    UUID NOT NULL REFERENCES rankalpha.portfolio(portfolio_id) ON DELETE CASCADE,
  currency_code   CHAR(3) NOT NULL DEFAULT 'USD',
  nlv_base_ccy    NUMERIC(20,4) NOT NULL,
  gross_leverage  NUMERIC(6,2),
  source_system   TEXT,
  load_ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (date_key, portfolio_id)
);

CREATE INDEX IF NOT EXISTS ix_broker_nlv_portfolio_date
  ON rankalpha.fact_portfolio_broker_nlv (portfolio_id, date_key DESC);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

