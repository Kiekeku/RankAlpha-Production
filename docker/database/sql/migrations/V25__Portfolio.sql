-- ===================================================================
--  V20250629_01__portfolio_core.sql
--  Adds portfolio tracking to RankAlpha
--  Idempotent: safe to re‑run (dev / CI) thanks to IF NOT EXISTS / 
--              CREATE OR REPLACE VIEW
-- ===================================================================

-- 1. Portfolio master table
CREATE TABLE IF NOT EXISTS rankalpha.portfolio (
    portfolio_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portfolio_name VARCHAR(50) NOT NULL,
    currency_code  CHAR(3)     NOT NULL DEFAULT 'USD',
    inception_date DATE,
    description    TEXT,
    CONSTRAINT uq_portfolio_name UNIQUE (portfolio_name)
);

COMMENT ON TABLE  rankalpha.portfolio IS 'Logical trading books (live or model)';
COMMENT ON COLUMN rankalpha.portfolio.currency_code IS 'ISO‑4217 base currency';

-- 2. Current positions (one row per asset in portfolio)
CREATE TABLE IF NOT EXISTS rankalpha.portfolio_position (
    position_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portfolio_id   UUID    NOT NULL
        REFERENCES rankalpha.portfolio (portfolio_id)
        ON DELETE CASCADE,
    stock_key      INT     NOT NULL
        REFERENCES rankalpha.dim_stock (stock_key),
    quantity       NUMERIC(20,4) NOT NULL,
    avg_cost       NUMERIC(20,4),          -- portfolio’s base CCY
    open_date      DATE,
    last_update_ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_portfolio_stock UNIQUE (portfolio_id, stock_key)
);
CREATE INDEX IF NOT EXISTS idx_portpos_portfolio ON rankalpha.portfolio_position (portfolio_id);
CREATE INDEX IF NOT EXISTS idx_portpos_stock     ON rankalpha.portfolio_position (stock_key);

-- 3. Human‑friendly view (symbol, company, qty, cost)
CREATE OR REPLACE VIEW rankalpha.vw_portfolio_position AS
SELECT
    p.portfolio_id,
    p.portfolio_name,
    pp.position_id,
    ds.symbol,
    ds.company_name,
    pp.quantity,
    pp.avg_cost,
    (pp.quantity * pp.avg_cost)      AS position_cost,
    pp.open_date,
    pp.last_update_ts
FROM   rankalpha.portfolio           p
JOIN   rankalpha.portfolio_position  pp USING (portfolio_id)
JOIN   rankalpha.dim_stock           ds ON ds.stock_key = pp.stock_key;


-- ===================================================================
--  END OF MIGRATION
-- ===================================================================
