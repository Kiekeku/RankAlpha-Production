/* ------------------------------------------------------------
   V92__ai_analysis_optional_tables.sql
   - Adds missing fact_ai_* tables used by the sentiment writer
     (events, risks, news, benchmarking, alt data, etc.).
   - Keeps statements idempotent so reruns are safe.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- 1) Event annotations captured by the sentiment app
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_event (
    event_id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id         uuid NOT NULL,
    event_title         text,
    event_summary       text,
    event_date          date,
    expected_impact_pct numeric(7,2),
    confidence_key      int4
        REFERENCES rankalpha.dim_confidence(confidence_key)
);

CREATE INDEX IF NOT EXISTS idx_ai_event_analysis
    ON rankalpha.fact_ai_event (analysis_id, event_date);

-- 2) Risk factors (probability × severity) per analysis
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_risk (
    risk_id        uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id    uuid NOT NULL,
    risk_title     text,
    risk_summary   text,
    probability_pct numeric(7,2),
    severity_pct    numeric(7,2)
);

CREATE INDEX IF NOT EXISTS idx_ai_risk_analysis
    ON rankalpha.fact_ai_risk (analysis_id);

-- 3) News snippets referenced by the AI analysis
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_news (
    news_id         uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id     uuid NOT NULL,
    published_at    timestamptz,
    headline        text,
    url             text,
    sentiment_score numeric(6,3)
);

CREATE INDEX IF NOT EXISTS idx_ai_news_analysis
    ON rankalpha.fact_ai_news (analysis_id, published_at);

-- 4) Scenario proximity metadata supplied by upstream AI
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_scenario_proximity (
    proximity_id     uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id      uuid NOT NULL,
    scenario_id      text,
    similarity_score numeric(7,4),
    scenario_summary text
);

CREATE INDEX IF NOT EXISTS idx_ai_scenario_proximity_analysis
    ON rankalpha.fact_ai_scenario_proximity (analysis_id);

-- 5) Benchmarking ranks (single row per analysis)
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_benchmarking (
    analysis_id          uuid PRIMARY KEY,
    revenue_growth_rank  smallint,
    margin_rank          smallint,
    valuation_rank       smallint,
    sentiment_rank       smallint
);

-- 6) Summary probability/return metrics for bull/base/bear mix
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_summary_metrics (
    analysis_id        uuid PRIMARY KEY,
    upside_pct         numeric(7,2),
    downside_pct       numeric(7,2),
    base_case_pct      numeric(7,2),
    risk_reward_ratio  numeric(7,2)
);

-- 7) High-level overall recommendation summary
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_overall_summary (
    analysis_id                   uuid PRIMARY KEY,
    overall_rating_key            int4
        REFERENCES rankalpha.dim_rating(rating_key),
    confidence_key                int4
        REFERENCES rankalpha.dim_confidence(confidence_key),
    recommendation_timeframe_key  int4
        REFERENCES rankalpha.dim_timeframe(timeframe_key),
    analyst_summary               jsonb
);

-- 8) Alternative data snapshot (card spend, app ranks, hiring)
CREATE TABLE IF NOT EXISTS rankalpha.fact_ai_alternative_data (
    analysis_id              uuid PRIMARY KEY,
    credit_card_spend_score  numeric(7,2),
    app_ranking_score        numeric(7,2),
    job_postings_trend       numeric(7,2)
);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
