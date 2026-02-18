/* ------------------------------------------------------------
   V99__benchmark_views.sql
   - Convenience view over benchmark prices
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

/* ---------- Benchmark prices with calendar + metadata ---------- */
DROP VIEW IF EXISTS rankalpha.vw_benchmark_price;

CREATE VIEW rankalpha.vw_benchmark_price AS
SELECT d.full_date      AS price_date,
       f.date_key,
       f.benchmark_key,
       b.benchmark_name,
       b.currency_code,
       b.description,
       f.close_px,
       f.total_return_factor
FROM   fact_benchmark_price f
JOIN   dim_date      d ON d.date_key      = f.date_key
JOIN   dim_benchmark b ON b.benchmark_key = f.benchmark_key;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

