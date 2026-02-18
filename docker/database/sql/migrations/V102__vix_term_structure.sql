/* ------------------------------------------------------------
   V100__vix_term_structure.sql
   - Daily VIX term structure facts + latest view for API
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

/* ---------- Fact table: VIX term structure ---------- */
CREATE TABLE IF NOT EXISTS rankalpha.fact_vix_term_structure (
  underlying_symbol TEXT NOT NULL DEFAULT 'SPX/VIX',
  date_key          INTEGER NOT NULL REFERENCES rankalpha.dim_date(date_key),
  as_of_date        DATE    NOT NULL,

  vix_1d            NUMERIC(14,6),
  vix_9d            NUMERIC(14,6),
  vix_1m            NUMERIC(14,6),
  vix_3m            NUMERIC(14,6),
  vix_6m            NUMERIC(14,6),
  vix_1y            NUMERIC(14,6),

  slope_1d_9d       NUMERIC(14,6),
  slope_9d_1m       NUMERIC(14,6),
  slope_1m_3m       NUMERIC(14,6),
  slope_3m_6m       NUMERIC(14,6),
  slope_6m_1y       NUMERIC(14,6),
  curve_slope       NUMERIC(14,6),

  ratio_1m_3m       NUMERIC(14,6),
  ratio_1m_6m       NUMERIC(14,6),
  ratio_3m_1y       NUMERIC(14,6),

  num_inversions            SMALLINT,
  is_contango               BOOLEAN,
  is_contango_full          BOOLEAN,
  is_backwardation_front    BOOLEAN,
  is_backwardation_short    BOOLEAN,

  regime          TEXT,
  risk_flag       SMALLINT,

  load_ts         TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
  updated_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),

  PRIMARY KEY (underlying_symbol, date_key)
);

CREATE INDEX IF NOT EXISTS idx_fact_vix_term_structure_date
  ON rankalpha.fact_vix_term_structure (underlying_symbol, date_key DESC);

/* ---------- View: latest per underlying ---------- */
DROP VIEW IF EXISTS rankalpha.vw_vix_term_structure_latest;

CREATE VIEW rankalpha.vw_vix_term_structure_latest AS
WITH latest AS (
    SELECT f.*,
           ROW_NUMBER() OVER (PARTITION BY f.underlying_symbol ORDER BY f.date_key DESC) AS rn
    FROM rankalpha.fact_vix_term_structure f
)
SELECT
    l.underlying_symbol,
    l.date_key,
    d.full_date      AS as_of_date,
    l.vix_1d, l.vix_9d, l.vix_1m, l.vix_3m, l.vix_6m, l.vix_1y,
    l.slope_1d_9d, l.slope_9d_1m, l.slope_1m_3m, l.slope_3m_6m, l.slope_6m_1y, l.curve_slope,
    l.ratio_1m_3m, l.ratio_1m_6m, l.ratio_3m_1y,
    l.num_inversions,
    l.is_contango,
    l.is_contango_full,
    l.is_backwardation_front,
    l.is_backwardation_short,
    l.regime,
    l.risk_flag,
    l.load_ts,
    l.updated_at
FROM latest l
JOIN rankalpha.dim_date d ON d.date_key = l.date_key
WHERE l.rn = 1;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
