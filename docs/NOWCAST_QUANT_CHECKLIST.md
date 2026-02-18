# Risk Nowcast — Quant Checklist (1‑pager)

Use this as the meeting checklist with a senior quant. It’s intentionally “mechanical”: what each number means, the exact transforms, and where to inspect the implementation.

Canonical deep-dive (UI → API → DB traceability + broader context): `macro.md`.

## Source of truth (Nowcast v2)
- **DB compute + storage:** `docker/database/sql/migrations/V121__nowcast_snapshots.sql`
  - Writes:
    - `rankalpha.fact_nowcast_snapshot` (overall + tiers + diagnostics + map coords)
    - `rankalpha.fact_nowcast_pillar_snapshot` (pillar scores + per-pillar JSON details)
  - Views:
    - `rankalpha.vw_nowcast_snapshot_latest`
    - `rankalpha.vw_nowcast_snapshot_series_with_deltas` (Δ1 trading day, Δ5 trading days)
  - Functions:
    - `rankalpha.fn_nowcast_snapshot_upsert_latest(model_version)`
    - `rankalpha.fn_nowcast_snapshot_backfill(model_version, trading_days)`
- **API read path:** `GET /api/v1/nowcast/latest` (`apps/api/src/routers/nowcast.py`)
- **Frontend render path:** Home card reads API and renders snapshot values:
  - `apps/frontend/src/features/regime/regime-summary.tsx`

## Score conventions
- All pillar scores are on a **risk-off scale**: `risk_off_score ∈ [0, 100]` where **higher = more stress / drawdown risk**.
- Z-score → score mapping uses a standard-normal CDF: `score = 100 * Φ(z)`.
  - Implemented in Postgres via `erf` (see `fn_nowcast_score_from_z`).
- Fixed standardization windows (to avoid UI “window drift”):
  - Short: `252` obs (min `60`)
  - Medium: `756` obs (min `200`)
  - Blend when both are available: `z_blend = 0.7*z252 + 0.3*z756` (else whichever exists).
- Inversion for risk-on signals: if “higher = risk-on”, invert before mapping (e.g., `Φ(-z)`).

## Pillars (inputs → transform → score)

### Tier 1 — Capacity for risk (50%)

**Liquidity**
- Inputs:
  - `rankalpha.vw_macro_series`: `US_ON_RRP`, `US_TGA_BAL`, `US_FED_WALCL`
- Label component:
  - Rule-based regime label from ON RRP / TGA (same label set as API).
  - Map label → liquidity ease:
    - Amplified Easing → 85
    - Liquidity Inflection / Easing → 70
    - Neutral / Cushioning Phase → 50
    - Reserve Drain / Tightening → 25
  - Convert to risk-off: `label_risk_off = 100 - ease`.
- Net Liquidity impulse component:
  - Net Liquidity (WALCL-anchored): `net = WALCL − TGA − ON_RRP` (levels in trillions for display).
  - Changes (WALCL-anchored): `Δ4w`, `Δ13w` (in trillions).
  - `ease_4w  = 100*Φ(delta_4w_z)`; `ease_13w = 100*Φ(delta_13w_z)`.
  - `netliq_ease = 0.6*ease_4w + 0.4*ease_13w`; `netliq_risk_off = 100 - netliq_ease`.
- Final: `liquidity_score = mean([label_risk_off, netliq_risk_off] over available)`.

**Vol / Tail (equity headline)**
- Inputs:
  - `rankalpha.fact_vix_term_structure` (`underlying_symbol='SPX/VIX'`) – term structure regime + risk flags.
  - `rankalpha.vw_benchmark_price` – `$SKEW` level.
- Term structure component (discrete risk-off):
  - `panic → 85`, `stressed → 70`, else based on `risk_flag` (>=2 → 85, >=1 → 70, else 45).
  - Fallback when `risk_flag` missing: backwardation → higher score; full contango → lower score.
- SKEW component:
  - `skew_z` computed from benchmark level history using the fixed windows above.
  - `skew_risk_off = 100*Φ(skew_z_blend)`.
- Final: `vol_tail_score = mean([term_risk_off, skew_risk_off] over available)`.

### Tier 2 — Cost of risk (30%)

**Funding Stress (FRA–OIS 3x6)**
- Inputs:
  - `rankalpha.fact_fra_ois` where `start_months=3`, `end_months=6`, `fra_source='SR3'`.
- Mapping:
  - `funding_score = 100*Φ(fra_ois_z)` (uses the stored `fra_ois_z`).

**Credit Stress (HY OAS z)**
- Inputs:
  - `rankalpha.fact_hy_stress` (default benchmark `%CCCHYS`).
- Mapping:
  - `credit_score = 100*Φ(hy_stress_z)` (uses the stored `hy_stress_z`).

**Rates & USD (equity drawdown version)**
- Inputs:
  - `rankalpha.vw_benchmark_price`: `$USDX`
  - `rankalpha.vw_risk_free_rate`: 2Y and 10Y yields (for slope and shock)
  - `rankalpha.vw_macro_series`: `US_TIPS_10Y_REAL_YIELD` (10Y real yield proxy)
- Derived features + mapping:
  - USDX level z: `usdx_risk_off = 100*Φ(usdx_z_blend)`
  - Curve slope: `slope_2s10s = y10 - y2`; `curve_risk_off = 100*Φ(-slope_z_blend)` (more inverted = more risk-off)
  - Real-rate change: `tips_delta20 = tips[t] - tips[t-20]`; `tips_risk_off = 100*Φ(tips_delta20_z_blend)`
  - **Rates shock magnitude (required):**
    - `delta5 = y10[t] - y10[t-5]`
    - `delta20 = y10[t] - y10[t-20]`
    - `shock_bp = max(|delta5|, |delta20|) * 100` (because yields are in pct points)
    - `rates_shock_risk_off = 100*Φ(shock_z_blend)`
- Final: `rates_usd_score = mean([usdx, curve, tips, rate_shock] over available)`.

### Tier 3 — Participation (20%)

**Market Breadth (SPX target exposure)**
- Inputs:
  - `rankalpha.vw_breadth_signals`: `US_SPX_BREADTH_TARGET_EXPOSURE` in `[0,1]`.
- Mapping:
  - `breadth_score = clamp((1 - target_exposure) * 100, 0, 100)`.

**Money Flow (cyc − def risk appetite)**
- Inputs:
  - `rankalpha.fact_score_history` filtered to score type `money flow score`.
  - Equity sectors mapped to SPDR proxies (XLY/XLI/XLF/XLK/XLE/XLB/XLC vs XLP/XLV/XLU/XLRE) inside the DB function.
- Derived feature:
  - `appetite[t] = mean(cyc scores) − mean(def scores)`
  - Standardize `appetite` using the fixed windows above.
- Mapping (higher appetite = more risk-on):
  - `flows_score = 100*Φ(-appetite_z_blend)`.

## Overall score, label, confidence

**Tier aggregation**
- Tier weights: Tier1=0.50, Tier2=0.30, Tier3=0.20 (re-normalized over available tiers).
- `tier_score = mean(pillar_scores in tier over available)`
- `overall_risk_off = weighted_mean(tier_scores, tier_weights)` clamped to `[0,100]`.

**Optional “no hiding place” booster**
- Uses `rankalpha.vw_stock_price_history` returns for `$SPX` and `TLT`:
  - `corr60 = corr_60d(log_ret($SPX), log_ret(TLT))`
  - `spx_ret20`, `tlt_ret20` are 20d log returns.
- Trigger (tightened):
  - `vol_tail_score >= 70`
  - `corr60 > 0.5`
  - `spx_ret20 < 0` AND `tlt_ret20 < 0`
- Boost:
  - `boost = 5 + clamp(((corr60 - 0.5)/0.5) * 10, 0, 10)` ⇒ `[5, 15]`
  - `overall_risk_off = clamp(overall_risk_off + boost, 0, 100)`

**Label**
- `overall >= 65` → `risk_off`
- `overall <= 35` → `risk_on`
- else → `neutral`

**Confidence**
- `coverage = (# pillars with score) / 7`
- `dist = clamp(abs(overall - 50)/25, 0, 1)`
- `coherence = clamp(1 - stddev(pillar_scores)/25, 0, 1)`
- `confidence = clamp(0.45*coverage + 0.30*dist + 0.25*coherence, 0, 1)`

## Cross-asset stress (peripheral) + 2D map

**Cross-asset stress (peripheral badge)**
- `cross_asset_stress_score = mean([funding_score, credit_score, MOVE_risk_off] over available)`
  - MOVE is `100*Φ(z_blend(MOVE level))` from `rankalpha.vw_benchmark_price` (`$MOVE`).
- Label uses the same 35/65 thresholds as the headline.

**Liquidity vs Stress map (trail)**
- Stored per day in `rankalpha.fact_nowcast_snapshot`:
  - `map_liquidity_ease = liquidity label ease score` (0..100)
  - `map_stress_score = mean([credit_score, funding_score, MOVE_risk_off, SKEW_risk_off] over available)`
- API returns a trailing series for visualization (default 60 days).

## “What changed” deltas (front-and-center)
- Stored snapshot series view: `rankalpha.vw_nowcast_snapshot_series_with_deltas`
  - `delta_1d = overall[t] - overall[t-1 trading day]`
  - `delta_5d = overall[t] - overall[t-5 trading days]`
  - Also carries `label_1d_ago`, `label_5d_ago` for quick glance.

## Where to inspect quickly
- API payload: `GET /api/v1/nowcast/latest`
- DB latest snapshot:
  - `SELECT * FROM rankalpha.vw_nowcast_snapshot_latest WHERE model_version='nowcast_v2';`
- DB history with deltas:
  - `SELECT * FROM rankalpha.vw_nowcast_snapshot_series_with_deltas WHERE model_version='nowcast_v2' ORDER BY date_key DESC LIMIT 30;`

