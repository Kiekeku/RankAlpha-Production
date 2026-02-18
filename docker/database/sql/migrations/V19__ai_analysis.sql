/* ------------------------------------------------------------
   AI STOCK ANALYSIS – STAR‑SCHEMA SUPPORT
   ------------------------------------------------------------ */

/* ============== 1. SMALL ENUM DIMENSIONS ================== */

-- 1.1 Asset‑type (needed for ETF / Crypto tagging)
CREATE TABLE IF NOT EXISTS rankalpha.dim_asset_type (
    asset_type_key serial PRIMARY KEY,
    asset_type_name varchar(20) UNIQUE NOT NULL
);

INSERT INTO rankalpha.dim_asset_type(asset_type_name)
SELECT unnest(ARRAY['equity','etf','crypto','other'])
ON CONFLICT DO NOTHING;

-- 1.2 Overall rating
CREATE TABLE IF NOT EXISTS rankalpha.dim_rating (
    rating_key  serial PRIMARY KEY,
    rating_label varchar(20) UNIQUE NOT NULL
);

INSERT INTO rankalpha.dim_rating(rating_label)
SELECT unnest(ARRAY['strong_buy','buy','neutral','sell','strong_sell'])
ON CONFLICT DO NOTHING;

-- 1.3 Confidence level
CREATE TABLE IF NOT EXISTS rankalpha.dim_confidence (
    confidence_key serial PRIMARY KEY,
    confidence_label varchar(10) UNIQUE NOT NULL
);

INSERT INTO rankalpha.dim_confidence(confidence_label)
SELECT unnest(ARRAY['low','medium','high'])
ON CONFLICT DO NOTHING;

-- 1.4 Recommendation timeframe
CREATE TABLE IF NOT EXISTS rankalpha.dim_timeframe (
    timeframe_key serial PRIMARY KEY,
    timeframe_label varchar(12) UNIQUE NOT NULL
);

INSERT INTO rankalpha.dim_timeframe(timeframe_label)
SELECT unnest(ARRAY['3m','6‑12m','12‑24m'])
ON CONFLICT DO NOTHING;

-- 1.5 Trend / Activity qualifiers (used by margins, cash‑flow & insider fields)
CREATE TABLE IF NOT EXISTS rankalpha.dim_trend_category (
    trend_key  serial PRIMARY KEY,
    trend_label varchar(20) UNIQUE NOT NULL
);

INSERT INTO rankalpha.dim_trend_category(trend_label)
SELECT unnest(ARRAY[
    'strong up','slight up','slight down','strong down',
    'strong net sales','slight net sales','slight net buy','strong net buy'
])
ON CONFLICT DO NOTHING;

/* ============== 2. DIM EXTENSIONS ========================= */

-- 2.1 Add asset_type_key into dim_stock when absent
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='rankalpha'
          AND table_name='dim_stock'
          AND column_name='asset_type_key'
    ) THEN
        ALTER TABLE rankalpha.dim_stock
          ADD COLUMN asset_type_key int4,
          ADD CONSTRAINT fk_dim_stock_asset_type
              FOREIGN KEY (asset_type_key)
              REFERENCES rankalpha.dim_asset_type(asset_type_key);
    END IF;
END$$;

/* Ensure STYLE dimension hosts the four factor labels */
INSERT INTO rankalpha.dim_style(style_name)
SELECT unnest(ARRAY['value','quality','momentum','low_vol'])
ON CONFLICT DO NOTHING;

/* ============== 3. CENTRAL FACT – ONE ROW PER AI RUN ======= */

CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_stock_analysis (
    analysis_id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),

    /* Star keys */
    date_key      int4  NOT NULL,  -- FK → dim_date
    stock_key     int4  NOT NULL,  -- FK → dim_stock
    source_key    int4  NOT NULL,  -- FK → dim_source (e.g. 'RankAlpha‑AI', v1)

    /* High‑level scalars from jsonData */
    market_cap_usd              numeric(20,2),
    revenue_cagr_3y_pct         numeric(6,2),

    gross_margin_trend_key      int4,
    net_margin_trend_key        int4,
    free_cash_flow_trend_key    int4,
    insider_activity_key        int4,

    beta_sp500                  numeric(6,4),
    rate_sensitivity_bps        numeric(10,2),
    fx_sensitivity              varchar(8),   -- high|medium|low
    commodity_exposure          varchar(8),

    news_sentiment_30d          numeric(5,2),
    social_sentiment_7d         numeric(5,2),
    options_skew_30d            numeric(7,3),
    short_interest_pct_float    numeric(6,2),
    employee_glassdoor_score    numeric(4,2),
    headline_buzz_score         varchar(6),   -- low|avg|high
    commentary                  text,

    overall_rating_key          int4,
    confidence_key              int4,
    timeframe_key               int4,

    load_ts                     timestamptz   DEFAULT now(),

    /* ---------- FKs ---------- */
    CONSTRAINT fk_ai_date      FOREIGN KEY(date_key)
        REFERENCES rankalpha.dim_date(date_key),
    CONSTRAINT fk_ai_stock     FOREIGN KEY(stock_key)
        REFERENCES rankalpha.dim_stock(stock_key),
    CONSTRAINT fk_ai_source    FOREIGN KEY(source_key)
        REFERENCES rankalpha.dim_source(source_key),

    FOREIGN KEY (gross_margin_trend_key)      REFERENCES rankalpha.dim_trend_category(trend_key),
    FOREIGN KEY (net_margin_trend_key)        REFERENCES rankalpha.dim_trend_category(trend_key),
    FOREIGN KEY (free_cash_flow_trend_key)    REFERENCES rankalpha.dim_trend_category(trend_key),
    FOREIGN KEY (insider_activity_key)        REFERENCES rankalpha.dim_trend_category(trend_key),
    FOREIGN KEY (overall_rating_key)          REFERENCES rankalpha.dim_rating(rating_key),
    FOREIGN KEY (confidence_key)              REFERENCES rankalpha.dim_confidence(confidence_key),
    FOREIGN KEY (timeframe_key)               REFERENCES rankalpha.dim_timeframe(timeframe_key)
);

/* ============== 4. SUPPORTING FACTS (1‑to‑1 or 1‑to‑many) == */

-- 4.1 Valuation snapshot (1‑to‑1 with analysis)
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_valuation_metrics (
    analysis_id             uuid PRIMARY KEY
        REFERENCES rankalpha.fact_ai_stock_analysis(analysis_id) ON DELETE CASCADE,
    pe_forward              numeric(10,2),
    ev_ebitda_forward       numeric(10,2),
    pe_percentile_in_sector numeric(6,2)
);

-- 4.2 Peer comparison (1‑to‑many)
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_peer_comparison (
    analysis_id     uuid NOT NULL,
    peer_stock_key  int4 NOT NULL,
    pe_forward      numeric(10,2),
    ev_ebitda_forward numeric(10,2),
    return_1y_pct   numeric(7,2),
    summary         text,

    PRIMARY KEY (analysis_id, peer_stock_key),
    FOREIGN KEY (analysis_id)    REFERENCES rankalpha.fact_ai_stock_analysis(analysis_id) ON DELETE CASCADE,
    FOREIGN KEY (peer_stock_key) REFERENCES rankalpha.dim_stock(stock_key)
);

-- 4.3 Factor scores (re‑use existing dim_style)
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_factor_score (
    analysis_id uuid NOT NULL,
    style_key   int4 NOT NULL,
    score       numeric(5,2) NOT NULL,

    PRIMARY KEY (analysis_id, style_key),
    FOREIGN KEY (analysis_id) REFERENCES rankalpha.fact_ai_stock_analysis(analysis_id) ON DELETE CASCADE,
    FOREIGN KEY (style_key)   REFERENCES rankalpha.dim_style(style_key)
);

-- 4.4 Catalysts (short‑ vs long‑term)
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_catalyst (
    catalyst_id    uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id    uuid NOT NULL,
    catalyst_type  varchar(10) NOT NULL,           -- 'short' | 'long'
    title          text NOT NULL,
    description    text,
    probability_pct          numeric(6,2),
    expected_price_move_pct  numeric(7,2),
    expected_date            date,
    priced_in_pct            numeric(6,2),
    price_drop_risk_pct      numeric(7,2),

    FOREIGN KEY (analysis_id) REFERENCES rankalpha.fact_ai_stock_analysis(analysis_id) ON DELETE CASCADE
);

-- 4.5 Scenario price targets
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_price_scenario (
    analysis_id   uuid NOT NULL,
    scenario_type varchar(6) NOT NULL,             -- bull|base|bear
    price_target  numeric(20,2),
    probability_pct numeric(6,2),

    PRIMARY KEY (analysis_id, scenario_type),
    FOREIGN KEY (analysis_id) REFERENCES rankalpha.fact_ai_stock_analysis(analysis_id) ON DELETE CASCADE
);

-- 4.6 Macro & headline risks plus data gaps – text arrays flattened
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_macro_risk (
    analysis_id uuid NOT NULL
        REFERENCES rankalpha.fact_ai_stock_analysis(analysis_id) ON DELETE CASCADE,
    risk_text   text,
    PRIMARY KEY (analysis_id, risk_text)
);

CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_headline_risk (
    analysis_id uuid NOT NULL
        REFERENCES rankalpha.fact_ai_stock_analysis(analysis_id) ON DELETE CASCADE,
    risk_text   text,
    PRIMARY KEY (analysis_id, risk_text)
);

CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_data_gap (
    analysis_id uuid NOT NULL
        REFERENCES rankalpha.fact_ai_stock_analysis(analysis_id) ON DELETE CASCADE,
    gap_text    text,
    PRIMARY KEY (analysis_id, gap_text)
);

/* ============== 5. OPTIONAL – REGISTER SOURCE ROW ========= */

-- If you have not yet recorded the AI engine as a data source:
INSERT INTO rankalpha.dim_source (source_name, version)
SELECT 'RankAlpha‑AI', '1'
ON CONFLICT (source_name, version) DO NOTHING;

/* ------------------------------------------------------------
   END – You can safely re‑run this script; all IF NOT EXISTS /
   ON CONFLICT guards make it idempotent.
   ------------------------------------------------------------ */
