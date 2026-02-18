/* ------------------------------------------------------------
   V106__usd_dxy_regime_series.sql
   - Seed $USDX benchmark row
   - Register DXY-derived macro series (level, trend, ROC, percentiles, regime)
   - Convenience view vw_dxy_signals
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

/* ---------- 1) Benchmark seed ---------------------------------------- */
INSERT INTO rankalpha.dim_benchmark (benchmark_name, currency_code, description)
VALUES ('$USDX', 'USD', 'US Dollar Index (DXY / USDX)')
ON CONFLICT (benchmark_name) DO NOTHING;

/* ---------- 2) Macro series catalogue entries ------------------------ */
INSERT INTO rankalpha.dim_macro_series (series_code, series_name, category, frequency, units, is_active)
VALUES
  ('US_DXY_LEVEL',             'US Dollar Index level',                    'fx',     'D', 'index_level', true),
  ('US_DXY_MA50',              'US Dollar Index 50d MA',                   'fx',     'D', 'index_level', true),
  ('US_DXY_MA100',             'US Dollar Index 100d MA',                  'fx',     'D', 'index_level', true),
  ('US_DXY_MA200',             'US Dollar Index 200d MA',                  'fx',     'D', 'index_level', true),
  ('US_DXY_ROC_1M',            'US Dollar Index 1M ROC',                   'fx',     'D', 'percent',     true),
  ('US_DXY_ROC_3M',            'US Dollar Index 3M ROC',                   'fx',     'D', 'percent',     true),
  ('US_DXY_ROC_6M',            'US Dollar Index 6M ROC',                   'fx',     'D', 'percent',     true),
  ('US_DXY_Z_3Y',              'US Dollar Index 3Y z-score',               'fx',     'D', 'z_score',     true),
  ('US_DXY_PCTL_5Y',           'US Dollar Index 5Y percentile',            'fx',     'D', 'percentile',  true),
  ('US_DXY_REGIME_STATE',      'US Dollar Index regime state (-1/0/+1)',   'regime', 'D', 'index',       true),
  ('US_DXY_SHOCK_UP_FLAG',     'US Dollar Index upside shock flag',        'regime', 'D', 'flag',        true),
  ('US_DXY_SHOCK_DOWN_FLAG',   'US Dollar Index downside shock flag',      'regime', 'D', 'flag',        true),
  ('US_DXY_RISK_SCORE',        'US Dollar Index regime risk score (0-1)',  'regime', 'D', 'index',       true)
ON CONFLICT (series_code) DO NOTHING;

/* ---------- 3) Convenience view -------------------------------------- */
DROP VIEW IF EXISTS rankalpha.vw_dxy_signals;
CREATE VIEW rankalpha.vw_dxy_signals AS
SELECT
    d.full_date AS as_of_date,
    m.series_code,
    m.series_name,
    m.category,
    m.frequency,
    m.units,
    f.value,
    f.source_key,
    f.load_ts
FROM rankalpha.fact_macro_series f
JOIN rankalpha.dim_macro_series m ON m.series_key = f.series_key
JOIN rankalpha.dim_date d ON d.date_key = f.date_key
WHERE m.series_code IN (
    'US_DXY_LEVEL',
    'US_DXY_MA50',
    'US_DXY_MA100',
    'US_DXY_MA200',
    'US_DXY_ROC_1M',
    'US_DXY_ROC_3M',
    'US_DXY_ROC_6M',
    'US_DXY_Z_3Y',
    'US_DXY_PCTL_5Y',
    'US_DXY_REGIME_STATE',
    'US_DXY_SHOCK_UP_FLAG',
    'US_DXY_SHOCK_DOWN_FLAG',
    'US_DXY_RISK_SCORE'
);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
