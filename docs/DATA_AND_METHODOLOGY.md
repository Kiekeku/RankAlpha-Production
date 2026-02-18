# RankAlpha Data & Methodology (Senior Quant Review)

Last updated: 2026-01-12

This document consolidates **what data RankAlpha collects** and **how it is transformed into signals** across:

- **Ingestion** (`apps/ingestion`): market/macro data acquisition + canonicalization + technical indicator computation.
- **Scorer** (`apps/scorer`): equity factor scoring, model weight estimation, and market/regime composites.
- **Database** (`docker/database/sql/migrations`): materialized views and functions that define grades, regimes, and nowcast snapshots.
- **API/UI** (`apps/api`, `apps/frontend`): read paths (no re-computation of grades; most “latest” outputs are DB views).

If you need deeper single-topic writeups, see:
- Functional data catalog (data products + lineage): `docs/DATA_CATALOG.md`
- Scoring (Value/Momentum/Grades): `docs/SCORING.md`
- Macro/Regime dashboard inventory + lineage: `macro.md`
- Risk Nowcast 1‑pager: `docs/NOWCAST_QUANT_CHECKLIST.md`
- Money Flow spec: `docs/money_flow.md`
- Macro series catalog & routing: `docs/macro_series.md`
- DB schema inventory: `docs/schemas.md`

---

## 1) Core data model (what “data” means in RankAlpha)

RankAlpha persists most outputs in Postgres schema `rankalpha` using a star-like layout:

- **Dimensions** (`dim_*`): dates, instruments, sources, metric dictionaries, etc.
- **Facts** (`fact_*`): time series and event data.
- **Views** (`vw_*`, `mv_*`): “latest” and query-friendly projections consumed by the API/UI.

The canonical calendar is `rankalpha.dim_date` (`date_key = YYYYMMDD`, includes `is_trading_day`).

---

## 2) Ingestion: collected datasets + derived indicators

### 2.1 Equity price history (raw market data)

**Primary external source(s)**
- Daily OHLCV is refreshed via existing Parquets when available; **broker previous-close snapshots** are used when configured; **yfinance** is used as a fallback for initial fills / tail repair. (See `apps/ingestion/README.md`.)

**Canonical storage contracts**
- **Parquet**: `/data/prices/<SYMBOL>.parquet` with columns exactly:
  - `Open, High, Low, Close, Adj Close, Volume`
  - Datetime index is tz-naive, sorted, unique.
- **Postgres** (read-optimized copy): `rankalpha.fact_security_price`
  - Fields: `open_px, high_px, low_px, close_px, volume, total_return_factor`
  - Convention: **Adj Close is canonical close** (ingestion maps it to `close_px`); O/H/L/Vol are nullable depending on source coverage.

**Primary API consumers**
- Prices: `GET /api/v1/prices/history`, `GET /api/v1/prices/latest`
- Any factor/scoring job that needs a DB-native price panel (e.g., weight estimation, macro composites using benchmarks)

### 2.2 Equity technical indicators (derived from daily OHLCV)

**Producer**
- Ingestion computes a standard daily snapshot per symbol from canonical OHLCV and upserts to:
  - Fact: `rankalpha.fact_technical_indicator(date_key, stock_key, indicator_code, value)`
  - Snapshot view: `rankalpha.vw_latest_technicals` (pivoted “latest day”)

**Indicator set (current)**
- Trend/level: `SMA20`, `SMA50`, `SMA200`, `EMA12`, `EMA26`
- Oscillators/vol: `RSI14` (Wilder), `ATR14`
- Bands: `BB_UPPER`, `BB_MIDDLE`, `BB_LOWER` (20d, 2σ)
- MACD: `MACD`, `MACD_SIGNAL`, `MACD_HIST` (12,26,9)
- Returns (percent): `RET_5D`, `RET_20D`, `RET_60D`, `RET_120D`
- Volume z-score: `VOL_Z20`
- Distance to 52w high (percent): `DIST_52W_HIGH` (252d)

**Primary API consumers**
- `GET /api/v1/technicals/latest?symbol=SYM` (from `vw_latest_technicals`)
- `GET /api/v1/technicals/series?symbol=SYM&indicators=SMA20,RSI14&days=120` (from `fact_technical_indicator`)

### 2.3 Macro / rates / benchmarks (raw + lightly-derived)

RankAlpha stores “single number per date” macro series in three primary tracks:

- **Macro prints & composites**: `rankalpha.dim_macro_series` + `rankalpha.fact_macro_series` (served through `rankalpha.vw_macro_series`)
- **Benchmark/index-like series**: `rankalpha.dim_benchmark` + `rankalpha.fact_benchmark_price` (served through `rankalpha.vw_benchmark_price`)
- **Risk-free curve**: `rankalpha.dim_tenor` + `rankalpha.fact_risk_free_rate` (served through `rankalpha.vw_risk_free_rate`)

Ingestion currently maintains (best-effort, toggleable) the subset below that powers the “Macro & Regime Dashboard”:

- **Liquidity plumbing (FRED)**: ON RRP (`US_ON_RRP`), TGA balance (`US_TGA_BAL`), Fed assets (`US_FED_WALCL`)
- **Fed balance sheet context (FRED)**: `US_FED_WSHOSHO` (SOMA proxy), `US_FED_TREAST`, `US_FED_MBST`
- **Real rates (FRED)**: `US_TIPS_10Y_REAL_YIELD`
- **Funding (broker + derived)**: SOFR futures snapshots (`rankalpha.fact_sofr_futures`) and derived FRA–OIS spreads (`rankalpha.fact_fra_ois`)
- **Credit stress (derived from benchmark tape)**: HY stress (`rankalpha.fact_hy_stress`) derived from CCC HY OAS benchmark (default `%CCCHYS`)
- **DXY regime (derived from benchmark tape)**: `US_DXY_*` series written into `fact_macro_series`
- **Breadth (derived)**: derived breadth indicators written into `fact_macro_series` and surfaced via `rankalpha.vw_breadth_signals`

For the full macro series catalog and the intended series→table routing, see `docs/macro_series.md`.

---

## 3) Scorer: factor scores, regimes, and weights

### 3.1 Equity factor scores (stored in `fact_score_history`)

The scorer writes daily cross-sectional scores into:
- `rankalpha.fact_score_history(date_key, stock_key, score_type_key, score, source_key, load_ts)`

Score types are enumerated in `rankalpha.dim_score_type` and include (non-exhaustive):
- **Core grading factors**: `momentum score`, `value score`, `sentiment score` (sentiment optional for the grade composite)
- **Momentum internals**: `momentum raw score`, `momentum residual score`
- **Rotation/flow**: `money flow score`
- **Legacy/diagnostic technicals**: `linear regression 200/90/50/30`, `SMA 200` (used by some backtests/guards and as historical diagnostics)

### 3.2 Momentum score (trend, cross-sectional)

This section is intentionally high-level to avoid duplicating scoring formulas across multiple docs.

**What it is**
- A daily 0–100 “trend” factor (and auditable components like `momentum raw score` / `momentum residual score`) written by the scorer to `rankalpha.fact_score_history`.

Canonical references (consolidated)
- Audit + lineage (inputs/outputs and where stored): `docs/DATA_CATALOG.md` (see “2.6 Equity factor scores” and “2.7 Model weights and composite grades”)
- Exact methodology + grade consumption behavior: `docs/SCORING.md`
- Implementation notes (operational / tunables): `apps/scorer/README.md`

### 3.3 Value score (fundamentals-based relative valuation)

This section is intentionally high-level to avoid duplicating scoring formulas across multiple docs.

**What it is**
- A daily 0–100 “relative cheapness” factor produced from the fundamentals panel and written by the scorer to `rankalpha.fact_score_history` as `value score`.

Canonical references (consolidated)
- Audit + lineage (what fundamentals exist and where stored): `docs/DATA_CATALOG.md` (see “2.5 Fundamentals” and “2.6 Equity factor scores”)
- Exact methodology + fallbacks: `docs/SCORING.md`
- Implementation notes (operational / tunables): `apps/scorer/README.md`

### 3.4 Money Flow score (price × volume “rotation”)

Money Flow is a daily cross-sectional signal intended to capture per-stock buying/selling pressure and sector-level risk appetite.

- Per-stock `money flow score` is built from CMF(5/20), volume surprise (60d), and a downweighted 20d return, standardized cross-sectionally (market-cap weighted), then mapped to a 1–100 percentile.
- The “flows” input to Nowcast is the **cyclical − defensive** sector spread built from the per-stock scores.

See the full functional spec at `docs/money_flow.md`.

### 3.5 Vol regime: VIX term structure + SPX/VIX VRP

**VIX term structure (`rankalpha.fact_vix_term_structure`)**
- Inputs: `$VIX1D, $VIX9D, $VIX, $VIX3M, $VIX6M, $VIX1Y` from `fact_benchmark_price`.
- Outputs: levels, slopes, ratios, contango/backwardation flags, and a discrete regime label + `risk_flag`.

**Variance Risk Premium (`rankalpha.fact_spx_vix_vrp`)**
- Inputs: SPX OHLC (`fact_security_price` for symbol `$SPX`) and VIX level (`fact_benchmark_price` for `$VIX`).
- RV: rolling sum of daily Rogers–Satchell variance (21 trading days ≈ 1 month).
- IV: `(VIX/100)^2 * (30/365)`.
- VRP: `IV − RV`, plus percentile-based regime mapping.

See `apps/scorer/README.md` and the Vol Regime API notes in `apps/api/README.md`.

### 3.6 Screener-based regime: style intensity → Risk-On/Risk-Off cores

This is a daily “market state” computed from screener breadth/intensity across canonical styles.

**Key artifacts**
- Universe: `rankalpha.mv_universe_regime_us`
- Style intensity: `rankalpha.mv_style_intensity_us`
- Robust per-style Z: `rankalpha.fact_style_z_us`
- Regime composite series: `rankalpha.fact_regime_series` + `rankalpha.vw_regime_series`
- Dynamic effective style weights (e.g., Pullback): `rankalpha.fact_regime_effective_weight`

**Core idea**
- Convert per-style intensity into a robust standardized signal per style (rolling median/MAD with fallbacks).
- Blend standardized styles into `RiskOnCore` and `RiskOffCore`, then compute `RegimeRaw = RiskOnCore − RiskOffCore`.
- Apply EMA smoothing and hysteresis-based labeling; create a 0–100 index from a z-scored EMA.

See `apps/scorer/README.md` (Regime section) for the precise definitions and thresholds.

### 3.7 Flow-based regime rules (no HMM)

Alongside the intensity regime, RankAlpha computes a purely rules-driven regime label from:
- entrants/exits/continuers by canonical style,
- churn and transition telemetry,
- persistence and tagging percentiles.

**Artifacts**
- `rankalpha.mv_screener_flow_us`, `rankalpha.mv_style_transition_us`
- `rankalpha.regime_rules_config` (tunable constants)
- `rankalpha.fact_regime_rules` (daily composites + label/tags)

See `apps/scorer/README.md` (Flow-Based Regime Rules).

### 3.8 Market structure (CVD) regime

This regime focuses on tape structure rather than style flows:
- Trend (EW index return t-stat, ~50d)
- RV20 (20d realized vol, annualized)
- Correlation (PC1 share of 20d returns matrix)
- Dispersion (robust cross-sectional MAD of single-day returns)

Persisted to `rankalpha.fact_regime_market_structure` and exposed via `rankalpha.vw_regime_market_structure` and:
- `GET /api/v1/market-structure/latest`
- `GET /api/v1/market-structure/series`

See `apps/scorer/README.md` (Market Structure Regime) and `docs/CVD-regime.docx` (deeper narrative).

### 3.9 Rank regime (Momentum ↔ Value rotation)

Rank regime is a daily factor-rotation snapshot exposed via:
- `GET /api/v1/signals/rank-regime`
- `GET /api/v1/signals/rank-regime/history`

**Artifact**
- `rankalpha.mv_rank_regime_daily` (materialized view)

**Outputs (examples)**
- FRI (factor rotation index) z-score, breadth/spread, turnover, tenure and hazard metrics, label + confidence.

See `apps/api/README.md` and the UI methodology page `apps/frontend/src/app/about/regime/page.tsx`.

### 3.10 Model weights (hybrid IC + risk parity)

Model weights define how Momentum/Value/Sentiment are blended into a composite for grades.
The scorer computes weights periodically (typically monthly) and persists them to:
- `rankalpha.dim_model_weight` (legacy)
- `rankalpha.dim_model_weight_version` + `rankalpha.dim_model_weight_item` (versioned)

Canonical references (consolidated)
- Audit + lineage (where weights live and who produces them): `docs/DATA_CATALOG.md` (see “2.7 Model weights and composite grades”)
- Exact methodology + consumption behavior: `docs/SCORING.md`
- Implementation notes (operational / tunables): `apps/scorer/README.md` and `apps/scorer/src/weights.py`

---

## 4) Grades: the final composite used by Rankings

Grades are computed in Postgres (not in the API) via:
- `rankalpha.mv_latest_grades`

**Inputs**
- Momentum (required): latest `momentum score` per symbol
- Value (required): latest `value score` per symbol
- Sentiment (optional): mapped to 0–100; omitted when missing (weights re-normalize)

**Outputs**
- `avg_score` mapped to 1..100 (cross-sectional percentile of composite)
- letter grade A–F (percentile bands)

See `docs/SCORING.md` for the grade MV semantics and fallbacks.

---

## 5) “Market Overview”: Risk Nowcast (daily snapshot with deltas)

Risk Nowcast is a dashboard-level synthesis that maps heterogeneous macro/market measures onto a common **0–100 risk-off** scale and persists nightly snapshots so “Δ1d / Δ5d” are stable.

**Source of truth**
- Tables: `rankalpha.fact_nowcast_snapshot`, `rankalpha.fact_nowcast_pillar_snapshot`
- Views: `rankalpha.vw_nowcast_snapshot_latest`, `rankalpha.vw_nowcast_snapshot_series_with_deltas`
- DB functions: `rankalpha.fn_nowcast_snapshot_upsert_latest`, `rankalpha.fn_nowcast_snapshot_backfill`

Pillars (headline, names only)
- Liquidity, Vol/Tail, Funding, Credit, Rates & USD, Breadth, Money Flow

Canonical references (consolidated)
- Audit + lineage (persisted artifacts, inputs, cadence): `docs/DATA_CATALOG.md` (see “2.16 Risk Nowcast”)
- Exact formulas + thresholds (quant checklist): `docs/NOWCAST_QUANT_CHECKLIST.md`
- UI → API → DB traceability for what the Home page displays: `macro.md`

---

## 6) Practical review checklist (what to validate with a quant)

Suggested agenda for a senior-quant review (all are inspectable via DB views or API “latest” endpoints):

1. **Price adj semantics**: confirm how `close_px` and `total_return_factor` relate to vendor-adjusted history and corporate actions.
2. **Universe policy**: confirm eligibility rules for each subsystem (grades vs money-flow vs regime universes can differ).
3. **Factor definitions**:
   - Momentum: windows, gating, neutralization, and whether log-slope units match intended interpretation.
   - Value: metric set, synthetic fallbacks, peer grouping, and handling of non-positive ratios.
4. **Cross-sectional transforms**: percentile mapping, z-score methods, winsorization, and weighting (market-cap weighting where used).
5. **Regime definitions**: confirm label hysteresis and thresholds; validate backfill length is sufficient for stable rolling stats.
6. **Nowcast calibration**: confirm pillar score mappings and the “no hiding place” booster trigger/size.
7. **Operational cadence**: verify which jobs are daily vs nightly snapshot, and what happens on missing data days.
