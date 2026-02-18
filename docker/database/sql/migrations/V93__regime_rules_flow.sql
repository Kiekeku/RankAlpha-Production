/* ------------------------------------------------------------
   V93__regime_rules_flow.sql
   - Flow-based screener metrics for regime rules
   - Pullback transition telemetry
   - Config + fact tables for rule-driven regime outputs
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

/* ------------------------------------------------------------
   Flow metrics per canonical style (US-only eligible universe)
   ------------------------------------------------------------ */
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
    SELECT date_key FROM universe_counts
)
SELECT
    d.date_key,
    cs.canonical_name AS style_name,
    COALESCE(ed.entered_total, 0)::numeric(20,6)     AS entered_count,
    COALESCE(ed.dropped_total, 0)::numeric(20,6)     AS dropped_count,
    COALESCE(cont.continuers_count, 0)::numeric(20,6) AS continuers_count,
    u.eligible_count::numeric(20,6)                  AS eligible_count
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
   Pullback transition diagnostics (t -> t+1)
   ------------------------------------------------------------ */
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_style_transition_us;

CREATE MATERIALIZED VIEW rankalpha.mv_style_transition_us AS
WITH canon AS (
    SELECT s.style_key, m.canonical_name
    FROM rankalpha.dim_style s
    JOIN rankalpha.dim_style_regime_map m ON m.style_key = s.style_key
),
base AS (
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
    JOIN rankalpha.mv_universe_regime_us u
      ON u.date_key = f.date_key
     AND u.stock_key = f.stock_key
     AND u.eligible IS TRUE
    WHERE COALESCE(cm.canonical_name, sty.style_name) IS NOT NULL
),
trading_days AS (
    SELECT
        d.date_key,
        LEAD(d.date_key) OVER (ORDER BY d.date_key) AS next_date_key
    FROM (
        SELECT DISTINCT date_key FROM base
    ) bt
    JOIN rankalpha.dim_date d ON d.date_key = bt.date_key
    WHERE d.is_trading_day
),
pullback_today AS (
    SELECT b.date_key, b.stock_key
    FROM base b
    WHERE b.canonical_name = 'Pullback'
),
transitions AS (
    SELECT
        pt.date_key,
        COUNT(*) AS pullback_count,
        COUNT(*) FILTER (WHERE nxt.canonical_name = 'Momentum') AS pull_to_momentum,
        COUNT(*) FILTER (WHERE nxt.canonical_name = 'Short')    AS pull_to_short
    FROM pullback_today pt
    JOIN trading_days td
      ON td.date_key = pt.date_key
     AND td.next_date_key IS NOT NULL
    LEFT JOIN base nxt
      ON nxt.date_key = td.next_date_key
     AND nxt.stock_key = pt.stock_key
    GROUP BY pt.date_key
)
SELECT
    td.date_key,
    COALESCE(tr.pullback_count, 0)::numeric(20,6)     AS pullback_count,
    COALESCE(tr.pull_to_momentum, 0)::numeric(20,6)   AS pull_to_momentum,
    COALESCE(tr.pull_to_short, 0)::numeric(20,6)      AS pull_to_short
FROM trading_days td
LEFT JOIN transitions tr ON tr.date_key = td.date_key;

CREATE UNIQUE INDEX IF NOT EXISTS mv_style_transition_us_pk
    ON rankalpha.mv_style_transition_us (date_key);

/* ------------------------------------------------------------
   Config + fact storage for rule-based regimes
   ------------------------------------------------------------ */
CREATE TABLE IF NOT EXISTS rankalpha.regime_rules_config (
    config_key TEXT PRIMARY KEY,
    z_window_days INTEGER NOT NULL DEFAULT 252,
    rs_window_days INTEGER NOT NULL DEFAULT 126,
    rs_weight_mb NUMERIC(8,4) NOT NULL DEFAULT 1.0,
    rs_weight_bb NUMERIC(8,4) NOT NULL DEFAULT -0.9,
    rs_weight_mri NUMERIC(8,4) NOT NULL DEFAULT -0.4,
    rs_weight_db NUMERIC(8,4) NOT NULL DEFAULT -0.5,
    rs_trend_threshold NUMERIC(8,4) NOT NULL DEFAULT 0.5,
    rs_riskoff_threshold NUMERIC(8,4) NOT NULL DEFAULT -0.5,
    defensive_pct_threshold NUMERIC(8,4) NOT NULL DEFAULT 0.8,
    mania_pct_threshold NUMERIC(8,4) NOT NULL DEFAULT 0.9,
    ps_veto_threshold NUMERIC(8,4) NOT NULL DEFAULT 0.0,
    hysteresis_days INTEGER NOT NULL DEFAULT 3,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
);

INSERT INTO rankalpha.regime_rules_config (config_key)
VALUES ('default')
ON CONFLICT (config_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS rankalpha.fact_regime_rules (
    date_key INTEGER NOT NULL REFERENCES rankalpha.dim_date(date_key),
    mb NUMERIC(14,6),
    bb NUMERIC(14,6),
    mri NUMERIC(14,6),
    db NUMERIC(14,6),
    tt NUMERIC(14,6),
    mrp NUMERIC(14,6),
    rop NUMERIC(14,6),
    dt NUMERIC(14,6),
    ps NUMERIC(14,6),
    tb NUMERIC(14,6),
    rs NUMERIC(14,6),
    rs_smooth NUMERIC(14,6),
    label TEXT NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}'::text[],
    config_version TEXT NOT NULL,
    load_ts TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (date_key)
);

CREATE INDEX IF NOT EXISTS idx_fact_regime_rules_date
    ON rankalpha.fact_regime_rules (date_key);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
