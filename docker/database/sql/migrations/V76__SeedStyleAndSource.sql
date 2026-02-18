SET search_path = rankalpha, public;

WITH style_payload(style_name, position_side, screener_weight) AS (
    VALUES
        ('Momentum',        'long', 1.0000),
        ('Pullback',        'long', 0.8000),
        ('MeanReversion',   'long', 0.6000),
        ('Growth',          'long', 1.0000),
        ('Value',           'long', 0.8000),
        ('ShortSqueeze',    'long', 0.7000),
        ('Earnings',        'long', 0.8000),
        ('IPO',             'long', 0.6000),
        ('Defensive',       'long', 0.5000),
        ('Short',           'short',0.8000)
)
INSERT INTO dim_style (style_name, position_side, screener_weight)
SELECT p.style_name, p.position_side, p.screener_weight
FROM style_payload p
ON CONFLICT (style_name)
DO UPDATE
SET position_side   = EXCLUDED.position_side,
    screener_weight = EXCLUDED.screener_weight;


WITH source_payload(source_name, version, exclude_from_screener, screener_weight) AS (
    VALUES
        ('RA-Momo-50DayBreakout',            '1', FALSE, 1.0000),
        ('RA-Momo-NearHighContinuation',     '1', FALSE, 1.0000),
        ('RA-Momo-Fresh52wBreakout',         '1', FALSE, 1.2000),
        ('RA-PullBack-Under50Over200',       '1', FALSE, 1.0000),
        ('RA-PullBack-ChannelUpWeeklyDown',  '1', FALSE, 0.8000),
        ('RA-MeanReversion-OversoldPop',     '1', FALSE, 1.0000),
        ('RA-MeanReversion-OversoldUptrend', '1', FALSE, 0.8000),
        ('RA-QualityGrowth-EPS',             '1', FALSE, 1.2000),
        ('RA-QualityGrowth-Trend',           '1', FALSE, 0.8000),
        ('RA-Value-Quality',                 '1', FALSE, 1.2000),
        ('RA-Value-Dividend',                '1', FALSE, 1.0000),
        ('RA-Value-IncomeQuality',           '1', FALSE, 0.8000),
        ('RA-ShortSqueeze-OnTheMove',        '1', FALSE, 1.0000),
        ('RA-ShortSqueeze-NearHigh',         '1', FALSE, 0.8000),
        ('RA-Earnings-PreSqueeze',           '1', FALSE, 1.0000),
        ('RA-Earnings-PostMomo',             '1', FALSE, 1.0000),
        ('RA-IPO-Momo',                      '1', FALSE, 1.0000),
        ('RA-Quality-LowBeta',               '1', FALSE, 0.8000),
        ('RA-Short-MomoBreakdown',           '1', FALSE, 1.0000),
        ('RA-Short-Resistance',              '1', FALSE, 0.8000)
)
INSERT INTO dim_source (
    source_name,
    version,
    exclude_from_screener,
    screener_weight
)
SELECT p.source_name, p.version, p.exclude_from_screener, p.screener_weight
FROM source_payload p
ON CONFLICT (source_name)
DO UPDATE
SET version               = EXCLUDED.version,
    exclude_from_screener = EXCLUDED.exclude_from_screener,
    screener_weight       = EXCLUDED.screener_weight;
