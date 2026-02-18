/* ------------------------------------------------------------
   V30__ai_analysis_full_view.sql
   One-stop, human-friendly view that denormalizes the AI analysis
   results into a single row per analysis_id with labeled fields and
   aggregated JSON/arrays for lists.
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE OR REPLACE VIEW rankalpha.vw_ai_analysis_full AS
SELECT
    a.analysis_id,
    a.date_key,
    d.full_date                                   AS as_of_date,
    s.symbol,
    s.company_name,
    COALESCE(at.asset_type_name, 'equity')        AS asset_type,
    src.source_name,

    -- Top-level scalars
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

    -- Valuation (1:1)
    v.pe_forward,
    v.ev_ebitda_forward,
    v.pe_percentile_in_sector,

    -- Factor scores pivoted
    fs.value_score,
    fs.quality_score,
    fs.momentum_score,
    fs.low_vol_score,

    -- Scenario targets pivoted
    ps.bull_price_target,
    ps.bull_probability_pct,
    ps.base_price_target,
    ps.base_probability_pct,
    ps.bear_price_target,
    ps.bear_probability_pct,

    -- Catalysts aggregated
    c.short_catalysts,
    c.long_catalysts,

    -- Risks and gaps
    r.macro_risks,
    r.headline_risks,
    r.data_gaps,

    -- Peers aggregated
    peers.peers,

    a.load_ts
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
           ) FILTER (WHERE catalyst_type = 'long')  AS long_catalysts
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
               ORDER BY pc.return_1y_pct DESC NULLS LAST
           ) AS peers
    FROM   fact_ai_peer_comparison pc
    JOIN   dim_stock peer ON peer.stock_key = pc.peer_stock_key
    GROUP BY pc.analysis_id
  ) peers ON peers.analysis_id = a.analysis_id;

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */

