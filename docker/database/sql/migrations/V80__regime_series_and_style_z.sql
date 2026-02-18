/* ------------------------------------------------------------
   V80__regime_series_and_style_z.sql
   - Fact tables for regime outputs and per-style Z values
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE TABLE IF NOT EXISTS rankalpha.fact_style_z_us (
  date_key     INTEGER NOT NULL REFERENCES rankalpha.dim_date(date_key),
  style_name   TEXT    NOT NULL,
  z_value      NUMERIC(12,6) NOT NULL,
  load_ts      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
  PRIMARY KEY (date_key, style_name)
);

CREATE INDEX IF NOT EXISTS idx_fact_style_z_us_style
  ON rankalpha.fact_style_z_us (style_name, date_key DESC);

CREATE TABLE IF NOT EXISTS rankalpha.fact_regime_series (
  date_key        INTEGER NOT NULL REFERENCES rankalpha.dim_date(date_key),
  risk_on_core    NUMERIC(12,6) NOT NULL,
  risk_off_core   NUMERIC(12,6) NOT NULL,
  regime_raw      NUMERIC(12,6) NOT NULL,
  ema10           NUMERIC(12,6) NOT NULL,
  ema50           NUMERIC(12,6) NOT NULL,
  regime_label    TEXT          NOT NULL,
  regime_index    NUMERIC(12,6) NOT NULL,
  participation   NUMERIC(12,6),
  load_ts         TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
  PRIMARY KEY (date_key)
);

CREATE INDEX IF NOT EXISTS idx_fact_regime_series_date
  ON rankalpha.fact_regime_series (date_key);

/* Convenience view joining date */
DROP VIEW IF EXISTS rankalpha.vw_regime_series;
CREATE VIEW rankalpha.vw_regime_series AS
SELECT d.full_date AS as_of_date,
       r.*
FROM rankalpha.fact_regime_series r
JOIN rankalpha.dim_date d ON d.date_key = r.date_key;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

