/* ------------------------------------------------------------
   V32__technical_indicators.sql
   Technical indicator storage and convenience view
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE TABLE IF NOT EXISTS rankalpha.fact_technical_indicator (
  date_key        int4 NOT NULL REFERENCES rankalpha.dim_date(date_key),
  stock_key       int4 NOT NULL REFERENCES rankalpha.dim_stock(stock_key),
  indicator_code  varchar(40) NOT NULL,   -- e.g., SMA20, RSI14, MACD, MACD_SIGNAL, BB_UPPER
  value           numeric(20,6),
  load_ts         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (date_key, stock_key, indicator_code)
);

CREATE INDEX IF NOT EXISTS idx_fti_symbol_date
  ON rankalpha.fact_technical_indicator (stock_key, date_key);

-- Latest-day snapshot pivot for common indicators
CREATE OR REPLACE VIEW rankalpha.vw_latest_technicals AS
WITH latest AS (
  SELECT MAX(date_key) AS max_date FROM rankalpha.fact_technical_indicator
)
SELECT
  d.full_date              AS as_of_date,
  s.symbol,
  s.company_name,
  MAX(value) FILTER (WHERE indicator_code = 'SMA20')      AS sma20,
  MAX(value) FILTER (WHERE indicator_code = 'SMA50')      AS sma50,
  MAX(value) FILTER (WHERE indicator_code = 'SMA200')     AS sma200,
  MAX(value) FILTER (WHERE indicator_code = 'EMA12')      AS ema12,
  MAX(value) FILTER (WHERE indicator_code = 'EMA26')      AS ema26,
  MAX(value) FILTER (WHERE indicator_code = 'RSI14')      AS rsi14,
  MAX(value) FILTER (WHERE indicator_code = 'ATR14')      AS atr14,
  MAX(value) FILTER (WHERE indicator_code = 'BB_UPPER')   AS bb_upper,
  MAX(value) FILTER (WHERE indicator_code = 'BB_MIDDLE')  AS bb_middle,
  MAX(value) FILTER (WHERE indicator_code = 'BB_LOWER')   AS bb_lower,
  MAX(value) FILTER (WHERE indicator_code = 'MACD')       AS macd,
  MAX(value) FILTER (WHERE indicator_code = 'MACD_SIGNAL') AS macd_signal,
  MAX(value) FILTER (WHERE indicator_code = 'MACD_HIST')  AS macd_hist,
  MAX(value) FILTER (WHERE indicator_code = 'RET_5D')     AS ret_5d,
  MAX(value) FILTER (WHERE indicator_code = 'RET_20D')    AS ret_20d,
  MAX(value) FILTER (WHERE indicator_code = 'RET_60D')    AS ret_60d,
  MAX(value) FILTER (WHERE indicator_code = 'RET_120D')   AS ret_120d,
  MAX(value) FILTER (WHERE indicator_code = 'VOL_Z20')    AS vol_z20,
  MAX(value) FILTER (WHERE indicator_code = 'DIST_52W_HIGH') AS dist_52w_high
FROM rankalpha.fact_technical_indicator f
JOIN latest ON f.date_key = latest.max_date
JOIN rankalpha.dim_stock s ON s.stock_key = f.stock_key
JOIN rankalpha.dim_date  d ON d.date_key  = f.date_key
GROUP BY d.full_date, s.symbol, s.company_name;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

