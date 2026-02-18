/* ------------------------------------------------------------
   V74__screener_position_side.sql
   Introduces position-side and weighting metadata for screener
   styles and reapplies screener views/materialized views so
   source/style weights flow into downstream aggregates.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

ALTER TABLE rankalpha.dim_style
    ADD COLUMN IF NOT EXISTS position_side TEXT NOT NULL DEFAULT 'long';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'dim_style_position_side_chk'
          AND conrelid = 'rankalpha.dim_style'::regclass
    ) THEN
        ALTER TABLE rankalpha.dim_style
            ADD CONSTRAINT dim_style_position_side_chk
            CHECK (position_side IN ('long', 'short'));
    END IF;
END $$;

ALTER TABLE rankalpha.dim_style
    ADD COLUMN IF NOT EXISTS screener_weight NUMERIC(6,4) NOT NULL DEFAULT 1.0;

/* ------------------------------------------------------------
   Recreate screener views with side + weighting metadata.
   ------------------------------------------------------------ */

DROP VIEW IF EXISTS rankalpha.v_latest_screener_consensus CASCADE;
DROP VIEW IF EXISTS rankalpha.v_latest_screener_values CASCADE;

CREATE VIEW rankalpha.v_latest_screener_values AS
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
    sty.position_side    AS position_side,
    src.screener_weight  AS source_weight,
    sty.screener_weight  AS style_weight,
    MIN(f.rank_value)    AS rank_value,
    (ARRAY_AGG(f.screening_runid ORDER BY f.load_ts DESC))[1] AS screening_runid,
    MAX(f.load_ts)       AS load_ts,
    COUNT(*)             AS appearances
FROM rankalpha.fact_screener_rank f
JOIN latest              ON f.date_key = latest.max_date
JOIN rankalpha.dim_date   dd  ON f.date_key   = dd.date_key
JOIN rankalpha.dim_stock  ds  ON f.stock_key  = ds.stock_key
JOIN rankalpha.dim_source src ON f.source_key = src.source_key
JOIN rankalpha.dim_style  sty ON f.style_key  = sty.style_key
WHERE src.exclude_from_screener IS NOT TRUE
GROUP BY
    f.date_key, dd.full_date,
    ds.symbol, ds.company_name, ds.sector, ds.exchange,
    src.source_name, sty.style_name, sty.position_side,
    src.screener_weight, sty.screener_weight;

CREATE VIEW rankalpha.v_latest_screener_consensus AS
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
    SUM(DISTINCT h.style_weight)  AS styles_distinct,
    SUM(DISTINCT h.source_weight) AS sources_distinct,
    ARRAY_AGG(DISTINCT h.style_name)  AS styles,
    ARRAY_AGG(DISTINCT h.source_name) AS sources,
    ARRAY_AGG(DISTINCT h.screening_runid) AS runids,
    MIN(h.style_rank_pct) AS min_style_rank_pct
  FROM hits h
  GROUP BY h.full_date, h.symbol, h.position_side
)
SELECT
  s.full_date,
  s.symbol,
  s.position_side,
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
  (
    GREATEST(
      0::numeric,
      LEAST(
        100::numeric,
        ROUND(
          (
            100::numeric - 100::numeric * COALESCE(s.min_style_rank_pct::numeric, 1::numeric)
          )
          + (10::numeric * LN(1 + COALESCE(s.appearances, 0))::numeric)
          + (5::numeric * COALESCE(s.styles_distinct, 0)::numeric)
          + (5::numeric * COALESCE(s.sources_distinct, 0)::numeric),
          2
        )
      )
    )
  )::numeric(6,2) AS consensus_score
FROM sym_agg s
LEFT JOIN primary_hit p
  ON p.symbol = s.symbol
 AND p.position_side = s.position_side;

/* ------------------------------------------------------------
   Recreate materialized views with side + weighting metadata.
   ------------------------------------------------------------ */

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_screener_changes;

CREATE MATERIALIZED VIEW rankalpha.mv_screener_changes AS
WITH latest_date AS (
    SELECT max(date_key) AS date_key
    FROM rankalpha.fact_screener_rank
),
recent_trading_days AS (
    SELECT dd.date_key,
           dd.full_date,
           ROW_NUMBER() OVER (ORDER BY dd.full_date DESC) AS rn
    FROM rankalpha.dim_date dd
    JOIN latest_date ld ON dd.full_date <= (
        SELECT full_date FROM rankalpha.dim_date WHERE date_key = ld.date_key
    )
    WHERE dd.is_trading_day
),
selected_days AS (
    SELECT date_key, full_date, rn
    FROM recent_trading_days
    WHERE rn <= 4
),
day_keys AS (
    SELECT
        MAX(CASE WHEN rn = 1 THEN date_key END) AS date_d0,
        MAX(CASE WHEN rn = 1 THEN full_date END) AS date_d0_full,
        MAX(CASE WHEN rn = 2 THEN date_key END) AS date_d1,
        MAX(CASE WHEN rn = 3 THEN date_key END) AS date_d2,
        MAX(CASE WHEN rn = 4 THEN date_key END) AS date_d3
    FROM selected_days
),
presence AS (
    SELECT f.stock_key,
           f.source_key,
           f.style_key,
           f.date_key,
           MIN(f.rank_value) AS rank_value
    FROM rankalpha.fact_screener_rank f
    JOIN day_keys dk ON f.date_key IN (dk.date_d0, dk.date_d1, dk.date_d2, dk.date_d3)
    JOIN rankalpha.dim_source src ON src.source_key = f.source_key
    WHERE src.exclude_from_screener IS NOT TRUE
    GROUP BY 1,2,3,4
),
wide_presence AS (
    SELECT stock_key,
           source_key,
           style_key,
           MAX(CASE WHEN date_key = dk.date_d0 THEN rank_value END) AS rank_d0,
           MAX(CASE WHEN date_key = dk.date_d1 THEN rank_value END) AS rank_d1,
           MAX(CASE WHEN date_key = dk.date_d2 THEN rank_value END) AS rank_d2,
           MAX(CASE WHEN date_key = dk.date_d3 THEN rank_value END) AS rank_d3
    FROM presence
    CROSS JOIN day_keys dk
    GROUP BY 1,2,3
),
last_seen_before_d0 AS (
    SELECT f.stock_key,
           f.source_key,
           f.style_key,
           MAX(f.date_key) AS last_seen_date_key
    FROM rankalpha.fact_screener_rank f
    JOIN rankalpha.dim_source src ON src.source_key = f.source_key
    CROSS JOIN day_keys dk
    WHERE dk.date_d0 IS NOT NULL
      AND f.date_key < dk.date_d0
      AND src.exclude_from_screener IS NOT TRUE
    GROUP BY 1,2,3
),
last_seen_before_window AS (
    SELECT f.stock_key,
           f.source_key,
           f.style_key,
           MAX(f.date_key) AS last_seen_date_key
    FROM rankalpha.fact_screener_rank f
    JOIN rankalpha.dim_source src ON src.source_key = f.source_key
    CROSS JOIN day_keys dk
    WHERE dk.date_d3 IS NOT NULL
      AND f.date_key < dk.date_d3
      AND src.exclude_from_screener IS NOT TRUE
    GROUP BY 1,2,3
),
prior_rank AS (
    SELECT DISTINCT ON (f.stock_key, f.source_key, f.style_key)
           f.stock_key,
           f.source_key,
           f.style_key,
           f.rank_value AS prior_rank_value,
           f.date_key AS prior_rank_date_key
    FROM rankalpha.fact_screener_rank f
    JOIN rankalpha.dim_source src ON src.source_key = f.source_key
    CROSS JOIN day_keys dk
    WHERE dk.date_d0 IS NOT NULL
      AND f.date_key < dk.date_d0
      AND src.exclude_from_screener IS NOT TRUE
    ORDER BY f.stock_key, f.source_key, f.style_key, f.date_key DESC
),
trading_calendar AS (
    SELECT date_key,
           full_date,
           ROW_NUMBER() OVER (ORDER BY full_date) AS trading_index
    FROM rankalpha.dim_date
    WHERE is_trading_day
),
entered_reentered AS (
    SELECT dk.date_d0 AS change_date_key,
           w.stock_key,
           w.source_key,
           w.style_key,
           CASE WHEN lsw.last_seen_date_key IS NULL THEN 'entered' ELSE 'reentered' END AS change_type,
           w.rank_d0 AS current_rank,
           pr.prior_rank_value AS previous_rank,
           CASE WHEN pr.prior_rank_value IS NULL THEN NULL ELSE w.rank_d0 - pr.prior_rank_value END AS rank_delta,
           lsb.last_seen_date_key,
           CASE WHEN lsb.last_seen_date_key IS NULL THEN NULL
                ELSE tc0.trading_index - tcl.trading_index
           END AS days_since_last_seen,
           CASE WHEN lsb.last_seen_date_key IS NULL THEN NULL
                ELSE tc0.trading_index - tcl.trading_index - 1
           END AS absent_trading_days
    FROM wide_presence w
    CROSS JOIN day_keys dk
    LEFT JOIN last_seen_before_d0 lsb
           ON lsb.stock_key = w.stock_key
          AND lsb.source_key = w.source_key
          AND ((lsb.style_key IS NULL AND w.style_key IS NULL)
               OR (lsb.style_key = w.style_key))
    LEFT JOIN last_seen_before_window lsw
           ON lsw.stock_key = w.stock_key
          AND lsw.source_key = w.source_key
          And ((lsw.style_key IS NULL AND w.style_key IS NULL)
               OR (lsw.style_key = w.style_key))
    LEFT JOIN prior_rank pr
           ON pr.stock_key = w.stock_key
          AND pr.source_key = w.source_key
          AND ((pr.style_key IS NULL AND w.style_key IS NULL)
               OR (pr.style_key = w.style_key))
    LEFT JOIN trading_calendar tc0 ON tc0.date_key = dk.date_d0
    LEFT JOIN trading_calendar tcl ON tcl.date_key = lsb.last_seen_date_key
    WHERE dk.date_d3 IS NOT NULL
      AND w.rank_d0 IS NOT NULL
      AND (dk.date_d1 IS NULL OR w.rank_d1 IS NULL)
      AND (dk.date_d2 IS NULL OR w.rank_d2 IS NULL)
      AND (dk.date_d3 IS NULL OR w.rank_d3 IS NULL)
),
dropped AS (
    SELECT dk.date_d0 AS change_date_key,
           w.stock_key,
           w.source_key,
           w.style_key,
           'dropped' AS change_type,
           NULL::INTEGER AS current_rank,
           w.rank_d3 AS previous_rank,
           NULL::INTEGER AS rank_delta,
           dk.date_d3 AS last_seen_date_key,
           CASE WHEN dk.date_d3 IS NULL THEN NULL
                ELSE tc0.trading_index - tc3.trading_index
           END AS days_since_last_seen,
           CASE WHEN dk.date_d3 IS NULL THEN NULL
                ELSE tc0.trading_index - tc3.trading_index
           END AS absent_trading_days
    FROM wide_presence w
    CROSS JOIN day_keys dk
    LEFT JOIN trading_calendar tc0 ON tc0.date_key = dk.date_d0
    LEFT JOIN trading_calendar tc3 ON tc3.date_key = dk.date_d3
    WHERE dk.date_d0 IS NOT NULL
      AND dk.date_d1 IS NOT NULL
      AND dk.date_d2 IS NOT NULL
      AND dk.date_d3 IS NOT NULL
      AND w.rank_d0 IS NULL
      AND w.rank_d1 IS NULL
      AND w.rank_d2 IS NULL
      AND w.rank_d3 IS NOT NULL
),
changes AS (
    SELECT * FROM entered_reentered
    UNION ALL
    SELECT * FROM dropped
)
SELECT c.change_date_key,
       dd.full_date AS change_date,
       c.stock_key,
       ds.symbol,
       ds.company_name,
       ds.sector,
       ds.exchange,
       c.source_key,
       so.source_name,
       so.screener_weight AS source_weight,
       c.style_key,
       st.style_name,
       COALESCE(st.position_side, 'long') AS position_side,
       COALESCE(st.screener_weight, 1.0) AS style_weight,
       COALESCE(st.screener_weight, 1.0) * so.screener_weight AS change_weight,
       c.change_type,
       c.current_rank,
       c.previous_rank,
       c.rank_delta,
       c.last_seen_date_key,
       dls.full_date AS last_seen_date,
       c.days_since_last_seen,
       c.absent_trading_days
FROM changes c
JOIN rankalpha.dim_date dd ON dd.date_key = c.change_date_key
JOIN rankalpha.dim_stock ds ON ds.stock_key = c.stock_key
JOIN rankalpha.dim_source so ON so.source_key = c.source_key AND so.exclude_from_screener IS NOT TRUE
LEFT JOIN rankalpha.dim_style st ON st.style_key = c.style_key
LEFT JOIN rankalpha.dim_date dls ON dls.date_key = c.last_seen_date_key;

CREATE UNIQUE INDEX mv_screener_changes_pk
    ON rankalpha.mv_screener_changes (change_date_key, stock_key, source_key, style_key, change_type)
    NULLS NOT DISTINCT;

CREATE INDEX mv_screener_changes_symbol
    ON rankalpha.mv_screener_changes (symbol, change_date DESC);

CREATE INDEX mv_screener_changes_type
    ON rankalpha.mv_screener_changes (change_type, change_date DESC);

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_screener_breadth;

CREATE MATERIALIZED VIEW rankalpha.mv_screener_breadth AS
WITH change_counts AS (
    SELECT
        d.full_date        AS change_date,
        c.style_key,
        SUM(
            CASE WHEN c.change_type = 'entered'
                 THEN COALESCE(sty.screener_weight, 1.0) * src.screener_weight
                 ELSE 0 END
        ) AS entered_count,
        SUM(
            CASE WHEN c.change_type = 'reentered'
                 THEN COALESCE(sty.screener_weight, 1.0) * src.screener_weight
                 ELSE 0 END
        ) AS reentered_count,
        SUM(
            CASE WHEN c.change_type = 'dropped'
                 THEN COALESCE(sty.screener_weight, 1.0) * src.screener_weight
                 ELSE 0 END
        ) AS dropped_count
    FROM   fact_screener_rank_change c
    JOIN   dim_date d   ON d.date_key   = c.change_date_key
    JOIN   dim_source src ON src.source_key = c.source_key
    LEFT JOIN dim_style sty  ON sty.style_key  = c.style_key
    WHERE  src.exclude_from_screener IS NOT TRUE
    GROUP  BY d.full_date, c.style_key
), eligible_universe AS (
    SELECT
        d.full_date AS change_date,
        r.style_key,
        SUM(COALESCE(sty.screener_weight, 1.0) * src.screener_weight) AS eligible_count
    FROM   fact_screener_rank r
    JOIN   dim_date d ON d.date_key = r.date_key
    JOIN   dim_source src ON src.source_key = r.source_key
    LEFT JOIN dim_style sty ON sty.style_key = r.style_key
    WHERE  src.exclude_from_screener IS NOT TRUE
    GROUP  BY d.full_date, r.style_key
), daily AS (
    SELECT
        e.change_date,
        e.style_key,
        COALESCE(cc.entered_count, 0)    AS entered_count,
        COALESCE(cc.reentered_count, 0)  AS reentered_count,
        COALESCE(cc.dropped_count, 0)    AS dropped_count,
        e.eligible_count,
        CASE WHEN COALESCE(e.eligible_count, 0) > 0 THEN COALESCE(cc.entered_count, 0)::numeric / e.eligible_count ELSE 0 END AS entered_pct,
        CASE WHEN COALESCE(e.eligible_count, 0) > 0 THEN COALESCE(cc.dropped_count, 0)::numeric / e.eligible_count ELSE 0 END AS dropped_pct,
        CASE WHEN COALESCE(e.eligible_count, 0) > 0 THEN (COALESCE(cc.entered_count, 0) - COALESCE(cc.dropped_count, 0))::numeric / e.eligible_count ELSE 0 END AS net_pct
    FROM eligible_universe e
    LEFT JOIN change_counts cc
      ON cc.change_date = e.change_date AND (
            (cc.style_key IS NULL AND e.style_key IS NULL)
         OR (cc.style_key = e.style_key)
      )
)
SELECT
    daily.change_date,
    daily.style_key,
    sty.style_name,
    COALESCE(sty.position_side, 'long') AS position_side,
    daily.entered_count,
    daily.reentered_count,
    daily.dropped_count,
    daily.eligible_count,
    daily.entered_pct,
    daily.dropped_pct,
    daily.net_pct,
    AVG(daily.entered_pct) OVER (
        PARTITION BY daily.style_key
        ORDER BY daily.change_date
        ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
    ) AS entered_pct_avg_5d,
    AVG(daily.dropped_pct) OVER (
        PARTITION BY daily.style_key
        ORDER BY daily.change_date
        ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
    ) AS dropped_pct_avg_5d,
    AVG(daily.net_pct) OVER (
        PARTITION BY daily.style_key
        ORDER BY daily.change_date
        ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
    ) AS net_pct_avg_5d
FROM daily
LEFT JOIN dim_style sty ON sty.style_key = daily.style_key;

CREATE UNIQUE INDEX mv_screener_breadth_uidx
    ON rankalpha.mv_screener_breadth (change_date, style_key);

CREATE INDEX mv_screener_breadth_style_date_idx
    ON rankalpha.mv_screener_breadth (style_key, change_date);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
