/* ------------------------------------------------------------
   V110__mv_screener_flow_us_days_from_ranks.sql
   Fix mv_screener_flow_us returning all-zero rows on days where
   fact_screener_rank hasn't been populated yet.

   Root cause:
     - mv_screener_flow_us "days" is sourced from universe_counts (mv_universe_regime_us),
       which can include dates beyond the latest screener rank snapshot.
     - For those dates, base_today/entered_dropped/continuers are empty, so flow metrics
       appear as 0 across the board, which then contaminates regime rules composites.

   Fix:
     - Restrict days to dates present in base_today (i.e., dates where screener ranks exist).
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- Downstream MV depends on mv_screener_flow_us
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_screener_breadth_flow;

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_screener_flow_us;

CREATE MATERIALIZED VIEW rankalpha.mv_screener_flow_us AS
WITH canon AS (
    SELECT s.style_key, m.canonical_name
    FROM rankalpha.dim_style s
    JOIN rankalpha.dim_style_regime_map m ON m.style_key = s.style_key
),
eligible AS (
    SELECT date_key, stock_key
    FROM rankalpha.mv_universe_regime_us
    WHERE eligible IS TRUE
),
universe_counts AS (
    SELECT date_key, COUNT(*) AS eligible_count
    FROM eligible
    GROUP BY date_key
),
entered_dropped AS (
    SELECT
        c.change_date_key AS date_key,
        COALESCE(cm.canonical_name, sty.style_name) AS canonical_name,
        COUNT(DISTINCT CASE WHEN c.change_type = 'entered' THEN c.stock_key END) AS entered_count,
        COUNT(DISTINCT CASE WHEN c.change_type = 'reentered' THEN c.stock_key END) AS reentered_count,
        COUNT(DISTINCT CASE WHEN c.change_type = 'dropped' THEN c.stock_key END) AS dropped_count
    FROM rankalpha.fact_screener_rank_change c
    JOIN rankalpha.dim_source src
      ON src.source_key = c.source_key
     AND src.exclude_from_screener IS NOT TRUE
    LEFT JOIN rankalpha.dim_style sty ON sty.style_key = c.style_key
    LEFT JOIN canon cm ON cm.style_key = c.style_key
    JOIN eligible e
      ON e.date_key = c.change_date_key
     AND e.stock_key = c.stock_key
    GROUP BY 1,2
),
entered_totals AS (
    SELECT
        date_key,
        canonical_name,
        COALESCE(entered_count, 0) + COALESCE(reentered_count, 0) AS entered_total,
        COALESCE(dropped_count, 0) AS dropped_total
    FROM entered_dropped
),
base_today AS (
    SELECT DISTINCT
        f.date_key,
        f.stock_key,
        COALESCE(cm.canonical_name, sty.style_name) AS canonical_name
    FROM rankalpha.fact_screener_rank f
    JOIN rankalpha.dim_source src
      ON src.source_key = f.source_key
     AND src.exclude_from_screener IS NOT TRUE
    LEFT JOIN rankalpha.dim_style sty ON sty.style_key = f.style_key
    LEFT JOIN canon cm ON cm.style_key = f.style_key
    JOIN eligible e
      ON e.date_key = f.date_key
     AND e.stock_key = f.stock_key
    WHERE COALESCE(cm.canonical_name, sty.style_name) IS NOT NULL
),
trading_days AS (
    SELECT
        d.date_key,
        LAG(d.date_key) OVER (ORDER BY d.date_key) AS prev_date_key
    FROM (
        SELECT DISTINCT date_key FROM base_today
    ) bt
    JOIN rankalpha.dim_date d ON d.date_key = bt.date_key
    WHERE d.is_trading_day
),
continuers AS (
    SELECT
        bt.date_key,
        bt.canonical_name,
        COUNT(*) AS continuers_count
    FROM base_today bt
    JOIN trading_days td
      ON td.date_key = bt.date_key
     AND td.prev_date_key IS NOT NULL
    JOIN base_today prev
      ON prev.date_key = td.prev_date_key
     AND prev.stock_key = bt.stock_key
     AND prev.canonical_name = bt.canonical_name
    GROUP BY bt.date_key, bt.canonical_name
),
canonical_set AS (
    SELECT DISTINCT canonical_name FROM canon
),
days AS (
    SELECT DISTINCT date_key FROM base_today
)
SELECT
    d.date_key,
    cs.canonical_name AS style_name,
    COALESCE(ed.entered_total, 0)::numeric(20,6)      AS entered_count,
    COALESCE(ed.dropped_total, 0)::numeric(20,6)      AS dropped_count,
    COALESCE(cont.continuers_count, 0)::numeric(20,6) AS continuers_count,
    u.eligible_count::numeric(20,6)                   AS eligible_count
FROM days d
CROSS JOIN canonical_set cs
JOIN universe_counts u
  ON u.date_key = d.date_key
LEFT JOIN entered_totals ed
  ON ed.date_key = d.date_key
 AND ed.canonical_name = cs.canonical_name
LEFT JOIN continuers cont
  ON cont.date_key = d.date_key
 AND cont.canonical_name = cs.canonical_name;

CREATE UNIQUE INDEX IF NOT EXISTS mv_screener_flow_us_pk
    ON rankalpha.mv_screener_flow_us (date_key, style_name);

CREATE INDEX IF NOT EXISTS mv_screener_flow_us_style_date
    ON rankalpha.mv_screener_flow_us (style_name, date_key);

/* ------------------------------------------------------------
   Recreate mv_screener_breadth_flow (depends on mv_screener_flow_us)
   ------------------------------------------------------------ */

CREATE MATERIALIZED VIEW rankalpha.mv_screener_breadth_flow AS
SELECT
  d.full_date     AS change_date,
  f.date_key      AS date_key,
  f.style_name    AS canonical_name,
  COALESCE(f.entered_count, 0)::numeric(20,6)    AS entered_count,
  COALESCE(f.dropped_count, 0)::numeric(20,6)    AS dropped_count,
  COALESCE(f.continuers_count, 0)::numeric(20,6) AS continuers_count,
  COALESCE(f.eligible_count, 0)::numeric(20,6)   AS eligible_count,
  CASE WHEN COALESCE(f.eligible_count, 0) > 0 THEN (f.entered_count / f.eligible_count)::numeric(12,6) ELSE 0::numeric(12,6) END AS entered_pct,
  CASE WHEN COALESCE(f.eligible_count, 0) > 0 THEN (f.dropped_count / f.eligible_count)::numeric(12,6) ELSE 0::numeric(12,6) END AS dropped_pct,
  CASE WHEN COALESCE(f.eligible_count, 0) > 0 THEN (f.continuers_count / f.eligible_count)::numeric(12,6) ELSE 0::numeric(12,6) END AS continuers_pct,
  CASE WHEN COALESCE(f.eligible_count, 0) > 0 THEN ((f.entered_count - f.dropped_count) / f.eligible_count)::numeric(12,6) ELSE 0::numeric(12,6) END AS net_pct_us,
  CASE WHEN COALESCE(f.eligible_count, 0) > 0 THEN ((f.entered_count + f.dropped_count) / f.eligible_count)::numeric(12,6) ELSE 0::numeric(12,6) END AS churn_pct
FROM rankalpha.mv_screener_flow_us f
JOIN rankalpha.dim_date d ON d.date_key = f.date_key;

CREATE UNIQUE INDEX IF NOT EXISTS mv_screener_breadth_flow_pk
  ON rankalpha.mv_screener_breadth_flow (date_key, canonical_name);

CREATE INDEX IF NOT EXISTS mv_screener_breadth_flow_style_date
  ON rankalpha.mv_screener_breadth_flow (canonical_name, date_key);
