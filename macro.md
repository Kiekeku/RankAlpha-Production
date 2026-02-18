# Macro & Regime Overview Page (Senior Quant Review)

This document inventories the **macro / regime measures surfaced on the Home “Macro & Regime Dashboard”** page, explains how they are consolidated into a single **Risk Nowcast score**, and traces each displayed number back to its **API endpoint** and **underlying DB object / series code**.

Scope:
- Home page: `apps/frontend/src/app/page.tsx`
- Components on Home:
  - **Risk Nowcast** card: `apps/frontend/src/features/regime/regime-summary.tsx`
  - **Macro Dashboard** cards: `apps/frontend/src/features/macro/macro-dashboard.tsx`
  - **Regime drilldown** panel: `apps/frontend/src/features/regime/regime-panel.tsx`

---

## 1) What’s on the Overview Page

### 1.1 Risk Nowcast (synthesis layer)
The **Risk Nowcast** card provides:
- A single composite **risk-off score** (0–100) and regime label (**Risk‑On / Mixed / Risk‑Off**)
- “What changed” deltas: **Δ1 trading day** and **Δ5 trading days** (computed from stored daily snapshots)
- A **pillar scoreboard** (Liquidity, Vol/Tail, Funding, Credit, Rates & USD, Breadth, Money Flow)
- A **Liquidity vs Stress** 2D regime map (trail)
- “Top drivers” (largest contributors to risk-off / risk-on)
- Alert pills (extreme pillars)

### 1.2 Macro Dashboard (raw macro snapshots + sparklines)
The Macro Dashboard surfaces eight macro “blocks” (each is a card with a latest snapshot plus a small sparkline/time-series view):

1. **Liquidity (ON RRP / TGA + Net Liquidity)**: levels + 1-step deltas + sparklines, plus Net Liquidity (WALCL − TGA − RRP)
2. **Funding Stress (FRA–OIS)**: key tenors + z-score sparkline
3. **Credit Stress (HY OAS)**: z-score + MA + sparkline
4. **Vol Regime (VIX + VRP)**: VIX 1M + curve slope + VRP + flags
5. **Rates & USD**: 10Y Treasury yield (risk-free curve), $USDX, curve slope (2s10s), and 10Y TIPS real yield (FRED DFII10) as a real-rate proxy
6. **Market Breadth**: SPX/NDX target exposure + net score + NYSE breadth/stress flags (incl. Zweig thrust)
7. **Money Flow (risk appetite)**: cyclical−defensive spread + top sector context + sparkline
8. **Cross‑Asset Radar (context-only)**: duration (TLT), real rates (DFII10), commodities (XAUUSD/WTI), EM risk (EMB), and FX crosses (USDJPY/USDCNY)
9. **Put/Call Ratios (context-only)**: CBOE equity and SPX put/call ratios (sentiment / hedging pressure)

### 1.3 Regime Panel (drilldown)
The bottom **RegimePanel** is an expanded view of the internal “style/tape” regime models:
- **Style Rotation (Momentum ↔ Value)**: FRI + breadth spread + tenure series
- **Market Styles Flow**: flow-rule label + breadth intensity composite
- **Market Structure (CVD)**: Trend/RV/Corr/Disp raw + z + sparklines, plus “tape classification”

These are intentionally more granular than the Nowcast; the Nowcast uses them primarily for context (e.g., “Style regime” and “Risk dial”).

---

## 2) Inventory & Traceability (UI → API → DB)

This section lists every measure currently displayed on the Home page and provides its lineage.

Notation:
- **Next BFF route**: the browser calls `/api/...` (Next.js route handlers under `apps/frontend/src/app/api/`)
- **API route**: the BFF proxies to the FastAPI backend (`/api/v1/...`)
- **DB object**: view/table in schema `rankalpha` used by the API router

### 2.1 Liquidity: ON RRP + TGA (+ Net Liquidity)

**Displayed (Macro Dashboard + Risk Nowcast pillar):**
- ON RRP level (billions) + delta (billions)
- TGA level (billions) + delta (billions)
- Liquidity regime label (rule-based)
- Net Liquidity level (trillions) + Δ4w/Δ13w (WALCL-anchored)
- Sparklines for ON RRP and TGA
- Sparkline for Net Liquidity

**Next BFF routes:**
- `GET /api/macro/liquidity/latest` → `apps/frontend/src/app/api/macro/liquidity/latest/route.ts`
- `GET /api/macro/liquidity/series?series=on_rrp` → `apps/frontend/src/app/api/macro/liquidity/series/route.ts`
- `GET /api/macro/liquidity/series?series=tga` → `apps/frontend/src/app/api/macro/liquidity/series/route.ts`
- `GET /api/macro/liquidity/net-liquidity/latest` → `apps/frontend/src/app/api/macro/liquidity/net-liquidity/latest/route.ts`
- `GET /api/macro/liquidity/net-liquidity/series` → `apps/frontend/src/app/api/macro/liquidity/net-liquidity/series/route.ts`

**API routes:**
- `GET /api/v1/macro/liquidity/latest` → `apps/api/src/routers/macro.py`
- `GET /api/v1/macro/liquidity/series` → `apps/api/src/routers/macro.py`
- `GET /api/v1/macro/liquidity/net-liquidity/latest` → `apps/api/src/routers/macro.py`
- `GET /api/v1/macro/liquidity/net-liquidity/series` → `apps/api/src/routers/macro.py`

**DB lineage:**
- `rankalpha.vw_macro_series` (model: `apps/common/src/models.py` → `VwMacroSeries`)
- Backed by `rankalpha.fact_macro_series` joined to `rankalpha.dim_macro_series` (model: `FactMacroSeries`, `DimMacroSeries`)

**Series codes used:**
- ON RRP: `US_ON_RRP`
- TGA: `US_TGA_BAL`
- WALCL (Fed total assets): `US_FED_WALCL`

**Liquidity regime rule (as implemented in API):**
- Computed from latest and prior values of ON RRP and TGA (deltas in **millions USD** internally)
- Labels:
  - `Amplified Easing`
  - `Neutral / Cushioning Phase`
  - `Reserve Drain / Tightening`
  - `Liquidity Inflection / Easing`

**Net Liquidity (as implemented in API):**
- Definition (levels, millions USD): `net_liquidity = WALCL − TGA − ON_RRP`
- Anchoring: Net Liquidity series is anchored to WALCL observation dates (weekly) to avoid daily noise from a weekly-updating WALCL.
- Change horizons: 4w (primary) and 13w (secondary) changes are returned (plus z-scores over the lookback window).

#### 2.1.1 Fed balance sheet / SOMA proxy (context-only; not a Nowcast driver)

The system also ingests a small **Fed balance sheet / SOMA composition** set from FRED. These series are **not used as direct Risk Nowcast drivers** (to avoid double-counting Fed plumbing that is already embedded in Net Liquidity), but they are available for drilldown/context panels.

**Next BFF routes:**
- `GET /api/macro/fed-balance-sheet/latest` → `apps/frontend/src/app/api/macro/fed-balance-sheet/latest/route.ts`
- `GET /api/macro/fed-balance-sheet/series?series=walcl|wshosho|treast|mbst` → `apps/frontend/src/app/api/macro/fed-balance-sheet/series/route.ts`

**API routes:**
- `GET /api/v1/macro/fed-balance-sheet/latest` → `apps/api/src/routers/macro.py`
- `GET /api/v1/macro/fed-balance-sheet/series` → `apps/api/src/routers/macro.py`

**DB lineage:**
- `rankalpha.vw_macro_series` (model: `VwMacroSeries`) for the four series below.

**Series codes used (stored in `dim_macro_series.series_code`):**
- `US_FED_WALCL` – Fed total assets (FRED `WALCL`)
- `US_FED_WSHOSHO` – **SOMA proxy** (FRED `WSHOSHO`; “Securities Held Outright”)
- `US_FED_TREAST` – SOMA Treasuries held outright (FRED `TREAST`)
- `US_FED_MBST` – SOMA MBS held outright (FRED `MBST`)

### 2.2 Funding Stress: FRA–OIS (SOFR futures)

**Displayed (Macro Dashboard + Risk Nowcast pillar):**
- FRA–OIS spread (bp) and regime label for:
  - 3x6 (primary)
  - 6x9, 9x12 (secondary pills)
- FRA–OIS z-score (sparkline from the 3x6 series)

**Next BFF routes:**
- `GET /api/fra-ois/latest?fra_source=SR3` → `apps/frontend/src/app/api/fra-ois/latest/route.ts`
- `GET /api/fra-ois/series?fra_source=SR3&start_months=3&end_months=6` → `apps/frontend/src/app/api/fra-ois/series/route.ts`

**API routes:**
- `GET /api/v1/fra-ois/latest` → `apps/api/src/routers/fra_ois.py`
- `GET /api/v1/fra-ois/series` → `apps/api/src/routers/fra_ois.py`

**DB lineage:**
- Latest snapshot: `rankalpha.vw_fra_ois_latest` (model: `VwFraOisLatest`)
- Time series: `rankalpha.fact_fra_ois` joined to `rankalpha.dim_date` (models: `FactFraOis`, `DimDate`)

**Key fields:**
- `spread_bp` (basis points)
- `fra_ois_z` (z-score; long-window rolling standardization, computed in DB/migration)

**Funding regime label (as implemented in API):**
- Based on `fra_ois_z`:
  - `easy` (z ≤ 0)
  - `normal` (0 < z ≤ 1)
  - `stressed` (1 < z ≤ 2)
  - `crisis` (z > 2)
  - `not_enough_data` (missing z)

### 2.3 Credit Stress: HY OAS (CCC)

**Displayed (Macro Dashboard + Risk Nowcast pillar):**
- `hy_stress_z` (z-score, displayed as “z (750d)”)
- `hy_stress_ma` (moving average)
- Label derived from z-score (risk_on / neutral / risk_off)
- Z-score sparkline

**Next BFF routes:**
- `GET /api/hy-stress/latest` → `apps/frontend/src/app/api/hy-stress/latest/route.ts`
- `GET /api/hy-stress/series` → `apps/frontend/src/app/api/hy-stress/series/route.ts`

**API routes:**
- `GET /api/v1/hy-stress/latest` → `apps/api/src/routers/hy_stress.py`
- `GET /api/v1/hy-stress/series` → `apps/api/src/routers/hy_stress.py`

**DB lineage:**
- `rankalpha.fact_hy_stress` (migration: `docker/database/sql/migrations/V100__hy_stress.sql`)
- Views:
  - `rankalpha.vw_hy_stress`
  - `rankalpha.vw_hy_stress_latest`
- Joined to:
  - `rankalpha.dim_benchmark` (to resolve `benchmark_name`)
  - `rankalpha.dim_date` (to resolve `as_of_date`)

**Default benchmark:**
- `benchmark_name = "%CCCHYS"` (per API router default)

### 2.4 Vol / Tail: VIX term structure + VRP + $MOVE + $SKEW

This “pillar” is split between:
- The **Vol Regime** card (VIX + VRP snapshots + flags), and
- The **Risk Nowcast Vol/Tail** pillar (adds $MOVE and $SKEW).

#### 2.4.3 Put/Call ratios (context-only)

**Displayed (Macro Dashboard; context-only):**
- Equity put/call ratio (CBOE): `#CBOEPCE`
- SPX index options put/call ratio (CBOE): `#CBOEPCSPX`

**Next BFF routes:**
- `GET /api/macro/put-call/series?series=equity` → `apps/frontend/src/app/api/macro/put-call/series/route.ts`
- `GET /api/macro/put-call/series?series=spx` → `apps/frontend/src/app/api/macro/put-call/series/route.ts`

**API routes:**
- `GET /api/v1/macro/put-call/series` → `apps/api/src/routers/macro.py`
- (also available) `GET /api/v1/macro/put-call/latest` → `apps/api/src/routers/macro.py`

**DB lineage:**
- `rankalpha.vw_macro_series` (model: `VwMacroSeries`)

**Series codes:**
- `#CBOEPC` (CBOE total options put/call)
- `#CBOEPCE` (CBOE equity-only put/call)
- `#CBOEPCI` (CBOE index options put/call)
- `#CBOEPCSPX` (CBOE S&P 500 index options put/call)

#### 2.4.1 VIX term structure + VRP (Vol Regime card)

**Displayed (Macro Dashboard):**
- VIX 1M level (`vix_1m`)
- Curve slope (`curve_slope`)
- VRP 30d (`vrp_30d`) + `vrp_regime` label + `vrp_state` / `vol_state`
- Flags: contango/backwardation, plus `risk_flag`, plus `regime` label

**Next BFF route:**
- `GET /api/vol-regime` → `apps/frontend/src/app/api/vol-regime/route.ts`

**API route:**
- `GET /api/v1/vol-regime` → `apps/api/src/routers/vol_regime.py`

**DB lineage (as used by API):**
- VIX term structure latest: `rankalpha.vw_vix_term_structure_latest` (model: `VwVixTermStructureLatest`)
- VRP (same date_key): `rankalpha.fact_spx_vix_vrp` (model: `FactSpxVixVrp`)

#### 2.4.2 $MOVE and $SKEW (rates vol + tail pricing proxies)

**Displayed (Risk Nowcast + map context):**
- Latest levels for `$MOVE` and `$SKEW`
- In Nowcast v2, these are standardized **server-side** and stored in the daily snapshot:
  - `$SKEW` contributes to the **Vol/Tail** pillar (equity tail pricing proxy)
  - `$MOVE` contributes to **cross-asset stress** (peripheral) and the map stress axis (context)

**Next BFF routes:**
- `GET /api/benchmarks/series?benchmark_name=$MOVE` → `apps/frontend/src/app/api/benchmarks/series/route.ts`
- `GET /api/benchmarks/series?benchmark_name=$SKEW` → `apps/frontend/src/app/api/benchmarks/series/route.ts`

**API routes:**
- `GET /api/v1/benchmarks/series` → `apps/api/src/routers/benchmarks.py`
- (also available) `GET /api/v1/benchmarks/latest`

**DB lineage:**
- Prices: `rankalpha.fact_benchmark_price` (model: `FactBenchmarkPrice`)
- Metadata: `rankalpha.dim_benchmark` (model: `DimBenchmark`)
- Calendar: `rankalpha.dim_date` (model: `DimDate`)
- Convenience view exists: `rankalpha.vw_benchmark_price` (migration: `docker/database/sql/migrations/V99__benchmark_views.sql`)

### 2.5 Market Breadth: exposure + breadth/stress flags

**Displayed (Macro Dashboard + Risk Nowcast pillar):**
- SPX:
  - `target_exposure` (0..1)
  - `net_score`
  - `regime_label` (derived from `regime_state`)
- NDX:
  - `target_exposure` (0..1)
  - `net_score`
  - `regime_label`
- NYSE flags:
  - `hindenburg_confirmed`
  - `trin_stress`
  - `persistent_new_lows`
  - `zweig_breadth_thrust`
- NYSE context:
  - `ad_ratio` (Advance/Decline Ratio)
- Sparklines:
  - SPX `target_exposure` series
  - NDX `target_exposure` series

**Next BFF routes:**
- `GET /api/breadth/latest` → `apps/frontend/src/app/api/breadth/latest/route.ts`
- `GET /api/breadth/series?universe=SPX&indicator=target_exposure` → `apps/frontend/src/app/api/breadth/series/route.ts`
- `GET /api/breadth/series?universe=NDX&indicator=target_exposure` → `apps/frontend/src/app/api/breadth/series/route.ts`

**API routes:**
- `GET /api/v1/breadth/latest` → `apps/api/src/routers/breadth.py`
- `GET /api/v1/breadth/series` → `apps/api/src/routers/breadth.py`

**DB lineage:**
- Primary breadth model outputs: `rankalpha.vw_breadth_signals` (model: `VwBreadthSignal`)
- NYSE context series (A/D ratio + Zweig thrust level): `rankalpha.vw_macro_series` (model: `VwMacroSeries`)

**Series codes used for displayed fields (from `UNIVERSE_SERIES` mapping in API router):**
- NYSE:
  - `US_NYA_HINDENBURG_OMEN_CONFIRMED`
  - `US_NYSE_TRIN_STRESS_FLAG`
  - `US_NYSE_PERSISTENT_NEW_LOWS_FLAG`
  - `#NYAZWBT` (NYSE Zweig Breadth Thrust level; context-only pill uses threshold `>= 0.615`)
  - `#NYSEADVR` (NYSE Advance/Decline Ratio; context-only tile)
- SPX:
  - `US_SPX_BREADTH_TARGET_EXPOSURE`
  - `US_SPX_BREADTH_NET_SCORE`
  - `US_SPX_BREADTH_REGIME_STATE` (used to derive `regime_label`)
- NDX:
  - `US_NDX_BREADTH_TARGET_EXPOSURE`
  - `US_NDX_BREADTH_NET_SCORE`
  - `US_NDX_BREADTH_REGIME_STATE`

**Regime label rule (as implemented in API):**
- `regime_state <= -0.5` → `risk_off`
- `regime_state >= 0.5` → `risk_on`
- else `neutral`

### 2.6 Rates & USD (10Y, USDX, curve, real-rate proxy)

**Displayed (Macro Dashboard + Risk Nowcast pillar):**
- 10Y Treasury yield: `tenor=10Y` level + Δ5d + sparkline
- Fed Funds (effective, O/N): `tenor=O/N` level + Δ20d (bp)
- USD strength: `$USDX` level + Δ5d + sparkline
- Curve slope: 2s10s (bps) + Δ20d + sparkline
- Real-rate proxy: 10Y TIPS real yield (DFII10) level + Δ20 (pp / bp)

**Next BFF routes:**
- `GET /api/benchmarks/series?benchmark_name=$USDX` → `apps/frontend/src/app/api/benchmarks/series/route.ts`
- `GET /api/rates/treasury/series?tenor=2Y` → `apps/frontend/src/app/api/rates/treasury/series/route.ts`
- `GET /api/rates/treasury/series?tenor=10Y` → `apps/frontend/src/app/api/rates/treasury/series/route.ts`
- `GET /api/rates/treasury/series?tenor=O%2FN` → `apps/frontend/src/app/api/rates/treasury/series/route.ts`
- `GET /api/macro/real-rates/tips10y/series` → `apps/frontend/src/app/api/macro/real-rates/tips10y/series/route.ts`

**API routes:**
- `GET /api/v1/benchmarks/series` (USDX) → `apps/api/src/routers/benchmarks.py`
- `GET /api/v1/rates/treasury/series` → `apps/api/src/routers/rates.py`
- `GET /api/v1/prices/history` → `apps/api/src/routers/prices.py`

**DB lineage:**
- `$USDX`: `rankalpha.fact_benchmark_price` + `rankalpha.dim_benchmark` + `rankalpha.dim_date`
- Treasury yields: `rankalpha.vw_risk_free_rate` (backed by `fact_risk_free_rate` + `dim_tenor` + `dim_date`)
- 10Y TIPS real yield: `rankalpha.vw_macro_series` (backed by `fact_macro_series` + `dim_macro_series`)

**Derived computations (UI):**
- `slope_2s10s = y10 − y2` (percentage points; displayed in bps)
- `tip_20d_log_return = ln(P_t / P_{t-20})`

### 2.7 Money Flow (risk appetite / sector rotation)

**Displayed (Macro Dashboard + Risk Nowcast pillar):**
- Risk appetite: cyclical − defensive spread (derived)
- Top sector context (by average “money flow score” across active equities)
- Top-5 sector list with average score
- Sparkline: cyclical−defensive spread over the last ~180 trading days

**Next BFF routes:**
- `GET /api/money-flow/sectors` → `apps/frontend/src/app/api/money-flow/sectors/route.ts`
- `GET /api/money-flow/sectors/series?days=180` → `apps/frontend/src/app/api/money-flow/sectors/series/route.ts`

**API routes:**
- `GET /api/v1/money-flow/sectors` → `apps/api/src/routers/money_flow.py`
- `GET /api/v1/money-flow/sectors/series` → `apps/api/src/routers/money_flow.py`

**DB lineage:**
- Base score fact: `rankalpha.fact_score_history` (model: `FactScoreHistory`)
- Score type definition: `rankalpha.dim_score_type` (model: `DimScoreType`)
- Equity metadata: `rankalpha.dim_stock` (model: `DimStock`) + `rankalpha.dim_asset_type`
- Calendar: `rankalpha.dim_date` (model: `DimDate`)

**Score type used:**
- `DimScoreType.score_type_name == "money flow score"`

**Aggregation:**
- For each sector and date, compute average of per-stock score across active equities.

**Derived risk appetite (UI):**
- Map each sector to a SPDR proxy (`sector_etf`) and compute:
  - `cyc_mean = mean(avg_score for cyclical ETFs)`
  - `def_mean = mean(avg_score for defensive ETFs)`
  - `appetite = cyc_mean − def_mean`

### 2.8 Cross‑Asset Radar (peripheral context; not a Nowcast driver)

**Purpose:** a compact “world view” for regimes where the *right hedge / tell* is outside equities. These tiles are **context-only** (not included in the Risk Nowcast weights) but help interpret the environment.

**Displayed (Macro Dashboard):**
- Duration: `TLT`
- Real rates: 10Y TIPS real yield (FRED `DFII10`) displayed as `TIPS10Y`
- Commodities proxies: `XAUUSD` (gold spot) and `WTI` (from `dim_benchmark` as `XAUUSD` and `@WTI`)
- EM risk: `EMB`
- FX: `USDJPY`, `USDCNY` (displayed). `USDCNY` is computed as the inverse of stored `CNYUSD` from `fact_fx_rate` (API also accepts `CNHUSD` as an alias when the DB stores onshore CNY).
- Per tile: latest level and small sparkline. Most tiles show Δ5d/Δ20d % and `rv20`; the real-rates tile shows Δ5d/Δ20d in bp (no `rv20`).

**Next BFF routes:**
- Prices (ETFs): `GET /api/prices/history?symbol=TLT|EMB` → `apps/frontend/src/app/api/prices/history/route.ts`
- Real rates: `GET /api/macro/real-rates/tips10y/series` → `apps/frontend/src/app/api/macro/real-rates/tips10y/series/route.ts`
- Benchmarks (commodities): `GET /api/benchmarks/series?benchmark_name=XAUUSD` and `benchmark_name=@WTI` → `apps/frontend/src/app/api/benchmarks/series/route.ts`
- FX:
  - `GET /api/fx/series?pair=USDJPY` → `apps/frontend/src/app/api/fx/series/route.ts`
  - `GET /api/fx/series?pair=CNHUSD` → `apps/frontend/src/app/api/fx/series/route.ts`

**API routes:**
- Prices: `GET /api/v1/prices/history` → `apps/api/src/routers/prices.py`
- Macro: `GET /api/v1/macro/real-rates/tips10y/series` → `apps/api/src/routers/macro.py`
- FX: `GET /api/v1/fx/series` (and `/fx/latest`) → `apps/api/src/routers/fx.py`

**DB lineage:**
- ETFs: `rankalpha.vw_stock_price_history` (via `DimStock` + `FactSecurityPrice` in the backend views)
- Real rates: `rankalpha.vw_macro_series` (series_code `US_TIPS_10Y_REAL_YIELD`, sourced from FRED `DFII10`)
- Commodities: `rankalpha.fact_benchmark_price` + `rankalpha.dim_benchmark` + `rankalpha.dim_date` (benchmark_name `XAUUSD` and `@WTI`)
- FX: `rankalpha.fact_fx_rate` + `rankalpha.dim_date` (fields: `from_ccy`, `to_ccy`, `mid_px`)

### 2.9 Style/Tape regime (context on Overview)

Although the macro pillars drive the “Nowcast”, the Home page also shows internal tape/style regime context:

**Style regime (Momentum ↔ Value):**
- Next BFF:
  - `GET /api/signals/rank-regime` → `apps/frontend/src/app/api/signals/rank-regime/route.ts`
  - `GET /api/signals/rank-regime/history` → `apps/frontend/src/app/api/signals/rank-regime/history/route.ts`
- API: `GET /api/v1/signals/rank-regime` (`apps/api/src/routers/rank_regime.py`)
- DB: `rankalpha.mv_rank_regime_daily` (model: `MvRankRegimeDaily`)
- Displayed fields:
  - `regime_label` (momentum_led/value_led/transition/stress)
  - `fri_z`
  - momentum/value breadth and spread

**Risk dial (Regime Index 0–100):**
- Next BFF:
  - `GET /api/screener/regime/latest` → `apps/frontend/src/app/api/screener/regime/latest/route.ts`
  - `GET /api/screener/regime/series` → `apps/frontend/src/app/api/screener/regime/series/route.ts`
- API: `GET /api/v1/screener/regime/latest` + series (`apps/api/src/routers/regime.py`)
- DB: `rankalpha.vw_regime_series` (model: `VwRegimeSeries`)
- Displayed fields:
  - `regime_index` (0–100)
  - `regime_label`
  - `risk_on_core`, `risk_off_core`, EMAs (available in drilldown)

**Flow rules (label/tags):**
- Next BFF:
  - `GET /api/screener/regime-rules/latest` → `apps/frontend/src/app/api/screener/regime-rules/latest/route.ts`
  - `GET /api/screener/regime-rules/series` → `apps/frontend/src/app/api/screener/regime-rules/series/route.ts`
- API: `GET /api/v1/screener/regime-rules/latest` (`apps/api/src/routers/regime_rules.py`)
- DB: `rankalpha.fact_regime_rules` joined to `rankalpha.dim_date` (models: `FactRegimeRules`, `DimDate`)
- Displayed: `label` and (in drilldown) component scores like `rs`, `tt`, `mrp`, etc.

**Market structure (C‑V‑D):**
- Next BFF:
  - `GET /api/market-structure/latest` → `apps/frontend/src/app/api/market-structure/latest/route.ts`
  - `GET /api/market-structure/series` → `apps/frontend/src/app/api/market-structure/series/route.ts`
- API: `GET /api/v1/market-structure/latest` + series (`apps/api/src/routers/market_structure.py`)
- DB: `rankalpha.vw_regime_market_structure` (model: `VwRegimeMarketStructure`)
- Displayed fields:
  - Raw + z for trend, RV20, correlation, dispersion
  - `label` (CalmUptrend / FragileUptrend / Choppy / Risk-Off / Neutral)

**Flow breadth sparkline (used inside Market Structure card):**
- Next BFF:
  - `GET /api/screener/breadth/flow` → `apps/frontend/src/app/api/screener/breadth/flow/route.ts`
- API: `GET /api/v1/screener/breadth/flow` (`apps/api/src/routers/screener.py`)
- DB: `rankalpha.mv_screener_breadth_flow` (model: `MvScreenerBreadthFlow`)

---

## 3) Consolidation: Risk Nowcast Score (0–100 risk-off)

### 3.1 Design intent
The Nowcast score is a **heuristic normalization** that puts heterogeneous measures on a common 0–100 “risk-off” scale so a PM can quickly see:
- whether conditions are broadly **supportive or stressed**
- **which macro block is driving** the environment
- whether the system is moving into/out of stress

It is **not** a calibrated portfolio optimizer; think of it as a dashboard-level nowcast.

**Implementation reference (Nowcast v2; source of truth is DB snapshots):**
- DB compute + storage: `docker/database/sql/migrations/V121__nowcast_snapshots.sql`
- API: `GET /api/v1/nowcast/latest` (`apps/api/src/routers/nowcast.py`)
- UI render: `apps/frontend/src/features/regime/regime-summary.tsx`

### 3.2 Canonical references (consolidated)
This document focuses on **what is on the Home page and how to trace it** (UI → API → DB).
To avoid duplicating audit-critical formulas across multiple docs, the Nowcast is documented in three layers:

- **Audit + lineage (persisted artifacts, inputs, cadence):** `docs/DATA_CATALOG.md` (see “2.16 Risk Nowcast”)
- **Exact formulas + thresholds (quant checklist):** `docs/NOWCAST_QUANT_CHECKLIST.md`
- **DB implementation (source of truth):** `docker/database/sql/migrations/V121__nowcast_snapshots.sql` and `docker/database/sql/migrations/V122__nowcast_money_flow_sector_coverage.sql`

### 3.3 Summary (what the system does)
- Nowcast produces a daily **risk-off** score in `[0, 100]` using tiered pillars (Liquidity, Vol/Tail, Funding, Credit, Rates & USD, Breadth, Money Flow).
- Results are **persisted nightly** (`rankalpha.fact_nowcast_snapshot`, `rankalpha.fact_nowcast_pillar_snapshot`) so deltas (Δ1d/Δ5d) and the 2D map trail are reproducible.

---

## 4) Caching & Nightly Refresh (operational)

The overview page is intentionally “heavy” (many endpoints). Two caching layers prevent DB hammering:

### 4.1 API caching (Redis HTTP cache)
FastAPI includes a Redis-backed read-through cache for GET JSON endpoints:
- Middleware: `apps/api/src/http_cache.py` (keys `httpcache:*`)
- TTL selection is route-based and configurable via `apps/api/src/settings.py`:
  - `cache_ttl_macro`, `cache_ttl_breadth`, `cache_ttl_fra_ois`, `cache_ttl_hy_stress`, `cache_ttl_vol_regime`, `cache_ttl_benchmarks`, `cache_ttl_rates`, `cache_ttl_money_flow`, `cache_ttl_technicals`
- (also used by the Overview page) `cache_ttl_fx`
- (also used by Cross‑Asset Radar) `cache_ttl_prices_history` and `cache_ttl_prices_latest`

Safety:
- Cache keys vary on `Authorization`, `Cookie`, and `X-API-Key` (hashed) to avoid cross-user leakage.

### 4.2 Frontend caching (Next.js fetch revalidation)
The Next BFF routes use `fetch(..., next: { revalidate, tags })` plus `Cache-Control` response headers:
- Most macro/regime endpoints: `revalidate=300` seconds, `s-maxage=300, stale-while-revalidate=900`
- Heavier/slow-changing endpoints (e.g., Money Flow and some screener/breadth endpoints): `revalidate=600` seconds, `s-maxage=600, stale-while-revalidate=1800`

### 4.3 Nightly refresh behavior
The Airflow DAG runs nightly (default 5:00 AM America/Denver; configurable via `PIPELINE_SCHEDULE` and `PIPELINE_TIMEZONE`):
- It triggers:
  - `POST /api/v1/grading/refresh` (invalidates API redis caches including `httpcache:`)
  - DB upserts for the Home **Risk Nowcast snapshot** (stores daily state for Δ1d/Δ5d and map trail)
  - `POST /api/v1/admin/cache/purge` (best-effort explicit purge; ensures “fresh now” after pipeline)
  - `POST /api/refresh-data` on the frontend (revalidates Next.js tags, including macro/regime/technicals)

---

## 5) Known Limitations / Review Questions (for PM/Quant)

1) **Heuristic mapping:** pillar scores are not fitted; they’re monotonic transforms designed for comparability.
2) **Static tier weights:** tiered weights reduce shock dilution, but they are still heuristic and should be reviewed (and possibly calibrated) over stress episodes.
3) **Robustness to outliers / non-normality:** MOVE/SKEW/spreads are not normal; consider winsorization, MAD z-scores, or percentiles if single crisis spikes flatten the post-crisis range.
4) **Data staleness:** confidence does not currently penalize staleness per input; consider a staleness penalty per pillar if latest datapoint is > N business days old.
5) **Breadth “target exposure” interpretation:** ensure PM consensus on treating this as a risk dial in `[0,1]`.
6) **Funding proxy interpretation:** FRA–OIS post-LIBOR depends on reconstruction; sanity-check behavior in known stress windows and consider redundant funding spreads (e.g., SOFR−EFFR, CP−T-bill) if needed.

If you want, we can add an explicit “Model card” section explaining why each pillar belongs, the intended interpretation, and “what trades it supports” (e.g., risk-on tilt, hedging intensity, beta sizing).
