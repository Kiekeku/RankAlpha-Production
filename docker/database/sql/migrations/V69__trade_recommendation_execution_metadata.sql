-- -------------------------------------------------------------------------------------------------
--  RankAlpha : FACT_TRADE_RECOMMENDATION – execution metadata extensions
--  • Adds structured order fields so trading systems can automate fills
--  • Updates the human-readable view to expose the new columns
--  • Idempotent and backfills existing rows with sensible defaults
-- -------------------------------------------------------------------------------------------------
SET search_path = rankalpha;

ALTER TABLE rankalpha.fact_trade_recommendation
    ADD COLUMN IF NOT EXISTS order_type           VARCHAR(16) NOT NULL DEFAULT 'MARKET',
    ADD COLUMN IF NOT EXISTS time_in_force        VARCHAR(12) NOT NULL DEFAULT 'DAY',
    ADD COLUMN IF NOT EXISTS valid_from_ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS expiry_ts            TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS portfolio_id         UUID REFERENCES rankalpha.portfolio(portfolio_id),
    ADD COLUMN IF NOT EXISTS limit_price          NUMERIC(20,4),
    ADD COLUMN IF NOT EXISTS stop_trigger_price   NUMERIC(20,4),
    ADD COLUMN IF NOT EXISTS routing_hint         VARCHAR(32),
    ADD COLUMN IF NOT EXISTS risk_budget_bps      NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS signal_version       VARCHAR(20),
    ADD COLUMN IF NOT EXISTS model_run_id         UUID,
    ADD COLUMN IF NOT EXISTS preconditions        JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS auto_hedge           BOOLEAN NOT NULL DEFAULT FALSE;

-- Align the new validity start with the original record creation timestamp
UPDATE rankalpha.fact_trade_recommendation
   SET valid_from_ts = COALESCE(valid_from_ts, create_ts)
 WHERE valid_from_ts IS DISTINCT FROM create_ts;

COMMENT ON COLUMN rankalpha.fact_trade_recommendation.order_type
  IS 'Execution style for the entry (MARKET, LIMIT, STOP, etc.)';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.time_in_force
  IS 'Broker time-in-force directive (DAY, GTC, IOC, ...).';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.valid_from_ts
  IS 'Timestamp when the recommendation becomes actionable.';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.expiry_ts
  IS 'Timestamp when the recommendation should be considered stale.';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.portfolio_id
  IS 'Optional portfolio sleeve that should own the trade.';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.limit_price
  IS 'Explicit limit price for limit/stop-limit orders.';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.stop_trigger_price
  IS 'Trigger price for stop/stop-limit style entries.';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.routing_hint
  IS 'Preferred venue or algorithm routing hint.';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.risk_budget_bps
  IS 'Risk budget allocated to the trade, in basis points.';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.signal_version
  IS 'Version string for the originating model or signal template.';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.model_run_id
  IS 'Identifier for the model run that produced the signal.';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.preconditions
  IS 'JSON blob capturing execution preconditions (e.g., spread, liquidity).';
COMMENT ON COLUMN rankalpha.fact_trade_recommendation.auto_hedge
  IS 'Whether the OMS should trigger an automatic hedge after fill.';

CREATE OR REPLACE VIEW rankalpha.vw_trade_recommendation (
    recommendation_id,
    recommendation_date,
    symbol,
    exchange,
    asset_type,
    source_name,
    source_version,
    action,
    recommended_price,
    stop_loss_price,
    take_profit_price,
    size_shares,
    size_percent,
    confidence_label,
    timeframe_label,
    strategy_name,
    description,
    is_live,
    filled_price,
    filled_date,
    create_ts,
    update_ts,
    order_type,
    time_in_force,
    valid_from_ts,
    expiry_ts,
    limit_price,
    stop_trigger_price,
    portfolio_id,
    portfolio_name,
    routing_hint,
    risk_budget_bps,
    signal_version,
    model_run_id,
    preconditions,
    auto_hedge
) AS
SELECT
    tr.recommendation_id,
    d.full_date           AS recommendation_date,
    s.symbol,
    s.exchange,
    at.asset_type_name    AS asset_type,
    src.source_name,
    src.version           AS source_version,
    tr.action,
    tr.recommended_price,
    tr.stop_loss_price,
    tr.take_profit_price,
    tr.size_shares,
    tr.size_percent,
    conf.confidence_label,
    tf.timeframe_label,
    tr.strategy_name,
    tr.description,
    tr.is_live,
    tr.filled_price,
    tr.filled_date,
    tr.create_ts,
    tr.update_ts,
    tr.order_type,
    tr.time_in_force,
    tr.valid_from_ts,
    tr.expiry_ts,
    tr.limit_price,
    tr.stop_trigger_price,
    tr.portfolio_id,
    p.portfolio_name,
    tr.routing_hint,
    tr.risk_budget_bps,
    tr.signal_version,
    tr.model_run_id,
    tr.preconditions,
    tr.auto_hedge
FROM   rankalpha.fact_trade_recommendation        tr
JOIN   rankalpha.dim_date          d   ON d.date_key   = tr.date_key
JOIN   rankalpha.dim_stock         s   ON s.stock_key  = tr.stock_key
LEFT   JOIN rankalpha.dim_asset_type at ON at.asset_type_key = s.asset_type_key
JOIN   rankalpha.dim_source        src ON src.source_key = tr.source_key
LEFT   JOIN rankalpha.dim_confidence conf ON conf.confidence_key = tr.confidence_key
LEFT   JOIN rankalpha.dim_timeframe tf   ON tf.timeframe_key  = tr.timeframe_key
LEFT   JOIN rankalpha.portfolio     p   ON p.portfolio_id = tr.portfolio_id;

COMMENT ON VIEW rankalpha.vw_trade_recommendation IS
'Readable projection of fact_trade_recommendation with decoded dimension labels and execution metadata';
