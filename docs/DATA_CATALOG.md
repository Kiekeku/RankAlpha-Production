# RankAlpha Data Catalog (Functional)

Last updated: 2026-01-19

This document describes RankAlpha’s **data products** from a functional perspective:
what each dataset represents, who produces it, how it is stored, how often it updates, and what consumes it.

This is intentionally **not** the technical schema reference. For an exhaustive table/view list, see `docs/schemas.md`
(and `docs/schema_mermaid.md` for a high-level ERD).

---

## 0) Mental model and scope

RankAlpha is **batch-first** and close-based for most signals:

- The canonical “as-of date” is typically the **latest completed trading day** (D-1).
- Most computed datasets are **daily snapshots** written to Postgres under schema `rankalpha`.
- The UI and API are consumers; “latest” outputs are expected to be stable and reproducible.

### Storage layers (where data lives)

1) **Parquet (canonical OHLCV store)**
   - Path: `/data/prices/<SYMBOL>.parquet`
   - Producer: `apps/ingestion`
   - Primary consumer: `apps/scorer`

2) **Postgres (truth layer)**
   - Schema: `rankalpha`
   - Producers: ingestion, scorer, newswire, sentiment, broker, portfolio engine, DB functions/MVs
   - Consumers: API, ad-hoc SQL, downstream services, frontend via API

3) **Redis (read cache / operational)**
   - Used by the API for HTTP caching and by some services for coordination.
   - Not a source of truth; safe to purge.

4) **Service volumes (operational artifacts)**
   - Sentiment schedule: `/data/analysis_schedule/analysis_schedule.json`
   - Sentiment logs: `/data/logs/sentiment_oai_*.log`

---

## 1) Orchestration (how data updates)

### Daily pipeline (Airflow)

Primary orchestrator: `infra/airflow/dags/pipeline.py` (DAG `rankalpha_pipeline`).

High-level flow:

1) **Ingestion** (`apps/ingestion`)
   - Refresh Parquet OHLCV and sync DB “price/tech/macro” artifacts.
2) **Universe refresh**
   - Refreshes `rankalpha.mv_universe_eligible` so downstream jobs use current eligibility.
3) **Scorer** (`apps/scorer`)
   - Computes factor scores, regimes, deltas, weights.
4) **Nowcast snapshot**
   - Computes the daily Nowcast DB snapshot and deltas (stored).
5) **Publish**
   - Calls API refresh endpoints (grades and AI analysis refresh) and/or refreshes materialized views directly.
   - Purges API Redis http cache and optionally notifies frontend to refresh.

Optional pipeline tasks:
- **Newswire**: pre-market “blitz” pull and optional analysis run.
- **Sentiment enqueue**: enqueues post-earnings and top-grade symbols for sentiment runs.

---

## 2) Data products (by domain)

Each section lists:
- **What it is** (functional meaning)
- **Producers** (services and upstream sources)
- **Storage** (where it lives)
- **Cadence** (how it updates)
- **Consumers** (API/UI and downstream computations)

### 2.1 Security master and metadata

**What it is**
- The master record for symbols (equities, ETFs, ADRs) and their metadata (exchange, sector, currency).
- “Active” is an operational flag used to keep the daily universe clean.

**Producers**
- Ingestion and other jobs may upsert symbol metadata as needed.
- Activity heuristics are maintained by ingestion.

**Storage**
- Postgres: `rankalpha.dim_stock` (and related dimensions such as `dim_asset_type`, sectors).

**Cadence**
- Updated opportunistically during ingestion/scoring and as symbols appear in upstream feeds.

**Consumers**
- All downstream domains join through `dim_stock` (scoring, news, AI, portfolio, broker).

Notes
- `dim_stock.currency_code` is treated as authoritative listing currency.
- `dim_stock.is_active` is maintained by ingestion based on recency heuristics.

### 2.2 Universe eligibility (price/liquidity policy)

**What it is**
- A daily “eligible” flag per symbol based on policy thresholds (price floor, liquidity, continuity).
- Used to define the consistent investable universe for scoring and selection.

**Producers**
- Materialized view built from policy + latest price/liquidity stats; refreshed after ingestion.

**Storage**
- Postgres:
  - Policy: `rankalpha.universe_policy`
  - Output MV: `rankalpha.mv_universe_eligible`

**Cadence**
- Refreshed daily in the pipeline after ingestion (or whenever policy changes).

**Consumers**
- Scorer universe gating (Momentum/Value/Money Flow).
- Sentiment symbol selection and filtering.

### 2.3 Equity price history (canonical OHLCV)

**What it is**
- Per-symbol daily OHLCV history, canonicalized.

**Producers and upstream sources**
- `apps/ingestion`:
  - Prefers existing Parquets and broker previous-close snapshots when configured.
  - Uses yfinance as fallback for initial fills/tail repairs when enabled.

**Storage**
1) Parquet: `/data/prices/<SYMBOL>.parquet` with canonical columns
   - `Open, High, Low, Close, Adj Close, Volume`
   - Datetime index tz-naive, sorted, unique
2) Postgres “read-optimized copy”:
   - `rankalpha.fact_security_price` (Adj Close is canonical `close_px`; O/H/L/Vol when present)
   - Views: `rankalpha.vw_stock_price_history`, `rankalpha.vw_latest_adj_close`

**Cadence**
- Daily (batch), plus opportunistic repair on refresh.

**Consumers**
- API: `/api/v1/prices/*` endpoints.
- Scorer: reads Parquet for factor computations.
- Nowcast: uses benchmark/price-derived features (via DB snapshot functions).
- Portfolio: valuation snapshots and internal-cross pricing use close-based prices.

### 2.4 Technical indicators (per symbol, per day)

**What it is**
- Daily technical indicator panel (moving averages, RSI, ATR, bands, returns, volume z, distance to 52w high).

**Producers**
- `apps/ingestion` computes from canonical OHLCV and upserts.

**Storage**
- Postgres: `rankalpha.fact_technical_indicator`
- Snapshot view: `rankalpha.vw_latest_technicals`

**Cadence**
- Daily after each symbol refresh (effectively daily batch).

**Consumers**
- API: `/api/v1/technicals/latest`, `/api/v1/technicals/series`
- UI: “Technicals” views and stock detail pages (read-only).

### 2.5 Fundamentals (financial statements and derived metrics)

**What it is**
- Fundamental metric panel (as-reported and TTM) used primarily by value scoring.

**Producers**
- Ingestion/fundamentals loaders (service-specific; not all fundamentals pipelines are always enabled).

**Storage**
- Postgres: `rankalpha.fact_fin_fundamentals` + dictionary `rankalpha.dim_fin_metric`
- View: `rankalpha.vw_fin_fundamentals`
- Metric inventory (what’s currently collected + coverage stats): `docs/fundamentals_metric_inventory.csv`

**Cadence**
- Vendor- and pipeline-dependent (often daily for “latest known”, but revisions are possible).

**Consumers**
- Scorer: Value score construction.
- API: `/api/v1/fundamentals/*` (and downstream score explanations).

### 2.6 Equity factor scores (Momentum, Value, Money Flow, others)

**What it is**
- The core cross-sectional score store: per symbol, per as-of date, per score type, on a 0–100 scale.

**Producers**
- `apps/scorer`:
  - Reads canonical Parquet for price series signals.
  - Reads fundamentals panel for value.
  - Computes Money Flow (price × volume) and other market-state metrics.

**Storage**
- Postgres: `rankalpha.fact_score_history` keyed by `(date_key, stock_key, score_type_key)`
- Score dictionary: `rankalpha.dim_score_type`
- Convenience projections: `rankalpha.vw_score_history`, `rankalpha.vw_stock_style_scores` (when present)

Common score types (current)
- Core pillars (typically used in grades):
  - `momentum score` (plus auditable components: `momentum raw score`, `momentum residual score`)
  - `value score`
  - `money flow score`
  - `sentiment score` (optional pillar; may be sparse depending on AI/news coverage)
- Diagnostics / legacy technical transforms (often used for debugging/backtests and UX explainability):
  - `SMA 200`
  - `linear regression 200`, `linear regression 90`, `linear regression 50`, `linear regression 30`
- Other score types may exist in `dim_score_type` depending on environment (e.g., quality/low-vol variants or experimental AI factors).

**Cadence**
- Daily (batch) for the latest as-of day.

**Consumers**
- Composite grades (DB MV).
- Rankings UI and API endpoints.
- Money Flow sector appetite (Nowcast flows input).

Related docs
- Scoring overview: `docs/SCORING.md`
- Money Flow spec: `docs/money_flow.md`

### 2.7 Model weights and composite grades (the “ranking product”)

**What it is**
- **Model weights**: how RankAlpha blends factors (Momentum/Value/Sentiment) in the composite.
- **Grades**: latest composite percentile score (1..100) and letter grade A–F.

**Producers**
- `apps/scorer`: computes weights periodically (monthly) using hybrid IC + risk-parity with shrinkage.
- Database layer: materialized view builds the final latest grades using latest available scores and weights.

**Storage**
- Postgres:
  - Weights: `rankalpha.dim_model_weight` (legacy) and versioned tables `rankalpha.dim_model_weight_version` + `rankalpha.dim_model_weight_item`
  - Grades: `rankalpha.mv_latest_grades`
  - Optional diagnostics (when enabled): factor return series `rankalpha.fact_factor_return` (dictionary `rankalpha.dim_factor`)

**Cadence**
- Weights: typically monthly (unless forced).
- Grades: updated after scorer run and refreshed/published by the pipeline.

**Consumers**
- API: `/api/v1/grading/*` (grades, weights, sectors, refresh)
- UI: Rankings and any “grade” surfaces.

Notes
- Momentum and Value are treated as required in the grade MV; Sentiment is optional and renormalized when missing.

### 2.8 Screeners and “What’s New” (membership, deltas, breadth)

**What it is**
- The screener system stores per-day style membership, then derives:
  - per-symbol consensus (style and source aggregation)
  - day-over-day entry/reentry/drop events
  - breadth and market-state summaries
  - functional inventory of styles and screeners (with descriptions for `RA-*` presets)

**Producers**
- `apps/scorer` maintains deltas and refreshes materialized views for consensus/changes/breadth.
- (Upstream screener ingestion varies by environment; stored in `fact_screener_rank`.)

**Storage**
- Postgres:
  - Raw ranks: `rankalpha.fact_screener_rank`
  - Presence/streak helpers: `rankalpha.fact_screener_presence`, `rankalpha.fact_screener_presence_side`
  - Style rollups (legacy/optional; many stacks keep these empty and rely on MVs instead): `rankalpha.fact_stock_scores`, `rankalpha.fact_stock_score_types`
  - Deltas/events: `rankalpha.fact_screener_rank_change`
  - Materialized views (examples): `rankalpha.mv_screener_changes`, `rankalpha.mv_screener_breadth`, `rankalpha.mv_screener_breadth_flow`
  - “Latest” projections (examples): `rankalpha.v_latest_screener_consensus`

**Cadence**
- Daily after the screener ingest + scorer run (MV refresh).

**Consumers**
- API: `/api/v1/screener/*` (consensus/changes/breadth and related endpoints)
- UI: Screener pages and “What’s New”.

Inventory and definitions
- Functional catalog (styles + screeners + descriptions): `docs/SCREENER_CATALOG.md`
- DB exports (style/source mapping + weights + last-seen coverage):
  - `docs/screener_style_source_inventory_fact.csv`
  - `docs/screener_style_source_inventory.csv`

### 2.9 Regime and market state (several complementary regimes)

RankAlpha intentionally has multiple “market state” products:

1) **Screener intensity regime** (Risk-On vs Risk-Off cores)
2) **Flow-based regime rules** (Trend / Chop / Risk-Off + tags)
3) **Market structure (CVD) regime** (trend/vol/corr/dispersion)
4) **Volatility regime** (VIX curve shape + VRP state)
5) **Rank regime** (Momentum ↔ Value migration flows) (when enabled)

**Producers**
- `apps/scorer`:
  - Regime series and effective weights (intensity-based).
  - Flow-based regime rules composites and tags.
  - Market structure regime.
  - Rank regime is exposed via its MV.

**Storage (examples)**
- Intensity regime: `rankalpha.fact_regime_series`, `rankalpha.fact_style_z_us`, `rankalpha.fact_regime_effective_weight`, view `rankalpha.vw_regime_series`
- Flow rules: `rankalpha.fact_regime_rules` (config in `rankalpha.regime_rules_config`)
- Market structure: `rankalpha.fact_regime_market_structure`, view `rankalpha.vw_regime_market_structure`
- Vol regime: `rankalpha.fact_vix_term_structure` and `rankalpha.fact_spx_vix_vrp` (exposed via `rankalpha.vw_vix_term_structure_latest`)
- Rank regime: `rankalpha.mv_rank_regime_daily` (MV) (when present)

**Cadence**
- Daily after scorer runs (with some supporting MV refreshes).

**Consumers**
- API:
  - `/api/v1/screener/regime/*`
  - `/api/v1/screener/regime-rules/*`
  - `/api/v1/market-structure/*`
  - `/api/v1/vol-regime`
  - `/api/v1/signals/rank-regime*`
- UI: Overview/Regime dashboards and methodology pages.

**Calculation summary (audit)**
- Screener intensity regime (“Risk‑On core vs Risk‑Off core”):
  - Inputs: `rankalpha.fact_screener_rank` (style hits per day) with per-source weights `rankalpha.dim_source.screener_weight`, plus a canonical mapping and regime weights in `rankalpha.dim_style_regime_map`.
  - Universe: `rankalpha.mv_universe_regime_us` defines the daily denominator U(t) (US-eligible universe).
  - Intensity: `rankalpha.mv_style_intensity_us` aggregates daily intensity per canonical style:
    - per (stock, canonical style) take `max(tier)` for the day; sum across stocks; divide by U(t).
  - Standardization (scorer): for each style f, compute a robust rolling Z-score Z_f(t) (median + MAD with fallbacks) and clip to a bounded range; persist to `rankalpha.fact_style_z_us`.
  - Cores (scorer):
    - RiskOnCore(t) = Σ w(f)·Z_f(t) over Risk‑On styles
    - RiskOffCore(t) = Σ w(f)·Z_f(t) over Risk‑Off styles
    - RegimeRaw(t) = RiskOnCore − RiskOffCore
    - Smooth: EMA10/EMA50 (computed over history) and label with hysteresis; persist to `rankalpha.fact_regime_series`.
  - Effective weights: the realized daily per-style weights used in the blend are persisted to `rankalpha.fact_regime_effective_weight` (used for transparency and audit).
- Flow-based regime rules (rules engine; no HMM):
  - Inputs: screener flow/breadth/transition materialized views (e.g., `rankalpha.mv_screener_flow_us`, `rankalpha.mv_style_transition_us`, `rankalpha.mv_screener_breadth_flow`) plus a tunable single-row config table `rankalpha.regime_rules_config`.
  - Outputs: daily composites + label + tags persisted to `rankalpha.fact_regime_rules` with a stored “config version” string for traceability.
- Market structure (CVD) regime:
  - Inputs: cross-sectional returns for the eligible universe + derived “tape” features (trend, realized vol, correlation, dispersion), standardized and labeled by thresholds; persisted to `rankalpha.fact_regime_market_structure` and served via `rankalpha.vw_regime_market_structure`.
- Volatility regime:
  - Inputs: term structure features in `rankalpha.fact_vix_term_structure` and VRP snapshot in `rankalpha.fact_spx_vix_vrp`.
  - Output: a labeled vol state exposed via `/api/v1/vol-regime` (and the “Vol Regime” macro card).
- Rank regime (when enabled):
  - Built as a materialized view `rankalpha.mv_rank_regime_daily` from factor/rank transitions; exposed as a signals endpoint (not required for Nowcast).

Related docs
- Regime and rules are described in `apps/scorer/README.md` and the UI methodology pages under `apps/frontend/src/app/about/`.

### 2.10 Macro, benchmarks, rates, and derived stress

**What it is**
- A set of macro and benchmark time series plus derived indicators used in macro dashboards and in the Nowcast.

**Producers and upstream sources**
- `apps/ingestion`:
  - FRED pulls for liquidity plumbing (RRP/TGA/WALCL) and selected macro prints.
  - Rates/futures snapshots via the Broker service when enabled (SOFR futures, FRA–OIS).
  - Derived series (HY stress, DXY regime features, breadth composites) written as macro series.

**Storage**
- Macro prints/composites: `rankalpha.dim_macro_series` + `rankalpha.fact_macro_series` (view `rankalpha.vw_macro_series`)
- Benchmarks: `rankalpha.dim_benchmark` + `rankalpha.fact_benchmark_price` (view `rankalpha.vw_benchmark_price`)
- Risk-free curve: `rankalpha.dim_tenor` + `rankalpha.fact_risk_free_rate` (view `rankalpha.vw_risk_free_rate`)
- Derived stress:
  - HY stress: `rankalpha.fact_hy_stress`
  - SOFR futures: `rankalpha.fact_sofr_futures`
  - FRA–OIS: `rankalpha.fact_fra_ois`
  - Breadth signals view: `rankalpha.vw_breadth_signals`

**Cadence**
- Mostly daily. Some series (FRED) use a rolling refetch lookback to capture revisions.

**Consumers**
- API:
  - `/api/v1/macro/*`, `/api/v1/benchmarks/*`, `/api/v1/rates/*`
  - `/api/v1/fra-ois/*`, `/api/v1/hy-stress/*`, `/api/v1/breadth/*`
- Nowcast snapshot computation uses these series as inputs.

### 2.10.1 Economic data inventory (DB-derived; audit-friendly)

This section describes **what economic / macro market data is currently available** in the RankAlpha warehouse.
It is derived from the dimension tables that define the canonical series universe.

Source-of-truth dimensions
- Macro series dictionary (economic prints + composites + breadth/sentiment indicators): `rankalpha.dim_macro_series`
- Benchmarks (tradable/index-like series levels): `rankalpha.dim_benchmark`
- Risk-free curve tenors: `rankalpha.dim_tenor` (used by `rankalpha.fact_risk_free_rate`)

Current size (from the DB export on 2026-01-19)
- Macro series: 619 total (619 active); 446 missing `category`; 464 missing `frequency`
- Benchmarks: 61 total (all have `currency_code`)
- Tenors: 7 total

Top `dim_macro_series.category` values currently populated (count of series)
- `breadth` (55), `activity` (28), `housing` (13), `prices` (12), `labor` (11), `income` (10), `money` (10)
- Smaller: `fx` (9), `external` (8), `conditions` (4), `liquidity` (4), `regime` (4), `sentiment` (4), `rates` (1)

Exports (generated from the current database)
- Macro series inventory (code/name/category/frequency/units/active/description): `docs/economic_data_inventory_macro_series.csv`
- Benchmark inventory (name/currency/description): `docs/economic_data_inventory_benchmarks.csv`
- Curve tenor inventory (label/days): `docs/economic_data_inventory_tenors.csv`
- Macro series coverage summary (counts by category + frequency): `docs/economic_data_summary_macro_series_counts.csv`
- Benchmark coverage summary (counts by currency): `docs/economic_data_summary_benchmark_counts.csv`

Audit notes / interpretation
- `dim_macro_series.category` is a **functional grouping** (e.g., `activity`, `labor`, `prices`, `money`, `conditions`, plus RankAlpha-specific groups like `breadth`, `technical`, `sentiment`, `regime`).
- `dim_macro_series.frequency` is stored as a single-letter code (`D`, `W`, `M`, `Q`) when known; some legacy series may have null/blank frequency and should be normalized over time.
- `dim_benchmark` is intentionally minimal (name + currency + description); “category/units” for many benchmarks is treated as a semantic convention rather than a warehouse-enforced field.

How to re-generate these inventories (SQL)
- Macro series:
  - `SELECT series_code, series_name, category, frequency, units, is_active, description FROM rankalpha.dim_macro_series ORDER BY category, series_code;`
- Benchmarks:
  - `SELECT benchmark_name, currency_code, description FROM rankalpha.dim_benchmark ORDER BY benchmark_name;`
- Tenors:
  - `SELECT tenor_label, tenor_days FROM rankalpha.dim_tenor ORDER BY tenor_days NULLS LAST, tenor_label;`

**How the Macro Dashboard is computed (audit)**
The Overview “Macro Dashboard” is primarily **latest snapshot + sparkline** UX over a small set of canonical series plus a few derived transforms. The deep UI→API→DB trace is in `macro.md`; below is a concise functional summary of the core computations.

- Liquidity (RRP/TGA + Net Liquidity):
  - Inputs: `rankalpha.vw_macro_series` series codes `US_ON_RRP`, `US_TGA_BAL`, `US_FED_WALCL`.
  - Liquidity label: rule-based classification from latest and prior ON RRP/TGA levels (used by the dashboard; the Nowcast snapshot implements an equivalent label rule in DB for auditability).
  - Net Liquidity: `WALCL − TGA − ON_RRP`, WALCL-anchored; changes are returned for 4w and 13w horizons.
- Funding stress (FRA–OIS):
  - Input: `rankalpha.fact_fra_ois` (primary tenor: 3x6 from SOFR futures `fra_source='SR3'`).
  - Health score uses `fra_ois_z` (standardized in DB); the dashboard also applies a simple label mapping in API.
- Credit stress (HY OAS):
  - Input: `rankalpha.fact_hy_stress` (default benchmark `%CCCHYS`).
  - Health score uses `hy_stress_z` (standardized in DB) and a moving average field for context.
- Vol regime (VIX term structure + VRP):
  - Inputs: `rankalpha.fact_vix_term_structure` (term structure state/flags) and `rankalpha.fact_spx_vix_vrp`.
  - Output: labeled state + flags (contango/backwardation, risk_flag) used in the dashboard.
- Rates & USD:
  - Inputs: Treasury curve from `rankalpha.vw_risk_free_rate` (2Y/10Y), USD index from `rankalpha.vw_benchmark_price` (`$USDX`), and 10Y TIPS real yield proxy from `rankalpha.vw_macro_series` (`US_TIPS_10Y_REAL_YIELD`).
  - Common derived features: 2s10s slope, level z-scores, and (in Nowcast) yield shock magnitude from max(|Δ5d|, |Δ20d|) moves in 10Y.
- Breadth:
  - Inputs: canonical breadth series are stored in `rankalpha.fact_macro_series` and exposed via `rankalpha.vw_breadth_signals` (e.g., SPX/NDX target exposure in `[0,1]` plus stress/thrust flags).
- Money Flow (sector risk appetite):
  - Input: per-stock `money flow score` from `rankalpha.fact_score_history`.
  - API builds sector-level series as cross-sectional averages by (date, sector) and derives a cyclical-minus-defensive appetite spread for the dashboard.
- Context-only tiles (Cross‑Asset Radar / Put‑Call):
  - Cross-asset radar pulls from `rankalpha.vw_benchmark_price` and `rankalpha.vw_macro_series`.
  - Put/call ratios are stored as macro series (e.g., `#CBOEPCE`, `#CBOEPCSPX`) and surfaced as context-only time series.

Related docs
- Macro series routing: `docs/macro_series.md`
- Macro/Regime dashboard lineage: `macro.md`

### 2.11 FX rates (currency conversion support)

**What it is**
- Daily FX mid rates used to translate local-currency prices and positions into a base currency (primarily USD).
- Used by portfolio valuation and some risk checks (especially for non-USD listings).

**Producers**
- Producer varies by environment:
  - Some stacks source FX from the broker service (or a vendor feed) and persist mid rates.
  - If no producer is enabled, FX conversion falls back to best-effort logic (inverse pairs) or will be unavailable for some symbols.

**Storage**
- Postgres: `rankalpha.fact_fx_rate` (fields: `from_ccy`, `to_ccy`, `mid_px`)

**Cadence**
- Typically daily (and/or backfilled historically), depending on the FX source.

**Consumers**
- Portfolio engine and portfolio API routes (valuation and sizing).
- API: `/api/v1/fx/*`

### 2.12 Borrow rates (short borrow cost)

**What it is**
- Daily borrow rate (basis points) for a stock, used to represent shorting friction / availability.

**Producers**
- Optional: typically sourced from a broker or a vendor borrow feed when enabled.

**Storage**
- Postgres: `rankalpha.fact_stock_borrow_rate`
- View: `rankalpha.vw_stock_borrow_rate`

**Cadence**
- Daily when enabled; may be sparse depending on coverage.

**Consumers**
- Portfolio risk checks and short-selling constraints when those workflows are enabled.

### 2.13 Implied volatility surface (by tenor)

**What it is**
- Per-symbol implied volatility snapshot by tenor (a lightweight “IV surface” panel).

**Producers**
- Optional: sourced from broker/options data or a vendor when enabled.

**Storage**
- Postgres: `rankalpha.fact_iv_surface`
- View: `rankalpha.vw_iv_surface`

**Cadence**
- Daily (or periodic) when enabled.

**Consumers**
- Volatility dashboards and portfolio risk checks when surfaced.

Related (risk diagnostics; optional)
- Factor returns: `rankalpha.fact_factor_return` (dictionary `rankalpha.dim_factor`)
- Pairwise correlations: `rankalpha.fact_stock_correlation`

### 2.14 Corporate actions (splits, dividends, spinoffs)

**What it is**
- Corporate action events that affect share counts, pricing, and/or cash flows (splits, dividends, spinoffs).
- Intended to support clean NAV reconstruction and position normalization.

**Producers**
- Optional: sourced from a vendor feed or broker corporate-actions endpoint when enabled.

**Storage**
- Postgres: `rankalpha.fact_corporate_action`

**Cadence**
- Event-driven; updated as new actions are declared/confirmed.

**Consumers**
- Portfolio engine (NAV/performance hygiene) and any reconciliation tooling.

### 2.15 Earnings calendar (next earnings date per stock)

**What it is**
- The earliest upcoming earnings date (and best-effort time-of-day label) per stock.
- Used for automation hooks (e.g., post-earnings analysis queues) and as a simple UI “calendar” reference.

**Producers and upstream sources**
- `apps/ingestion` (optional): pulls a forward window from Finnhub earnings calendar and keeps the “next known” event per symbol.

**Storage**
- Postgres: `rankalpha.fact_stock_next_earnings`

**Cadence**
- Daily with ingestion when enabled (window is configurable; stale rows are pruned).

**Consumers**
- Airflow: post-earnings enqueue uses `fact_stock_next_earnings` to schedule next-day sentiment jobs.
- UI/API: may use as a lightweight “upcoming earnings” badge when surfaced (currently not a primary API surface).

Related docs
- Ingestion config + behavior: `apps/ingestion/README.md`
- Schema inventory: `docs/schemas.md`

### 2.16 Risk Nowcast (daily snapshot with deltas)

**What it is**
- A daily 0–100 “risk-off” synthesis (headline) plus a cross-asset stress badge and a 2D state map.
- Stored snapshots mean “Δ1d / Δ5d” are reproducible.

**Producers**
- Database functions compute and persist snapshots nightly.
- Airflow triggers snapshot computation as part of the daily pipeline.

**Storage**
- `rankalpha.fact_nowcast_snapshot`
- `rankalpha.fact_nowcast_pillar_snapshot`
- Views:
  - `rankalpha.vw_nowcast_snapshot_latest`
  - `rankalpha.vw_nowcast_snapshot_series_with_deltas`

**Cadence**
- Daily after the underlying macro/benchmark inputs are refreshed.

**Consumers**
- API: `/api/v1/nowcast/latest`
- UI: Overview “Risk Nowcast” card and dashboards.

**How the Nowcast is computed (audit)**
- Source of truth: nightly DB upsert into snapshot tables (not computed in the UI).
  - Migration: `docker/database/sql/migrations/V121__nowcast_snapshots.sql` (and `V122__nowcast_money_flow_sector_coverage.sql` for the Money Flow pillar coverage guard).
  - Primary function: `rankalpha.fn_nowcast_snapshot_upsert_latest(model_version)` (calls per-date upsert and persists a durable daily snapshot).
- Score convention: all pillar scores are on a **risk-off** 0–100 scale (higher = more stressed / higher drawdown risk).
- Standardization: fixed windows to avoid UI “window drift” (short=252, medium=756) with a blended z-score when both exist.
- Z → score mapping: `risk_off_score = 100 * Φ(z)` where Φ is the standard normal CDF (implemented via `erf` in Postgres).
- Tiered design (weights are re-normalized over available pillars):
  - Tier 1 (50%): Liquidity, Vol/Tail
  - Tier 2 (30%): Funding, Credit, Rates & USD
  - Tier 3 (20%): Breadth, Money Flow
- Pillars (inputs → transforms):
  - Liquidity: combines a rule-based RRP/TGA “liquidity label” (mapped to risk-off) plus Net Liquidity impulse from `WALCL − TGA − ON_RRP` changes (4w/13w).
  - Vol/Tail: term-structure discrete risk score from `rankalpha.fact_vix_term_structure` plus standardized `$SKEW` level from `rankalpha.vw_benchmark_price`.
  - Funding: FRA–OIS 3x6 z-score from `rankalpha.fact_fra_ois`.
  - Credit: HY stress z-score from `rankalpha.fact_hy_stress`.
  - Rates & USD: standardized USDX level, curve slope (2s10s), TIPS Δ20d, and 10Y yield shock magnitude from `rankalpha.vw_risk_free_rate` / `rankalpha.vw_benchmark_price` / `rankalpha.vw_macro_series`.
  - Breadth: maps SPX target exposure `∈ [0,1]` to risk-off via `100*(1 - target_exposure)`.
  - Money Flow: cyclical-minus-defensive sector appetite derived from per-stock `money flow score` (coverage thresholds enforced in v2).
- Output artifacts:
  - Overall + label + confidence + map coords: `rankalpha.fact_nowcast_snapshot`
  - Per-pillar scores + JSON details: `rankalpha.fact_nowcast_pillar_snapshot`
  - Deltas (Δ1d, Δ5d) are computed from stored snapshots in `rankalpha.vw_nowcast_snapshot_series_with_deltas`.

Related docs
- Quant checklist: `docs/NOWCAST_QUANT_CHECKLIST.md`
- Canonical narrative: `macro.md` and `docs/risk_nowcast.md`

### 2.17 Newswire (raw news, clustering, material events, impacts)

**What it is**
- A news ingestion and triage layer:
  - raw articles and partner submissions
  - dedup/cluster near-duplicates
  - material event objects and impacted tickers
  - optional LLM escalation hooks

**Producers and upstream sources**
- `apps/newswire` collector (GDELT/Serper/RSS) + queue worker for partner suggestions.

**Storage**
- Postgres (see migrations and `docs/schemas.md`):
  - raw article and sentiment/event/impact tables
  - suggestion and ingest queue tables (`news_suggestion`, `news_ingest_queue`)

**Cadence**
- Continuous polling loop (not strictly daily).
- Airflow may run a bounded “blitz” pass (pre-market) depending on configuration.

**Consumers**
- API: `/api/v1/news/*` endpoints (including suggestions and admin views).
- Sentiment: can enqueue high-materiality events for re-analysis (optional).

Related docs
- Service overview: `apps/newswire/README.md`

### 2.18 AI analysis and sentiment (per-symbol AI outputs)

**What it is**
- A denormalized, query-friendly store of AI-generated analysis:
  - thesis, scenarios, catalysts, risks, factor scores, summaries
  - optionally used as a “Sentiment” pillar in grades (when mapped)

**Producers**
- `apps/sentiment` runs multi-agent analysis in three modes:
  - on-demand symbol
  - consensus batch from screener consensus
  - catalyst-driven schedule loop (file-backed schedule + DB state)

**Storage**
- Postgres: `rankalpha.fact_ai_stock_analysis` and child tables; views such as:
  - `rankalpha.vw_ai_analysis_full`
  - `rankalpha.vw_ai_analysis_latest`
  - `rankalpha.mv_ai_scenario_proximity` (when enabled)
- Operational volumes:
  - schedule JSON under `/data/analysis_schedule`
  - logs under `/data/logs`

**Cadence**
- Best-effort; typically daily/near-daily for covered symbols depending on schedule and caps.

**Consumers**
- API: `/api/v1/ai-analysis/*` endpoints and admin refresh endpoints.
- UI: AI analysis pages and scenario proximity surfaces.

Related docs
- Service overview and modes: `apps/sentiment/README.md`
- AI sentiment and AI analysis data (audit view): `docs/AI_SENTIMENT_DATA.md`

### 2.19 Trading signals (ideas) and broker execution queue

**What it is**
- A unified “trade recommendation” record that can represent:
  - external strategy ideas (non-broker sources)
  - approved executable broker orders (source scoped to `broker::<ACCOUNT>`)

**Producers**
- External strategy repos submit via API `POST /api/v1/trading/signals` (token gated).
- Portfolio approvals export executable broker orders into `fact_trade_recommendation` under `broker::<ACCOUNT>`.
- Broker runner claims eligible recommendations (`is_live=true`) before placing orders.

**Storage**
- Postgres:
  - `rankalpha.fact_trade_recommendation` (+ view `rankalpha.vw_trade_recommendation`)
  - execution ledger: `rankalpha.fact_portfolio_trade` (fills)

**Cadence**
- Event-driven (on idea submission and on broker runner polling loop).

**Consumers**
- Broker runner (`apps/broker`) reads broker-scoped recommendations and places orders.
- Portfolio engine uses recommendation lineage tables for attribution (where configured).

Related docs
- External ingestion contract: `docs/TRADING_SIGNAL_INGESTION.md`
- Portfolio approval/export runbook: `docs/PORTFOLIO_CONSTRUCTION.md`

### 2.20 Portfolio construction, runs, and performance tracking

**What it is**
- A supervised, auditable workflow to turn ideas and models into broker-ready trade lists:
  - portfolios (broker/model/sleeve), deployments (allocations), policies (risk constraints)
  - daily runs (draft/approved), baseline/target snapshots, approved order intents
  - execution attribution hooks and NAV/performance facts

**Producers**
- Portfolio engine (`apps/portfolio` + shared engine in `apps/common/src/portfolio/`).
- Broker fills ingestor writes executed trades.

**Storage**
- Postgres:
  - portfolio master and run tables (`portfolio*`)
  - `rankalpha.portfolio_run`, `rankalpha.portfolio_order_intent`, and related linkage tables
  - performance facts: NAV, positions history, risk metrics (when populated)

**Cadence**
- Runs are typically daily (or operator-triggered), approvals are manual by design.

**Consumers**
- API: `/api/v1/portfolio/*` and admin surfaces.
- Broker export step writes executable recommendations.

Related docs
- Canonical spec/runbook: `docs/PORTFOLIO_CONSTRUCTION.md`

---

## 3) Where to look next (operator and developer shortcuts)

- “What data exists (schema inventory)”: `docs/schemas.md`
- “What’s production vs scaffolding”: `docs/RankAlpha_current_state.md`
- “Macro + Nowcast deep lineage”: `macro.md`, `docs/NOWCAST_QUANT_CHECKLIST.md`
- “Value/Momentum/Grades”: `docs/SCORING.md`
- “Screeners catalog (styles + definitions)”: `docs/SCREENER_CATALOG.md`
- “Fundamentals inventory (metrics + coverage)”: `docs/fundamentals_metric_inventory.csv`
- “Portfolio model”: `docs/PORTFOLIO_CONSTRUCTION.md`
- “External signal ingestion”: `docs/TRADING_SIGNAL_INGESTION.md`

---

## Appendix A: Scorer Outputs Checklist (Audit/Compliance)

This appendix is a **single, audit-friendly checklist** of what the scorer produces and/or refreshes.

Scope
- Producer: `apps/scorer` (daily batch service + optional backfills/tools).
- Calendar: close-based “as-of” is typically the latest completed trading day (D-1).
- Storage: Postgres schema `rankalpha` unless noted.
- Explicit non-scope: technical indicators are produced by `apps/ingestion` (`rankalpha.fact_technical_indicator`).

### A.1 Facts written/upserted by the scorer

Each item below is a **truth-layer artifact** that is written (insert/upsert) by scorer code paths.

#### Scores (per symbol, per day)

- **Dataset:** Equity score history (cross-sectional factor scores)
  - **DB objects:** `rankalpha.fact_score_history` (dictionary: `rankalpha.dim_score_type`)
  - **Cadence:** Daily
  - **Primary API consumers:** grades and scoring surfaces (indirectly via `mv_latest_grades`); pipeline health uses `fact_score_history` recency.
  - **Typical scorer-written score types (current):**
    - Core: `momentum score`, `momentum raw score`, `momentum residual score`, `value score`, `money flow score`
    - Optional: `sentiment score` (coverage depends on AI/news)
    - Diagnostics/legacy transforms: `SMA 200`, `linear regression 200/90/50/30`
    - Optional AI-derived factors (when enabled): `quality score`, `ai momentum score`, `low volatility score`

#### Weights (factor blending parameters)

- **Dataset:** Model weights used by grades (hybrid IC + risk-parity + shrinkage)
  - **DB objects:** `rankalpha.dim_model_weight` (legacy), `rankalpha.dim_model_weight_version`, `rankalpha.dim_model_weight_item`
  - **Cadence:** Typically monthly (or forced)
  - **Primary API consumers:** `/api/v1/grading/weights`
  - **Operational note:** scorer may clear `rankalpha.admin_flag('force_recompute_weights')` after a successful recompute.

#### Screener deltas and streak helpers

- **Dataset:** Screener change events (entered/reentered/dropped)
  - **DB objects:** `rankalpha.fact_screener_rank_change`
  - **Cadence:** Daily (after screener ingest)
  - **Primary API consumers:** `/api/v1/screener/changes`
- **Dataset:** Per-style presence + consecutive day streaks
  - **DB objects:** `rankalpha.fact_screener_presence`
  - **Cadence:** Daily (latest screener day)
  - **Primary API consumers:** screener setup “streak” UX (via latest screener projections)
- **Dataset:** Per-side (bullish/short) presence + consecutive day streaks
  - **DB objects:** `rankalpha.fact_screener_presence_side`
  - **Cadence:** Daily (latest screener day)
  - **Primary API consumers:** screener setup UX (bullish vs bearish chips)

#### Regime and market state

- **Dataset:** Style intensity Z-scores (US regime universe)
  - **DB objects:** `rankalpha.fact_style_z_us`
  - **Cadence:** Daily
  - **Primary API consumers:** regime dashboards and “Risk-On/Risk-Off” explanations.
- **Dataset:** Regime series (Risk-On core / Risk-Off core / label / index)
  - **DB objects:** `rankalpha.fact_regime_series`
  - **Cadence:** Daily
  - **Primary API consumers:** `/api/v1/screener/regime/*` and Overview regime visuals.
- **Dataset:** Effective regime weights (the realized per-style weights used in the regime blend)
  - **DB objects:** `rankalpha.fact_regime_effective_weight`
  - **Cadence:** Daily
  - **Primary API consumers:** regime explanation UX and diagnostics.
- **Dataset:** Flow-based regime rules (Trend / Chop / Risk-Off + tags + composites)
  - **DB objects:** `rankalpha.fact_regime_rules` (config: `rankalpha.regime_rules_config`)
  - **Cadence:** Daily
  - **Primary API consumers:** `/api/v1/screener/regime-rules/latest`, `/api/v1/screener/regime-rules/series`
- **Dataset:** Market structure regime (trend/vol/corr/dispersion + label)
  - **DB objects:** `rankalpha.fact_regime_market_structure` (served through `rankalpha.vw_regime_market_structure`)
  - **Cadence:** Daily
  - **Primary API consumers:** `/api/v1/market-structure/latest`, `/api/v1/market-structure/series`

#### Volatility term structure and VRP

- **Dataset:** VIX term structure features + regime label
  - **DB objects:** `rankalpha.fact_vix_term_structure` (served through `rankalpha.vw_vix_term_structure_latest`)
  - **Cadence:** Daily (or when benchmark inputs are refreshed)
  - **Primary API consumers:** `/api/v1/vol-regime`
- **Dataset:** SPX/VIX variance risk premium (VRP) snapshot + state labels
  - **DB objects:** `rankalpha.fact_spx_vix_vrp`
  - **Cadence:** Daily
  - **Primary API consumers:** `/api/v1/vol-regime`

### A.2 Materialized views refreshed by the scorer

These objects are **refreshed** by scorer for downstream reads; they are not “authored” by scorer but are operationally part of the scorer run.

- **Screener change diff MV:** `rankalpha.mv_screener_changes` (refreshed; feeds `fact_screener_rank_change`)
- **Latest screener scores MV:** `rankalpha.mv_screener_scores_latest` (refreshed; feeds setups UX)
- **US regime universe MV:** `rankalpha.mv_universe_regime_us` (refreshed; dependency for multiple regime computations)
- **US style intensity MV:** `rankalpha.mv_style_intensity_us` (refreshed; regime inputs)
- **Flow/breadth MVs (for flow-based regime rules):**
  - `rankalpha.mv_screener_flow_us`
  - `rankalpha.mv_screener_breadth_flow`
  - `rankalpha.mv_style_transition_us`
  - `rankalpha.mv_screener_breadth`
- **Rank regime MV (when enabled):** `rankalpha.mv_rank_regime_daily`

Note
- Scorer includes a generic “refresh all `mv_%`” helper, but the operational intent is to refresh only the dependency MVs listed above (to avoid unnecessary lock/refresh load).

### A.3 How grades relate to scorer outputs (audit note)

- Scorer writes the **inputs** (scores + weights).
- Grades are computed by a DB materialized view:
  - **DB object:** `rankalpha.mv_latest_grades`
  - **Refresh:** typically triggered by the pipeline via API refresh endpoints after scorer completes (not directly authored by scorer logic).

### A.4 Quick verification queries (recommended for audits)

Use these to validate that a given run produced the expected “latest” artifacts:

- Latest score day and which score types updated:
  - `SELECT max(date_key) FROM rankalpha.fact_score_history;`
  - `SELECT st.score_type_name, max(f.date_key) FROM rankalpha.fact_score_history f JOIN rankalpha.dim_score_type st ON st.score_type_key=f.score_type_key GROUP BY 1 ORDER BY 2 DESC;`
- Latest weights:
  - `SELECT max(as_of_date) FROM rankalpha.dim_model_weight;`
  - `SELECT max(effective_from) FROM rankalpha.dim_model_weight_version WHERE model_code='default';`
- Latest screener-derived artifacts:
  - `SELECT max(change_date_key) FROM rankalpha.fact_screener_rank_change;`
  - `SELECT max(date_key) FROM rankalpha.fact_screener_presence;`
  - `SELECT max(date_key) FROM rankalpha.fact_screener_presence_side;`
- Latest regime/vol outputs:
  - `SELECT max(date_key) FROM rankalpha.fact_regime_series;`
  - `SELECT max(date_key) FROM rankalpha.fact_regime_rules;`
  - `SELECT max(date_key) FROM rankalpha.fact_regime_market_structure;`
  - `SELECT max(date_key) FROM rankalpha.fact_vix_term_structure;`
  - `SELECT max(date_key) FROM rankalpha.fact_spx_vix_vrp;`
