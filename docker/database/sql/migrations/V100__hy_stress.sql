-- =====================================================================
--  V100 : High‑yield stress tape derived from CCC HY OAS (CCCHYS)
-- =====================================================================

CREATE TABLE IF NOT EXISTS rankalpha.fact_hy_stress (
    date_key        INT         NOT NULL REFERENCES rankalpha.dim_date(date_key),
    benchmark_key   INT         NOT NULL REFERENCES rankalpha.dim_benchmark(benchmark_key),
    hy_stress_raw   NUMERIC(14, 6),
    hy_stress_ma    NUMERIC(14, 6),
    hy_stress_z     NUMERIC(14, 6),
    load_ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fact_hy_stress_pkey PRIMARY KEY (date_key, benchmark_key)
);

-- Full series view
CREATE OR REPLACE VIEW rankalpha.vw_hy_stress AS
SELECT d.full_date AS as_of_date,
       f.date_key,
       f.benchmark_key,
       b.benchmark_name,
       f.hy_stress_raw,
       f.hy_stress_ma,
       f.hy_stress_z,
       f.load_ts
FROM   rankalpha.fact_hy_stress f
JOIN   rankalpha.dim_date d      ON d.date_key = f.date_key
JOIN   rankalpha.dim_benchmark b ON b.benchmark_key = f.benchmark_key;

-- Latest per benchmark
CREATE OR REPLACE VIEW rankalpha.vw_hy_stress_latest AS
WITH latest AS (
  SELECT benchmark_key, MAX(date_key) AS date_key
  FROM rankalpha.fact_hy_stress
  GROUP BY benchmark_key
)
SELECT d.full_date AS as_of_date,
       f.date_key,
       f.benchmark_key,
       b.benchmark_name,
       f.hy_stress_raw,
       f.hy_stress_ma,
       f.hy_stress_z,
       f.load_ts
FROM   rankalpha.fact_hy_stress f
JOIN   latest l ON l.benchmark_key = f.benchmark_key AND l.date_key = f.date_key
JOIN   rankalpha.dim_date d      ON d.date_key = f.date_key
JOIN   rankalpha.dim_benchmark b ON b.benchmark_key = f.benchmark_key;
