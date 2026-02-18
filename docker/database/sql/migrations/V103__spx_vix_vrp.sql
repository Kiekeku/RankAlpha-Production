/* VRP between SPX realized variance and VIX implied variance */

-- Fact table
CREATE TABLE IF NOT EXISTS rankalpha.fact_spx_vix_vrp (
  underlying_symbol TEXT NOT NULL DEFAULT 'SPX/VIX',
  date_key          INT  NOT NULL REFERENCES rankalpha.dim_date(date_key),

  spx_close   NUMERIC(20,4),
  vix_close   NUMERIC(20,4),

  rv_30d_var  NUMERIC(18,8),
  iv_30d_var  NUMERIC(18,8),
  vrp_30d     NUMERIC(18,8),

  vrp_p20     NUMERIC(18,8),
  vrp_p80     NUMERIC(18,8),
  vix_p33     NUMERIC(18,8),
  vix_p66     NUMERIC(18,8),

  vrp_state   TEXT,
  vol_state   TEXT,
  vrp_regime  TEXT,

  load_ts     TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
  updated_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),

  CONSTRAINT fact_spx_vix_vrp_pkey PRIMARY KEY (underlying_symbol, date_key)
);

CREATE INDEX IF NOT EXISTS idx_fact_spx_vix_vrp_date
  ON rankalpha.fact_spx_vix_vrp (underlying_symbol, date_key DESC);

-- View: latest per underlying_symbol
DROP VIEW IF EXISTS rankalpha.vw_spx_vix_vrp_latest;
CREATE VIEW rankalpha.vw_spx_vix_vrp_latest AS
WITH latest AS (
    SELECT f.*,
           ROW_NUMBER() OVER (PARTITION BY f.underlying_symbol ORDER BY f.date_key DESC) AS rn
    FROM rankalpha.fact_spx_vix_vrp f
)
SELECT
    l.underlying_symbol,
    l.date_key,
    d.full_date AS as_of_date,
    l.spx_close,
    l.vix_close,
    l.rv_30d_var,
    l.iv_30d_var,
    l.vrp_30d,
    l.vrp_p20,
    l.vrp_p80,
    l.vix_p33,
    l.vix_p66,
    l.vrp_state,
    l.vol_state,
    l.vrp_regime,
    l.load_ts,
    l.updated_at
FROM latest l
JOIN rankalpha.dim_date d ON d.date_key = l.date_key
WHERE l.rn = 1;

