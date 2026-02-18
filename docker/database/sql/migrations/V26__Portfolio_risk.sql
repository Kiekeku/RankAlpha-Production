-- ======================================================================
--  V20250629_02__portfolio_time_series.sql
--  Adds market data, trade ledger, historical positions, NAV, P&L,
--  benchmark & factor data, FX rates and risk metrics ‑ plus analyst
--  views. 100 % idempotent.
-- ======================================================================
SET search_path = rankalpha;

-- ───────────────────────────────────────────────────────────────────────
-- 1. DAILY MARKET PRICES & CORP ACTIONS
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_security_price (
    date_key     INT  NOT NULL REFERENCES dim_date(date_key),
    stock_key    INT  NOT NULL REFERENCES dim_stock(stock_key),
    open_px      NUMERIC(20,4),
    high_px      NUMERIC(20,4),
    low_px       NUMERIC(20,4),
    close_px     NUMERIC(20,4),
    total_return_factor NUMERIC(18,8),
    volume       BIGINT,
    load_ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (date_key, stock_key)
);

CREATE TABLE IF NOT EXISTS fact_corporate_action (
    action_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    stock_key    INT  NOT NULL REFERENCES dim_stock(stock_key),
    action_type  VARCHAR(12) NOT NULL,          -- SPLIT / DVD / SPINOFF / …
    ex_date      DATE NOT NULL,
    ratio_or_amt NUMERIC(18,8),                 -- split ratio OR cash div
    declared_ts  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ───────────────────────────────────────────────────────────────────────
-- 2. BENCHMARK & FACTOR RETURNS
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_benchmark (
    benchmark_key  SERIAL PRIMARY KEY,
    benchmark_name VARCHAR(50) UNIQUE NOT NULL,
    currency_code  CHAR(3)  NOT NULL DEFAULT 'USD',
    description    TEXT
);

CREATE TABLE IF NOT EXISTS fact_benchmark_price (
    date_key       INT NOT NULL REFERENCES dim_date(date_key),
    benchmark_key  INT NOT NULL REFERENCES dim_benchmark(benchmark_key),
    close_px       NUMERIC(20,4),
    total_return_factor NUMERIC(18,8),
    PRIMARY KEY (date_key, benchmark_key)
);

CREATE TABLE IF NOT EXISTS dim_factor (
    factor_key   SERIAL PRIMARY KEY,
    model_name   VARCHAR(20) NOT NULL,          -- e.g. 'FF5', 'Barra'
    factor_name  VARCHAR(40) NOT NULL,
    description  TEXT,
    UNIQUE (model_name, factor_name)
);

CREATE TABLE IF NOT EXISTS fact_factor_return (
    date_key     INT NOT NULL REFERENCES dim_date(date_key),
    factor_key   INT NOT NULL REFERENCES dim_factor(factor_key),
    daily_return NUMERIC(10,6) NOT NULL,
    PRIMARY KEY (date_key, factor_key)
);

-- ───────────────────────────────────────────────────────────────────────
-- 3. FX RATES
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_fx_rate (
    date_key   INT NOT NULL REFERENCES dim_date(date_key),
    from_ccy   CHAR(3) NOT NULL,
    to_ccy     CHAR(3) NOT NULL,
    mid_px     NUMERIC(18,8) NOT NULL,
    PRIMARY KEY (date_key, from_ccy, to_ccy)
);

-- ───────────────────────────────────────────────────────────────────────
-- 4. TRADE LEDGER & HISTORICAL POSITIONS
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_portfolio_trade (
    trade_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portfolio_id  UUID NOT NULL REFERENCES portfolio(portfolio_id)
                    ON DELETE CASCADE,
    stock_key     INT  NOT NULL REFERENCES dim_stock(stock_key),
    exec_ts       TIMESTAMPTZ NOT NULL,
    side          CHAR(4) NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity      NUMERIC(20,4) NOT NULL,
    price         NUMERIC(20,4) NOT NULL,
    commission    NUMERIC(20,4),
    venue         VARCHAR(12),
    strategy_tag  VARCHAR(40)
);
CREATE INDEX IF NOT EXISTS idx_trade_portfolio_date
      ON fact_portfolio_trade (portfolio_id, exec_ts DESC);

CREATE TABLE IF NOT EXISTS fact_portfolio_position_hist (
    effective_date  DATE NOT NULL,
    portfolio_id    UUID NOT NULL REFERENCES portfolio(portfolio_id)
                       ON DELETE CASCADE,
    stock_key       INT  NOT NULL REFERENCES dim_stock(stock_key),
    quantity        NUMERIC(20,4) NOT NULL,
    avg_cost        NUMERIC(20,4),
    run_id          UUID NOT NULL DEFAULT uuid_generate_v4(),
    PRIMARY KEY (effective_date, portfolio_id, stock_key)
);

-- ───────────────────────────────────────────────────────────────────────
-- 5. NAV & P/L
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_portfolio_nav (
    date_key      INT  NOT NULL REFERENCES dim_date(date_key),
    portfolio_id  UUID NOT NULL REFERENCES portfolio(portfolio_id)
                     ON DELETE CASCADE,
    nav_base_ccy  NUMERIC(20,4) NOT NULL,
    gross_leverage NUMERIC(6,2),
    capital_inflow  NUMERIC(20,4),
    capital_outflow NUMERIC(20,4),
    load_ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (date_key, portfolio_id)
);

CREATE TABLE IF NOT EXISTS fact_portfolio_pnl (
    date_key      INT  NOT NULL REFERENCES dim_date(date_key),
    portfolio_id  UUID NOT NULL REFERENCES portfolio(portfolio_id)
                     ON DELETE CASCADE,
    unrealised_pnl NUMERIC(20,4),
    realised_pnl   NUMERIC(20,4),
    dividend_income NUMERIC(20,4),
    fees            NUMERIC(20,4),
    PRIMARY KEY (date_key, portfolio_id)
);

-- ───────────────────────────────────────────────────────────────────────
-- 6. RISK METRICS
-- ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_portfolio_risk (
    date_key     INT NOT NULL REFERENCES dim_date(date_key),
    portfolio_id UUID NOT NULL REFERENCES portfolio(portfolio_id)
                    ON DELETE CASCADE,
    metric_name  VARCHAR(32) NOT NULL,
    metric_value NUMERIC(20,6) NOT NULL,
    methodology  VARCHAR(20),
    PRIMARY KEY (date_key, portfolio_id, metric_name)
);

-- ───────────────────────────────────────────────────────────────────────
-- 7. ANALYST‑FRIENDLY VIEWS
-- ───────────────────────────────────────────────────────────────────────

-- Current snapshot (weight vs latest NAV)
CREATE OR REPLACE VIEW vw_portfolio_snapshot AS
SELECT
    p.portfolio_id,
    p.portfolio_name,
    ds.symbol,
    ds.company_name,
    pp.quantity,
    pp.avg_cost,
    sp.close_px AS last_close,
    (pp.quantity * sp.close_px) AS market_value,
    nav.nav_base_ccy            AS nav,
    (pp.quantity * sp.close_px) / nav.nav_base_ccy AS weight_pct,
    pp.last_update_ts
FROM portfolio_position pp
JOIN portfolio p USING (portfolio_id)
JOIN dim_stock   ds ON ds.stock_key = pp.stock_key
JOIN LATERAL (
        SELECT close_px
        FROM   fact_security_price sp
        WHERE  sp.stock_key = pp.stock_key
        ORDER  BY sp.date_key DESC
        LIMIT  1
) sp ON TRUE
JOIN LATERAL (
        SELECT nav_base_ccy
        FROM   fact_portfolio_nav nav
        WHERE  nav.portfolio_id = p.portfolio_id
        ORDER  BY nav.date_key DESC
        LIMIT  1
) nav ON TRUE;

-- Rolling performance vs benchmark
CREATE OR REPLACE VIEW vw_portfolio_performance AS
SELECT
    nav.date_key,
    d.full_date,
    p.portfolio_id,
    p.portfolio_name,
    nav.nav_base_ccy,
    LAG(nav.nav_base_ccy) OVER (PARTITION BY p.portfolio_id ORDER BY nav.date_key)
        AS nav_prev,
    (nav.nav_base_ccy /
     LAG(nav.nav_base_ccy) OVER (PARTITION BY p.portfolio_id ORDER BY nav.date_key) - 1)
        AS daily_return
FROM fact_portfolio_nav nav
JOIN portfolio p USING (portfolio_id)
JOIN dim_date d   USING (date_key);

-- Turnover %
CREATE OR REPLACE VIEW vw_portfolio_turnover AS
SELECT
    dd.full_date,
    t.portfolio_id,
    p.portfolio_name,
    SUM(ABS(t.quantity * t.price)) AS notional_traded,
    nav.nav_base_ccy,
    SUM(ABS(t.quantity * t.price))/nav.nav_base_ccy AS turnover_pct
FROM fact_portfolio_trade t
JOIN dim_date dd ON dd.full_date = DATE(t.exec_ts)
JOIN LATERAL (
        SELECT nav_base_ccy
        FROM   fact_portfolio_nav nav
        WHERE  nav.portfolio_id = t.portfolio_id
          AND  nav.date_key     = dd.date_key
) nav ON TRUE
JOIN portfolio p ON p.portfolio_id = t.portfolio_id
GROUP BY dd.full_date, t.portfolio_id, p.portfolio_name, nav.nav_base_ccy;

-- Top contributors (yesterday)
CREATE OR REPLACE VIEW vw_portfolio_top_contrib AS
WITH last_prices AS (
    SELECT stock_key,
           close_px,
           ROW_NUMBER() OVER (PARTITION BY stock_key ORDER BY date_key DESC) AS rn
    FROM   fact_security_price
)
SELECT
    p.portfolio_id,
    p.portfolio_name,
    ds.symbol,
    ds.company_name,
    pp.quantity,
    lp.close_px,
    (pp.quantity * lp.close_px) - (pp.quantity * pp.avg_cost) AS unreal_pnl
FROM   portfolio_position pp
JOIN   portfolio p      USING (portfolio_id)
JOIN   dim_stock ds     ON ds.stock_key = pp.stock_key
JOIN   last_prices lp   ON lp.stock_key = pp.stock_key AND lp.rn = 1
ORDER  BY ABS((pp.quantity * lp.close_px) - (pp.quantity * pp.avg_cost)) DESC
LIMIT 20;

-- Risk dashboard (simple)
CREATE OR REPLACE VIEW vw_risk_dashboard AS
SELECT
    r.date_key,
    d.full_date,
    p.portfolio_name,
    MAX(CASE WHEN metric_name = 'VaR_95_1d'      THEN metric_value END) AS var_95_1d,
    MAX(CASE WHEN metric_name = 'Beta_SP500'     THEN metric_value END) AS beta_spx,
    MAX(CASE WHEN metric_name = 'Liquidity_Days' THEN metric_value END) AS liq_days
FROM fact_portfolio_risk r
JOIN portfolio p   USING (portfolio_id)
JOIN dim_date d    USING (date_key)
GROUP BY r.date_key, d.full_date, p.portfolio_name;


-- ======================================================================
--  END OF MIGRATION
-- ======================================================================
