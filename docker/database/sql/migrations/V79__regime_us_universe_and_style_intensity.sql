/* ------------------------------------------------------------
   V79__regime_us_universe_and_style_intensity.sql
   - Add daily US-only universe MV (mv_universe_regime_us)
   - Add per-style daily intensity MV (mv_style_intensity_us)
   - Seed styles EarningsPre/EarningsPost if missing
   - Create mapping table for canonical regime names and weights
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

/* ---------- Seed Earnings styles (idempotent) ---------------------- */
INSERT INTO rankalpha.dim_style(style_name, position_side, screener_weight)
SELECT v.style_name, v.position_side, v.screener_weight
FROM (
  VALUES
    ('EarningsPre',  'long', 1.0),
    ('EarningsPost', 'long', 1.0)
) AS v(style_name, position_side, screener_weight)
ON CONFLICT (style_name) DO NOTHING;

/* ---------- Canonical regime mapping (idempotent) ------------------ */
CREATE TABLE IF NOT EXISTS rankalpha.dim_style_regime_map (
  style_key       INTEGER NOT NULL REFERENCES rankalpha.dim_style(style_key) ON DELETE CASCADE,
  canonical_name  TEXT    NOT NULL,
  regime_weight   NUMERIC(6,3) NOT NULL,
  PRIMARY KEY (style_key)
);

/* Seed canonical names and regime weights (Risk-On positive, Risk-Off negative applied later in composition) */
WITH m(style_name, canonical_name, regime_weight) AS (
  VALUES
    ('Momentum',        'Momentum',        1.0),
    ('Pullback',        'Pullback',        0.6),
    ('Growth',          'QualityGrowth',   0.9),
    ('Value',           'ValueGARP',       0.4),
    ('IPO',             'IPO',             0.5),
    ('EarningsPost',    'EarningsPost',    0.6),
    ('ShortSqueeze',    'Squeeze',         0.3),
    ('Short',           'Short',           1.0),
    ('MeanReversion',   'MeanRev',         0.6),
    ('Defensive',       'Defensive',       0.5),
    ('EarningsPre',     'EarningsPre',     0.3)
)
INSERT INTO rankalpha.dim_style_regime_map(style_key, canonical_name, regime_weight)
SELECT s.style_key, m.canonical_name, m.regime_weight
FROM   rankalpha.dim_style s
JOIN   m ON m.style_name = s.style_name
ON CONFLICT (style_key) DO UPDATE
SET canonical_name = EXCLUDED.canonical_name,
    regime_weight  = EXCLUDED.regime_weight;

/* ---------- Universe MV (US-only, point-in-time) ------------------- */
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_universe_regime_us;

CREATE MATERIALIZED VIEW rankalpha.mv_universe_regime_us AS
WITH latest AS (
  SELECT MAX(d.full_date) AS latest_date FROM rankalpha.dim_date d
),
trading_days AS (
  SELECT d.date_key, d.full_date,
         ROW_NUMBER() OVER (ORDER BY d.full_date) AS idx
  FROM rankalpha.dim_date d
  WHERE d.is_trading_day
),
-- helper windows for continuity and 3m average volume (63d)
bars_22 AS (
  SELECT s.stock_key, sp.date_key, COUNT(*) OVER (
           PARTITION BY s.stock_key
           ORDER BY sp.date_key
           ROWS BETWEEN 21 PRECEDING AND CURRENT ROW
         ) AS bars_22
  FROM rankalpha.dim_stock s
  JOIN rankalpha.fact_security_price sp ON sp.stock_key = s.stock_key
),
avgvol_63 AS (
  SELECT s.stock_key, sp.date_key,
         AVG(sp.volume) OVER (
           PARTITION BY s.stock_key
           ORDER BY sp.date_key
           ROWS BETWEEN 62 PRECEDING AND CURRENT ROW
         ) AS avg_vol_63
  FROM rankalpha.dim_stock s
  JOIN rankalpha.fact_security_price sp ON sp.stock_key = s.stock_key
),
latest_px AS (
  SELECT sp.stock_key, sp.date_key, sp.close_px AS close_px
  FROM rankalpha.fact_security_price sp
)
SELECT
  d.date_key,
  ds.stock_key,
  ds.symbol,
  ds.exchange,
  CASE
    WHEN ds.exchange ILIKE ANY (ARRAY['OTC%','OTCQB%','OTCMKTS%','PINK%']) THEN FALSE
    WHEN NOT (ds.exchange ILIKE ANY (ARRAY['NYSE%','NASDAQ%','AMEX%','CBOE%'])) THEN FALSE
    WHEN at.asset_type_name NOT ILIKE 'equity' THEN FALSE -- excludes ETF/ETN/CEF/prefs if typed distinctly
    WHEN lp.close_px IS NULL OR lp.close_px < 10 THEN FALSE
    WHEN av.avg_vol_63 IS NULL OR av.avg_vol_63 < 1000000 THEN FALSE
    WHEN b22.bars_22 IS NULL OR b22.bars_22 < 15 THEN FALSE
    ELSE TRUE
  END AS eligible
FROM trading_days d
CROSS JOIN rankalpha.dim_stock ds
LEFT JOIN rankalpha.dim_asset_type at ON at.asset_type_key = ds.asset_type_key
LEFT JOIN latest_px lp   ON lp.stock_key = ds.stock_key AND lp.date_key = d.date_key
LEFT JOIN avgvol_63 av   ON av.stock_key = ds.stock_key AND av.date_key = d.date_key
LEFT JOIN bars_22  b22   ON b22.stock_key = ds.stock_key AND b22.date_key = d.date_key;

CREATE UNIQUE INDEX IF NOT EXISTS mv_universe_regime_us_pk
  ON rankalpha.mv_universe_regime_us (date_key, stock_key);

CREATE INDEX IF NOT EXISTS mv_universe_regime_us_date_eligible
  ON rankalpha.mv_universe_regime_us (date_key, eligible);

/* ---------- Style Intensity MV (US, max-tier per symbol) ----------- */
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_style_intensity_us;

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
