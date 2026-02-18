/* ------------------------------------------------------------
   V128__broker_trade_rec_unique.sql
   Idempotent broker export for portfolio engine runs.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- Broker-exported trade recommendations should be idempotent per (day, account, symbol, action).
-- We tag these rows with strategy_name='BROKER_RUN' to avoid constraining other ingestion paths.
CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_rec_broker_run
  ON rankalpha.fact_trade_recommendation (date_key, stock_key, source_key, action)
  WHERE strategy_name = 'BROKER_RUN';

