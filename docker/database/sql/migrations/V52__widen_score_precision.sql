/* ------------------------------------------------------------
   V52__widen_score_precision.sql
   Widen score columns to numeric(14,2) and recreate mv_latest_grades
   to accommodate the updated precision.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

-- Drop dependent views/materialized views so type changes succeed.
DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_latest_grades;
DROP VIEW IF EXISTS rankalpha.vw_score_history;
DROP VIEW IF EXISTS rankalpha.vw_stock_style_scores;
DROP VIEW IF EXISTS rankalpha.vw_ai_factor_scores;
DROP VIEW IF EXISTS rankalpha.vw_ai_analysis_full;

-- Expand precision on score storage tables.
ALTER TABLE rankalpha.fact_score_history
    ALTER COLUMN score TYPE numeric(14,2);

ALTER TABLE rankalpha.fact_stock_scores
    ALTER COLUMN score_value TYPE numeric(14,2);

ALTER TABLE rankalpha.fact_stock_score_types
    ALTER COLUMN score_value TYPE numeric(14,2);

ALTER TABLE rankalpha.fact_ai_factor_score
    ALTER COLUMN score TYPE numeric(14,2);

/* ------------------------------------------------------------
   Recreate dependent views with the widened precision.
   ------------------------------------------------------------ */

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

CREATE OR REPLACE VIEW rankalpha.vw_ai_analysis_full AS
SELECT
    a.analysis_id,
    a.date_key,
    d.full_date                                   AS as_of_date,
    s.symbol,
    s.company_name,
    COALESCE(at.asset_type_name, 'equity')        AS asset_type,
    src.source_name,

    a.market_cap_usd,
    a.revenue_cagr_3y_pct,
    t_gm.trend_label                              AS gross_margin_trend,
    t_nm.trend_label                              AS net_margin_trend,
    t_fcf.trend_label                             AS free_cash_flow_trend,
    t_ins.trend_label                             AS insider_activity,

    a.beta_sp500,
    a.rate_sensitivity_bps,
    a.fx_sensitivity,
    a.commodity_exposure,

    a.news_sentiment_30d,
    a.social_sentiment_7d,
    a.options_skew_30d,
    a.short_interest_pct_float,
    a.employee_glassdoor_score,
    a.headline_buzz_score,
    a.commentary,

    rat.rating_label                              AS overall_rating,
    conf.confidence_label                         AS confidence,
    tf.timeframe_label                            AS recommendation_timeframe,

    v.pe_forward,
    v.ev_ebitda_forward,
    v.pe_percentile_in_sector,

    fs.value_score,
    fs.quality_score,
    fs.momentum_score,
    fs.low_vol_score,

    ps.bull_price_target,
    ps.bull_probability_pct,
    ps.base_price_target,
    ps.base_probability_pct,
    ps.bear_price_target,
    ps.bear_probability_pct,

    c.short_catalysts,
    c.long_catalysts,

    r.macro_risks,
    r.headline_risks,
    r.data_gaps,

    peers.peers,

    a.load_ts,

    c.events,
    asu.bull_case        AS analyst_bull_case,
    asu.bear_case        AS analyst_bear_case,
    asu.valuation_check  AS analyst_valuation_check
FROM   fact_ai_stock_analysis           a
JOIN   dim_stock                        s     ON s.stock_key   = a.stock_key
JOIN   dim_date                         d     ON d.date_key    = a.date_key
JOIN   dim_source                       src   ON src.source_key = a.source_key
LEFT  JOIN dim_asset_type               at    ON at.asset_type_key = s.asset_type_key
LEFT  JOIN dim_trend_category           t_gm  ON t_gm.trend_key   = a.gross_margin_trend_key
LEFT  JOIN dim_trend_category           t_nm  ON t_nm.trend_key   = a.net_margin_trend_key
LEFT  JOIN dim_trend_category           t_fcf ON t_fcf.trend_key  = a.free_cash_flow_trend_key
LEFT  JOIN dim_trend_category           t_ins ON t_ins.trend_key  = a.insider_activity_key
LEFT  JOIN dim_rating                   rat   ON rat.rating_key   = a.overall_rating_key
LEFT  JOIN dim_confidence               conf  ON conf.confidence_key = a.confidence_key
LEFT  JOIN dim_timeframe                tf    ON tf.timeframe_key = a.timeframe_key
LEFT  JOIN fact_ai_valuation_metrics    v     ON v.analysis_id    = a.analysis_id

LEFT  JOIN (
    SELECT fs.analysis_id,
           MAX(CASE WHEN sty.style_name = 'value'    THEN fs.score END) AS value_score,
           MAX(CASE WHEN sty.style_name = 'quality'  THEN fs.score END) AS quality_score,
           MAX(CASE WHEN sty.style_name = 'momentum' THEN fs.score END) AS momentum_score,
           MAX(CASE WHEN sty.style_name = 'low_vol'  THEN fs.score END) AS low_vol_score
    FROM   fact_ai_factor_score fs
    JOIN   dim_style            sty ON sty.style_key = fs.style_key
    GROUP BY fs.analysis_id
  ) fs ON fs.analysis_id = a.analysis_id

LEFT  JOIN (
    SELECT analysis_id,
           jsonb_agg(
               jsonb_build_object(
                   'title', title,
                   'description', description,
                   'probability_pct', probability_pct,
                   'expected_price_move_pct', expected_price_move_pct,
                   'expected_date', expected_date,
                   'priced_in_pct', priced_in_pct,
                   'price_drop_risk_pct', price_drop_risk_pct
               )
               ORDER BY expected_date NULLS LAST
           ) FILTER (WHERE catalyst_type = 'short') AS short_catalysts,

           jsonb_agg(
               jsonb_build_object(
                   'title', title,
                   'description', description,
                   'probability_pct', probability_pct,
                   'expected_price_move_pct', expected_price_move_pct,
                   'expected_date', expected_date,
                   'priced_in_pct', priced_in_pct,
                   'price_drop_risk_pct', price_drop_risk_pct
               )
               ORDER BY expected_date NULLS LAST
           ) FILTER (WHERE catalyst_type = 'long')  AS long_catalysts,

           jsonb_agg(
               jsonb_build_object(
                   'catalyst_type', catalyst_type,
                   'title', title,
                   'description', description,
                   'probability_pct', probability_pct,
                   'expected_price_move_pct', expected_price_move_pct,
                   'expected_date', expected_date,
                   'priced_in_pct', priced_in_pct,
                   'price_drop_risk_pct', price_drop_risk_pct
               )
               ORDER BY expected_date NULLS LAST
           ) FILTER (WHERE catalyst_type IS NOT NULL AND catalyst_type NOT IN ('short','long')) AS events
    FROM   fact_ai_catalyst
    GROUP BY analysis_id
  ) c ON c.analysis_id = a.analysis_id

LEFT  JOIN (
    SELECT analysis_id,
           MAX(CASE WHEN scenario_type = 'bull' THEN price_target     END) AS bull_price_target,
           MAX(CASE WHEN scenario_type = 'bull' THEN probability_pct  END) AS bull_probability_pct,
           MAX(CASE WHEN scenario_type = 'base' THEN price_target     END) AS base_price_target,
           MAX(CASE WHEN scenario_type = 'base' THEN probability_pct  END) AS base_probability_pct,
           MAX(CASE WHEN scenario_type = 'bear' THEN price_target     END) AS bear_price_target,
           MAX(CASE WHEN scenario_type = 'bear' THEN probability_pct  END) AS bear_probability_pct
    FROM   fact_ai_price_scenario
    GROUP BY analysis_id
  ) ps ON ps.analysis_id = a.analysis_id

LEFT  JOIN (
    SELECT a.analysis_id,
           ARRAY_REMOVE(ARRAY_AGG(DISTINCT mr.risk_text), NULL) AS macro_risks,
           ARRAY_REMOVE(ARRAY_AGG(DISTINCT hr.risk_text), NULL) AS headline_risks,
           ARRAY_REMOVE(ARRAY_AGG(DISTINCT dg.gap_text),  NULL) AS data_gaps
    FROM   fact_ai_stock_analysis a
    LEFT  JOIN fact_ai_macro_risk    mr ON mr.analysis_id = a.analysis_id
    LEFT  JOIN fact_ai_headline_risk hr ON hr.analysis_id = a.analysis_id
    LEFT  JOIN fact_ai_data_gap      dg ON dg.analysis_id = a.analysis_id
    GROUP BY a.analysis_id
  ) r ON r.analysis_id = a.analysis_id

LEFT  JOIN (
    SELECT pc.analysis_id,
           jsonb_agg(
               jsonb_build_object(
                   'peer_symbol', peer.symbol,
                   'pe_forward', pc.pe_forward,
                   'ev_ebitda_forward', pc.ev_ebitda_forward,
                   'return_1y_pct', pc.return_1y_pct,
                   'summary', pc.summary
               )
               ORDER BY peer.symbol
           ) AS peers
    FROM   fact_ai_peer_comparison pc
    JOIN   dim_stock peer ON peer.stock_key = pc.peer_stock_key
    GROUP BY pc.analysis_id
  ) peers ON peers.analysis_id = a.analysis_id

LEFT  JOIN (
    SELECT analysis_id,
           bull_case,
           bear_case,
           valuation_check
    FROM   fact_ai_analyst_summary
  ) asu ON asu.analysis_id = a.analysis_id
;

/* ------------------------------------------------------------
   Recreate mv_latest_grades (definition copied from V50 with
   casts widened to numeric(14,2) where applicable).
   ------------------------------------------------------------ */

CREATE MATERIALIZED VIEW rankalpha.mv_latest_grades AS
WITH latest AS (
  SELECT d.date_key, d.full_date
  FROM   dim_date d
  JOIN   fact_score_history f ON f.date_key = d.date_key
  ORDER  BY d.full_date DESC
  LIMIT 1
),
weights_raw AS (
  SELECT
    COALESCE(w.w_momentum, 0.4)::numeric(6,4)  AS w_m,
    COALESCE(w.w_value, 0.4)::numeric(6,4)     AS w_v,
    COALESCE(w.w_sentiment, 0.2)::numeric(6,4) AS w_s
  FROM rankalpha.dim_model_weight w
  ORDER BY w.as_of_date DESC
  LIMIT 1
),
weights AS (
  SELECT
    COALESCE((SELECT w_m FROM weights_raw), 0.4)::numeric(6,4) AS w_m,
    COALESCE((SELECT w_v FROM weights_raw), 0.4)::numeric(6,4) AS w_v,
    COALESCE((SELECT w_s FROM weights_raw), 0.2)::numeric(6,4) AS w_s
),
momentum_new AS (
  SELECT s.symbol,
         r.momentum_score
  FROM (
    SELECT f.stock_key,
           f.score::numeric(14,2) AS momentum_score,
           ROW_NUMBER() OVER (
             PARTITION BY f.stock_key
             ORDER BY f.date_key DESC, f.load_ts DESC, f.fact_id DESC
           ) AS rn
    FROM   fact_score_history f
    JOIN   dim_score_type t ON t.score_type_key = f.score_type_key
    WHERE  t.score_type_name = 'momentum score'
  ) r
  JOIN dim_stock s ON s.stock_key = r.stock_key
  WHERE r.rn = 1
),
momentum_legacy AS (
  SELECT s.symbol,
         MAX(f.score)::numeric(14,2) AS momentum_raw
  FROM   fact_score_history f
  JOIN   latest l ON f.date_key = l.date_key
  JOIN   dim_score_type t ON t.score_type_key = f.score_type_key
  JOIN   dim_stock s ON s.stock_key = f.stock_key
  WHERE  t.score_type_name = 'linear regression 200'
  GROUP  BY s.symbol
),
pcts AS (
  SELECT
    percentile_cont(0.05) WITHIN GROUP (ORDER BY momentum_raw) AS p05,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY momentum_raw) AS p95
  FROM momentum_legacy
),
ai_latest AS (
  SELECT symbol, value_score AS ai_value_score, news_sentiment_30d
  FROM (
    SELECT a.symbol,
           a.value_score,
           a.news_sentiment_30d,
           ROW_NUMBER() OVER (PARTITION BY a.symbol ORDER BY a.as_of_date DESC) AS rn
    FROM   vw_ai_analysis_full a
  ) x WHERE rn = 1
),
value_fund AS (
  SELECT s.symbol,
         r.value_score
  FROM (
    SELECT f.stock_key,
           f.score::numeric(14,2) AS value_score,
           ROW_NUMBER() OVER (
             PARTITION BY f.stock_key
             ORDER BY f.date_key DESC, f.load_ts DESC, f.fact_id DESC
           ) AS rn
    FROM   fact_score_history f
    JOIN   dim_score_type t ON t.score_type_key = f.score_type_key
    WHERE  t.score_type_name = 'value score'
  ) r
  JOIN dim_stock s ON s.stock_key = r.stock_key
  WHERE r.rn = 1
),
news AS (
  SELECT na.stock_key,
         AVG(ns.sentiment_score)::numeric(5,3) AS news_avg
  FROM   fact_news_articles na
  JOIN   fact_news_sentiment ns ON ns.article_id = na.article_id
  JOIN   dim_date d ON d.date_key = na.article_date
  JOIN   latest l ON d.full_date >= l.full_date - interval '30 days'
  GROUP  BY na.stock_key
),
sentiment_latest AS (
  SELECT s.symbol,
         r.sentiment_score
  FROM (
    SELECT f.stock_key,
           f.score::numeric(14,2) AS sentiment_score,
           ROW_NUMBER() OVER (
             PARTITION BY f.stock_key
             ORDER BY f.date_key DESC, f.load_ts DESC, f.fact_id DESC
           ) AS rn
    FROM   fact_score_history f
    JOIN   dim_score_type t ON t.score_type_key = f.score_type_key
    WHERE  t.score_type_name = 'sentiment score'
  ) r
  JOIN dim_stock s ON s.stock_key = r.stock_key
  WHERE r.rn = 1
),
base AS (
  SELECT
    l.full_date                              AS as_of_date,
    st.symbol,
    st.company_name,
    st.sector,
    st.exchange,
    COALESCE(mn.momentum_score,
             LEAST(100.0, GREATEST(0.0, ((ml.momentum_raw - p.p05) / NULLIF(p.p95 - p.p05, 0)) * 100.0))) AS m_eff,
    COALESCE(vf.value_score, ai.ai_value_score) AS v_eff,
    COALESCE(sl.sentiment_score, (COALESCE(ai.news_sentiment_30d, n.news_avg) + 1.0) * 50.0) AS s_eff,
    (SELECT w_m FROM weights) AS w_m,
    (SELECT w_v FROM weights) AS w_v,
    (SELECT w_s FROM weights) AS w_s
  FROM dim_stock st
  JOIN latest l ON TRUE
  LEFT JOIN momentum_new mn    ON mn.symbol = st.symbol
  LEFT JOIN momentum_legacy ml ON ml.symbol = st.symbol
  CROSS JOIN pcts p
  LEFT JOIN ai_latest ai ON ai.symbol = st.symbol
  LEFT JOIN value_fund vf ON vf.symbol = st.symbol
  LEFT JOIN news n ON n.stock_key = st.stock_key
  LEFT JOIN sentiment_latest sl ON sl.symbol = st.symbol
  WHERE st.is_active IS TRUE
),
ranked AS (
  SELECT
    as_of_date,
    symbol,
    company_name,
    sector,
    exchange,
    m_eff AS momentum_score,
    v_eff AS value_score,
    s_eff AS sentiment_score,
    CASE
      WHEN m_eff IS NOT NULL AND v_eff IS NOT NULL THEN (
        (COALESCE(m_eff, 0) * w_m)
      + (COALESCE(v_eff, 0) * w_v)
      + (COALESCE(s_eff, 0) * w_s)
      ) / NULLIF(
          (CASE WHEN m_eff IS NOT NULL THEN w_m ELSE 0 END)
        + (CASE WHEN v_eff IS NOT NULL THEN w_v ELSE 0 END)
        + (CASE WHEN s_eff IS NOT NULL THEN w_s ELSE 0 END), 0)
      ELSE NULL
    END AS composite_raw
  FROM base
)
SELECT
  as_of_date,
  symbol,
  company_name,
  sector,
  exchange,
  momentum_score,
  value_score,
  sentiment_score,
  CASE WHEN composite_raw IS NOT NULL THEN
    ROUND((CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0)::numeric, 2)
  ELSE NULL END AS avg_score,
  CASE
    WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 90 THEN 'A'
    WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 70 THEN 'B'
    WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 45 THEN 'C'
    WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 20 THEN 'D'
    WHEN composite_raw IS NOT NULL THEN 'F'
    ELSE 'N/A'
  END AS grade,
  CASE
    WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 90 THEN 5
    WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 70 THEN 4
    WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 45 THEN 3
    WHEN (CASE WHEN composite_raw IS NOT NULL THEN (CUME_DIST() OVER (ORDER BY composite_raw ASC NULLS LAST) * 99.0 + 1.0) ELSE NULL END) >= 20 THEN 2
    WHEN composite_raw IS NOT NULL THEN 1
    ELSE 0
  END AS grade_order
FROM ranked;

-- Recreate indexes dropped with the materialized view.
CREATE UNIQUE INDEX IF NOT EXISTS mv_latest_grades_symbol_uidx
  ON rankalpha.mv_latest_grades (symbol);

CREATE INDEX IF NOT EXISTS mv_latest_grades_grade_order_idx
  ON rankalpha.mv_latest_grades (grade_order DESC, symbol);

CREATE INDEX IF NOT EXISTS mv_latest_grades_sector_idx
  ON rankalpha.mv_latest_grades (sector);

CREATE INDEX IF NOT EXISTS mv_latest_grades_sector_grade_idx
  ON rankalpha.mv_latest_grades (sector, grade_order DESC, symbol);

CREATE INDEX IF NOT EXISTS mv_latest_grades_sector_symbol_idx
  ON rankalpha.mv_latest_grades (sector, symbol);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
