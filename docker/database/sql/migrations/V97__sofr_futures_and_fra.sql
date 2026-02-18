-- =====================================================================
--  V97 : SOFR futures (SR1/SR3) and derived FRA–OIS storage
-- =====================================================================

-- Fact: SOFR futures quotes (daily snapshots)
CREATE TABLE IF NOT EXISTS rankalpha.fact_sofr_futures (
    date_key     INT            NOT NULL REFERENCES rankalpha.dim_date(date_key),
    root         VARCHAR(4)     NOT NULL CHECK (root IN ('SR1','SR3')),
    year_num     INT            NOT NULL,
    month_num    INT            NOT NULL CHECK (month_num BETWEEN 1 AND 12),
    local_symbol TEXT           NOT NULL,
    conid        BIGINT,
    last_px      NUMERIC(10,4),            -- e.g., 95.3750
    settle_px    NUMERIC(10,4),            -- prior settle if available
    load_ts      TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT fact_sofr_futures_pkey PRIMARY KEY (date_key, root, year_num, month_num)
);

CREATE INDEX IF NOT EXISTS ix_sofr_futures_conid ON rankalpha.fact_sofr_futures (conid);
CREATE INDEX IF NOT EXISTS ix_sofr_futures_symbol ON rankalpha.fact_sofr_futures (local_symbol);

-- Latest snapshot view per root (front-to-back ordering)
CREATE OR REPLACE VIEW rankalpha.vw_sofr_futures_latest AS
WITH latest AS (
  SELECT root, MAX(date_key) AS date_key
  FROM rankalpha.fact_sofr_futures
  GROUP BY root
)
SELECT d.full_date     AS as_of_date,
       f.root,
       f.year_num      AS contract_year,
       f.month_num     AS contract_month,
       f.local_symbol,
       f.conid,
       f.last_px,
       f.settle_px
FROM   rankalpha.fact_sofr_futures f
JOIN   latest l ON l.root = f.root AND l.date_key = f.date_key
JOIN   rankalpha.dim_date d ON d.date_key = f.date_key
ORDER  BY f.root, f.year_num, f.month_num;

-- Fact: Derived FRA vs OIS forward (daily)
CREATE TABLE IF NOT EXISTS rankalpha.fact_fra_ois (
    date_key     INT            NOT NULL REFERENCES rankalpha.dim_date(date_key),
    start_months INT            NOT NULL,
    end_months   INT            NOT NULL,
    fra_source   VARCHAR(4)     NOT NULL CHECK (fra_source IN ('SR1','SR3')),
    fra_rate     NUMERIC(10,6),            -- decimal (e.g., 0.046800)
    ois_forward  NUMERIC(10,6),            -- decimal (from curve)
    spread_bp    NUMERIC(12,4),            -- (fra - ois) * 1e4
    load_ts      TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT fact_fra_ois_pkey PRIMARY KEY (date_key, start_months, end_months, fra_source)
);

-- Convenience view of latest FRA–OIS per tenor
CREATE OR REPLACE VIEW rankalpha.vw_fra_ois_latest AS
WITH latest AS (
  SELECT start_months, end_months, fra_source, MAX(date_key) AS date_key
  FROM rankalpha.fact_fra_ois
  GROUP BY start_months, end_months, fra_source
)
SELECT d.full_date AS as_of_date,
       f.start_months,
       f.end_months,
       f.fra_source,
       f.fra_rate,
       f.ois_forward,
       f.spread_bp
FROM   rankalpha.fact_fra_ois f
JOIN   latest l ON l.start_months = f.start_months
               AND l.end_months   = f.end_months
               AND l.fra_source   = f.fra_source
               AND l.date_key     = f.date_key
JOIN   rankalpha.dim_date d ON d.date_key = f.date_key
ORDER  BY f.start_months, f.end_months, f.fra_source;

-- Optionally grant read to existing readonly role if you have one
-- GRANT SELECT ON rankalpha.fact_sofr_futures, rankalpha.fact_fra_ois TO rankalpha_readonly;
-- GRANT SELECT ON rankalpha.vw_sofr_futures_latest, rankalpha.vw_fra_ois_latest TO rankalpha_readonly;

