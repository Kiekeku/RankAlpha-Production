-- V101__breadth_regime_series.sql
-- Add regime-level breadth series and refresh the breadth view.

-- 1) dim_macro_series additions for regime signals
INSERT INTO rankalpha.dim_macro_series (series_code, series_name, category, frequency, units, is_active)
VALUES
    ('US_SPX_BREADTH_THRUST_SCORE',        'S&P 500 Breadth Thrust Score',        'breadth', 'D', 'index', true),
    ('US_SPX_BREADTH_FRAG_SCORE',          'S&P 500 Breadth Fragility Score',     'breadth', 'D', 'index', true),
    ('US_SPX_BREADTH_NET_SCORE',           'S&P 500 Breadth Net Score',           'breadth', 'D', 'index', true),
    ('US_SPX_BREADTH_REGIME_STATE',        'S&P 500 Breadth Regime State',        'breadth', 'D', 'index', true),
    ('US_SPX_BREADTH_TARGET_EXPOSURE',     'S&P 500 Breadth Target Exposure',     'breadth', 'D', 'index', true),
    ('US_NDX_BREADTH_THRUST_SCORE',        'Nasdaq-100 Breadth Thrust Score',     'breadth', 'D', 'index', true),
    ('US_NDX_BREADTH_FRAG_SCORE',          'Nasdaq-100 Breadth Fragility Score',  'breadth', 'D', 'index', true),
    ('US_NDX_BREADTH_NET_SCORE',           'Nasdaq-100 Breadth Net Score',        'breadth', 'D', 'index', true),
    ('US_NDX_BREADTH_REGIME_STATE',        'Nasdaq-100 Breadth Regime State',     'breadth', 'D', 'index', true),
    ('US_NDX_BREADTH_TARGET_EXPOSURE',     'Nasdaq-100 Breadth Target Exposure',  'breadth', 'D', 'index', true)
ON CONFLICT (series_code) DO NOTHING;

-- 2) Recreate breadth view to include regime series
DROP VIEW IF EXISTS rankalpha.vw_breadth_signals;
CREATE VIEW rankalpha.vw_breadth_signals AS
SELECT
    d.full_date        AS as_of_date,
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
    'US_NYA_HINDENBURG_OMEN_RAW',
    'US_NYA_HINDENBURG_OMEN_CONFIRMED',
    'US_NYSE_HLLI',
    'US_SPX_NET_NEW_HIGHS',
    'US_NDX_NET_NEW_HIGHS',
    'US_SPX_WHALEY_ADT5',
    'US_SPX_WHALEY_ADT5_BULL_FLAG',
    'US_SPX_WHALEY_ADT5_CAPITULATION_FLAG',
    'US_NDX_WHALEY_ADT5',
    'US_NDX_WHALEY_ADT5_BULL_FLAG',
    'US_NDX_WHALEY_ADT5_CAPITULATION_FLAG',
    'US_SPX_BAM10_UP_FLAG',
    'US_SPX_BAM10_DOWN_FLAG',
    'US_NDX_BAM10_UP_FLAG',
    'US_NDX_BAM10_DOWN_FLAG',
    'US_SPX_MCCLELLAN_THRUST_FLAG',
    'US_NDX_MCCLELLAN_THRUST_FLAG',
    'US_SPX_MCCLELLAN_SUM_BREAKDOWN_FLAG',
    'US_NDX_MCCLELLAN_SUM_BREAKDOWN_FLAG',
    'US_NYSE_PERSISTENT_NEW_LOWS_FLAG',
    'US_SPX_PERSISTENT_NEW_LOWS_FLAG',
    'US_NDX_PERSISTENT_NEW_LOWS_FLAG',
    'US_SPX_PCT_ABOVE_200D_THRUST_FLAG',
    'US_SPX_PCT_BELOW_200D_COLLAPSE_FLAG',
    'US_NDX_PCT_ABOVE_200D_THRUST_FLAG',
    'US_NDX_PCT_BELOW_200D_COLLAPSE_FLAG',
    'US_SPX_TRIN_STRESS_FLAG',
    'US_NDX_TRIN_STRESS_FLAG',
    'US_NYSE_TRIN_STRESS_FLAG',
    'US_SPX_AD_BEARISH_DIVERGENCE_FLAG',
    'US_NDX_AD_BEARISH_DIVERGENCE_FLAG',
    'US_SPX_BREADTH_THRUST_SCORE',
    'US_SPX_BREADTH_FRAG_SCORE',
    'US_SPX_BREADTH_NET_SCORE',
    'US_SPX_BREADTH_REGIME_STATE',
    'US_SPX_BREADTH_TARGET_EXPOSURE',
    'US_NDX_BREADTH_THRUST_SCORE',
    'US_NDX_BREADTH_FRAG_SCORE',
    'US_NDX_BREADTH_NET_SCORE',
    'US_NDX_BREADTH_REGIME_STATE',
    'US_NDX_BREADTH_TARGET_EXPOSURE'
);

