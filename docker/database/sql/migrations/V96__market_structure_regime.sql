/* ------------------------------------------------------------
   V96__market_structure_regime.sql
   Market Structure (CVD-style) regime facts and convenience view
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- Fact table for Market Structure regime components
CREATE TABLE IF NOT EXISTS rankalpha.fact_regime_market_structure (
  date_key           INTEGER NOT NULL REFERENCES rankalpha.dim_date(date_key),

  -- raw components
  trend_raw          NUMERIC(14,6),              -- t-stat of EW index returns over trend_window (e.g., 50d)
  rv20_ann           NUMERIC(14,6),              -- 20d realized volatility (annualized) of EW index
  corr_pca1_share    NUMERIC(14,6),              -- share of variance explained by PC1 of cross-sectional returns (20d window)
  disp_cs_mad        NUMERIC(14,6),              -- cross-sectional dispersion (robust MAD) of today’s returns

  -- standardized (rolling z over ~252d)
  trend_z            NUMERIC(14,6),
  rv20_z             NUMERIC(14,6),
  corr_z             NUMERIC(14,6),
  disp_z             NUMERIC(14,6),

  label              TEXT NOT NULL,              -- {CalmUptrend, FragileUptrend, Choppy, Risk-Off, Neutral}
  load_ts            TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
  PRIMARY KEY (date_key)
);

CREATE INDEX IF NOT EXISTS idx_fact_regime_ms_date
  ON rankalpha.fact_regime_market_structure (date_key);

-- Convenience view joining date
DROP VIEW IF EXISTS rankalpha.vw_regime_market_structure;
CREATE VIEW rankalpha.vw_regime_market_structure AS
SELECT d.full_date AS as_of_date,
       f.*
FROM rankalpha.fact_regime_market_structure f
JOIN rankalpha.dim_date d ON d.date_key = f.date_key;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

