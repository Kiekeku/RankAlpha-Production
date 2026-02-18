-- Rebuild US regime universe/materialized views to avoid Cartesian growth.
-- This version anchors on fact_security_price rows instead of day × stock cross joins,
-- dramatically reducing refresh cost while preserving the eligibility policy.

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_style_intensity_us;
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_universe_regime_us;

CREATE MATERIALIZED VIEW rankalpha.mv_universe_regime_us AS
WITH price_enriched AS (
    SELECT
        sp.date_key,
        sp.stock_key,
        sp.close_px,
        COUNT(*) OVER (
            PARTITION BY sp.stock_key
            ORDER BY sp.date_key
            ROWS BETWEEN 21 PRECEDING AND CURRENT ROW
        ) AS bars_22,
        AVG(sp.volume) OVER (
            PARTITION BY sp.stock_key
            ORDER BY sp.date_key
            ROWS BETWEEN 62 PRECEDING AND CURRENT ROW
        ) AS avg_vol_63
    FROM rankalpha.fact_security_price sp
)
SELECT
    pe.date_key,
    pe.stock_key,
    ds.symbol,
    ds.exchange,
    CASE
        WHEN ds.exchange ILIKE ANY (ARRAY['OTC%','OTCQB%','OTCMKTS%','PINK%']) THEN FALSE
        WHEN NOT (ds.exchange ILIKE ANY (ARRAY['NYSE%','NASDAQ%','AMEX%','CBOE%'])) THEN FALSE
        WHEN at.asset_type_name NOT ILIKE 'equity' THEN FALSE
        WHEN pe.close_px IS NULL OR pe.close_px < 10 THEN FALSE
        WHEN pe.avg_vol_63 IS NULL OR pe.avg_vol_63 < 1000000 THEN FALSE
        WHEN pe.bars_22 IS NULL OR pe.bars_22 < 15 THEN FALSE
        ELSE TRUE
    END AS eligible
FROM price_enriched pe
JOIN rankalpha.dim_stock ds ON ds.stock_key = pe.stock_key
LEFT JOIN rankalpha.dim_asset_type at ON at.asset_type_key = ds.asset_type_key
JOIN rankalpha.dim_date d ON d.date_key = pe.date_key
WHERE d.is_trading_day;

CREATE UNIQUE INDEX IF NOT EXISTS mv_universe_regime_us_pk
    ON rankalpha.mv_universe_regime_us (date_key, stock_key);

CREATE INDEX IF NOT EXISTS mv_universe_regime_us_date_eligible
    ON rankalpha.mv_universe_regime_us (date_key, eligible);

CREATE MATERIALIZED VIEW rankalpha.mv_style_intensity_us AS
WITH canon AS (
    SELECT s.style_key, m.canonical_name
    FROM rankalpha.dim_style s
    JOIN rankalpha.dim_style_regime_map m ON m.style_key = s.style_key
),
base AS (
    SELECT f.date_key,
           ds.stock_key,
           ds.symbol,
           c.canonical_name,
           src.screener_weight AS tier
    FROM   rankalpha.fact_screener_rank f
    JOIN   rankalpha.dim_stock ds    ON ds.stock_key = f.stock_key
    JOIN   rankalpha.dim_source src  ON src.source_key = f.source_key AND src.exclude_from_screener IS NOT TRUE
    JOIN   rankalpha.dim_style sty   ON sty.style_key = f.style_key
    JOIN   canon c                   ON c.style_key = sty.style_key
    JOIN   rankalpha.mv_universe_regime_us u
             ON u.date_key = f.date_key AND u.stock_key = f.stock_key AND u.eligible IS TRUE
),
per_symbol_style AS (
    SELECT date_key, canonical_name, stock_key, MAX(tier) AS max_tier
    FROM base
    GROUP BY date_key, canonical_name, stock_key
),
universe_counts AS (
    SELECT date_key, COUNT(*) AS u_count
    FROM rankalpha.mv_universe_regime_us
    WHERE eligible IS TRUE
    GROUP BY date_key
),
sum_by_style AS (
    SELECT date_key, canonical_name, SUM(max_tier) AS total_tier
    FROM per_symbol_style
    GROUP BY date_key, canonical_name
),
canonical_set AS (
    SELECT DISTINCT canonical_name FROM rankalpha.dim_style_regime_map
),
days AS (
    SELECT DISTINCT date_key FROM universe_counts
)
SELECT d.date_key,
       cs.canonical_name AS style_name,
       (COALESCE(s.total_tier, 0))::numeric(12,6) / NULLIF(u.u_count, 0) AS intensity_raw,
       u.u_count AS universe_count
FROM days d
CROSS JOIN canonical_set cs
JOIN universe_counts u ON u.date_key = d.date_key
LEFT JOIN sum_by_style s ON s.date_key = d.date_key AND s.canonical_name = cs.canonical_name;

CREATE UNIQUE INDEX IF NOT EXISTS mv_style_intensity_us_pk
    ON rankalpha.mv_style_intensity_us (date_key, style_name);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
