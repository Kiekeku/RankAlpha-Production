-- Add z-score column for FRA–OIS and backfill with rolling stats

ALTER TABLE rankalpha.fact_fra_ois
  ADD COLUMN IF NOT EXISTS fra_ois_z numeric(12,6);

-- Recreate latest view to include z
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
       f.spread_bp,
       f.fra_ois_z
FROM   rankalpha.fact_fra_ois f
JOIN   latest l ON l.start_months = f.start_months
               AND l.end_months   = f.end_months
               AND l.fra_source   = f.fra_source
               AND l.date_key     = f.date_key
JOIN   rankalpha.dim_date d ON d.date_key = f.date_key
ORDER  BY f.start_months, f.end_months, f.fra_source;

-- Backfill z using 5-day MA smoothed spread, 750-day window, require >=500 obs, clip [-3,5]
WITH s AS (
  SELECT f.date_key,
         f.start_months,
         f.end_months,
         f.fra_source,
         d.full_date,
         AVG(f.spread_bp) OVER (
           PARTITION BY f.start_months, f.end_months, f.fra_source
           ORDER BY d.full_date
           ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
         ) AS spread_sma5
  FROM rankalpha.fact_fra_ois f
  JOIN rankalpha.dim_date d ON d.date_key = f.date_key
),
z AS (
  SELECT
    date_key,
    start_months,
    end_months,
    fra_source,
    spread_sma5,
    COUNT(spread_sma5) OVER (
      PARTITION BY start_months, end_months, fra_source
      ORDER BY full_date
      ROWS BETWEEN 749 PRECEDING AND CURRENT ROW
    ) AS cnt,
    AVG(spread_sma5) OVER (
      PARTITION BY start_months, end_months, fra_source
      ORDER BY full_date
      ROWS BETWEEN 749 PRECEDING AND CURRENT ROW
    ) AS mu,
    STDDEV_SAMP(spread_sma5) OVER (
      PARTITION BY start_months, end_months, fra_source
      ORDER BY full_date
      ROWS BETWEEN 749 PRECEDING AND CURRENT ROW
    ) AS sigma
  FROM s
)
UPDATE rankalpha.fact_fra_ois f
SET fra_ois_z = GREATEST(-3.0, LEAST((z.spread_sma5 - z.mu) / NULLIF(z.sigma, 0), 5.0))
FROM z
WHERE f.date_key = z.date_key
  AND f.start_months = z.start_months
  AND f.end_months = z.end_months
  AND f.fra_source = z.fra_source
  AND z.spread_sma5 IS NOT NULL
  AND z.cnt >= 500
  AND z.sigma IS NOT NULL;

