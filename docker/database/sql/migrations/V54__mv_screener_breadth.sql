/* ------------------------------------------------------------
   V54__mv_screener_breadth.sql
   Materialized view aggregating screener change breadth per style.
   Includes raw counts, normalized percentages, and 5-day averages.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_screener_breadth;

CREATE MATERIALIZED VIEW rankalpha.mv_screener_breadth AS
WITH change_counts AS (
    SELECT
        d.full_date        AS change_date,
        c.style_key,
        SUM(CASE WHEN c.change_type = 'entered'    THEN 1 ELSE 0 END) AS entered_count,
        SUM(CASE WHEN c.change_type = 'reentered'  THEN 1 ELSE 0 END) AS reentered_count,
        SUM(CASE WHEN c.change_type = 'dropped'    THEN 1 ELSE 0 END) AS dropped_count
    FROM   fact_screener_rank_change c
    JOIN   dim_date d   ON d.date_key   = c.change_date_key
    WHERE  c.style_key IS NOT NULL
    GROUP  BY d.full_date, c.style_key
), eligible_universe AS (
    SELECT
        d.full_date AS change_date,
        r.style_key,
        COUNT(DISTINCT r.stock_key) AS eligible_count
    FROM   fact_screener_rank r
    JOIN   dim_date d ON d.date_key = r.date_key
    WHERE  r.style_key IS NOT NULL
    GROUP  BY d.full_date, r.style_key
), daily AS (
    SELECT
        e.change_date,
        e.style_key,
        COALESCE(cc.entered_count, 0)    AS entered_count,
        COALESCE(cc.reentered_count, 0)  AS reentered_count,
        COALESCE(cc.dropped_count, 0)    AS dropped_count,
        e.eligible_count,
        CASE WHEN e.eligible_count > 0 THEN COALESCE(cc.entered_count, 0)::numeric / e.eligible_count ELSE 0 END AS entered_pct,
        CASE WHEN e.eligible_count > 0 THEN COALESCE(cc.dropped_count, 0)::numeric / e.eligible_count ELSE 0 END AS dropped_pct,
        CASE WHEN e.eligible_count > 0 THEN (COALESCE(cc.entered_count, 0) - COALESCE(cc.dropped_count, 0))::numeric / e.eligible_count ELSE 0 END AS net_pct
    FROM eligible_universe e
    LEFT JOIN change_counts cc
      ON cc.change_date = e.change_date AND cc.style_key = e.style_key
)
SELECT
    daily.change_date,
    daily.style_key,
    sty.style_name,
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
JOIN dim_style sty ON sty.style_key = daily.style_key;

CREATE UNIQUE INDEX mv_screener_breadth_uidx
    ON rankalpha.mv_screener_breadth (change_date, style_key);

CREATE INDEX mv_screener_breadth_style_date_idx
    ON rankalpha.mv_screener_breadth (style_key, change_date);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
