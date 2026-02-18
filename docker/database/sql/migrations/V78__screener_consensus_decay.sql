/* ------------------------------------------------------------
   V78__screener_consensus_decay.sql
   - Recreate v_latest_screener_consensus with decay-based
     screener scores blended into the composite consensus score.
   - Joins mv_screener_scores_latest to reuse family decay,
     reinforcement, breadth, and streak bonuses.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

DROP VIEW IF EXISTS rankalpha.v_latest_screener_consensus CASCADE;

CREATE VIEW rankalpha.v_latest_screener_consensus AS
WITH latest AS (
  SELECT MAX(date_key) AS max_date
  FROM rankalpha.fact_screener_rank
), hits AS (
  SELECT
    f.date_key,
    dd.full_date,
    ds.symbol,
    ds.company_name,
    ds.sector,
    ds.exchange,
    sty.style_name,
    sty.position_side,
    src.source_name,
    sty.screener_weight AS style_weight,
    src.screener_weight AS source_weight,
    sty.screener_weight * src.screener_weight AS hit_weight,
    f.rank_value,
    f.screening_runid,
    f.load_ts,
    COUNT(*) OVER (PARTITION BY sty.style_name) AS style_size,
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
  WHERE src.exclude_from_screener IS NOT TRUE
    AND ds.is_active IS TRUE
), primary_hit AS (
  SELECT symbol, position_side, source_name AS primary_source, style_name AS primary_style
  FROM (
    SELECT symbol,
           position_side,
           source_name,
           style_name,
           rank_value,
           load_ts,
           ROW_NUMBER() OVER (
               PARTITION BY symbol, position_side
               ORDER BY rank_value ASC, load_ts DESC
           ) AS rn
    FROM hits
  ) t
  WHERE rn = 1
), distinct_styles AS (
  SELECT
    h.full_date,
    h.symbol,
    h.position_side,
    h.style_name,
    MAX(h.style_weight) AS style_weight
  FROM hits h
  GROUP BY h.full_date, h.symbol, h.position_side, h.style_name
), distinct_sources AS (
  SELECT
    h.full_date,
    h.symbol,
    h.position_side,
    h.source_name,
    MAX(h.source_weight) AS source_weight
  FROM hits h
  GROUP BY h.full_date, h.symbol, h.position_side, h.source_name
), styles_weighted AS (
  SELECT full_date, symbol, position_side, SUM(style_weight) AS styles_distinct
  FROM distinct_styles
  GROUP BY full_date, symbol, position_side
), sources_weighted AS (
  SELECT full_date, symbol, position_side, SUM(source_weight) AS sources_distinct
  FROM distinct_sources
  GROUP BY full_date, symbol, position_side
), sym_agg AS (
  SELECT
    h.full_date,
    h.symbol,
    h.position_side,
    MAX(h.company_name) AS company_name,
    MAX(h.sector)       AS sector,
    MAX(h.exchange)     AS exchange,
    MIN(h.rank_value)   AS rank_best,
    AVG(h.rank_value)::numeric(10,2) AS rank_avg,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY h.rank_value) AS rank_median,
    SUM(h.hit_weight)   AS appearances,
    ARRAY_AGG(DISTINCT h.style_name)  AS styles,
    ARRAY_AGG(DISTINCT h.source_name) AS sources,
    ARRAY_AGG(DISTINCT h.screening_runid) AS runids,
    MIN(h.style_rank_pct) AS min_style_rank_pct
  FROM hits h
  GROUP BY h.full_date, h.symbol, h.position_side
), scores AS (
  SELECT
    ms.as_of_date,
    ms.symbol,
    ms.long_score_raw,
    ms.short_score_raw,
    ms.net_score_raw,
    ms.families_count_long,
    ms.families_count_short,
    ms.screens_count_long,
    ms.screens_count_short,
    ms.tier12_hits_long,
    ms.tier12_hits_short,
    ms.breadth_bonus_long,
    ms.any_bonus_long,
    ms.family_streak_bonus_long,
    ms.any_bonus_short,
    ms.family_streak_bonus_short,
    ms.long_pct,
    ms.short_pct,
    ms.net_pct
  FROM rankalpha.mv_screener_scores_latest ms
)
SELECT
  b.full_date,
  b.symbol,
  b.position_side,
  b.company_name,
  b.sector,
  b.exchange,
  p.primary_source,
  p.primary_style,
  b.rank_best,
  b.rank_avg,
  b.rank_median,
  b.appearances,
  COALESCE(sw.styles_distinct, 0) AS styles_distinct,
  COALESCE(srcw.sources_distinct, 0) AS sources_distinct,
  b.styles,
  b.sources,
  b.runids,
  b.min_style_rank_pct,
  COALESCE(sc.long_score_raw, 0)::numeric(12,4)  AS long_score_raw,
  COALESCE(sc.short_score_raw, 0)::numeric(12,4) AS short_score_raw,
  COALESCE(sc.net_score_raw, 0)::numeric(12,4)   AS net_score_raw,
  COALESCE(sc.families_count_long, 0)           AS families_count_long,
  COALESCE(sc.families_count_short, 0)          AS families_count_short,
  COALESCE(sc.screens_count_long, 0)            AS screens_count_long,
  COALESCE(sc.screens_count_short, 0)           AS screens_count_short,
  COALESCE(sc.tier12_hits_long, 0)              AS tier12_hits_long,
  COALESCE(sc.tier12_hits_short, 0)             AS tier12_hits_short,
  COALESCE(sc.breadth_bonus_long, 0)::numeric(6,4)       AS breadth_bonus_long,
  COALESCE(sc.any_bonus_long, 0)::numeric(6,4)           AS any_bonus_long,
  COALESCE(sc.family_streak_bonus_long, 0)::numeric(6,4) AS family_streak_bonus_long,
  COALESCE(sc.any_bonus_short, 0)::numeric(6,4)          AS any_bonus_short,
  COALESCE(sc.family_streak_bonus_short, 0)::numeric(6,4) AS family_streak_bonus_short,
  COALESCE(sc.long_pct, NULL)::numeric(6,2)     AS long_pct,
  COALESCE(sc.short_pct, NULL)::numeric(6,2)    AS short_pct,
  COALESCE(sc.net_pct, NULL)::numeric(6,2)      AS net_pct,
  (
    GREATEST(
      0::numeric,
      LEAST(
        100::numeric,
        ROUND(
          (
            (
              100::numeric - 100::numeric * COALESCE(b.min_style_rank_pct::numeric, 1::numeric)
            )
            + (10::numeric * LN(1 + COALESCE(b.appearances, 0))::numeric)
            + (5::numeric * COALESCE(sw.styles_distinct, 0)::numeric)
            + (5::numeric * COALESCE(srcw.sources_distinct, 0)::numeric)
          )
          + CASE
              WHEN b.position_side = 'long' THEN
                (12::numeric * COALESCE(sc.long_score_raw, 0)::numeric)
                + (6::numeric * GREATEST(COALESCE(sc.net_score_raw, 0)::numeric, 0::numeric))
                - (6::numeric * GREATEST(COALESCE(sc.short_score_raw, 0)::numeric, 0::numeric))
              ELSE
                (12::numeric * COALESCE(sc.short_score_raw, 0)::numeric)
                + (6::numeric * GREATEST((-1)::numeric * COALESCE(sc.net_score_raw, 0)::numeric, 0::numeric))
                - (6::numeric * GREATEST(COALESCE(sc.long_score_raw, 0)::numeric, 0::numeric))
            END,
          2
        )
      )
    )
  )::numeric(6,2) AS consensus_score
FROM sym_agg b
LEFT JOIN primary_hit p
  ON p.symbol = b.symbol
 AND p.position_side = b.position_side
LEFT JOIN styles_weighted sw
  ON sw.full_date = b.full_date
 AND sw.symbol = b.symbol
 AND sw.position_side = b.position_side
LEFT JOIN sources_weighted srcw
  ON srcw.full_date = b.full_date
 AND srcw.symbol = b.symbol
 AND srcw.position_side = b.position_side
LEFT JOIN scores sc
  ON sc.symbol = b.symbol
 AND sc.as_of_date = b.full_date;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
