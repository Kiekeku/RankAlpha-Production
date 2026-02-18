/* ------------------------------------------------------------
   V95__mv_rank_regime_daily.sql
   Momentum↔Value rank‑migration daily regime metrics
   - Uses eligible US universe (mv_universe_regime_us) per day
   - Includes breadth, flows, turnover, hazards, tenure, skew/dispersion
   - Computes EMA(10) + z‑scores (252d) for Val→Mom and Mom→Val flows
   - Produces FRI_z = z(Val→Mom) − z(Mom→Val), FRI_log, label, confidence
   ------------------------------------------------------------ */

SET search_path = rankalpha, public;

DROP MATERIALIZED VIEW IF EXISTS rankalpha.mv_rank_regime_daily;

CREATE MATERIALIZED VIEW rankalpha.mv_rank_regime_daily AS
WITH params AS (
  SELECT 10::numeric AS ema_days,
         252::int AS z_window,
         1e-6::numeric AS eps,
         (2.0 / (10.0 + 1.0))::numeric AS alpha
),
score_types AS (
  SELECT
    MAX(CASE WHEN score_type_name = 'momentum score' THEN score_type_key END) AS mom_key,
    MAX(CASE WHEN score_type_name = 'value score' THEN score_type_key END) AS val_key
  FROM dim_score_type
),
-- universe per trading day (US‑only eligible)
u AS (
  SELECT date_key, stock_key
  FROM mv_universe_regime_us
  WHERE eligible IS TRUE
),
-- latest per stock/date momentum/value percentiles in [0,100]
m_scores AS (
  SELECT f.date_key, f.stock_key,
         (f.score)::numeric(12,6) AS m_score,
         ROW_NUMBER() OVER (PARTITION BY f.date_key, f.stock_key ORDER BY f.load_ts DESC, f.fact_id DESC) AS rn
  FROM fact_score_history f, score_types st
  WHERE f.score_type_key = st.mom_key
),
v_scores AS (
  SELECT f.date_key, f.stock_key,
         (f.score)::numeric(12,6) AS v_score,
         ROW_NUMBER() OVER (PARTITION BY f.date_key, f.stock_key ORDER BY f.load_ts DESC, f.fact_id DESC) AS rn
  FROM fact_score_history f, score_types st
  WHERE f.score_type_key = st.val_key
),
base AS (
  SELECT d.date_key,
         u.stock_key,
         COALESCE(ms.m_score, NULL) AS m_score,
         COALESCE(vs.v_score, NULL) AS v_score,
         CASE WHEN COALESCE(ms.m_score, 0) >= 90 THEN TRUE ELSE FALSE END AS is_m_top,
         CASE WHEN COALESCE(vs.v_score, 0) >= 90 THEN TRUE ELSE FALSE END AS is_v_top
  FROM (SELECT DISTINCT date_key FROM u) d
  JOIN u ON u.date_key = d.date_key
  LEFT JOIN m_scores ms ON ms.date_key = d.date_key AND ms.stock_key = u.stock_key AND ms.rn = 1
  LEFT JOIN v_scores vs ON vs.date_key = d.date_key AND vs.stock_key = u.stock_key AND vs.rn = 1
),
-- map to prior trading day per available date in base
trading_days AS (
  SELECT d.date_key,
         LAG(d.date_key) OVER (ORDER BY d.date_key) AS prev_date_key,
         LEAD(d.date_key) OVER (ORDER BY d.date_key) AS next_date_key,
         ROW_NUMBER() OVER (ORDER BY d.date_key) AS rn
  FROM (SELECT DISTINCT date_key FROM base) d
),
today AS (
  SELECT b.*, td.prev_date_key, td.rn
  FROM base b
  JOIN trading_days td ON td.date_key = b.date_key
),
yday AS (
  SELECT b.date_key, b.stock_key, b.is_m_top AS y_is_m_top, b.is_v_top AS y_is_v_top
  FROM base b
),
joined AS (
  SELECT t.date_key, t.rn, t.stock_key,
         t.is_m_top, t.is_v_top,
         y.y_is_m_top, y.y_is_v_top
  FROM today t
  LEFT JOIN yday y
    ON y.date_key = t.prev_date_key
   AND y.stock_key = t.stock_key
),
-- daily aggregates
daily AS (
  SELECT
    j.date_key,
    td.rn,
    COUNT(*)::numeric AS universe_size,
    AVG(CASE WHEN j.is_m_top THEN 1.0 ELSE 0.0 END)::numeric(12,6) AS momentum_breadth,
    AVG(CASE WHEN j.is_v_top THEN 1.0 ELSE 0.0 END)::numeric(12,6) AS value_breadth,
    AVG(COALESCE(ms.m_score,0.0) - COALESCE(vs.v_score,0.0))::numeric(12,6) AS factor_skew_mean,
    STDDEV_SAMP(ms.m_score)::numeric(12,6) AS dispersion_m_std,
    STDDEV_SAMP(vs.v_score)::numeric(12,6) AS dispersion_v_std,
    -- flows on U(t−1) ∩ U(t)
    SUM(CASE WHEN (j.y_is_v_top IS TRUE AND COALESCE(j.y_is_m_top, FALSE) IS FALSE AND j.is_m_top IS TRUE) THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*),0) AS val_to_mom_raw,
    SUM(CASE WHEN (j.y_is_m_top IS TRUE AND COALESCE(j.y_is_v_top, FALSE) IS FALSE AND j.is_v_top IS TRUE) THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*),0) AS mom_to_val_raw,
    -- top bucket turnover (union of changes)
    SUM(CASE WHEN (COALESCE(j.is_m_top, FALSE) <> COALESCE(j.y_is_m_top, FALSE)) OR (COALESCE(j.is_v_top, FALSE) <> COALESCE(j.y_is_v_top, FALSE)) THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*),0) AS top_bucket_turnover,
    -- hazards: exits from yesterday's top buckets among intersection
    SUM(CASE WHEN (COALESCE(j.y_is_m_top, FALSE) IS TRUE AND COALESCE(j.is_m_top, FALSE) IS FALSE) THEN 1 ELSE 0 END)::numeric AS m_exits_count,
    SUM(CASE WHEN (COALESCE(j.y_is_m_top, FALSE) IS TRUE) THEN 1 ELSE 0 END)::numeric AS m_prev_count,
    SUM(CASE WHEN (COALESCE(j.y_is_v_top, FALSE) IS TRUE AND COALESCE(j.is_v_top, FALSE) IS FALSE) THEN 1 ELSE 0 END)::numeric AS v_exits_count,
    SUM(CASE WHEN (COALESCE(j.y_is_v_top, FALSE) IS TRUE) THEN 1 ELSE 0 END)::numeric AS v_prev_count
  FROM joined j
  JOIN trading_days td ON td.date_key = j.date_key
  LEFT JOIN m_scores ms ON ms.date_key = j.date_key AND ms.stock_key = j.stock_key AND ms.rn = 1
  LEFT JOIN v_scores vs ON vs.date_key = j.date_key AND vs.stock_key = j.stock_key AND vs.rn = 1
  GROUP BY j.date_key, td.rn
),
hazards AS (
  SELECT date_key, rn,
         (CASE WHEN m_prev_count > 0 THEN (m_exits_count / NULLIF(m_prev_count,0)) ELSE 0 END)::numeric(12,6) AS hazard_m,
         (CASE WHEN v_prev_count > 0 THEN (v_exits_count / NULLIF(v_prev_count,0)) ELSE 0 END)::numeric(12,6) AS hazard_v
  FROM daily
),
streaks_m_flags AS (
  SELECT t.date_key, t.stock_key, t.is_m_top,
         CASE WHEN t.is_m_top IS TRUE AND COALESCE(LAG(t.is_m_top) OVER (PARTITION BY t.stock_key ORDER BY t.date_key), FALSE) IS FALSE THEN 1 ELSE 0 END AS start_m
  FROM today t
),
streaks_m AS (
  SELECT f.date_key, f.stock_key, f.is_m_top,
         CASE WHEN f.is_m_top THEN
           SUM(f.start_m) OVER (PARTITION BY f.stock_key ORDER BY f.date_key ROWS UNBOUNDED PRECEDING)
         ELSE NULL END AS grp
  FROM streaks_m_flags f
),
streaks_v_flags AS (
  SELECT t.date_key, t.stock_key, t.is_v_top,
         CASE WHEN t.is_v_top IS TRUE AND COALESCE(LAG(t.is_v_top) OVER (PARTITION BY t.stock_key ORDER BY t.date_key), FALSE) IS FALSE THEN 1 ELSE 0 END AS start_v
  FROM today t
),
streaks_v AS (
  SELECT f.date_key, f.stock_key, f.is_v_top,
         CASE WHEN f.is_v_top THEN
           SUM(f.start_v) OVER (PARTITION BY f.stock_key ORDER BY f.date_key ROWS UNBOUNDED PRECEDING)
         ELSE NULL END AS grp
  FROM streaks_v_flags f
),
tenure_m AS (
  SELECT date_key,
         ROW_NUMBER() OVER (PARTITION BY stock_key, grp ORDER BY date_key) AS streak_len
  FROM streaks_m
  WHERE is_m_top IS TRUE
),
tenure_v AS (
  SELECT date_key,
         ROW_NUMBER() OVER (PARTITION BY stock_key, grp ORDER BY date_key) AS streak_len
  FROM streaks_v
  WHERE is_v_top IS TRUE
),
tenure_daily AS (
  SELECT d.date_key, d.rn,
         PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY tm.streak_len)::numeric(12,6) AS tenure_m_median_days,
         PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY tv.streak_len)::numeric(12,6) AS tenure_v_median_days
  FROM trading_days d
  LEFT JOIN tenure_m tm ON tm.date_key = d.date_key
  LEFT JOIN tenure_v tv ON tv.date_key = d.date_key
  GROUP BY d.date_key, d.rn
),
daily_all AS (
  SELECT d.date_key, d.rn,
         d.universe_size, d.momentum_breadth, d.value_breadth,
         (d.momentum_breadth - d.value_breadth)::numeric(12,6) AS breadth_spread,
         d.val_to_mom_raw, d.mom_to_val_raw, d.top_bucket_turnover,
         h.hazard_m, h.hazard_v,
         t.tenure_m_median_days, t.tenure_v_median_days,
         d.factor_skew_mean, d.dispersion_m_std, d.dispersion_v_std
  FROM daily d
  LEFT JOIN hazards h ON h.date_key = d.date_key AND h.rn = d.rn
  LEFT JOIN tenure_daily t ON t.date_key = d.date_key AND t.rn = d.rn
),
base2 AS (
  SELECT date_key, rn,
         COALESCE(val_to_mom_raw, 0.0)::numeric(12,6) AS v2m_raw,
         COALESCE(mom_to_val_raw, 0.0)::numeric(12,6) AS m2v_raw
  FROM daily_all
  ORDER BY rn
),
sma AS (
  SELECT b.rn, b.date_key,
         b.v2m_raw,
         b.m2v_raw,
         AVG(b.v2m_raw) OVER (ORDER BY b.rn ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS v2m_ema,
         AVG(b.m2v_raw) OVER (ORDER BY b.rn ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS m2v_ema
  FROM base2 b
),
zcalc AS (
  SELECT a.date_key, a.rn,
         a.v2m_raw, a.m2v_raw, a.v2m_ema, a.m2v_ema,
         (a.v2m_ema - AVG(a.v2m_ema) OVER (ORDER BY a.rn ROWS BETWEEN 251 PRECEDING AND CURRENT ROW))
           / NULLIF(STDDEV_SAMP(a.v2m_ema) OVER (ORDER BY a.rn ROWS BETWEEN 251 PRECEDING AND CURRENT ROW), 0.0) AS v2m_z,
         (a.m2v_ema - AVG(a.m2v_ema) OVER (ORDER BY a.rn ROWS BETWEEN 251 PRECEDING AND CURRENT ROW))
           / NULLIF(STDDEV_SAMP(a.m2v_ema) OVER (ORDER BY a.rn ROWS BETWEEN 251 PRECEDING AND CURRENT ROW), 0.0) AS m2v_z
  FROM sma a
),
final_series AS (
  SELECT d.*, z.v2m_ema, z.m2v_ema, z.v2m_z, z.m2v_z,
         LN( (z.v2m_ema + (SELECT eps FROM params)) / NULLIF(z.m2v_ema + (SELECT eps FROM params), 0.0) )::numeric(12,6) AS fri_log,
         (z.v2m_z - z.m2v_z)::numeric(12,6) AS fri_z,
         -- normalized flows by turnover
         (CASE WHEN d.top_bucket_turnover > 0 THEN d.val_to_mom_raw / d.top_bucket_turnover ELSE 0 END)::numeric(12,6) AS val_to_mom_norm,
         (CASE WHEN d.top_bucket_turnover > 0 THEN d.mom_to_val_raw / d.top_bucket_turnover ELSE 0 END)::numeric(12,6) AS mom_to_val_norm
  FROM daily_all d
  JOIN zcalc z ON z.date_key = d.date_key AND z.rn = d.rn
),
 labels AS (
  SELECT f.*, 
         -- slopes: 5‑day delta on FRI_z
         (f.fri_z - COALESCE(LAG(f.fri_z, 5) OVER (ORDER BY f.rn), f.fri_z))::numeric(12,6) AS fri_slope_5d,
         -- z for turnover and hazards for confidence/stress
         (f.top_bucket_turnover - AVG(f.top_bucket_turnover) OVER (ORDER BY f.rn ROWS BETWEEN 251 PRECEDING AND CURRENT ROW))
           / NULLIF(STDDEV_SAMP(f.top_bucket_turnover) OVER (ORDER BY f.rn ROWS BETWEEN 251 PRECEDING AND CURRENT ROW), 0.0) AS tt_z,
         (f.hazard_m - AVG(f.hazard_m) OVER (ORDER BY f.rn ROWS BETWEEN 251 PRECEDING AND CURRENT ROW))
           / NULLIF(STDDEV_SAMP(f.hazard_m) OVER (ORDER BY f.rn ROWS BETWEEN 251 PRECEDING AND CURRENT ROW), 0.0) AS hz_m_z,
         (f.hazard_v - AVG(f.hazard_v) OVER (ORDER BY f.rn ROWS BETWEEN 251 PRECEDING AND CURRENT ROW))
            / NULLIF(STDDEV_SAMP(f.hazard_v) OVER (ORDER BY f.rn ROWS BETWEEN 251 PRECEDING AND CURRENT ROW), 0.0) AS hz_v_z
  FROM final_series f
),
labels2 AS (
  SELECT l.*, 
         -- base conditions
         (CASE WHEN l.fri_z >= 0.5 AND l.fri_slope_5d >= 0 AND COALESCE(l.hz_m_z,0) <= 0 THEN TRUE ELSE FALSE END) AS cond_mom,
         (CASE WHEN l.fri_z <= -0.5 AND l.fri_slope_5d <= 0 AND COALESCE(l.hz_m_z,0) >= 0 THEN TRUE ELSE FALSE END) AS cond_val,
         -- stress sub‑conditions
          (CASE WHEN COALESCE(l.tt_z,0) >= 1.2816 THEN 1 ELSE 0 END
           + CASE WHEN GREATEST(COALESCE(l.hz_m_z,0), COALESCE(l.hz_v_z,0)) >= 1.2816 THEN 1 ELSE 0 END
           + CASE WHEN ABS(l.fri_z) <= 0.3 THEN 1 ELSE 0 END) AS stress_signals
  FROM labels l
),
labels3 AS (
  SELECT l2.*,
         -- hysteresis counts (rewrite to avoid window-over-window reliance): current + lag1 + lag2
         ( (CASE WHEN l2.stress_signals >= 2 THEN 1 ELSE 0 END)
           + COALESCE(CASE WHEN LAG(l2.stress_signals, 1) OVER (ORDER BY l2.rn) >= 2 THEN 1 ELSE 0 END, 0)
           + COALESCE(CASE WHEN LAG(l2.stress_signals, 2) OVER (ORDER BY l2.rn) >= 2 THEN 1 ELSE 0 END, 0)
         ) AS stress_2of3,
         (CASE WHEN l2.cond_mom AND COALESCE(LAG(l2.cond_mom) OVER (ORDER BY l2.rn), FALSE) THEN TRUE ELSE FALSE END) AS cond_mom_confirm,
         (CASE WHEN l2.cond_val AND COALESCE(LAG(l2.cond_val) OVER (ORDER BY l2.rn), FALSE) THEN TRUE ELSE FALSE END) AS cond_val_confirm
  FROM labels2 l2
),
final AS (
  SELECT l3.date_key,
         l3.universe_size::int AS universe_size,
         l3.momentum_breadth::numeric(12,6) AS momentum_breadth,
         l3.value_breadth::numeric(12,6) AS value_breadth,
         l3.breadth_spread::numeric(12,6) AS breadth_spread,
         l3.val_to_mom_raw::numeric(12,6) AS val_to_mom_raw,
         l3.mom_to_val_raw::numeric(12,6) AS mom_to_val_raw,
         l3.top_bucket_turnover::numeric(12,6) AS top_bucket_turnover,
         l3.val_to_mom_norm::numeric(12,6) AS val_to_mom_norm,
         l3.mom_to_val_norm::numeric(12,6) AS mom_to_val_norm,
         l3.fri_z::numeric(12,6) AS fri_z,
         l3.fri_log::numeric(12,6) AS fri_log,
         l3.tenure_m_median_days::numeric(12,6) AS tenure_m_median_days,
         l3.tenure_v_median_days::numeric(12,6) AS tenure_v_median_days,
         l3.hazard_m::numeric(12,6) AS hazard_m,
         l3.hazard_v::numeric(12,6) AS hazard_v,
         l3.factor_skew_mean::numeric(12,6) AS factor_skew_mean,
         l3.dispersion_m_std::numeric(12,6) AS dispersion_m_std,
         l3.dispersion_v_std::numeric(12,6) AS dispersion_v_std,
         CASE
           WHEN l3.stress_2of3 >= 2 THEN 'stress'
           WHEN l3.cond_mom_confirm OR (l3.cond_mom AND ABS(l3.fri_z) >= 1.0) THEN 'momentum_led'
           WHEN l3.cond_val_confirm OR (l3.cond_val AND ABS(l3.fri_z) >= 1.0) THEN 'value_led'
           ELSE 'transition'
         END AS regime_label,
         -- Confidence
         CASE
           WHEN (CASE WHEN l3.stress_2of3 >= 2 THEN TRUE ELSE FALSE END) THEN
             (1.0 / (1.0 + EXP(-COALESCE(l3.tt_z,0)))) * (1.0 / (1.0 + EXP(-GREATEST(COALESCE(l3.hz_m_z,0), COALESCE(l3.hz_v_z,0))))) * (1.0 - (LEAST(ABS(l3.fri_z), 4.0) / 2.0))
           WHEN l3.fri_z IS NOT NULL THEN
             (1.0 / (1.0 + EXP(-LEAST(ABS(l3.fri_z), 4.0)))) * (1.0 - (1.0 / (1.0 + EXP(-COALESCE(l3.hz_m_z,0)))))
           ELSE NULL
         END::numeric(12,6) AS regime_confidence
  FROM labels3 l3
)
SELECT d.full_date AS as_of_date,
       f.*
FROM final f
JOIN dim_date d ON d.date_key = f.date_key
ORDER BY f.date_key;

CREATE UNIQUE INDEX IF NOT EXISTS mv_rank_regime_daily_pk
  ON rankalpha.mv_rank_regime_daily (as_of_date);

/* ------------------------------------------------------------
   END OF FILE
   ------------------------------------------------------------ */
