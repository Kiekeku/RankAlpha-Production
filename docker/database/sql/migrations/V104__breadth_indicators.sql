-- V100__breadth_indicators.sql
-- Seed derived breadth indicator series and expose a convenience view.

-- 1) Ensure a source row for internally derived indicators
INSERT INTO rankalpha.dim_source (source_name, version, exclude_from_screener, screener_weight)
VALUES ('RankAlphaDerived', '1', false, 1.0)
ON CONFLICT (source_name) DO NOTHING;

-- 2) Seed dim_macro_series rows for derived breadth indicators
INSERT INTO rankalpha.dim_macro_series (series_code, series_name, category, frequency, units, is_active)
VALUES
    ('US_NYA_HINDENBURG_OMEN_RAW',               'NYSE Hindenburg Omen (raw)',                    'breadth', 'D', 'flag',  true),
    ('US_NYA_HINDENBURG_OMEN_CONFIRMED',         'NYSE Hindenburg Omen (confirmed cluster)',      'breadth', 'D', 'flag',  true),
    ('US_NYSE_HLLI',                             'NYSE Fosback High-Low Logic Index',             'breadth', 'D', 'index', true),

    ('US_SPX_NET_NEW_HIGHS',                     'S&P 500 Net New Highs (ratio)',                 'breadth', 'D', 'ratio', true),
    ('US_NDX_NET_NEW_HIGHS',                     'Nasdaq-100 Net New Highs (ratio)',              'breadth', 'D', 'ratio', true),

    ('US_SPX_WHALEY_ADT5',                       'S&P 500 Whaley ADT-5',                          'breadth', 'D', 'ratio', true),
    ('US_SPX_WHALEY_ADT5_BULL_FLAG',             'S&P 500 Whaley ADT-5 Bull Flag',                'breadth', 'D', 'flag',  true),
    ('US_SPX_WHALEY_ADT5_CAPITULATION_FLAG',     'S&P 500 Whaley ADT-5 Capitulation Flag',        'breadth', 'D', 'flag',  true),
    ('US_NDX_WHALEY_ADT5',                       'Nasdaq-100 Whaley ADT-5',                       'breadth', 'D', 'ratio', true),
    ('US_NDX_WHALEY_ADT5_BULL_FLAG',             'Nasdaq-100 Whaley ADT-5 Bull Flag',             'breadth', 'D', 'flag',  true),
    ('US_NDX_WHALEY_ADT5_CAPITULATION_FLAG',     'Nasdaq-100 Whaley ADT-5 Capitulation Flag',     'breadth', 'D', 'flag',  true),

    ('US_SPX_BAM10_UP_FLAG',                     'S&P 500 Deemer Breakaway Momentum 10D Up',      'breadth', 'D', 'flag',  true),
    ('US_SPX_BAM10_DOWN_FLAG',                   'S&P 500 Deemer Breakaway Momentum 10D Down',    'breadth', 'D', 'flag',  true),
    ('US_NDX_BAM10_UP_FLAG',                     'Nasdaq-100 Deemer Breakaway Momentum 10D Up',   'breadth', 'D', 'flag',  true),
    ('US_NDX_BAM10_DOWN_FLAG',                   'Nasdaq-100 Deemer Breakaway Momentum 10D Down', 'breadth', 'D', 'flag',  true),

    ('US_SPX_MCCLELLAN_THRUST_FLAG',             'S&P 500 McClellan Thrust (10d, -100/+100)',     'breadth', 'D', 'flag',  true),
    ('US_NDX_MCCLELLAN_THRUST_FLAG',             'Nasdaq-100 McClellan Thrust (10d, -100/+100)',  'breadth', 'D', 'flag',  true),
    ('US_SPX_MCCLELLAN_SUM_BREAKDOWN_FLAG',      'S&P 500 McClellan Summation Breakdown',         'breadth', 'D', 'flag',  true),
    ('US_NDX_MCCLELLAN_SUM_BREAKDOWN_FLAG',      'Nasdaq-100 McClellan Summation Breakdown',      'breadth', 'D', 'flag',  true),

    ('US_NYSE_PERSISTENT_NEW_LOWS_FLAG',         'NYSE Persistent New Lows (>=5% for 3d)',        'breadth', 'D', 'flag',  true),
    ('US_SPX_PERSISTENT_NEW_LOWS_FLAG',          'S&P 500 Persistent New Lows (>=5% for 3d)',     'breadth', 'D', 'flag',  true),
    ('US_NDX_PERSISTENT_NEW_LOWS_FLAG',          'Nasdaq-100 Persistent New Lows (>=5% for 3d)',  'breadth', 'D', 'flag',  true),

    ('US_SPX_PCT_ABOVE_200D_THRUST_FLAG',        'S&P 500 %>200D Thrust (+20pp/10d)',             'breadth', 'D', 'flag',  true),
    ('US_SPX_PCT_BELOW_200D_COLLAPSE_FLAG',      'S&P 500 %<200D Collapse (+20pp/10d)',           'breadth', 'D', 'flag',  true),
    ('US_NDX_PCT_ABOVE_200D_THRUST_FLAG',        'Nasdaq-100 %>200D Thrust (+20pp/10d)',          'breadth', 'D', 'flag',  true),
    ('US_NDX_PCT_BELOW_200D_COLLAPSE_FLAG',      'Nasdaq-100 %<200D Collapse (+20pp/10d)',        'breadth', 'D', 'flag',  true),

    ('US_SPX_TRIN_STRESS_FLAG',                  'S&P 500 TRIN Stress',                           'breadth', 'D', 'flag',  true),
    ('US_NDX_TRIN_STRESS_FLAG',                  'Nasdaq-100 TRIN Stress',                        'breadth', 'D', 'flag',  true),
    ('US_NYSE_TRIN_STRESS_FLAG',                 'NYSE TRIN Stress',                              'breadth', 'D', 'flag',  true),

    ('US_SPX_AD_BEARISH_DIVERGENCE_FLAG',        'S&P 500 A/D Line Bearish Divergence',           'breadth', 'D', 'flag',  true),
    ('US_NDX_AD_BEARISH_DIVERGENCE_FLAG',        'Nasdaq-100 A/D Line Bearish Divergence',        'breadth', 'D', 'flag',  true)
ON CONFLICT (series_code) DO NOTHING;

-- 3) Convenience view for breadth signals (derived indicators only)
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
    'US_NDX_AD_BEARISH_DIVERGENCE_FLAG'
);

