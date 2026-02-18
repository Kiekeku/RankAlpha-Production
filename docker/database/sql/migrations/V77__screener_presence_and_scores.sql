/* ------------------------------------------------------------
   V77__screener_presence_and_scores.sql
   - Add streak/presence fact tables (family + side)
   - Create mv_screener_scores_latest (raw + derived metrics)
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

/* ---------- Presence (per family/style) ----------------------------- */
CREATE TABLE IF NOT EXISTS rankalpha.fact_screener_presence (
    date_key            INTEGER NOT NULL REFERENCES rankalpha.dim_date(date_key),
    stock_key           INTEGER NOT NULL REFERENCES rankalpha.dim_stock(stock_key),
    style_key           INTEGER NOT NULL REFERENCES rankalpha.dim_style(style_key),
    present_today       BOOLEAN NOT NULL,
    consec_days_family  SMALLINT NOT NULL,
    load_ts             TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (date_key, stock_key, style_key)
);

CREATE INDEX IF NOT EXISTS idx_fact_screener_presence_stock
  ON rankalpha.fact_screener_presence (stock_key, date_key DESC);

CREATE INDEX IF NOT EXISTS idx_fact_screener_presence_style
  ON rankalpha.fact_screener_presence (style_key, date_key DESC);

/* ---------- Presence (per side: long/short) ------------------------- */
CREATE TABLE IF NOT EXISTS rankalpha.fact_screener_presence_side (
    date_key              INTEGER NOT NULL REFERENCES rankalpha.dim_date(date_key),
    stock_key             INTEGER NOT NULL REFERENCES rankalpha.dim_stock(stock_key),
    position_side         TEXT    NOT NULL CHECK (position_side IN ('long','short')),
    present_any_side      BOOLEAN NOT NULL,
    consec_days_any_side  SMALLINT NOT NULL,
    load_ts               TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (date_key, stock_key, position_side)
);

CREATE INDEX IF NOT EXISTS idx_fact_screener_presence_side_stock
  ON rankalpha.fact_screener_presence_side (stock_key, position_side, date_key DESC);

/* ---------- Score MV (latest trading day) --------------------------- */
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_screener_scores_latest;

CREATE MATERIALIZED VIEW rankalpha.mv_screener_scores_latest AS
WITH base AS (
    SELECT v.date_key,
           v.full_date AS as_of_date,
           v.symbol,
           v.company_name,
           v.sector,
           v.exchange,
           v.style      AS style_name,
           v.position_side,
           v.source     AS source_name,
           v.style_weight,
           v.source_weight
    FROM   rankalpha.v_latest_screener_values v
    JOIN   rankalpha.mv_universe_eligible ue ON ue.symbol = v.symbol AND ue.eligible IS TRUE
), hits AS (
    SELECT b.*, 
           ROW_NUMBER() OVER (
               PARTITION BY b.symbol, b.style_name
               ORDER BY b.source_weight DESC, b.source_name ASC
           ) AS rn,
           COUNT(*) OVER (PARTITION BY b.symbol, b.style_name) AS screens_total
    FROM base b
), fam AS (
    SELECT
        h.as_of_date,
        h.symbol,
        h.style_name,
        h.position_side,
        MAX(h.style_weight) AS style_weight,
        SUM(CASE h.rn
                WHEN 1 THEN 1.00 * h.source_weight
                WHEN 2 THEN 0.70 * h.source_weight
                WHEN 3 THEN 0.50 * h.source_weight
                WHEN 4 THEN 0.35 * h.source_weight
                WHEN 5 THEN 0.25 * h.source_weight
                ELSE 0
            END) AS decayed_sum,
        MAX(h.screens_total) AS screens_total,
        SUM(CASE WHEN h.source_weight = 1.2 THEN 1 ELSE 0 END) AS tier12_hits_family
    FROM hits h
    GROUP BY h.as_of_date, h.symbol, h.style_name, h.position_side
), fam_score AS (
    SELECT as_of_date,
           symbol,
           style_name,
           position_side,
           style_weight * decayed_sum AS family_score,
           screens_total,
           tier12_hits_family
    FROM fam
), fam_split AS (
    SELECT
        fs.as_of_date,
        fs.symbol,
        /* long-side aggregates */
        SUM(CASE WHEN fs.position_side = 'long' THEN fs.family_score ELSE 0 END) AS long_families_sum,
        COUNT(*) FILTER (WHERE fs.position_side = 'long' AND fs.family_score > 0) AS families_count_long,
        SUM(CASE WHEN fs.position_side = 'long' THEN fs.screens_total ELSE 0 END) AS screens_count_long,
        SUM(CASE WHEN fs.position_side = 'long' THEN fs.tier12_hits_family ELSE 0 END) AS tier12_hits_long,
        MAX(CASE WHEN fs.position_side = 'long' AND fs.screens_total >= 2 THEN 1 ELSE 0 END) AS reinforcement_long_flag,
        /* short-side aggregates (single family) */
        SUM(CASE WHEN fs.position_side = 'short' THEN fs.family_score ELSE 0 END) AS short_family_sum,
        COUNT(*) FILTER (WHERE fs.position_side = 'short' AND fs.family_score > 0) AS families_count_short,
        SUM(CASE WHEN fs.position_side = 'short' THEN fs.screens_total ELSE 0 END) AS screens_count_short,
        SUM(CASE WHEN fs.position_side = 'short' THEN fs.tier12_hits_family ELSE 0 END) AS tier12_hits_short,
        MAX(CASE WHEN fs.position_side = 'short' AND fs.screens_total >= 2 THEN 1 ELSE 0 END) AS reinforcement_short_flag
    FROM fam_score fs
    GROUP BY fs.as_of_date, fs.symbol
), breadth AS (
    SELECT
        as_of_date,
        symbol,
        LEAST(1.5::numeric, GREATEST(0, 0.5 * (families_count_long - 1))) AS breadth_bonus_long
    FROM fam_split
), streak_any AS (
    SELECT
        s.as_of_date,
        s.symbol,
        -- any presence bonus is side-specific
        LEAST(0.5::numeric, 0.1 * COALESCE(ps_long.consec_days_any_side, 0))  AS any_bonus_long,
        LEAST(0.5::numeric, 0.1 * COALESCE(ps_short.consec_days_any_side, 0)) AS any_bonus_short
    FROM (SELECT DISTINCT as_of_date, symbol FROM base) s
    LEFT JOIN rankalpha.dim_stock ds ON ds.symbol = s.symbol
    LEFT JOIN rankalpha.fact_screener_presence_side ps_long
           ON ps_long.date_key = (SELECT MAX(date_key) FROM rankalpha.dim_date dd WHERE dd.full_date = s.as_of_date)
          AND ps_long.stock_key = ds.stock_key
          AND ps_long.position_side = 'long'
    LEFT JOIN rankalpha.fact_screener_presence_side ps_short
           ON ps_short.date_key = (SELECT MAX(date_key) FROM rankalpha.dim_date dd WHERE dd.full_date = s.as_of_date)
          AND ps_short.stock_key = ds.stock_key
          AND ps_short.position_side = 'short'
), streak_family AS (
    -- Sum per-family bonuses with caps: long (cap 1.0), short (cap 0.5)
    WITH fam_today AS (
      SELECT b.as_of_date, ds.stock_key, sty.style_key, sty.position_side
      FROM base b
      JOIN rankalpha.dim_style sty ON sty.style_name = b.style_name
      JOIN rankalpha.dim_stock ds  ON ds.symbol = b.symbol
      GROUP BY b.as_of_date, ds.stock_key, sty.style_key, sty.position_side
    ), fam_bonus AS (
      SELECT
        ft.as_of_date,
        ft.stock_key,
        ft.position_side,
        LEAST(0.5::numeric, 0.1 * COALESCE(fp.consec_days_family, 0)) AS fam_bonus
      FROM fam_today ft
      LEFT JOIN rankalpha.fact_screener_presence fp
        ON fp.date_key = (SELECT MAX(date_key) FROM rankalpha.dim_date dd WHERE dd.full_date = ft.as_of_date)
       AND fp.stock_key = ft.stock_key
       AND fp.style_key = ft.style_key
    )
    SELECT
      s.as_of_date,
      ds.symbol,
      LEAST(1.0::numeric, COALESCE(SUM(CASE WHEN fb.position_side='long'  THEN fb.fam_bonus END), 0)) AS family_streak_bonus_long,
      LEAST(0.5::numeric, COALESCE(SUM(CASE WHEN fb.position_side='short' THEN fb.fam_bonus END), 0)) AS family_streak_bonus_short
    FROM (SELECT DISTINCT as_of_date, symbol FROM base) s
    LEFT JOIN rankalpha.dim_stock ds ON ds.symbol = s.symbol
    LEFT JOIN fam_bonus fb ON fb.as_of_date = s.as_of_date AND fb.stock_key = ds.stock_key
    GROUP BY s.as_of_date, ds.symbol
)
SELECT
    f.as_of_date,
    f.symbol,
    -- raw totals
    (COALESCE(f.long_families_sum,0)::numeric + COALESCE(b.breadth_bonus_long,0) +
     COALESCE(CASE WHEN f.reinforcement_long_flag=1 THEN 1 ELSE 0 END,0) +
     COALESCE(sa.any_bonus_long,0) + COALESCE(sf.family_streak_bonus_long,0))::numeric(12,4) AS long_score_raw,
    (COALESCE(f.short_family_sum,0)::numeric +
     COALESCE(CASE WHEN f.reinforcement_short_flag=1 THEN 1 ELSE 0 END,0) +
     COALESCE(sa.any_bonus_short,0) + COALESCE(sf.family_streak_bonus_short,0))::numeric(12,4) AS short_score_raw,
    ((COALESCE(f.long_families_sum,0) + COALESCE(b.breadth_bonus_long,0) +
      COALESCE(CASE WHEN f.reinforcement_long_flag=1 THEN 1 ELSE 0 END,0) +
      COALESCE(sa.any_bonus_long,0) + COALESCE(sf.family_streak_bonus_long,0))
     -
     (COALESCE(f.short_family_sum,0) + COALESCE(CASE WHEN f.reinforcement_short_flag=1 THEN 1 ELSE 0 END,0) +
      COALESCE(sa.any_bonus_short,0) + COALESCE(sf.family_streak_bonus_short,0)))::numeric(12,4) AS net_score_raw,
    -- counts + tie-break helpers
    COALESCE(f.families_count_long,0)   AS families_count_long,
    COALESCE(f.screens_count_long,0)    AS screens_count_long,
    COALESCE(f.tier12_hits_long,0)      AS tier12_hits_long,
    COALESCE(f.families_count_short,0)  AS families_count_short,
    COALESCE(f.screens_count_short,0)   AS screens_count_short,
    COALESCE(f.tier12_hits_short,0)     AS tier12_hits_short,
    -- bonuses surfaced
    COALESCE(b.breadth_bonus_long,0)    AS breadth_bonus_long,
    COALESCE(sa.any_bonus_long,0)       AS any_bonus_long,
    COALESCE(sf.family_streak_bonus_long,0)  AS family_streak_bonus_long,
    COALESCE(sa.any_bonus_short,0)      AS any_bonus_short,
    COALESCE(sf.family_streak_bonus_short,0) AS family_streak_bonus_short,
    -- percentiles (side-specific active sets)
    CASE WHEN (COALESCE(f.long_families_sum,0) + COALESCE(b.breadth_bonus_long,0) + COALESCE(CASE WHEN f.reinforcement_long_flag=1 THEN 1 ELSE 0 END,0) + COALESCE(sa.any_bonus_long,0) + COALESCE(sf.family_streak_bonus_long,0)) > 0
         THEN 100.0 * percent_rank() OVER (
                PARTITION BY 1
                ORDER BY (COALESCE(f.long_families_sum,0) + COALESCE(b.breadth_bonus_long,0) + COALESCE(CASE WHEN f.reinforcement_long_flag=1 THEN 1 ELSE 0 END,0) + COALESCE(sa.any_bonus_long,0) + COALESCE(sf.family_streak_bonus_long,0))
              )
         ELSE NULL END AS long_pct,
    CASE WHEN (COALESCE(f.short_family_sum,0) + COALESCE(CASE WHEN f.reinforcement_short_flag=1 THEN 1 ELSE 0 END,0) + COALESCE(sa.any_bonus_short,0) + COALESCE(sf.family_streak_bonus_short,0)) > 0
         THEN 100.0 * percent_rank() OVER (
                PARTITION BY 2
                ORDER BY (COALESCE(f.short_family_sum,0) + COALESCE(CASE WHEN f.reinforcement_short_flag=1 THEN 1 ELSE 0 END,0) + COALESCE(sa.any_bonus_short,0) + COALESCE(sf.family_streak_bonus_short,0))
              )
         ELSE NULL END AS short_pct,
    CASE WHEN ABS(
            (COALESCE(f.long_families_sum,0) + COALESCE(b.breadth_bonus_long,0) + COALESCE(CASE WHEN f.reinforcement_long_flag=1 THEN 1 ELSE 0 END,0) + COALESCE(sa.any_bonus_long,0) + COALESCE(sf.family_streak_bonus_long,0))
            - (COALESCE(f.short_family_sum,0) + COALESCE(CASE WHEN f.reinforcement_short_flag=1 THEN 1 ELSE 0 END,0) + COALESCE(sa.any_bonus_short,0) + COALESCE(sf.family_streak_bonus_short,0))
         ) > 0
         THEN 100.0 * percent_rank() OVER (
                PARTITION BY 3
                ORDER BY ABS(
                    (COALESCE(f.long_families_sum,0) + COALESCE(b.breadth_bonus_long,0) + COALESCE(CASE WHEN f.reinforcement_long_flag=1 THEN 1 ELSE 0 END,0) + COALESCE(sa.any_bonus_long,0) + COALESCE(sf.family_streak_bonus_long,0))
                  - (COALESCE(f.short_family_sum,0) + COALESCE(CASE WHEN f.reinforcement_short_flag=1 THEN 1 ELSE 0 END,0) + COALESCE(sa.any_bonus_short,0) + COALESCE(sf.family_streak_bonus_short,0))
                )
              )
         ELSE NULL END AS net_pct
FROM fam_split f
LEFT JOIN breadth b   ON b.as_of_date = f.as_of_date AND b.symbol = f.symbol
LEFT JOIN streak_any sa ON sa.as_of_date = f.as_of_date AND sa.symbol = f.symbol
LEFT JOIN streak_family sf ON sf.as_of_date = f.as_of_date AND sf.symbol = f.symbol;

CREATE UNIQUE INDEX mv_screener_scores_latest_pk
  ON rankalpha.mv_screener_scores_latest (as_of_date, symbol);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

