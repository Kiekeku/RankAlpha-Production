-- -------------------------------------------------------------------------------------------------
--  RankAlpha : FACT_TRADE_RECOMMENDATION
--  • One row per *recommended* trade idea (not the executed transaction)
--  • Idempotent – all objects guarded with IF NOT EXISTS
-- -------------------------------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS rankalpha;

-- Required for UUID default
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Enumerated action type
DO $$
BEGIN
   IF NOT EXISTS (SELECT 1
                  FROM pg_type t
                  JOIN pg_namespace n ON n.oid = t.typnamespace
                  WHERE t.typname = 'trade_action'
                    AND n.nspname = 'rankalpha') THEN
      CREATE TYPE rankalpha.trade_action AS ENUM ('BUY', 'SELL', 'SHORT', 'COVER');
   END IF;
END$$;

-- 2. Main table
CREATE TABLE IF NOT EXISTS rankalpha.fact_trade_recommendation
(
    recommendation_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    date_key                INT  NOT NULL REFERENCES rankalpha.dim_date   (date_key),
    stock_key               INT  NOT NULL REFERENCES rankalpha.dim_stock  (stock_key),
    source_key              INT  NOT NULL REFERENCES rankalpha.dim_source (source_key),

    action                  rankalpha.trade_action NOT NULL,
    recommended_price       NUMERIC(20,4),
    stop_loss_price         NUMERIC(20,4),
    take_profit_price       NUMERIC(20,4),

    size_shares             INT,
    size_percent            NUMERIC(6,2),      -- % of portfolio or notional

    confidence_key          INT REFERENCES rankalpha.dim_confidence(confidence_key),
    timeframe_key           INT REFERENCES rankalpha.dim_timeframe (timeframe_key),

    strategy_name           VARCHAR(50),
    description             VARCHAR(1000),

    is_live                 BOOLEAN DEFAULT FALSE,   -- order placed?
    filled_price            NUMERIC(20,4),
    filled_date             DATE,

    create_ts               TIMESTAMPTZ DEFAULT now() NOT NULL,
    update_ts               TIMESTAMPTZ DEFAULT now() NOT NULL,

    -- Prevent duplicate calls for same idea on same day
    CONSTRAINT uq_trade_rec UNIQUE (date_key, stock_key, source_key, action)
);

-- 3. Book‑keeping trigger (touch update_ts on UPDATE)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'trg_set_fact_trade_rec_update_ts') THEN
    CREATE FUNCTION rankalpha.trg_set_fact_trade_rec_update_ts()
    RETURNS TRIGGER AS $f$
    BEGIN
      NEW.update_ts := now();
      RETURN NEW;
    END
    $f$ LANGUAGE plpgsql;
  
    CREATE TRIGGER trg_fact_trade_rec_ts
      BEFORE UPDATE ON rankalpha.fact_trade_recommendation
      FOR EACH ROW
      EXECUTE FUNCTION rankalpha.trg_set_fact_trade_rec_update_ts();
  END IF;
END$$;


-- -------------------------------------------------------------------------------------------------
--  RankAlpha : Human‑readable view for trade recommendations
-- -------------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW rankalpha.vw_trade_recommendation AS
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
    tr.update_ts
FROM   rankalpha.fact_trade_recommendation        tr
JOIN   rankalpha.dim_date          d   ON d.date_key   = tr.date_key
JOIN   rankalpha.dim_stock         s   ON s.stock_key  = tr.stock_key
LEFT   JOIN rankalpha.dim_asset_type at ON at.asset_type_key = s.asset_type_key
JOIN   rankalpha.dim_source        src ON src.source_key = tr.source_key
LEFT   JOIN rankalpha.dim_confidence conf ON conf.confidence_key = tr.confidence_key
LEFT   JOIN rankalpha.dim_timeframe tf   ON tf.timeframe_key  = tr.timeframe_key;

COMMENT ON VIEW rankalpha.vw_trade_recommendation IS
'Readable projection of fact_trade_recommendation with decoded dimension labels';
