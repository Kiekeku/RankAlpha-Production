/* ------------------------------------------------------------
   V31__latest_screener_consensus.sql
   Consensus view over latest screener results – one row per symbol
   with aggregation features and a composite consensus_score.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE OR REPLACE VIEW rankalpha.v_latest_screener_consensus AS
WITH latest AS (
  SELECT MAX(date_key) AS max_date FROM rankalpha.fact_screener_rank
), hits AS (
  SELECT
    f.date_key,
    dd.full_date,
    ds.symbol,
    ds.company_name,
    ds.sector,
    ds.exchange,
    sty.style_name,
    src.source_name,
    f.rank_value,
    f.screening_runid,
    f.load_ts,
    COUNT(*) OVER (PARTITION BY sty.style_name) AS style_size,
    /* normalized rank percentile within the style (0 best … 1 worst) */
    CASE
      WHEN COUNT(*) OVER (PARTITION BY sty.style_name) <= 1 THEN 0.0
      ELSE (GREATEST(f.rank_value - 1, 0)::numeric) / NULLIF(COUNT(*) OVER (PARTITION BY sty.style_name) - 1, 0)
    END AS style_rank_pct
  FROM rankalpha.fact_screener_rank f
  JOIN latest              ON f.date_key = latest.max_date
  JOIN rankalpha.dim_date   dd  ON f.date_key   = dd.date_key
  JOIN rankalpha.dim_stock  ds  ON f.stock_key  = ds.stock_key
  JOIN rankalpha.dim_source src ON f.source_key = src.source_key
  JOIN rankalpha.dim_style  sty ON f.style_key  = sty.style_key
), primary_hit AS (
  /* take the best (lowest) rank per symbol; tie-break by newest load_ts */
  SELECT symbol, source_name AS primary_source, style_name AS primary_style
  FROM (
    SELECT symbol, source_name, style_name, rank_value, load_ts,
           ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY rank_value ASC, load_ts DESC) AS rn
    FROM hits
  ) t
  WHERE rn = 1
), sym_agg AS (
  SELECT
    h.full_date,
    h.symbol,
    MAX(h.company_name) AS company_name,
    MAX(h.sector)       AS sector,
    MAX(h.exchange)     AS exchange,
    MIN(h.rank_value)   AS rank_best,
    AVG(h.rank_value)::numeric(10,2) AS rank_avg,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY h.rank_value) AS rank_median,
    COUNT(*)             AS appearances,
    COUNT(DISTINCT h.style_name)  AS styles_distinct,
    COUNT(DISTINCT h.source_name) AS sources_distinct,
    MIN(h.style_rank_pct) AS min_style_rank_pct,
    ARRAY_AGG(DISTINCT h.style_name)  AS styles,
    ARRAY_AGG(DISTINCT h.source_name) AS sources,
    ARRAY_AGG(DISTINCT h.screening_runid) AS runids
  FROM hits h
  GROUP BY h.full_date, h.symbol
)
SELECT
  s.full_date,
  s.symbol,
  s.company_name,
  s.sector,
  s.exchange,
  p.primary_source,
  p.primary_style,
  s.rank_best,
  s.rank_avg,
  s.rank_median,
  s.appearances,
  s.styles_distinct,
  s.sources_distinct,
  s.styles,
  s.sources,
  s.runids,
  s.min_style_rank_pct,
  /* Composite consensus score: 100 - 100*min_style_rank_pct + bonuses */
  (
    GREATEST(
      0::numeric,
      LEAST(
        100::numeric,
        ROUND(
          (
            100::numeric - 100::numeric * COALESCE(s.min_style_rank_pct::numeric, 1::numeric)
          )
          + (10::numeric * LN(1 + s.appearances)::numeric)
          + (5::numeric * s.styles_distinct::numeric)
          + (5::numeric * s.sources_distinct::numeric),
          2
        )
      )
    )
  )::numeric(6,2) AS consensus_score
FROM sym_agg s
LEFT JOIN primary_hit p ON p.symbol = s.symbol;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
