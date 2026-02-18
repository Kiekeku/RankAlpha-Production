/* ------------------------------------------------------------
   V98__macro_series.sql
   - Dimension + fact tables for macroeconomic time series
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

/* ---------- 1. Dimension: macro series catalogue -------------- */
CREATE TABLE IF NOT EXISTS rankalpha.dim_macro_series (
  series_key   SERIAL PRIMARY KEY,
  series_code  TEXT    NOT NULL UNIQUE,  -- e.g. 'US_CPI_ALL', 'US_NFP'
  series_name  TEXT    NOT NULL,        -- human-readable name
  category     TEXT,                    -- activity, labor, inflation, credit, rates, etc.
  frequency    TEXT,                    -- D / W / M / Q
  units        TEXT,                    -- index, %, bps, billions_usd, etc.
  is_active    BOOLEAN NOT NULL DEFAULT TRUE,
  description  TEXT
);

/* ---------- 2. Fact: macro series observations ----------------- */
CREATE TABLE IF NOT EXISTS rankalpha.fact_macro_series (
  date_key     INTEGER NOT NULL REFERENCES rankalpha.dim_date(date_key),
  series_key   INTEGER NOT NULL REFERENCES rankalpha.dim_macro_series(series_key),
  source_key   INTEGER     REFERENCES rankalpha.dim_source(source_key),
  value        NUMERIC(20,6) NOT NULL,
  load_ts      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
  PRIMARY KEY (date_key, series_key)
);

CREATE INDEX IF NOT EXISTS idx_fact_macro_series_series_date
  ON rankalpha.fact_macro_series (series_key, date_key DESC);

/* ---------- 3. Convenience view with calendar join ------------- */
DROP VIEW IF EXISTS rankalpha.vw_macro_series;

CREATE VIEW rankalpha.vw_macro_series AS
SELECT d.full_date      AS as_of_date,
       f.date_key,
       m.series_code,
       m.series_name,
       m.category,
       m.frequency,
       m.units,
       f.value,
       f.source_key,
       f.load_ts
FROM   rankalpha.fact_macro_series   f
JOIN   rankalpha.dim_date           d ON d.date_key   = f.date_key
JOIN   rankalpha.dim_macro_series   m ON m.series_key = f.series_key;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

