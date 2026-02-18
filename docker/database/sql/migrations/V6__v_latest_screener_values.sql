CREATE OR REPLACE VIEW v_latest_screener_values AS
SELECT
    f.date_key,
    dd.full_date,
    ds.symbol,
    ds.company_name,
    ds.sector,
    ds.exchange,
    src.source_name    AS source,
    sty.style_name     AS style,
    f.rank_value,
    f.screening_runid,
    f.load_ts
FROM fact_screener_rank f
  -- join to pick only the latest date_key
  JOIN (
    SELECT MAX(date_key) AS max_date
      FROM fact_screener_rank
  ) latest
    ON f.date_key = latest.max_date

  -- dimensions for lookup
  JOIN dim_date   dd  ON f.date_key    = dd.date_key
  JOIN dim_stock  ds  ON f.stock_key   = ds.stock_key
  JOIN dim_source src ON f.source_key  = src.source_key
  JOIN dim_style  sty ON f.style_key   = sty.style_key
;
