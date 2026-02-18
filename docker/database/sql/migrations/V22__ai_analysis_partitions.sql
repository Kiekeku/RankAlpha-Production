/* ------------------------------------------------------------------
   V20250701_01__partition_fact_ai_stock_analysis_pk.sql
   DROP + re-CREATE fact_ai_stock_analysis as a RANGE-partitioned table
   with composite PK (date_key, analysis_id), build 2010–2035 partitions,
   and add indexes. Idempotent for an empty table.
   ------------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- 1) Drop any existing parent (and its partitions)
DROP TABLE IF EXISTS rankalpha.fact_ai_stock_analysis CASCADE;

-- 2) Re-create as a partitioned table with composite PK including date_key
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_stock_analysis (
  date_key                int4       NOT NULL
      REFERENCES rankalpha.dim_date(date_key),
  analysis_id             uuid       NOT NULL DEFAULT uuid_generate_v4(),
  stock_key               int4       NOT NULL
      REFERENCES rankalpha.dim_stock(stock_key),
  source_key              int4       NOT NULL
      REFERENCES rankalpha.dim_source(source_key),

  market_cap_usd          numeric(20,2),
  revenue_cagr_3y_pct     numeric(6,2),

  gross_margin_trend_key  int4
      REFERENCES rankalpha.dim_trend_category(trend_key),
  net_margin_trend_key    int4
      REFERENCES rankalpha.dim_trend_category(trend_key),
  free_cash_flow_trend_key int4
      REFERENCES rankalpha.dim_trend_category(trend_key),
  insider_activity_key    int4
      REFERENCES rankalpha.dim_trend_category(trend_key),

  beta_sp500              numeric(6,4),
  rate_sensitivity_bps    numeric(10,2),
  fx_sensitivity          varchar(8),
  commodity_exposure      varchar(8),

  news_sentiment_30d      numeric(5,2),
  social_sentiment_7d     numeric(5,2),
  options_skew_30d        numeric(7,3),
  short_interest_pct_float numeric(6,2),
  employee_glassdoor_score numeric(4,2),
  headline_buzz_score     varchar(6),
  commentary              text,

  overall_rating_key      int4
      REFERENCES rankalpha.dim_rating(rating_key),
  confidence_key          int4
      REFERENCES rankalpha.dim_confidence(confidence_key),
  timeframe_key           int4
      REFERENCES rankalpha.dim_timeframe(timeframe_key),

  load_ts                 timestamptz NOT NULL DEFAULT now(),

  PRIMARY KEY (date_key, analysis_id)
) PARTITION BY RANGE (date_key);


-- 3) Build yearly child partitions for 2010 → 2035
DO $$
BEGIN
  FOR yr IN 2010..2035 LOOP
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_stock_analysis_%1$s
         PARTITION OF rankalpha.fact_ai_stock_analysis
         FOR VALUES FROM (%1$s0101) TO (%2$s0101)',
      yr, yr+1
    );
  END LOOP;
END
$$ LANGUAGE plpgsql;


-- 4) Re-create indexes on the parent (inherited by children)
CREATE INDEX IF NOT EXISTS idx_ai_stock_analysis_stock_date
  ON rankalpha.fact_ai_stock_analysis (stock_key, date_key);

CREATE INDEX IF NOT EXISTS idx_ai_stock_analysis_rating_conf
  ON rankalpha.fact_ai_stock_analysis (overall_rating_key, confidence_key);


-- 5) Re-create indexes on all other fact_ai_* tables
CREATE INDEX IF NOT EXISTS idx_ai_val_metrics_analysis
  ON rankalpha.fact_ai_valuation_metrics (analysis_id);

CREATE INDEX IF NOT EXISTS idx_ai_peer_analysis_pair
  ON rankalpha.fact_ai_peer_comparison (analysis_id, peer_stock_key);

CREATE INDEX IF NOT EXISTS idx_ai_factor_score
  ON rankalpha.fact_ai_factor_score (analysis_id, style_key);

CREATE INDEX IF NOT EXISTS idx_ai_catalyst_type_date
  ON rankalpha.fact_ai_catalyst (analysis_id, catalyst_type, expected_date);

CREATE INDEX IF NOT EXISTS idx_ai_price_scenario_type
  ON rankalpha.fact_ai_price_scenario (analysis_id, scenario_type);

CREATE INDEX IF NOT EXISTS idx_ai_macro_risk_analysis
  ON rankalpha.fact_ai_macro_risk (analysis_id);

CREATE INDEX IF NOT EXISTS idx_ai_headline_risk_analysis
  ON rankalpha.fact_ai_headline_risk (analysis_id);

CREATE INDEX IF NOT EXISTS idx_ai_data_gap_analysis
  ON rankalpha.fact_ai_data_gap (analysis_id);
