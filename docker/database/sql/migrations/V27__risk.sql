-- ====================================================================
--  V23__risk_tables.sql   (idempotent: CREATE … IF NOT EXISTS / ALTER)
-- ====================================================================
--  Adds market‑risk specific dimensions & facts
--  Author: Quant@RankAlpha   Date: 2025‑06‑29
-- --------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rankalpha.dim_var_method (
    var_method_key serial PRIMARY KEY,
    method_label   varchar(30) UNIQUE NOT NULL,
    description    text
);

CREATE TABLE IF NOT EXISTS rankalpha.fact_portfolio_var (
    date_key        int      NOT NULL,
    portfolio_id    uuid     NOT NULL,
    var_method_key  int      NOT NULL,
    horizon_days    int      NOT NULL,
    confidence_pct  numeric(5,2) NOT NULL,
    var_value       numeric(20,4) NOT NULL,
    es_value        numeric(20,4),
    load_ts         timestamptz DEFAULT now() NOT NULL,
    PRIMARY KEY (date_key, portfolio_id, var_method_key,
                 horizon_days, confidence_pct),
    FOREIGN KEY (date_key)       REFERENCES rankalpha.dim_date(date_key),
    FOREIGN KEY (portfolio_id)   REFERENCES rankalpha.portfolio(portfolio_id)
                                   ON DELETE CASCADE,
    FOREIGN KEY (var_method_key) REFERENCES rankalpha.dim_var_method(var_method_key)
);

CREATE TABLE IF NOT EXISTS rankalpha.dim_stress_scenario (
    scenario_key   serial PRIMARY KEY,
    scenario_name  varchar(50) UNIQUE NOT NULL,
    category       varchar(20),
    reference_date date,
    severity_label varchar(12),
    description    text
);

CREATE TABLE IF NOT EXISTS rankalpha.fact_portfolio_scenario_pnl (
    date_key     int   NOT NULL,
    portfolio_id uuid  NOT NULL,
    scenario_key int   NOT NULL,
    pnl_value    numeric(20,4) NOT NULL,
    load_ts      timestamptz DEFAULT now() NOT NULL,
    PRIMARY KEY (date_key, portfolio_id, scenario_key),
    FOREIGN KEY (date_key)     REFERENCES rankalpha.dim_date(date_key),
    FOREIGN KEY (portfolio_id) REFERENCES rankalpha.portfolio(portfolio_id)
                                 ON DELETE CASCADE,
    FOREIGN KEY (scenario_key) REFERENCES rankalpha.dim_stress_scenario(scenario_key)
);

CREATE TABLE IF NOT EXISTS rankalpha.fact_portfolio_factor_exposure (
    date_key       int   NOT NULL,
    portfolio_id   uuid  NOT NULL,
    factor_key     int   NOT NULL,
    exposure_value numeric(20,6) NOT NULL,
    load_ts        timestamptz DEFAULT now() NOT NULL,
    PRIMARY KEY (date_key, portfolio_id, factor_key),
    FOREIGN KEY (date_key)     REFERENCES rankalpha.dim_date(date_key),
    FOREIGN KEY (portfolio_id) REFERENCES rankalpha.portfolio(portfolio_id)
                                 ON DELETE CASCADE,
    FOREIGN KEY (factor_key)   REFERENCES rankalpha.dim_factor(factor_key)
);

-- ====================================================================
--  V24__risk_views.sql      – human‑friendly risk views
-- ====================================================================
--  These CREATE OR REPLACE VIEW statements are fully idempotent and
--  can be rerun safely.  No grants are included; add at the bottom
--  if you delegate BI access to a separate role.
-- --------------------------------------------------------------------

-- ── 1. Daily VaR / ES ----------------------------------------------
CREATE OR REPLACE VIEW rankalpha.vw_portfolio_var AS
SELECT
    d.full_date            AS risk_date,
    p.portfolio_name,
    m.method_label,
    f.horizon_days,
    f.confidence_pct,
    f.var_value,
    f.es_value,
    f.load_ts
FROM   rankalpha.fact_portfolio_var        f
JOIN   rankalpha.dim_date                  d  ON d.date_key      = f.date_key
JOIN   rankalpha.portfolio                 p  ON p.portfolio_id  = f.portfolio_id
JOIN   rankalpha.dim_var_method            m  ON m.var_method_key = f.var_method_key;

COMMENT ON VIEW rankalpha.vw_portfolio_var IS
'Daily portfolio‑level VaR / ES with method, horizon & confidence unpacked';

-- ── 2. Factor exposure snapshot -------------------------------------
CREATE OR REPLACE VIEW rankalpha.vw_portfolio_factor_exposure AS
SELECT
    d.full_date            AS exposure_date,
    p.portfolio_name,
    f.model_name,
    f.factor_name,
    e.exposure_value,
    e.load_ts
FROM   rankalpha.fact_portfolio_factor_exposure e
JOIN   rankalpha.dim_date                       d  ON d.date_key     = e.date_key
JOIN   rankalpha.portfolio                      p  ON p.portfolio_id = e.portfolio_id
JOIN   rankalpha.dim_factor                     f  ON f.factor_key   = e.factor_key;

COMMENT ON VIEW rankalpha.vw_portfolio_factor_exposure IS
'Per‑factor exposure (beta, DV01, etc.) by date and portfolio';

-- ── 3. Stress‑test P/L ---------------------------------------------
CREATE OR REPLACE VIEW rankalpha.vw_portfolio_scenario_pnl AS
SELECT
    d.full_date              AS scenario_date,
    p.portfolio_name,
    s.scenario_name,
    s.category,
    s.severity_label,
    pnl.pnl_value,
    pnl.load_ts
FROM   rankalpha.fact_portfolio_scenario_pnl  pnl
JOIN   rankalpha.dim_date                     d  ON d.date_key      = pnl.date_key
JOIN   rankalpha.portfolio                    p  ON p.portfolio_id  = pnl.portfolio_id
JOIN   rankalpha.dim_stress_scenario          s  ON s.scenario_key  = pnl.scenario_key;

COMMENT ON VIEW rankalpha.vw_portfolio_scenario_pnl IS
'Realised P/L under historical or hypothetical stress scenarios';
