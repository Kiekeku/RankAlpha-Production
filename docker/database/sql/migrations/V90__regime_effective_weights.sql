/* ------------------------------------------------------------
   V81__regime_effective_weights.sql
   - Table to persist daily effective regime weights per canonical style
   - Backfill historical rows using fact_style_z_us and dim_style_regime_map
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE TABLE IF NOT EXISTS rankalpha.fact_regime_effective_weight (
  date_key        INTEGER NOT NULL REFERENCES rankalpha.dim_date(date_key),
  canonical_name  TEXT    NOT NULL,
  effective_weight NUMERIC(12,6) NOT NULL,
  g_factor        NUMERIC(12,6),
  base_weight     NUMERIC(12,6),
  load_ts         TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
  PRIMARY KEY (date_key, canonical_name)
);

CREATE INDEX IF NOT EXISTS idx_regime_eff_w_date
  ON rankalpha.fact_regime_effective_weight (date_key);

/* -------- Backfill: compute effective weight for Pullback, base for others -------- */
WITH weights_by_canonical AS (
  SELECT canonical_name, MAX(regime_weight)::numeric(12,6) AS base_weight
  FROM rankalpha.dim_style_regime_map
  GROUP BY canonical_name
), z AS (
  SELECT
    fs.date_key,
    MAX(CASE WHEN fs.style_name = 'Momentum'  THEN fs.z_value END) AS z_momo,
    MAX(CASE WHEN fs.style_name = 'Pullback'  THEN fs.z_value END) AS z_pull,
    MAX(CASE WHEN fs.style_name = 'MeanRev'   THEN fs.z_value END) AS z_mr,
    MAX(CASE WHEN fs.style_name = 'Short'     THEN fs.z_value END) AS z_short
  FROM rankalpha.fact_style_z_us fs
  GROUP BY fs.date_key
), dates AS (
  SELECT DISTINCT date_key FROM rankalpha.fact_style_z_us
)
INSERT INTO rankalpha.fact_regime_effective_weight (date_key, canonical_name, effective_weight, g_factor, base_weight)
SELECT
  d.date_key,
  w.canonical_name,
  CASE WHEN w.canonical_name = 'Pullback' THEN
    -- effective = base * clamp(tanh((Zm - Zp)/0.75) - 0.3*max(0, max(0, 0.5*Zmr+0.5*Zshort) - 0.25))
    w.base_weight * LEAST(1.0, GREATEST(-1.0,
      tanh( ((COALESCE(z.z_momo,0) - COALESCE(z.z_pull,0)) / 0.75)::double precision )
      - 0.3 * GREATEST(0.0, GREATEST(0.0, 0.5*COALESCE(z.z_mr,0) + 0.5*COALESCE(z.z_short,0)) - 0.25)
    ))
  ELSE w.base_weight END AS effective_weight,
  CASE WHEN w.canonical_name = 'Pullback' THEN
    LEAST(1.0, GREATEST(-1.0,
      tanh( ((COALESCE(z.z_momo,0) - COALESCE(z.z_pull,0)) / 0.75)::double precision )
      - 0.3 * GREATEST(0.0, GREATEST(0.0, 0.5*COALESCE(z.z_mr,0) + 0.5*COALESCE(z.z_short,0)) - 0.25)
    ))
  ELSE 1.0 END AS g_factor,
  w.base_weight
FROM dates d
LEFT JOIN z ON z.date_key = d.date_key
JOIN weights_by_canonical w ON TRUE
ON CONFLICT (date_key, canonical_name) DO UPDATE SET
  effective_weight = EXCLUDED.effective_weight,
  g_factor = EXCLUDED.g_factor,
  base_weight = EXCLUDED.base_weight,
  load_ts = now();

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

