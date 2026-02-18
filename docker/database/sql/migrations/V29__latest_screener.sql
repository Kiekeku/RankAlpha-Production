/* idempotent: safe to run again and again */
CREATE OR REPLACE VIEW rankalpha.v_latest_screener_values AS
WITH latest AS (
    SELECT MAX(date_key) AS max_date
    FROM rankalpha.fact_screener_rank
)
SELECT
    f.date_key,
    dd.full_date,
    ds.symbol,
    ds.company_name,
    ds.sector,
    ds.exchange,
    src.source_name      AS source,
    sty.style_name       AS style,

    /* best (lowest) rank on the day */
    MIN(f.rank_value)    AS rank_value,

    /* pick run-id that belongs to the freshest load_ts */
    (ARRAY_AGG(f.screening_runid ORDER BY f.load_ts DESC))[1]
                         AS screening_runid,
    MAX(f.load_ts)       AS load_ts,

    /* NEW – put **after** the existing columns */
    COUNT(*)             AS appearances
FROM       rankalpha.fact_screener_rank f
JOIN latest              ON f.date_key = latest.max_date
JOIN rankalpha.dim_date   dd  ON f.date_key   = dd.date_key
JOIN rankalpha.dim_stock  ds  ON f.stock_key  = ds.stock_key
JOIN rankalpha.dim_source src ON f.source_key = src.source_key
JOIN rankalpha.dim_style  sty ON f.style_key  = sty.style_key
GROUP BY
    f.date_key, dd.full_date,
    ds.symbol, ds.company_name, ds.sector, ds.exchange,
    src.source_name, sty.style_name;
