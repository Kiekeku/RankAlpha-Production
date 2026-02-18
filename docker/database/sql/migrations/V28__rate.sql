-- =====================================================================
--  V2  :  Market reference rates & volatility surface
-- =====================================================================

-- ---------- 1. Dimension: tenor --------------------------------------
CREATE TABLE IF NOT EXISTS rankalpha.dim_tenor (
    tenor_key    SERIAL PRIMARY KEY,
    tenor_label  VARCHAR(10) NOT NULL UNIQUE,            -- 'O/N','1M','3M', …
    tenor_days   SMALLINT    NOT NULL
);

-- ---------- 2. Fact: daily risk‑free curve ---------------------------
CREATE TABLE IF NOT EXISTS rankalpha.fact_risk_free_rate (
    date_key     INT     NOT NULL REFERENCES rankalpha.dim_date(date_key),
    tenor_key    INT     NOT NULL REFERENCES rankalpha.dim_tenor(tenor_key),
    rate_pct     NUMERIC(10,4) NOT NULL,                 -- e.g. 5.3250 (% p.a.)
    load_ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fact_rfr_pkey PRIMARY KEY (date_key, tenor_key)
);

-- ---------- 3. Fact: stock borrow (short‑sale) cost ------------------
CREATE TABLE IF NOT EXISTS rankalpha.fact_stock_borrow_rate (
    date_key     INT     NOT NULL REFERENCES rankalpha.dim_date(date_key),
    stock_key    INT     NOT NULL REFERENCES rankalpha.dim_stock(stock_key),
    borrow_rate_bp NUMERIC(12,4) NOT NULL,               -- bps annualised
    load_ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fact_borrow_pkey PRIMARY KEY (date_key, stock_key)
);

-- ---------- 4. Fact: simplified IV surface ---------------------------
CREATE TABLE IF NOT EXISTS rankalpha.fact_iv_surface (
    date_key     INT     NOT NULL REFERENCES rankalpha.dim_date(date_key),
    stock_key    INT     NOT NULL REFERENCES rankalpha.dim_stock(stock_key),
    tenor_key    INT     NOT NULL REFERENCES rankalpha.dim_tenor(tenor_key),
    implied_vol  NUMERIC(8,4)  NOT NULL,                 -- 0.2456 = 24.56%
    load_ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fact_iv_pkey PRIMARY KEY (date_key, stock_key, tenor_key)
);

-- ---------- 5. Human‑friendly views ----------------------------------
-- Risk‑free curve
CREATE OR REPLACE VIEW rankalpha.vw_risk_free_rate AS
SELECT d.full_date         AS rate_date,
       t.tenor_label,
       f.rate_pct
FROM   rankalpha.fact_risk_free_rate f
JOIN   rankalpha.dim_date  d ON d.date_key  = f.date_key
JOIN   rankalpha.dim_tenor t ON t.tenor_key = f.tenor_key;

-- Stock borrow
CREATE OR REPLACE VIEW rankalpha.vw_stock_borrow_rate AS
SELECT d.full_date AS borrow_date,
       s.symbol,
       f.borrow_rate_bp
FROM   rankalpha.fact_stock_borrow_rate f
JOIN   rankalpha.dim_date  d ON d.date_key  = f.date_key
JOIN   rankalpha.dim_stock s ON s.stock_key = f.stock_key;

-- IV surface (most used aggregation)
CREATE OR REPLACE VIEW rankalpha.vw_iv_surface AS
SELECT d.full_date      AS iv_date,
       s.symbol,
       t.tenor_label,
       f.implied_vol
FROM   rankalpha.fact_iv_surface f
JOIN   rankalpha.dim_date  d ON d.date_key  = f.date_key
JOIN   rankalpha.dim_stock s ON s.stock_key = f.stock_key
JOIN   rankalpha.dim_tenor t ON t.tenor_key = f.tenor_key;

-- Grants for read‑only roles can be added here if you have RBAC.
