/* ------------------------------------------------------------
   V20250629_02__rankalpha_views.sql
   Human‑consumable views on RankAlpha star schema
   ------------------------------------------------------------ */

-- 0 ▪ Utilities (optional)
SET search_path = rankalpha, public;

-- ==========================================================
-- 1 ▪ CORE FINANCIAL VIEWs
-- ==========================================================

/* 1.1 Fundamentals – each row one metric value */
CREATE OR REPLACE VIEW rankalpha.vw_fin_fundamentals AS
SELECT
    f.date_key,
    dt.full_date          AS as_of_date,
    s.symbol,
    s.company_name,
    m.metric_code,
    m.metric_name,
    f.fiscal_year,
    f.fiscal_period,
    f.metric_value,
    src.source_name,
    f.load_ts
FROM   rankalpha.fact_fin_fundamentals   f
JOIN   rankalpha.dim_stock          s   ON s.stock_key = f.stock_key
JOIN   rankalpha.dim_fin_metric     m   ON m.metric_key = f.metric_key
JOIN   rankalpha.dim_date           dt  ON dt.date_key = f.date_key
JOIN   rankalpha.dim_source         src ON src.source_key = f.source_key;


/* 1.2 Score history (all custom score types) */
CREATE OR REPLACE VIEW rankalpha.vw_score_history AS
SELECT
    h.date_key,
    d.full_date          AS as_of_date,
    s.symbol,
    st.score_type_name,
    h.score,
    src.source_name,
    h.load_ts
FROM   rankalpha.fact_score_history      h
JOIN   rankalpha.dim_stock          s   ON s.stock_key = h.stock_key
JOIN   rankalpha.dim_score_type     st  ON st.score_type_key = h.score_type_key
JOIN   rankalpha.dim_date           d   ON d.date_key = h.date_key
JOIN   rankalpha.dim_source         src ON src.source_key = h.source_key;


/* 1.3 High‑level style scores (Value, Quality, etc.) */
CREATE OR REPLACE VIEW rankalpha.vw_stock_style_scores AS
SELECT
    ss.date_key,
    d.full_date          AS as_of_date,
    s.symbol,
    sty.style_name,
    ss.score_value,
    ss.rank_value,
    ss.score_runid,
    ss.load_ts
FROM   rankalpha.fact_stock_scores  ss
JOIN   rankalpha.dim_stock     s   ON s.stock_key = ss.stock_key
JOIN   rankalpha.dim_style     sty ON sty.style_key = ss.style_key
JOIN   rankalpha.dim_date      d   ON d.date_key = ss.date_key;


/* 1.4 Screener rank snapshot */
CREATE OR REPLACE VIEW rankalpha.vw_screener_rank AS
SELECT
    r.date_key,
    d.full_date          AS as_of_date,
    s.symbol,
    sty.style_name,
    r.rank_value,
    r.screening_runid,
    r.load_ts,
    src.source_name
FROM   rankalpha.fact_screener_rank r
JOIN   rankalpha.dim_stock     s   ON s.stock_key = r.stock_key
LEFT  JOIN rankalpha.dim_style sty ON sty.style_key = r.style_key
JOIN   rankalpha.dim_date      d   ON d.date_key = r.date_key
JOIN   rankalpha.dim_source    src ON src.source_key = r.source_key;


-- ==========================================================
-- 2 ▪ AI STOCK‑ANALYSIS VIEWs
-- ==========================================================

/* 2.1 Single‑row snapshot per AI run (most‑used columns) */
CREATE OR REPLACE VIEW rankalpha.vw_ai_stock_analysis_summary AS
SELECT
    a.analysis_id,
    d.full_date                                       AS as_of_date,
    s.symbol,
    s.company_name,
    at.asset_type_name                                AS asset_type,
    a.market_cap_usd,
    a.revenue_cagr_3y_pct,
    t_gm.trend_label                                  AS gross_margin_trend,
    t_nm.trend_label                                  AS net_margin_trend,
    t_fcf.trend_label                                 AS free_cash_flow_trend,
    t_ins.trend_label                                 AS insider_activity,
    a.news_sentiment_30d,
    a.social_sentiment_7d,
    a.options_skew_30d,
    a.short_interest_pct_float,
    a.employee_glassdoor_score,
    a.headline_buzz_score,
    rat.rating_label                                  AS overall_rating,
    conf.confidence_label                             AS confidence,
    tf.timeframe_label                                AS recommendation_timeframe,
    src.source_name,
    a.load_ts
FROM   rankalpha.fact_ai_stock_analysis a
JOIN   rankalpha.dim_stock          s     ON s.stock_key = a.stock_key
LEFT  JOIN rankalpha.dim_asset_type at    ON at.asset_type_key = s.asset_type_key
JOIN   rankalpha.dim_date           d     ON d.date_key   = a.date_key
JOIN   rankalpha.dim_source         src   ON src.source_key = a.source_key
LEFT  JOIN rankalpha.dim_trend_category t_gm  ON t_gm.trend_key = a.gross_margin_trend_key
LEFT  JOIN rankalpha.dim_trend_category t_nm  ON t_nm.trend_key = a.net_margin_trend_key
LEFT  JOIN rankalpha.dim_trend_category t_fcf ON t_fcf.trend_key = a.free_cash_flow_trend_key
LEFT  JOIN rankalpha.dim_trend_category t_ins ON t_ins.trend_key = a.insider_activity_key
LEFT  JOIN rankalpha.dim_rating       rat    ON rat.rating_key = a.overall_rating_key
LEFT  JOIN rankalpha.dim_confidence   conf   ON conf.confidence_key = a.confidence_key
LEFT  JOIN rankalpha.dim_timeframe    tf     ON tf.timeframe_key = a.timeframe_key;


/* 2.2 Valuation metrics – one‑to‑one with analysis_id */
CREATE OR REPLACE VIEW rankalpha.vw_ai_valuation_metrics AS
SELECT
    a.analysis_id,
    d.full_date           AS as_of_date,
    s.symbol,
    v.pe_forward,
    v.ev_ebitda_forward,
    v.pe_percentile_in_sector
FROM   rankalpha.fact_ai_valuation_metrics v
JOIN   rankalpha.fact_ai_stock_analysis a ON a.analysis_id = v.analysis_id
JOIN   rankalpha.dim_date            d    ON d.date_key   = a.date_key
JOIN   rankalpha.dim_stock           s    ON s.stock_key  = a.stock_key;


/* 2.3 Factor scores (Value / Quality / Momentum / Low‑Vol) */
CREATE OR REPLACE VIEW rankalpha.vw_ai_factor_scores AS
SELECT
    a.analysis_id,
    d.full_date           AS as_of_date,
    s.symbol,
    sty.style_name,
    fs.score
FROM   rankalpha.fact_ai_factor_score fs
JOIN   rankalpha.fact_ai_stock_analysis a ON a.analysis_id = fs.analysis_id
JOIN   rankalpha.dim_style           sty  ON sty.style_key = fs.style_key
JOIN   rankalpha.dim_date            d    ON d.date_key   = a.date_key
JOIN   rankalpha.dim_stock           s    ON s.stock_key  = a.stock_key;


/* 2.4 Peer comparison – one row per (subject, peer) */
CREATE OR REPLACE VIEW rankalpha.vw_ai_peer_comparison AS
SELECT
    a.analysis_id,
    d.full_date                           AS as_of_date,
    subj.symbol                           AS subject_symbol,
    peer.symbol                           AS peer_symbol,
    pc.pe_forward,
    pc.ev_ebitda_forward,
    pc.return_1y_pct,
    pc.summary
FROM   rankalpha.fact_ai_peer_comparison pc
JOIN   rankalpha.fact_ai_stock_analysis a  ON a.analysis_id = pc.analysis_id
JOIN   rankalpha.dim_stock           subj  ON subj.stock_key = a.stock_key
JOIN   rankalpha.dim_stock           peer  ON peer.stock_key = pc.peer_stock_key
JOIN   rankalpha.dim_date            d     ON d.date_key   = a.date_key;


/* 2.5 Catalysts (short‑ & long‑term) */
CREATE OR REPLACE VIEW rankalpha.vw_ai_catalysts AS
SELECT
    a.analysis_id,
    d.full_date          AS as_of_date,
    s.symbol,
    c.catalyst_type,
    c.title,
    c.description,
    c.probability_pct,
    c.expected_price_move_pct,
    c.expected_date,
    c.priced_in_pct,
    c.price_drop_risk_pct
FROM   rankalpha.fact_ai_catalyst c
JOIN   rankalpha.fact_ai_stock_analysis a ON a.analysis_id = c.analysis_id
JOIN   rankalpha.dim_date            d    ON d.date_key   = a.date_key
JOIN   rankalpha.dim_stock           s    ON s.stock_key  = a.stock_key;


/* 2.6 Scenario price targets */
CREATE OR REPLACE VIEW rankalpha.vw_ai_price_scenarios AS
SELECT
    a.analysis_id,
    d.full_date          AS as_of_date,
    s.symbol,
    ps.scenario_type,
    ps.price_target,
    ps.probability_pct
FROM   rankalpha.fact_ai_price_scenario ps
JOIN   rankalpha.fact_ai_stock_analysis a ON a.analysis_id = ps.analysis_id
JOIN   rankalpha.dim_date            d    ON d.date_key   = a.date_key
JOIN   rankalpha.dim_stock           s    ON s.stock_key  = a.stock_key;


/* 2.7 Combined risk narratives (macro, headline, data gaps) */
CREATE OR REPLACE VIEW rankalpha.vw_ai_risks AS
SELECT a.analysis_id,
       d.full_date AS as_of_date,
       s.symbol,
       'macro'     AS risk_type,
       mr.risk_text
FROM   rankalpha.fact_ai_macro_risk mr
JOIN   rankalpha.fact_ai_stock_analysis a ON a.analysis_id = mr.analysis_id
JOIN   rankalpha.dim_date            d    ON d.date_key   = a.date_key
JOIN   rankalpha.dim_stock           s    ON s.stock_key  = a.stock_key

UNION ALL
SELECT a.analysis_id,
       d.full_date,
       s.symbol,
       'headline',
       hr.risk_text
FROM   rankalpha.fact_ai_headline_risk hr
JOIN   rankalpha.fact_ai_stock_analysis a ON a.analysis_id = hr.analysis_id
JOIN   rankalpha.dim_date            d    ON d.date_key   = a.date_key
JOIN   rankalpha.dim_stock           s    ON s.stock_key  = a.stock_key

UNION ALL
SELECT a.analysis_id,
       d.full_date,
       s.symbol,
       'data_gap',
       dg.gap_text        AS risk_text
FROM   rankalpha.fact_ai_data_gap dg
JOIN   rankalpha.fact_ai_stock_analysis a ON a.analysis_id = dg.analysis_id
JOIN   rankalpha.dim_date            d    ON d.date_key   = a.date_key
JOIN   rankalpha.dim_stock           s    ON s.stock_key  = a.stock_key;


/* ------------------------------------------------------------
   END OF VIEW DEFINITIONS
   ------------------------------------------------------------ */
