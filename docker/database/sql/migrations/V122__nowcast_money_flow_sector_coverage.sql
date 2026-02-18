/* ------------------------------------------------------------
   V122__nowcast_money_flow_sector_coverage.sql
   - Tighten money-flow appetite validity via sector coverage
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

CREATE OR REPLACE FUNCTION rankalpha.fn_nowcast_snapshot_upsert_for_date(
  p_as_of_date DATE,
  p_model_version TEXT DEFAULT 'nowcast_v2'
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
  v_date_key INTEGER;
BEGIN
  SELECT d.date_key
  INTO v_date_key
  FROM rankalpha.dim_date d
  WHERE d.full_date = p_as_of_date
    AND d.is_trading_day IS TRUE;

  IF v_date_key IS NULL THEN
    RAISE EXCEPTION 'nowcast snapshot requires a trading day in dim_date (as_of_date=%)', p_as_of_date;
  END IF;

  WITH
  params AS (
    SELECT
      v_date_key::int                    AS asof_date_key,
      p_as_of_date::date                 AS asof_date,
      p_model_version::text              AS model_version,
      252::int                           AS w_short,
      756::int                           AS w_med,
      60::int                            AS min_short,
      200::int                           AS min_med,
      4::int                             AS min_mf_cyc_sectors,
      3::int                             AS min_mf_def_sectors
  ),

  /* ---------- Liquidity: ON RRP / TGA label + Net Liquidity impulse ---------- */
  rrp_last2 AS (
    SELECT d.date_key, d.full_date, m.value::double precision AS v
    FROM rankalpha.vw_macro_series m
    JOIN rankalpha.dim_date d ON d.full_date = m.as_of_date
    JOIN params p ON TRUE
    WHERE m.series_code = 'US_ON_RRP'
      AND d.full_date <= p.asof_date
      AND m.value IS NOT NULL
    ORDER BY d.date_key DESC
    LIMIT 2
  ),
  tga_last2 AS (
    SELECT d.date_key, d.full_date, m.value::double precision AS v
    FROM rankalpha.vw_macro_series m
    JOIN rankalpha.dim_date d ON d.full_date = m.as_of_date
    JOIN params p ON TRUE
    WHERE m.series_code = 'US_TGA_BAL'
      AND d.full_date <= p.asof_date
      AND m.value IS NOT NULL
    ORDER BY d.date_key DESC
    LIMIT 2
  ),
  liq_label_inputs AS (
    SELECT
      (SELECT v FROM rrp_last2 ORDER BY date_key DESC LIMIT 1) AS rrp_latest_mn,
      (SELECT v FROM rrp_last2 ORDER BY date_key DESC OFFSET 1 LIMIT 1) AS rrp_prev_mn,
      (SELECT v FROM tga_last2 ORDER BY date_key DESC LIMIT 1) AS tga_latest_mn,
      (SELECT v FROM tga_last2 ORDER BY date_key DESC OFFSET 1 LIMIT 1) AS tga_prev_mn,
      (SELECT date_key FROM rrp_last2 ORDER BY date_key DESC LIMIT 1) AS rrp_date_key,
      (SELECT date_key FROM tga_last2 ORDER BY date_key DESC LIMIT 1) AS tga_date_key
  ),
  liq_label AS (
    SELECT
      CASE
        WHEN rrp_latest_mn IS NULL OR rrp_prev_mn IS NULL OR tga_latest_mn IS NULL OR tga_prev_mn IS NULL THEN NULL
        WHEN (rrp_latest_mn / 1000.0) > 300.0 AND (rrp_latest_mn - rrp_prev_mn) < 0.0 AND (tga_latest_mn - tga_prev_mn) <= 0.0 THEN 'Amplified Easing'
        WHEN (rrp_latest_mn / 1000.0) > 100.0 AND (rrp_latest_mn / 1000.0) <= 300.0 THEN 'Neutral / Cushioning Phase'
        WHEN (rrp_latest_mn / 1000.0) <= 100.0 AND (tga_latest_mn - tga_prev_mn) > 0.0 THEN 'Reserve Drain / Tightening'
        WHEN (rrp_latest_mn / 1000.0) <= 100.0 AND (tga_latest_mn - tga_prev_mn) < 0.0 THEN 'Liquidity Inflection / Easing'
        ELSE NULL
      END AS regime_label,
      (rrp_latest_mn - rrp_prev_mn) AS rrp_delta_mn,
      (tga_latest_mn - tga_prev_mn) AS tga_delta_mn,
      (rrp_latest_mn / 1000.0) AS rrp_value_bil,
      (tga_latest_mn / 1000.0) AS tga_value_bil,
      GREATEST(COALESCE(rrp_date_key, 0), COALESCE(tga_date_key, 0)) AS data_date_key
    FROM liq_label_inputs
  ),
  liq_label_ease AS (
    SELECT
      regime_label,
      rrp_delta_mn, tga_delta_mn,
      rrp_value_bil, tga_value_bil,
      data_date_key,
      CASE
        WHEN regime_label = 'Amplified Easing' THEN 85.0
        WHEN regime_label = 'Liquidity Inflection / Easing' THEN 70.0
        WHEN regime_label = 'Neutral / Cushioning Phase' THEN 50.0
        WHEN regime_label = 'Reserve Drain / Tightening' THEN 25.0
        ELSE NULL
      END AS ease_score
    FROM liq_label
  ),
  liq_label_risk_off AS (
    SELECT
      regime_label,
      rrp_delta_mn, tga_delta_mn,
      rrp_value_bil, tga_value_bil,
      data_date_key,
      CASE WHEN ease_score IS NULL THEN NULL ELSE (100.0 - ease_score) END AS risk_off_score
    FROM liq_label_ease
  ),

  walcl_hist AS (
    SELECT d.date_key, d.full_date, m.value::double precision AS walcl_mn
    FROM rankalpha.vw_macro_series m
    JOIN rankalpha.dim_date d ON d.full_date = m.as_of_date
    JOIN params p ON TRUE
    WHERE m.series_code = 'US_FED_WALCL'
      AND d.full_date <= p.asof_date
      AND m.value IS NOT NULL
    ORDER BY d.date_key DESC
    LIMIT 520
  ),
  walcl_hist_asc AS (
    SELECT * FROM walcl_hist ORDER BY date_key ASC
  ),
  -- forward fill TGA and ON RRP onto WALCL dates
  netliq_raw AS (
    SELECT
      w.date_key,
      w.full_date,
      w.walcl_mn,
      (
        SELECT m.value::double precision
        FROM rankalpha.vw_macro_series m
        JOIN rankalpha.dim_date d ON d.full_date = m.as_of_date
        WHERE m.series_code = 'US_TGA_BAL'
          AND d.full_date <= w.full_date
          AND m.value IS NOT NULL
        ORDER BY d.date_key DESC
        LIMIT 1
      ) AS tga_mn,
      (
        SELECT m.value::double precision
        FROM rankalpha.vw_macro_series m
        JOIN rankalpha.dim_date d ON d.full_date = m.as_of_date
        WHERE m.series_code = 'US_ON_RRP'
          AND d.full_date <= w.full_date
          AND m.value IS NOT NULL
        ORDER BY d.date_key DESC
        LIMIT 1
      ) AS rrp_mn
    FROM walcl_hist_asc w
  ),
  netliq AS (
    SELECT
      date_key,
      full_date,
      walcl_mn,
      tga_mn,
      rrp_mn,
      CASE
        WHEN walcl_mn IS NULL OR tga_mn IS NULL OR rrp_mn IS NULL THEN NULL
        ELSE (walcl_mn - tga_mn - rrp_mn)
      END AS net_mn,
      CASE
        WHEN walcl_mn IS NULL OR tga_mn IS NULL OR rrp_mn IS NULL THEN NULL
        ELSE (walcl_mn - tga_mn - rrp_mn) / 1000000.0
      END AS net_trn
    FROM netliq_raw
  ),
  netliq_deltas AS (
    SELECT
      *,
      (net_trn - LAG(net_trn, 4) OVER (ORDER BY date_key)) AS delta_4w_trn,
      (net_trn - LAG(net_trn, 13) OVER (ORDER BY date_key)) AS delta_13w_trn
    FROM netliq
  ),
  netliq_obs AS (
    SELECT *
    FROM netliq_deltas
    ORDER BY date_key DESC
    LIMIT 1
  ),
  netliq_delta_stats AS (
    SELECT
      -- stats computed over the available WALCL-anchored history (up to 520 obs)
      AVG(delta_4w_trn) FILTER (WHERE delta_4w_trn IS NOT NULL) AS mu4,
      STDDEV_SAMP(delta_4w_trn) FILTER (WHERE delta_4w_trn IS NOT NULL) AS sd4,
      COUNT(delta_4w_trn) FILTER (WHERE delta_4w_trn IS NOT NULL) AS n4,
      AVG(delta_13w_trn) FILTER (WHERE delta_13w_trn IS NOT NULL) AS mu13,
      STDDEV_SAMP(delta_13w_trn) FILTER (WHERE delta_13w_trn IS NOT NULL) AS sd13,
      COUNT(delta_13w_trn) FILTER (WHERE delta_13w_trn IS NOT NULL) AS n13
    FROM netliq_deltas
  ),
  netliq_z AS (
    SELECT
      o.date_key AS data_date_key,
      o.net_trn,
      o.delta_4w_trn,
      o.delta_13w_trn,
      CASE WHEN s.n4 >= 52 AND s.sd4 IS NOT NULL AND s.sd4 > 0 THEN (o.delta_4w_trn - s.mu4) / s.sd4 ELSE NULL END AS delta_4w_z,
      CASE WHEN s.n13 >= 52 AND s.sd13 IS NOT NULL AND s.sd13 > 0 THEN (o.delta_13w_trn - s.mu13) / s.sd13 ELSE NULL END AS delta_13w_z
    FROM netliq_obs o
    CROSS JOIN netliq_delta_stats s
  ),
  netliq_ease AS (
    SELECT
      data_date_key,
      net_trn,
      delta_4w_trn,
      delta_13w_trn,
      delta_4w_z,
      delta_13w_z,
      rankalpha.fn_nowcast_score_from_z(delta_4w_z) AS ease_4w,
      rankalpha.fn_nowcast_score_from_z(delta_13w_z) AS ease_13w
    FROM netliq_z
  ),
  netliq_ease_blend AS (
    SELECT
      data_date_key,
      net_trn,
      delta_4w_trn,
      delta_13w_trn,
      delta_4w_z,
      delta_13w_z,
      ease_4w,
      ease_13w,
      CASE
        WHEN ease_4w IS NULL AND ease_13w IS NULL THEN NULL
        WHEN ease_4w IS NOT NULL AND ease_13w IS NOT NULL THEN (0.6 * ease_4w + 0.4 * ease_13w)
        WHEN ease_4w IS NOT NULL THEN ease_4w
        ELSE ease_13w
      END AS netliq_ease_score
    FROM netliq_ease
  ),
  netliq_risk_off AS (
    SELECT
      data_date_key,
      net_trn,
      delta_4w_trn,
      delta_13w_trn,
      delta_4w_z,
      delta_13w_z,
      netliq_ease_score,
      CASE WHEN netliq_ease_score IS NULL THEN NULL ELSE (100.0 - netliq_ease_score) END AS risk_off_score
    FROM netliq_ease_blend
  ),
  liquidity_pillar AS (
    SELECT
      'liquidity'::text AS pillar_key,
      1::smallint AS tier,
      CASE
        WHEN l.risk_off_score IS NULL AND n.risk_off_score IS NULL THEN NULL
        WHEN l.risk_off_score IS NOT NULL AND n.risk_off_score IS NOT NULL THEN (l.risk_off_score + n.risk_off_score) / 2.0
        WHEN l.risk_off_score IS NOT NULL THEN l.risk_off_score
        ELSE n.risk_off_score
      END AS score,
      GREATEST(COALESCE(l.data_date_key, 0), COALESCE(n.data_date_key, 0))::int AS data_date_key,
      jsonb_build_object(
        'regime_label', l.regime_label,
        'rrp_value_bil', l.rrp_value_bil,
        'tga_value_bil', l.tga_value_bil,
        'rrp_change_mn', l.rrp_delta_mn,
        'tga_change_mn', l.tga_delta_mn,
        'label_risk_off', l.risk_off_score,
        'net_liquidity_trn', n.net_trn,
        'delta_4w_trn', n.delta_4w_trn,
        'delta_13w_trn', n.delta_13w_trn,
        'delta_4w_z', n.delta_4w_z,
        'delta_13w_z', n.delta_13w_z,
        'netliq_risk_off', n.risk_off_score
      ) AS details
    FROM (SELECT 1) _
    LEFT JOIN liq_label_risk_off l ON TRUE
    LEFT JOIN netliq_risk_off n ON TRUE
  ),

  /* ---------- Vol / Tail (equity): term structure + SKEW ---------- */
  vix_obs AS (
    SELECT
      f.date_key,
      f.regime,
      f.risk_flag,
      f.is_backwardation_front,
      f.is_backwardation_short,
      f.is_contango_full,
      f.vix_1m,
      f.curve_slope
    FROM rankalpha.fact_vix_term_structure f
    JOIN params p ON TRUE
    WHERE f.underlying_symbol = 'SPX/VIX'
      AND f.date_key <= p.asof_date_key
    ORDER BY f.date_key DESC
    LIMIT 1
  ),
  vix_term_score AS (
    SELECT
      date_key AS data_date_key,
      vix_1m,
      curve_slope,
      regime,
      risk_flag,
      is_backwardation_front,
      is_backwardation_short,
      is_contango_full,
      CASE
        WHEN lower(coalesce(regime,'')) = 'panic' THEN 85.0
        WHEN lower(coalesce(regime,'')) = 'stressed' THEN 70.0
        WHEN risk_flag IS NOT NULL AND risk_flag >= 2 THEN 85.0
        WHEN risk_flag IS NOT NULL AND risk_flag >= 1 THEN 70.0
        WHEN risk_flag IS NOT NULL THEN 45.0
        WHEN coalesce(is_backwardation_front,false) OR coalesce(is_backwardation_short,false) THEN 80.0
        WHEN coalesce(is_contango_full,false) THEN 35.0
        ELSE 50.0
      END AS risk_off_score
    FROM vix_obs
  ),
  skew_obs AS (
    SELECT b.date_key, b.close_px::double precision AS level
    FROM rankalpha.vw_benchmark_price b
    JOIN params p ON TRUE
    WHERE b.benchmark_name = '$SKEW'
      AND b.date_key <= p.asof_date_key
      AND b.close_px IS NOT NULL
    ORDER BY b.date_key DESC
    LIMIT 1
  ),
  skew_hist AS (
    SELECT b.close_px::double precision AS v
    FROM rankalpha.vw_benchmark_price b
    JOIN skew_obs o ON TRUE
    JOIN params p ON TRUE
    WHERE b.benchmark_name = '$SKEW'
      AND b.date_key <= o.date_key
      AND b.close_px IS NOT NULL
    ORDER BY b.date_key DESC
    LIMIT (SELECT w_med FROM params)
  ),
  skew_hist_num AS (
    SELECT v, ROW_NUMBER() OVER () AS rn
    FROM skew_hist
  ),
  skew_stats AS (
    SELECT
      (SELECT COUNT(*) FROM skew_hist_num WHERE rn <= (SELECT w_short FROM params)) AS n252,
      (SELECT AVG(v) FROM skew_hist_num WHERE rn <= (SELECT w_short FROM params)) AS mu252,
      (SELECT STDDEV_SAMP(v) FROM skew_hist_num WHERE rn <= (SELECT w_short FROM params)) AS sd252,
      (SELECT COUNT(*) FROM skew_hist_num) AS n756,
      (SELECT AVG(v) FROM skew_hist_num) AS mu756,
      (SELECT STDDEV_SAMP(v) FROM skew_hist_num) AS sd756
  ),
  skew_z AS (
    SELECT
      o.date_key AS data_date_key,
      o.level,
      CASE
        WHEN s.n252 >= (SELECT min_short FROM params) AND s.sd252 IS NOT NULL AND s.sd252 > 0 THEN (o.level - s.mu252) / s.sd252
        ELSE NULL
      END AS z252,
      CASE
        WHEN s.n756 >= (SELECT min_med FROM params) AND s.sd756 IS NOT NULL AND s.sd756 > 0 THEN (o.level - s.mu756) / s.sd756
        ELSE NULL
      END AS z756
    FROM skew_obs o
    CROSS JOIN skew_stats s
  ),
  skew_z_blend AS (
    SELECT
      data_date_key,
      level,
      z252,
      z756,
      CASE
        WHEN z252 IS NULL AND z756 IS NULL THEN NULL
        WHEN z252 IS NOT NULL AND z756 IS NOT NULL THEN (0.7*z252 + 0.3*z756)
        WHEN z252 IS NOT NULL THEN z252
        ELSE z756
      END AS z_blend
    FROM skew_z
  ),
  skew_score AS (
    SELECT
      data_date_key,
      level,
      z252,
      z756,
      z_blend,
      rankalpha.fn_nowcast_score_from_z(z_blend) AS risk_off_score
    FROM skew_z_blend
  ),
  vol_tail_pillar AS (
    SELECT
      'vol_tail'::text AS pillar_key,
      1::smallint AS tier,
      CASE
        WHEN t.risk_off_score IS NULL AND s.risk_off_score IS NULL THEN NULL
        WHEN t.risk_off_score IS NOT NULL AND s.risk_off_score IS NOT NULL THEN (t.risk_off_score + s.risk_off_score) / 2.0
        WHEN t.risk_off_score IS NOT NULL THEN t.risk_off_score
        ELSE s.risk_off_score
      END AS score,
      GREATEST(COALESCE(t.data_date_key, 0), COALESCE(s.data_date_key, 0))::int AS data_date_key,
      jsonb_build_object(
        'vix_1m', t.vix_1m,
        'curve_slope', t.curve_slope,
        'regime', t.regime,
        'risk_flag', t.risk_flag,
        'term_risk_off', t.risk_off_score,
        'skew', s.level,
        'skew_z252', s.z252,
        'skew_z756', s.z756,
        'skew_z', s.z_blend,
        'skew_risk_off', s.risk_off_score
      ) AS details
    FROM (SELECT 1) _
    LEFT JOIN vix_term_score t ON TRUE
    LEFT JOIN skew_score s ON TRUE
  ),

  /* ---------- Funding stress (FRA–OIS 3x6 z) ---------- */
  fra_obs AS (
    SELECT
      f.date_key,
      f.spread_bp::double precision AS spread_bp,
      f.fra_ois_z::double precision AS fra_ois_z
    FROM rankalpha.fact_fra_ois f
    JOIN params p ON TRUE
    WHERE f.start_months = 3
      AND f.end_months = 6
      AND f.fra_source = 'SR3'
      AND f.date_key <= p.asof_date_key
    ORDER BY f.date_key DESC
    LIMIT 1
  ),
  funding_pillar AS (
    SELECT
      'funding'::text AS pillar_key,
      2::smallint AS tier,
      rankalpha.fn_nowcast_score_from_z(f.fra_ois_z) AS score,
      f.date_key::int AS data_date_key,
      jsonb_build_object(
        'spread_bp', f.spread_bp,
        'fra_ois_z', f.fra_ois_z
      ) AS details
    FROM (SELECT 1) _
    LEFT JOIN fra_obs f ON TRUE
  ),

  /* ---------- Credit stress (HY OAS z) ---------- */
  hy_obs AS (
    SELECT
      h.date_key,
      h.hy_stress_raw::double precision AS hy_stress_raw,
      h.hy_stress_ma::double precision AS hy_stress_ma,
      h.hy_stress_z::double precision AS hy_stress_z,
      b.benchmark_name
    FROM rankalpha.fact_hy_stress h
    JOIN rankalpha.dim_benchmark b ON b.benchmark_key = h.benchmark_key
    JOIN params p ON TRUE
    WHERE b.benchmark_name = '%CCCHYS'
      AND h.date_key <= p.asof_date_key
    ORDER BY h.date_key DESC
    LIMIT 1
  ),
  credit_pillar AS (
    SELECT
      'credit'::text AS pillar_key,
      2::smallint AS tier,
      rankalpha.fn_nowcast_score_from_z(h.hy_stress_z) AS score,
      h.date_key::int AS data_date_key,
      jsonb_build_object(
        'benchmark_name', h.benchmark_name,
        'hy_stress_raw', h.hy_stress_raw,
        'hy_stress_ma', h.hy_stress_ma,
        'hy_stress_z', h.hy_stress_z
      ) AS details
    FROM (SELECT 1) _
    LEFT JOIN hy_obs h ON TRUE
  ),

  /* ---------- Rates & USD (equity drawdown): USDX + curve + real-rate change + rates shock magnitude ---------- */
  usdx_obs AS (
    SELECT b.date_key, b.close_px::double precision AS level
    FROM rankalpha.vw_benchmark_price b
    JOIN params p ON TRUE
    WHERE b.benchmark_name = '$USDX'
      AND b.date_key <= p.asof_date_key
      AND b.close_px IS NOT NULL
    ORDER BY b.date_key DESC
    LIMIT 1
  ),
  usdx_hist AS (
    SELECT b.close_px::double precision AS v
    FROM rankalpha.vw_benchmark_price b
    JOIN usdx_obs o ON TRUE
    JOIN params p ON TRUE
    WHERE b.benchmark_name = '$USDX'
      AND b.date_key <= o.date_key
      AND b.close_px IS NOT NULL
    ORDER BY b.date_key DESC
    LIMIT (SELECT w_med FROM params)
  ),
  usdx_hist_num AS (
    SELECT v, ROW_NUMBER() OVER () AS rn
    FROM usdx_hist
  ),
  usdx_stats AS (
    SELECT
      (SELECT COUNT(*) FROM usdx_hist_num WHERE rn <= (SELECT w_short FROM params)) AS n252,
      (SELECT AVG(v) FROM usdx_hist_num WHERE rn <= (SELECT w_short FROM params)) AS mu252,
      (SELECT STDDEV_SAMP(v) FROM usdx_hist_num WHERE rn <= (SELECT w_short FROM params)) AS sd252,
      (SELECT COUNT(*) FROM usdx_hist_num) AS n756,
      (SELECT AVG(v) FROM usdx_hist_num) AS mu756,
      (SELECT STDDEV_SAMP(v) FROM usdx_hist_num) AS sd756
  ),
  usdx_z AS (
    SELECT
      o.date_key AS data_date_key,
      o.level,
      CASE
        WHEN s.n252 >= (SELECT min_short FROM params) AND s.sd252 IS NOT NULL AND s.sd252 > 0 THEN (o.level - s.mu252) / s.sd252
        ELSE NULL
      END AS z252,
      CASE
        WHEN s.n756 >= (SELECT min_med FROM params) AND s.sd756 IS NOT NULL AND s.sd756 > 0 THEN (o.level - s.mu756) / s.sd756
        ELSE NULL
      END AS z756
    FROM usdx_obs o
    CROSS JOIN usdx_stats s
  ),
  usdx_z_blend AS (
    SELECT
      data_date_key,
      level,
      z252, z756,
      CASE
        WHEN z252 IS NULL AND z756 IS NULL THEN NULL
        WHEN z252 IS NOT NULL AND z756 IS NOT NULL THEN (0.7*z252 + 0.3*z756)
        WHEN z252 IS NOT NULL THEN z252
        ELSE z756
      END AS z_blend
    FROM usdx_z
  ),
  usdx_score AS (
    SELECT
      data_date_key,
      level,
      z252,
      z756,
      z_blend,
      rankalpha.fn_nowcast_score_from_z(z_blend) AS risk_off_score
    FROM usdx_z_blend
  ),

  y10_hist AS (
    SELECT d.date_key, r.rate_pct::double precision AS y10
    FROM rankalpha.vw_risk_free_rate r
    JOIN rankalpha.dim_date d ON d.full_date = r.rate_date
    JOIN params p ON TRUE
    WHERE upper(r.tenor_label) = '10Y'
      AND d.full_date <= p.asof_date
      AND r.rate_pct IS NOT NULL
    ORDER BY d.date_key DESC
    LIMIT ((SELECT w_med FROM params) + 25)
  ),
  y2_hist AS (
    SELECT d.date_key, r.rate_pct::double precision AS y2
    FROM rankalpha.vw_risk_free_rate r
    JOIN rankalpha.dim_date d ON d.full_date = r.rate_date
    JOIN params p ON TRUE
    WHERE upper(r.tenor_label) = '2Y'
      AND d.full_date <= p.asof_date
      AND r.rate_pct IS NOT NULL
    ORDER BY d.date_key DESC
    LIMIT ((SELECT w_med FROM params) + 25)
  ),
  curve_hist AS (
    SELECT
      y10.date_key,
      (y10.y10 - y2.y2) AS slope_2s10s
    FROM y10_hist y10
    JOIN y2_hist y2 ON y2.date_key = y10.date_key
    ORDER BY y10.date_key DESC
    LIMIT (SELECT w_med FROM params)
  ),
  curve_obs AS (
    SELECT * FROM curve_hist ORDER BY date_key DESC LIMIT 1
  ),
  curve_hist_num AS (
    SELECT slope_2s10s::double precision AS v, ROW_NUMBER() OVER () AS rn
    FROM curve_hist
  ),
  curve_stats AS (
    SELECT
      (SELECT COUNT(*) FROM curve_hist_num WHERE rn <= (SELECT w_short FROM params)) AS n252,
      (SELECT AVG(v) FROM curve_hist_num WHERE rn <= (SELECT w_short FROM params)) AS mu252,
      (SELECT STDDEV_SAMP(v) FROM curve_hist_num WHERE rn <= (SELECT w_short FROM params)) AS sd252,
      (SELECT COUNT(*) FROM curve_hist_num) AS n756,
      (SELECT AVG(v) FROM curve_hist_num) AS mu756,
      (SELECT STDDEV_SAMP(v) FROM curve_hist_num) AS sd756
  ),
  curve_z AS (
    SELECT
      o.date_key AS data_date_key,
      o.slope_2s10s,
      CASE
        WHEN s.n252 >= (SELECT min_short FROM params) AND s.sd252 IS NOT NULL AND s.sd252 > 0 THEN (o.slope_2s10s - s.mu252) / s.sd252
        ELSE NULL
      END AS z252,
      CASE
        WHEN s.n756 >= (SELECT min_med FROM params) AND s.sd756 IS NOT NULL AND s.sd756 > 0 THEN (o.slope_2s10s - s.mu756) / s.sd756
        ELSE NULL
      END AS z756
    FROM curve_obs o
    CROSS JOIN curve_stats s
  ),
  curve_z_blend AS (
    SELECT
      data_date_key,
      slope_2s10s,
      z252, z756,
      CASE
        WHEN z252 IS NULL AND z756 IS NULL THEN NULL
        WHEN z252 IS NOT NULL AND z756 IS NOT NULL THEN (0.7*z252 + 0.3*z756)
        WHEN z252 IS NOT NULL THEN z252
        ELSE z756
      END AS z_blend
    FROM curve_z
  ),
  curve_score AS (
    SELECT
      data_date_key,
      slope_2s10s,
      z252,
      z756,
      z_blend,
      -- more inverted (lower slope) => higher risk-off: invert sign
      rankalpha.fn_nowcast_score_from_z(-z_blend) AS risk_off_score
    FROM curve_z_blend
  ),

  tips_hist AS (
    SELECT d.date_key, m.value::double precision AS v
    FROM rankalpha.vw_macro_series m
    JOIN rankalpha.dim_date d ON d.full_date = m.as_of_date
    JOIN params p ON TRUE
    WHERE m.series_code = 'US_TIPS_10Y_REAL_YIELD'
      AND d.full_date <= p.asof_date
      AND m.value IS NOT NULL
    ORDER BY d.date_key DESC
    LIMIT ((SELECT w_med FROM params) + 25)
  ),
  tips_hist_asc AS (
    SELECT * FROM tips_hist ORDER BY date_key ASC
  ),
  tips_delta AS (
    SELECT
      date_key,
      (v - LAG(v, 20) OVER (ORDER BY date_key)) AS delta20
    FROM tips_hist_asc
  ),
  tips_obs AS (
    SELECT * FROM tips_delta ORDER BY date_key DESC LIMIT 1
  ),
  tips_hist_num AS (
    SELECT delta20::double precision AS v, ROW_NUMBER() OVER () AS rn
    FROM tips_delta
    WHERE delta20 IS NOT NULL
    ORDER BY date_key DESC
    LIMIT (SELECT w_med FROM params)
  ),
  tips_stats AS (
    SELECT
      (SELECT COUNT(*) FROM tips_hist_num WHERE rn <= (SELECT w_short FROM params)) AS n252,
      (SELECT AVG(v) FROM tips_hist_num WHERE rn <= (SELECT w_short FROM params)) AS mu252,
      (SELECT STDDEV_SAMP(v) FROM tips_hist_num WHERE rn <= (SELECT w_short FROM params)) AS sd252,
      (SELECT COUNT(*) FROM tips_hist_num) AS n756,
      (SELECT AVG(v) FROM tips_hist_num) AS mu756,
      (SELECT STDDEV_SAMP(v) FROM tips_hist_num) AS sd756
  ),
  tips_z AS (
    SELECT
      o.date_key AS data_date_key,
      o.delta20,
      CASE
        WHEN s.n252 >= (SELECT min_short FROM params) AND s.sd252 IS NOT NULL AND s.sd252 > 0 THEN (o.delta20 - s.mu252) / s.sd252
        ELSE NULL
      END AS z252,
      CASE
        WHEN s.n756 >= (SELECT min_med FROM params) AND s.sd756 IS NOT NULL AND s.sd756 > 0 THEN (o.delta20 - s.mu756) / s.sd756
        ELSE NULL
      END AS z756
    FROM tips_obs o
    CROSS JOIN tips_stats s
  ),
  tips_z_blend AS (
    SELECT
      data_date_key,
      delta20,
      z252, z756,
      CASE
        WHEN z252 IS NULL AND z756 IS NULL THEN NULL
        WHEN z252 IS NOT NULL AND z756 IS NOT NULL THEN (0.7*z252 + 0.3*z756)
        WHEN z252 IS NOT NULL THEN z252
        ELSE z756
      END AS z_blend
    FROM tips_z
  ),
  tips_score AS (
    SELECT
      data_date_key,
      delta20,
      z252,
      z756,
      z_blend,
      rankalpha.fn_nowcast_score_from_z(z_blend) AS risk_off_score
    FROM tips_z_blend
  ),

  y10_hist_asc AS (
    SELECT * FROM y10_hist ORDER BY date_key ASC
  ),
  y10_changes AS (
    SELECT
      date_key,
      y10,
      (y10 - LAG(y10, 5) OVER (ORDER BY date_key)) AS delta5,
      (y10 - LAG(y10, 20) OVER (ORDER BY date_key)) AS delta20
    FROM y10_hist_asc
  ),
  y10_shock AS (
    SELECT
      date_key,
      y10,
      delta5,
      delta20,
      CASE
        WHEN delta5 IS NULL AND delta20 IS NULL THEN NULL
        ELSE GREATEST(COALESCE(ABS(delta5), 0.0), COALESCE(ABS(delta20), 0.0)) * 100.0
      END AS shock_bp
    FROM y10_changes
  ),
  y10_shock_obs AS (
    SELECT * FROM y10_shock ORDER BY date_key DESC LIMIT 1
  ),
  y10_shock_hist_num AS (
    SELECT shock_bp::double precision AS v, ROW_NUMBER() OVER () AS rn
    FROM y10_shock
    WHERE shock_bp IS NOT NULL
    ORDER BY date_key DESC
    LIMIT (SELECT w_med FROM params)
  ),
  y10_shock_stats AS (
    SELECT
      (SELECT COUNT(*) FROM y10_shock_hist_num WHERE rn <= (SELECT w_short FROM params)) AS n252,
      (SELECT AVG(v) FROM y10_shock_hist_num WHERE rn <= (SELECT w_short FROM params)) AS mu252,
      (SELECT STDDEV_SAMP(v) FROM y10_shock_hist_num WHERE rn <= (SELECT w_short FROM params)) AS sd252,
      (SELECT COUNT(*) FROM y10_shock_hist_num) AS n756,
      (SELECT AVG(v) FROM y10_shock_hist_num) AS mu756,
      (SELECT STDDEV_SAMP(v) FROM y10_shock_hist_num) AS sd756
  ),
  y10_shock_z AS (
    SELECT
      o.date_key AS data_date_key,
      o.y10,
      o.delta5,
      o.delta20,
      o.shock_bp,
      CASE
        WHEN s.n252 >= (SELECT min_short FROM params) AND s.sd252 IS NOT NULL AND s.sd252 > 0 THEN (o.shock_bp - s.mu252) / s.sd252
        ELSE NULL
      END AS z252,
      CASE
        WHEN s.n756 >= (SELECT min_med FROM params) AND s.sd756 IS NOT NULL AND s.sd756 > 0 THEN (o.shock_bp - s.mu756) / s.sd756
        ELSE NULL
      END AS z756
    FROM y10_shock_obs o
    CROSS JOIN y10_shock_stats s
  ),
  y10_shock_z_blend AS (
    SELECT
      data_date_key,
      y10,
      delta5,
      delta20,
      shock_bp,
      z252, z756,
      CASE
        WHEN z252 IS NULL AND z756 IS NULL THEN NULL
        WHEN z252 IS NOT NULL AND z756 IS NOT NULL THEN (0.7*z252 + 0.3*z756)
        WHEN z252 IS NOT NULL THEN z252
        ELSE z756
      END AS z_blend
    FROM y10_shock_z
  ),
  y10_shock_score AS (
    SELECT
      data_date_key,
      y10,
      delta5,
      delta20,
      shock_bp,
      z252,
      z756,
      z_blend,
      rankalpha.fn_nowcast_score_from_z(z_blend) AS risk_off_score
    FROM y10_shock_z_blend
  ),

  rates_usd_pillar AS (
    SELECT
      'rates_usd'::text AS pillar_key,
      2::smallint AS tier,
      (
        SELECT AVG(x) FROM (
          SELECT usdx.risk_off_score AS x FROM usdx_score usdx
          UNION ALL
          SELECT curve.risk_off_score AS x FROM curve_score curve
          UNION ALL
          SELECT tips.risk_off_score AS x FROM tips_score tips
          UNION ALL
          SELECT shock.risk_off_score AS x FROM y10_shock_score shock
        ) s
        WHERE x IS NOT NULL
      ) AS score,
      GREATEST(
        COALESCE((SELECT data_date_key FROM usdx_score), 0),
        COALESCE((SELECT data_date_key FROM curve_score), 0),
        COALESCE((SELECT data_date_key FROM tips_score), 0),
        COALESCE((SELECT data_date_key FROM y10_shock_score), 0)
      )::int AS data_date_key,
      jsonb_build_object(
        'usdx', (SELECT level FROM usdx_score),
        'usdx_z', (SELECT z_blend FROM usdx_score),
        'usdx_risk_off', (SELECT risk_off_score FROM usdx_score),
        'slope_2s10s', (SELECT slope_2s10s FROM curve_score),
        'slope_2s10s_z', (SELECT z_blend FROM curve_score),
        'curve_risk_off', (SELECT risk_off_score FROM curve_score),
        'tips_delta20', (SELECT delta20 FROM tips_score),
        'tips_delta20_z', (SELECT z_blend FROM tips_score),
        'tips_risk_off', (SELECT risk_off_score FROM tips_score),
        'y10', (SELECT y10 FROM y10_shock_score),
        'y10_delta5', (SELECT delta5 FROM y10_shock_score),
        'y10_delta20', (SELECT delta20 FROM y10_shock_score),
        'y10_shock_bp', (SELECT shock_bp FROM y10_shock_score),
        'y10_shock_z', (SELECT z_blend FROM y10_shock_score),
        'rates_shock_risk_off', (SELECT risk_off_score FROM y10_shock_score)
      ) AS details
  ),

  /* ---------- Breadth (SPX target exposure) ---------- */
  breadth_obs AS (
    SELECT d.date_key, s.value::double precision AS target_exposure
    FROM rankalpha.vw_breadth_signals s
    JOIN rankalpha.dim_date d ON d.full_date = s.as_of_date
    JOIN params p ON TRUE
    WHERE s.series_code = 'US_SPX_BREADTH_TARGET_EXPOSURE'
      AND d.full_date <= p.asof_date
      AND s.value IS NOT NULL
    ORDER BY d.date_key DESC
    LIMIT 1
  ),
  breadth_pillar AS (
    SELECT
      'breadth'::text AS pillar_key,
      3::smallint AS tier,
      rankalpha.fn_nowcast_clamp((1.0 - b.target_exposure) * 100.0, 0.0, 100.0) AS score,
      b.date_key::int AS data_date_key,
      jsonb_build_object(
        'target_exposure', b.target_exposure
      ) AS details
    FROM (SELECT 1) _
    LEFT JOIN breadth_obs b ON TRUE
  ),

  /* ---------- Money flow (cyc - def appetite) ---------- */
  mf_score_type AS (
    SELECT score_type_key
    FROM rankalpha.dim_score_type
    WHERE score_type_name = 'money flow score'
    LIMIT 1
  ),
  mf_dates AS (
    SELECT dd.date_key
    FROM rankalpha.dim_date dd
    JOIN params p ON TRUE
    WHERE dd.is_trading_day IS TRUE
      AND dd.full_date <= p.asof_date
    ORDER BY dd.date_key DESC
    LIMIT (SELECT w_med FROM params)
  ),
  mf_sector_day AS (
    SELECT
      f.date_key,
      CASE
        WHEN upper(trim(ds.sector)) = 'ENERGY' THEN 'XLE'
        WHEN upper(trim(ds.sector)) LIKE '%MATERIAL%' OR upper(trim(ds.sector)) LIKE '%METAL%' OR upper(trim(ds.sector)) LIKE '%CHEM%' THEN 'XLB'
        WHEN upper(trim(ds.sector)) LIKE '%INDUSTRIAL%' OR upper(trim(ds.sector)) LIKE '%CAPITAL GOODS%' OR upper(trim(ds.sector)) LIKE '%TRANSPORT%' THEN 'XLI'
        WHEN upper(trim(ds.sector)) LIKE '%TECH%' OR upper(trim(ds.sector)) LIKE '%SOFTWARE%' OR upper(trim(ds.sector)) LIKE '%SEMICON%' OR upper(trim(ds.sector)) LIKE '%HARDWARE%' THEN 'XLK'
        WHEN upper(trim(ds.sector)) LIKE '%COMMUNICATION%' OR upper(trim(ds.sector)) LIKE '%TELE%' OR upper(trim(ds.sector)) LIKE '%MEDIA%' THEN 'XLC'
        WHEN upper(trim(ds.sector)) LIKE '%CONSUMER STAPLES%' OR upper(trim(ds.sector)) LIKE '%FOOD%' OR upper(trim(ds.sector)) LIKE '%BEVERAGE%' OR upper(trim(ds.sector)) LIKE '%PERSONAL PRODUCTS%' THEN 'XLP'
        WHEN upper(trim(ds.sector)) LIKE '%CONSUMER%' OR upper(trim(ds.sector)) LIKE '%RETAIL%' OR upper(trim(ds.sector)) LIKE '%APPAREL%' OR upper(trim(ds.sector)) LIKE '%AUTOMOBILE%' THEN 'XLY'
        WHEN upper(trim(ds.sector)) LIKE '%FINANC%' OR upper(trim(ds.sector)) LIKE '%BANK%' OR upper(trim(ds.sector)) LIKE '%INSURANCE%' THEN 'XLF'
        WHEN upper(trim(ds.sector)) LIKE '%HEALTH%' THEN 'XLV'
        WHEN upper(trim(ds.sector)) LIKE '%REAL ESTATE%' THEN 'XLRE'
        WHEN upper(trim(ds.sector)) LIKE '%UTILIT%' THEN 'XLU'
        ELSE NULL
      END AS sector_etf,
      AVG(f.score)::double precision AS avg_score
    FROM rankalpha.fact_score_history f
    JOIN mf_score_type st ON st.score_type_key = f.score_type_key
    JOIN rankalpha.dim_stock ds ON ds.stock_key = f.stock_key
    LEFT JOIN rankalpha.dim_asset_type at ON at.asset_type_key = ds.asset_type_key
    JOIN mf_dates md ON md.date_key = f.date_key
    WHERE ds.is_active IS TRUE
      AND ds.sector IS NOT NULL
      AND trim(ds.sector) <> ''
      AND upper(trim(ds.sector)) <> 'UNKNOWN'
      AND COALESCE(at.asset_type_name, 'equity') ILIKE 'equity'
    GROUP BY f.date_key, sector_etf
  ),
  mf_appetite_series AS (
    SELECT
      date_key,
      AVG(avg_score) FILTER (WHERE sector_etf IN ('XLY','XLI','XLF','XLK','XLE','XLB','XLC')) AS cyc_mean,
      AVG(avg_score) FILTER (WHERE sector_etf IN ('XLP','XLV','XLU','XLRE')) AS def_mean,
      COUNT(avg_score) FILTER (WHERE sector_etf IN ('XLY','XLI','XLF','XLK','XLE','XLB','XLC')) AS cyc_sectors_present,
      COUNT(avg_score) FILTER (WHERE sector_etf IN ('XLP','XLV','XLU','XLRE')) AS def_sectors_present
    FROM mf_sector_day
    WHERE sector_etf IS NOT NULL
    GROUP BY date_key
  ),
  mf_appetite AS (
    SELECT
      date_key,
      (cyc_mean - def_mean) AS appetite
    FROM mf_appetite_series
    JOIN params p ON TRUE
    WHERE cyc_mean IS NOT NULL AND def_mean IS NOT NULL
      AND cyc_sectors_present >= p.min_mf_cyc_sectors
      AND def_sectors_present >= p.min_mf_def_sectors
  ),
  mf_obs AS (
    SELECT * FROM mf_appetite ORDER BY date_key DESC LIMIT 1
  ),
  mf_hist AS (
    SELECT appetite::double precision AS v
    FROM mf_appetite
    WHERE date_key <= (SELECT date_key FROM mf_obs)
    ORDER BY date_key DESC
    LIMIT (SELECT w_med FROM params)
  ),
  mf_hist_num AS (
    SELECT v, ROW_NUMBER() OVER () AS rn
    FROM mf_hist
  ),
  mf_stats AS (
    SELECT
      (SELECT COUNT(*) FROM mf_hist_num WHERE rn <= (SELECT w_short FROM params)) AS n252,
      (SELECT AVG(v) FROM mf_hist_num WHERE rn <= (SELECT w_short FROM params)) AS mu252,
      (SELECT STDDEV_SAMP(v) FROM mf_hist_num WHERE rn <= (SELECT w_short FROM params)) AS sd252,
      (SELECT COUNT(*) FROM mf_hist_num) AS n756,
      (SELECT AVG(v) FROM mf_hist_num) AS mu756,
      (SELECT STDDEV_SAMP(v) FROM mf_hist_num) AS sd756
  ),
  mf_z AS (
    SELECT
      o.date_key AS data_date_key,
      o.appetite,
      CASE
        WHEN s.n252 >= (SELECT min_short FROM params) AND s.sd252 IS NOT NULL AND s.sd252 > 0 THEN (o.appetite - s.mu252) / s.sd252
        ELSE NULL
      END AS z252,
      CASE
        WHEN s.n756 >= (SELECT min_med FROM params) AND s.sd756 IS NOT NULL AND s.sd756 > 0 THEN (o.appetite - s.mu756) / s.sd756
        ELSE NULL
      END AS z756
    FROM mf_obs o
    CROSS JOIN mf_stats s
  ),
  mf_z_blend AS (
    SELECT
      data_date_key,
      appetite,
      z252, z756,
      CASE
        WHEN z252 IS NULL AND z756 IS NULL THEN NULL
        WHEN z252 IS NOT NULL AND z756 IS NOT NULL THEN (0.7*z252 + 0.3*z756)
        WHEN z252 IS NOT NULL THEN z252
        ELSE z756
      END AS z_blend
    FROM mf_z
  ),
  mf_score AS (
    SELECT
      data_date_key,
      appetite,
      z252,
      z756,
      z_blend,
      -- appetite positive => risk-on, so invert
      rankalpha.fn_nowcast_score_from_z(-z_blend) AS risk_off_score
    FROM mf_z_blend
  ),
  flows_pillar AS (
    SELECT
      'flows'::text AS pillar_key,
      3::smallint AS tier,
      s.risk_off_score AS score,
      s.data_date_key::int AS data_date_key,
      jsonb_build_object(
        'appetite', s.appetite,
        'appetite_z', s.z_blend,
        'risk_off', s.risk_off_score
      ) AS details
    FROM (SELECT 1) _
    LEFT JOIN mf_score s ON TRUE
  ),

  /* ---------- Cross-asset stress (peripheral): include MOVE + funding + credit ---------- */
  move_obs AS (
    SELECT b.date_key, b.close_px::double precision AS level
    FROM rankalpha.vw_benchmark_price b
    JOIN params p ON TRUE
    WHERE b.benchmark_name = '$MOVE'
      AND b.date_key <= p.asof_date_key
      AND b.close_px IS NOT NULL
    ORDER BY b.date_key DESC
    LIMIT 1
  ),
  move_hist AS (
    SELECT b.close_px::double precision AS v
    FROM rankalpha.vw_benchmark_price b
    JOIN move_obs o ON TRUE
    JOIN params p ON TRUE
    WHERE b.benchmark_name = '$MOVE'
      AND b.date_key <= o.date_key
      AND b.close_px IS NOT NULL
    ORDER BY b.date_key DESC
    LIMIT (SELECT w_med FROM params)
  ),
  move_hist_num AS (
    SELECT v, ROW_NUMBER() OVER () AS rn
    FROM move_hist
  ),
  move_stats AS (
    SELECT
      (SELECT COUNT(*) FROM move_hist_num WHERE rn <= (SELECT w_short FROM params)) AS n252,
      (SELECT AVG(v) FROM move_hist_num WHERE rn <= (SELECT w_short FROM params)) AS mu252,
      (SELECT STDDEV_SAMP(v) FROM move_hist_num WHERE rn <= (SELECT w_short FROM params)) AS sd252,
      (SELECT COUNT(*) FROM move_hist_num) AS n756,
      (SELECT AVG(v) FROM move_hist_num) AS mu756,
      (SELECT STDDEV_SAMP(v) FROM move_hist_num) AS sd756
  ),
  move_z AS (
    SELECT
      o.date_key AS data_date_key,
      o.level,
      CASE
        WHEN s.n252 >= (SELECT min_short FROM params) AND s.sd252 IS NOT NULL AND s.sd252 > 0 THEN (o.level - s.mu252) / s.sd252
        ELSE NULL
      END AS z252,
      CASE
        WHEN s.n756 >= (SELECT min_med FROM params) AND s.sd756 IS NOT NULL AND s.sd756 > 0 THEN (o.level - s.mu756) / s.sd756
        ELSE NULL
      END AS z756
    FROM move_obs o
    CROSS JOIN move_stats s
  ),
  move_z_blend AS (
    SELECT
      data_date_key,
      level,
      z252, z756,
      CASE
        WHEN z252 IS NULL AND z756 IS NULL THEN NULL
        WHEN z252 IS NOT NULL AND z756 IS NOT NULL THEN (0.7*z252 + 0.3*z756)
        WHEN z252 IS NOT NULL THEN z252
        ELSE z756
      END AS z_blend
    FROM move_z
  ),
  move_score AS (
    SELECT
      data_date_key,
      level,
      z_blend,
      rankalpha.fn_nowcast_score_from_z(z_blend) AS risk_off_score
    FROM move_z_blend
  ),

  /* ---------- Pillar set (core) ---------- */
  pillars AS (
    SELECT pillar_key, tier, score, data_date_key, details FROM liquidity_pillar
    UNION ALL
    SELECT pillar_key, tier, score, data_date_key, details FROM vol_tail_pillar
    UNION ALL
    SELECT pillar_key, tier, score, data_date_key, details FROM funding_pillar
    UNION ALL
    SELECT pillar_key, tier, score, data_date_key, details FROM credit_pillar
    UNION ALL
    SELECT pillar_key, tier, score, data_date_key, details FROM rates_usd_pillar
    UNION ALL
    SELECT pillar_key, tier, score, data_date_key, details FROM breadth_pillar
    UNION ALL
    SELECT pillar_key, tier, score, data_date_key, details FROM flows_pillar
  ),
  upsert_pillars AS (
    INSERT INTO rankalpha.fact_nowcast_pillar_snapshot (
      date_key, model_version, pillar_key, tier, score, data_date_key, details
    )
    SELECT
      (SELECT asof_date_key FROM params),
      (SELECT model_version FROM params),
      pillar_key,
      tier,
      score,
      NULLIF(data_date_key, 0),
      details
    FROM pillars
    ON CONFLICT (date_key, model_version, pillar_key) DO UPDATE SET
      tier = EXCLUDED.tier,
      score = EXCLUDED.score,
      data_date_key = EXCLUDED.data_date_key,
      details = EXCLUDED.details,
      computed_at = now()
    RETURNING 1
  ),
  tier_scores AS (
    SELECT
      tier,
      AVG(score) AS tier_score,
      COUNT(*) FILTER (WHERE score IS NOT NULL) AS n
    FROM pillars
    GROUP BY tier
  ),
  overall_base AS (
    SELECT
      -- tier weights: 0.50 / 0.30 / 0.20, re-normalized over available tiers
      (
        SELECT SUM(w * ts.tier_score) / NULLIF(SUM(w), 0)
        FROM (
          SELECT 1 AS tier, 0.50::double precision AS w UNION ALL
          SELECT 2 AS tier, 0.30::double precision AS w UNION ALL
          SELECT 3 AS tier, 0.20::double precision AS w
        ) tw
        JOIN tier_scores ts ON ts.tier = tw.tier
        WHERE ts.tier_score IS NOT NULL
      ) AS overall_risk_off
  ),

  /* ---------- No hiding place booster (returns-based correlation) ---------- */
  spx_prices AS (
    SELECT dd.date_key, dd.full_date, v.adj_close_px::double precision AS px
    FROM rankalpha.vw_stock_price_history v
    JOIN rankalpha.dim_date dd ON dd.full_date = v.price_date
    JOIN params p ON TRUE
    WHERE v.symbol = '$SPX'
      AND dd.full_date <= p.asof_date
      AND v.adj_close_px IS NOT NULL
    ORDER BY dd.date_key DESC
    LIMIT 65
  ),
  tlt_prices AS (
    SELECT dd.date_key, dd.full_date, v.adj_close_px::double precision AS px
    FROM rankalpha.vw_stock_price_history v
    JOIN rankalpha.dim_date dd ON dd.full_date = v.price_date
    JOIN params p ON TRUE
    WHERE v.symbol = 'TLT'
      AND dd.full_date <= p.asof_date
      AND v.adj_close_px IS NOT NULL
    ORDER BY dd.date_key DESC
    LIMIT 65
  ),
  joined_px AS (
    SELECT s.date_key, s.full_date, s.px AS spx_px, t.px AS tlt_px
    FROM spx_prices s
    JOIN tlt_prices t ON t.date_key = s.date_key
  ),
  joined_px_asc AS (
    SELECT * FROM joined_px ORDER BY date_key ASC
  ),
  returns AS (
    SELECT
      date_key,
      full_date,
      LN(spx_px / NULLIF(LAG(spx_px, 1) OVER (ORDER BY date_key), 0)) AS spx_lr,
      LN(tlt_px / NULLIF(LAG(tlt_px, 1) OVER (ORDER BY date_key), 0)) AS tlt_lr,
      LN(spx_px / NULLIF(LAG(spx_px, 20) OVER (ORDER BY date_key), 0)) AS spx_lr20,
      LN(tlt_px / NULLIF(LAG(tlt_px, 20) OVER (ORDER BY date_key), 0)) AS tlt_lr20
    FROM joined_px_asc
  ),
  corr60 AS (
    SELECT
      (SELECT CORR(spx_lr, tlt_lr) FROM (SELECT * FROM returns WHERE spx_lr IS NOT NULL AND tlt_lr IS NOT NULL ORDER BY date_key DESC LIMIT 60) r) AS corr_60d,
      (SELECT spx_lr20 FROM returns ORDER BY date_key DESC LIMIT 1) AS spx_ret20,
      (SELECT tlt_lr20 FROM returns ORDER BY date_key DESC LIMIT 1) AS tlt_ret20
  ),
  overall_final AS (
    SELECT
      b.overall_risk_off AS base_score,
      vt.score AS vol_tail_score,
      c.corr_60d,
      c.spx_ret20,
      c.tlt_ret20,
      CASE
        WHEN b.overall_risk_off IS NULL THEN NULL
        WHEN vt.score IS NULL OR c.corr_60d IS NULL THEN rankalpha.fn_nowcast_clamp(b.overall_risk_off, 0.0, 100.0)
        WHEN vt.score >= 70.0 AND c.corr_60d > 0.5 AND c.spx_ret20 < 0 AND c.tlt_ret20 < 0
          THEN rankalpha.fn_nowcast_clamp(
            b.overall_risk_off + (5.0 + rankalpha.fn_nowcast_clamp(((c.corr_60d - 0.5) / 0.5) * 10.0, 0.0, 10.0)),
            0.0,
            100.0
          )
        ELSE rankalpha.fn_nowcast_clamp(b.overall_risk_off, 0.0, 100.0)
      END AS overall_risk_off,
      CASE
        WHEN b.overall_risk_off IS NULL THEN FALSE
        WHEN vt.score >= 70.0 AND c.corr_60d > 0.5 AND c.spx_ret20 < 0 AND c.tlt_ret20 < 0 THEN TRUE
        ELSE FALSE
      END AS booster_applied,
      CASE
        WHEN vt.score >= 70.0 AND c.corr_60d > 0.5 AND c.spx_ret20 < 0 AND c.tlt_ret20 < 0
          THEN (5.0 + rankalpha.fn_nowcast_clamp(((c.corr_60d - 0.5) / 0.5) * 10.0, 0.0, 10.0))
        ELSE 0.0
      END AS booster_amount
    FROM overall_base b
    LEFT JOIN vol_tail_pillar vt ON TRUE
    LEFT JOIN corr60 c ON TRUE
  ),

  confidence_calc AS (
    SELECT
      o.overall_risk_off,
      (SELECT COUNT(*) FILTER (WHERE score IS NOT NULL) FROM pillars)::double precision / 7.0 AS coverage,
      CASE
        WHEN o.overall_risk_off IS NULL THEN 0.0
        ELSE rankalpha.fn_nowcast_clamp(ABS(o.overall_risk_off - 50.0) / 25.0, 0.0, 1.0)
      END AS dist,
      COALESCE((SELECT STDDEV_SAMP(score) FROM pillars WHERE score IS NOT NULL), 25.0) AS disagreement,
      rankalpha.fn_nowcast_clamp(1.0 - (COALESCE((SELECT STDDEV_SAMP(score) FROM pillars WHERE score IS NOT NULL), 25.0) / 25.0), 0.0, 1.0) AS coherence,
      rankalpha.fn_nowcast_clamp(
        0.45 * ((SELECT COUNT(*) FILTER (WHERE score IS NOT NULL) FROM pillars)::double precision / 7.0)
        + 0.30 * (
          CASE
            WHEN o.overall_risk_off IS NULL THEN 0.0
            ELSE rankalpha.fn_nowcast_clamp(ABS(o.overall_risk_off - 50.0) / 25.0, 0.0, 1.0)
          END
        )
        + 0.25 * rankalpha.fn_nowcast_clamp(1.0 - (COALESCE((SELECT STDDEV_SAMP(score) FROM pillars WHERE score IS NOT NULL), 25.0) / 25.0), 0.0, 1.0),
        0.0,
        1.0
      ) AS confidence
    FROM overall_final o
  ),

  cross_asset AS (
    SELECT
      (
        SELECT AVG(x) FROM (
          SELECT (SELECT score FROM funding_pillar) AS x
          UNION ALL
          SELECT (SELECT score FROM credit_pillar) AS x
          UNION ALL
          SELECT (SELECT risk_off_score FROM move_score) AS x
        ) s
        WHERE x IS NOT NULL
      ) AS cross_asset_stress_score,
      rankalpha.fn_nowcast_label_from_score(
        (
          SELECT AVG(x) FROM (
            SELECT (SELECT score FROM funding_pillar) AS x
            UNION ALL
            SELECT (SELECT score FROM credit_pillar) AS x
            UNION ALL
            SELECT (SELECT risk_off_score FROM move_score) AS x
          ) s
          WHERE x IS NOT NULL
        )
      ) AS cross_asset_label,
      (SELECT level FROM move_score) AS move_level,
      (SELECT z_blend FROM move_score) AS move_z,
      (SELECT risk_off_score FROM move_score) AS move_risk_off
  ),

  map_xy AS (
    SELECT
      (SELECT ease_score FROM liq_label_ease) AS liquidity_ease,
      (
        SELECT AVG(x) FROM (
          SELECT (SELECT score FROM credit_pillar) AS x
          UNION ALL
          SELECT (SELECT score FROM funding_pillar) AS x
          UNION ALL
          SELECT (SELECT risk_off_score FROM move_score) AS x
          UNION ALL
          SELECT (SELECT risk_off_score FROM skew_score) AS x
        ) s
        WHERE x IS NOT NULL
      ) AS stress_score
  )

  INSERT INTO rankalpha.fact_nowcast_snapshot (
    date_key,
    model_version,
    overall_risk_off_score,
    nowcast_label,
    confidence,
    coverage,
    tier1_score,
    tier2_score,
    tier3_score,
    cross_asset_stress_score,
    cross_asset_label,
    map_liquidity_ease,
    map_stress_score,
    spx_tlt_corr60,
    spx_ret20,
    tlt_ret20,
    booster_applied,
    booster_amount
  )
  SELECT
    (SELECT asof_date_key FROM params),
    (SELECT model_version FROM params),
    o.overall_risk_off,
    rankalpha.fn_nowcast_label_from_score(o.overall_risk_off),
    c.confidence,
    c.coverage,
    (SELECT tier_score FROM tier_scores WHERE tier = 1),
    (SELECT tier_score FROM tier_scores WHERE tier = 2),
    (SELECT tier_score FROM tier_scores WHERE tier = 3),
    xa.cross_asset_stress_score,
    xa.cross_asset_label,
    m.liquidity_ease,
    m.stress_score,
    o.corr_60d,
    o.spx_ret20,
    o.tlt_ret20,
    o.booster_applied,
    o.booster_amount
  FROM overall_final o
  CROSS JOIN confidence_calc c
  CROSS JOIN cross_asset xa
  CROSS JOIN map_xy m
  ON CONFLICT (date_key, model_version) DO UPDATE SET
    overall_risk_off_score = EXCLUDED.overall_risk_off_score,
    nowcast_label = EXCLUDED.nowcast_label,
    confidence = EXCLUDED.confidence,
    coverage = EXCLUDED.coverage,
    tier1_score = EXCLUDED.tier1_score,
    tier2_score = EXCLUDED.tier2_score,
    tier3_score = EXCLUDED.tier3_score,
    cross_asset_stress_score = EXCLUDED.cross_asset_stress_score,
    cross_asset_label = EXCLUDED.cross_asset_label,
    map_liquidity_ease = EXCLUDED.map_liquidity_ease,
    map_stress_score = EXCLUDED.map_stress_score,
    spx_tlt_corr60 = EXCLUDED.spx_tlt_corr60,
    spx_ret20 = EXCLUDED.spx_ret20,
    tlt_ret20 = EXCLUDED.tlt_ret20,
    booster_applied = EXCLUDED.booster_applied,
    booster_amount = EXCLUDED.booster_amount,
    computed_at = now();

END;
$$;
