-- Adds change-tracking storage for screener deltas and supporting materialized view.

CREATE TABLE IF NOT EXISTS rankalpha.fact_screener_rank_change (
    change_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    change_date_key INTEGER NOT NULL REFERENCES rankalpha.dim_date(date_key),
    stock_key INTEGER NOT NULL REFERENCES rankalpha.dim_stock(stock_key),
    source_key INTEGER NOT NULL REFERENCES rankalpha.dim_source(source_key),
    style_key INTEGER REFERENCES rankalpha.dim_style(style_key),
    change_type TEXT NOT NULL CHECK (change_type IN ('entered', 'reentered', 'dropped')),
    current_rank INTEGER,
    previous_rank INTEGER,
    rank_delta INTEGER,
    last_seen_date_key INTEGER REFERENCES rankalpha.dim_date(date_key),
    days_since_last_seen INTEGER,
    absent_trading_days INTEGER,
    load_ts TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (change_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_screener_rank_change_dim
    ON rankalpha.fact_screener_rank_change (change_date_key, stock_key, source_key, COALESCE(style_key, -1), change_type);

CREATE INDEX IF NOT EXISTS idx_fact_screener_rank_change_date
    ON rankalpha.fact_screener_rank_change (change_date_key);

CREATE INDEX IF NOT EXISTS idx_fact_screener_rank_change_type_date
    ON rankalpha.fact_screener_rank_change (change_type, change_date_key);

CREATE INDEX IF NOT EXISTS idx_fact_screener_rank_change_stock
    ON rankalpha.fact_screener_rank_change (stock_key, change_date_key DESC);

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
    CROSS JOIN day_keys dk
    WHERE dk.date_d0 IS NOT NULL
      AND f.date_key < dk.date_d0
    GROUP BY 1,2,3
),
last_seen_before_window AS (
    SELECT f.stock_key,
           f.source_key,
           f.style_key,
           MAX(f.date_key) AS last_seen_date_key
    FROM rankalpha.fact_screener_rank f
    CROSS JOIN day_keys dk
    WHERE dk.date_d3 IS NOT NULL
      AND f.date_key < dk.date_d3
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
    CROSS JOIN day_keys dk
    WHERE dk.date_d0 IS NOT NULL
      AND f.date_key < dk.date_d0
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
          AND ((lsw.style_key IS NULL AND w.style_key IS NULL)
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
       c.style_key,
       st.style_name,
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
JOIN rankalpha.dim_source so ON so.source_key = c.source_key
LEFT JOIN rankalpha.dim_style st ON st.style_key = c.style_key
LEFT JOIN rankalpha.dim_date dls ON dls.date_key = c.last_seen_date_key;

CREATE UNIQUE INDEX IF NOT EXISTS mv_screener_changes_pk
    ON rankalpha.mv_screener_changes (change_date_key, stock_key, source_key, COALESCE(style_key, -1), change_type);

CREATE INDEX IF NOT EXISTS mv_screener_changes_symbol
    ON rankalpha.mv_screener_changes (symbol, change_date DESC);

CREATE INDEX IF NOT EXISTS mv_screener_changes_type
    ON rankalpha.mv_screener_changes (change_type, change_date DESC);
