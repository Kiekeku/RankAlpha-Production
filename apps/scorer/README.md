# RankAlpha Score Engine

## Purpose
The Scorer service calculates financial metrics and generates investment scores for stocks based on momentum, value, and other quantitative factors. It transforms raw market data into actionable investment signals, providing the core ranking logic for the RankAlpha platform.

## Technologies & Tools

### Core Technologies
- **Python 3.12**: High-performance computation runtime
- **NumPy**: Vectorized numerical operations
- **Pandas**: Time-series analysis and data manipulation
- **SQLAlchemy**: Database operations and queries

### Calculation Libraries
- **SciPy**: Statistical functions and optimizations
- **TA-Lib**: Technical analysis indicators (optional)
- **Scikit-learn**: Machine learning models for scoring

## Design Principles

### 1. **Reproducibility**
- Deterministic calculations
- Version-controlled scoring algorithms
- Audit trail for score changes
- Point-in-time accuracy

### 2. **Performance**
- Vectorized computations
- Efficient database queries
- Batch processing capabilities
- Caching of intermediate results

### 3. **Flexibility**
- Configurable scoring parameters
- Pluggable metric modules
- Custom weighting schemes
- A/B testing support

### 4. **Transparency**
- Explainable score components
- Calculation breakdowns
- Historical score tracking
- Debug mode for validation

## Project Structure

### Core Files

#### `main.py`
- **Purpose**: Main orchestration for score calculation pipeline
- **Key Functions**:
  - `calculate_all_scores()`: Run complete scoring pipeline
  - `calculate_momentum_scores()`: Price and volume momentum metrics
  - `calculate_value_scores()`: Fundamental value metrics
  - `calculate_quality_scores()`: Company quality indicators
  - `calculate_composite_scores()`: Weighted combination scores
  - `rank_and_percentile()`: Convert scores to rankings
  - `store_results()`: Persist scores to database

## Scoring Methodology

### Momentum Scores (Raw, Residual, Composite)
Momentum now ships as two auditable signals plus a composite written under the legacy name:

- Momentum Raw Score (`momentum raw score`): blended log‑slope (t‑stat weighted), no neutralization. Matches the “what you see on the chart”.
- Momentum Residual Score (`momentum residual score`): same blend, then de‑meaned by group median (Sector for now; fallback to market median when group size < `SCORING_MOMENTUM_MIN_GROUP_SIZE`).
- Momentum Score (`momentum score`): composite used by grades. Default is a 70/30 blend Residual/Raw (configurable).

- Windows: 200, 90, 50, 30 trading days.
- Per window w:
  - Regress log(Adj Close) on time over the last w observations → slope and r (corr).
  - Coverage gate: require ≥ `SCORING_MOMENTUM_MIN_VALID_FRAC` of valid price points; otherwise skip the window.
  - Compute t‑stat from r and n: `t = r * sqrt(n − 2) / sqrt(1 − r²)` (if n > 2 and r² < 1).
  - Effective weight: `eff_w = base_w × (min(1, |t| / SCORING_MOMENTUM_TSTAT_CAP))²`.
- Blend across windows: `blended = sum(slope_w × eff_w) / sum(eff_w)`.
- Raw score: percentile rank of `blended` across the as‑of universe; map to 1..100 via `(pct × 99 + 1)`.
- Residual score: subtract group median (Sector) when group size ≥ `SCORING_MOMENTUM_MIN_GROUP_SIZE`, else subtract market median; percentile rank to 1..100.
- Composite score (written as `momentum score`):
  - Mode: `SCORING_MOMENTUM_COMPOSITE_MODE` = residual | raw | blend (default blend).
  - Weights when blend: `SCORING_MOMENTUM_RESIDUAL_WEIGHT` (default 0.7) and `SCORING_MOMENTUM_RAW_WEIGHT` (default 0.3).
  - The composite is a convex combination of the Raw and Residual percentiles.

As‑of trading day
- Selection uses the latest day with price data that also meets a coverage threshold across the eligible universe.
  - Coverage threshold: `SCORING_ASOF_MIN_COVERAGE` (default `0.5` → 50% of eligible symbols must have prices on that day).
  - If no recent day meets the threshold, the scorer uses the latest price day.
- Any ticker is accepted if its latest usable price date is ≥ the as‑of day; data beyond as‑of is truncated to the as‑of day for consistency.
- A grace window of previous trading days is allowed (configurable via `SCORING_ASOF_GRACE_TRADING_DAYS`, default `1`): if a ticker’s latest price is within that window (e.g., exactly the previous trading day when set to 1), it is still processed. Only symbols older than that window are skipped.
  - All per‑ticker series are truncated to the as‑of day before computing slopes.

Env knobs (see Environment Variables below): per‑window base weights, min valid frac, t‑stat cap, min group size, composite mode and weights.

### Money Flow Score (price × volume)
- Universe: active + `mv_universe_eligible` and requires a non-empty, non-UNKNOWN sector (sectorless ETFs/indexes excluded).
- Components per symbol (latest day, coverage gated by `SCORING_MF_MIN_VALID_FRAC`, default 0.8):
  - CMF(5), CMF(20)
  - Volume surprise: `log(volume / rolling 60d median)`
  - Return: 20-day price return (downweighted to limit overlap with momentum)
- Cross-sectional z-scores (winsorized ±3), composite:
  - Default weights: `0.4*z_cmf20 + 0.2*z_cmf5 + 0.3*z_vol_surp + 0.1*z_ret20`
  - Cross-sectional distribution is **market-cap weighted** (latest `mktcap` from fundamentals, weight=`log1p(mktcap)`), so large caps drive mean/std and percentile thresholds.
  - Weighted percentile → `money flow score` (1..100) stored in `fact_score_history`
- Tunables: `SCORING_MF_COMPONENT_WEIGHTS`, `SCORING_MF_MIN_VALID_FRAC`

### Valuation Score (Fundamentals)
The Valuation Score is derived from financial ratio data in `fact_fin_fundamentals` (not AI) and produces a 0–100 score where higher means cheaper valuation versus peers.

- Inputs (lower is cheaper; grouped into buckets with per-bucket fallbacks):
  - EV/EBITDA: synthetic `ev2ebitda_synth` built from `mktcap + netdebt` over `ttmebitd` (Weight 25%)
  - EV/FCF: `ev2fcf_curttm` → `ev2fcf_cura` (Weight 25%)
  - P/FCF: `ttmprfcfps` → `aprfcfps` → `pfcf_synth` (Weight 20%)
  - P/S: `ttmpr2rev` → `apr2rev` (Weight 15%)
  - P/B: `price2bk` → `aprice2bk` → `pr2tanbk` → `apr2tanbk` (Weight 10%)
  - P/E: `peexclxor` → `peinclxor` → `pebexclxor` → `pe_synth` (Weight 5%)
  - Dividend yield: `divyield_curttm` (Weight 0% by default; used in Financials override)

- Sector overrides:
  - Financials: PB 50%, PE 30%, Div 20%
  - Real Estate: PB 50%, Div 30%, PS 20%

- Relative scoring per metric m:
  - Convert ratios to “cheapness yields” via `yield = 1 / ratio` (direct yields like dividend yield are used as-is)
  - Higher yield => cheaper => higher percentile score
  - Peer percentile: within each peer group, percentile-rank yields; if peer group < 5 names, fall back to market percentile
  - Blend: 70% peer + 30% market when peer group is large enough

- Combine across metrics:
  - Weighted average with dynamic reweighting when some metrics are missing (weights renormalize to 1 for available metrics)
  - Coverage guardrail: when bucket coverage is low, shrink the score toward neutral (50) in proportion to coverage
  - Clamp final score to [0, 100]

- Data window and filtering:
  - Uses the latest `date_key` snapshot from `fact_fin_fundamentals`
  - “Price-like” ratios require recency within ~7 calendar days; statement-like inputs used for synthesis allow a longer window (~400 days)
  - Non‑positive ratios are treated as worst (penalized) rather than silently dropped
  - If a symbol has no valid ratios, no Valuation Score is written

Note: This replaces the prior AI-derived value score; AI quality/momentum/low‑volatility and sentiment scores remain.

### Final Grade (MV Composite)
Final Grade and the composite score are produced by the materialized view `rankalpha.mv_latest_grades`:

- Inputs per symbol:
  - Momentum: prefer new `momentum score` (1–100) from `fact_score_history`; fallback to legacy LR200 cross‑section scaling
  - Value: fundamentals‑based `value score` (1–100) from `fact_score_history`; fallback to AI value score
  - Sentiment: maps to 0–100 via `(news_sentiment_30d or 30D news avg + 1) × 50`
- Composite weighting with dynamic reweighting (no penalty for missing sentiment):
  - Weights: Momentum 40%, Value 40%, Sentiment 20%
  - If a component is NULL, its weight is excluded and remaining weights renormalize to sum to 1
- Percentile mapping and grade bands:
  - Cross‑sectional percentile of composite → `avg_score` in [1..100] via (pct × 99 + 1)
  - Grade bands: A ≥ 90, B ≥ 70, C ≥ 45, D ≥ 20, else F; N/A if no components

The API uses `mv_latest_grades.avg_score` for grading to match the MV definition.

### VIX Term Structure & Vol Regime
- Inputs: six VIX index tenors from `fact_benchmark_price` via `dim_benchmark`: `$VIX1D, $VIX9D, $VIX, $VIX3M, $VIX6M, $VIX1Y`.
- Pre‑processing: pivot to daily wide frame; per‑tenor forward fill up to 2 days (`SCORING_VIX_FFILL_LIMIT`); drop days with remaining gaps. Only dates with all tenors are kept.
- Features written to `fact_vix_term_structure` (PK `underlying_symbol`, `date_key`, default underlying `SPX/VIX`):
  - Levels: `vix_1d, vix_9d, vix_1m, vix_3m, vix_6m, vix_1y`
  - Slopes: adjacent spreads plus `curve_slope = vix_1y - vix_1d`
  - Ratios: `ratio_1m_3m`, `ratio_1m_6m`, `ratio_3m_1y`
  - Flags: `is_contango_full` (1d<9d<1m<3m<6m<1y), `is_contango` (front contango + ≥2 of 3 back slopes up), `is_backwardation_front` (1m>3m), `is_backwardation_short` (9d>1m), `num_inversions` (count of non‑positive adjacent slopes)
- Regime classification (daily):
  - Rolling percentiles on `vix_1m` over trailing 750 trading days (`SCORING_VIX_WINDOW_DAYS`): calm ≤ 30th (`SCORING_VIX_CALM_PCT`), stress ≥ 70th (`SCORING_VIX_STRESS_PCT`), panic ≥ 90th (`SCORING_VIX_PANIC_PCT`).
  - `panic`: vix_1m ≥ panic_pct AND backwardation (front or short)
  - `stressed`: vix_1m ≥ stress_pct AND backwardation
  - `calm`: vix_1m ≤ calm_pct AND relaxed contango flag
  - else `neutral`
  - Dates with < 750 prior observations → `regime = NULL`, `risk_flag = NULL`; otherwise `risk_flag = 1` for stressed/panic, 0 for calm/neutral.
- Orchestration: scorer `main.py` runs `VixTermStructureService` each day after other pipelines; upserts into `fact_vix_term_structure` idempotently.

### SPX/VIX Variance Risk Premium (VRP)
- Inputs:
  - SPX OHLC from `fact_security_price` / `dim_stock` (`symbol = '$SPX'`)
  - VIX level from `fact_benchmark_price` / `dim_benchmark` (`benchmark_name = '$VIX'`)
- Realized variance (RV): daily Rogers–Satchell variance using SPX OHLC  
  `gk_var = 0.5*(ln(H/L))^2 - (2*ln2 - 1)*(ln(C/O))^2`; 30‑day RV is the rolling sum over 21 trading days (`SCORING_VRP_TRADING_DAYS`).
- Implied variance (IV): `(VIX/100)^2 * (30/365)` (VIX treated as 30‑day annualized volatility).
- VRP: `iv_30d_var - rv_30d_var`; stored in `fact_spx_vix_vrp` (PK `underlying_symbol`, `date_key`, default `SPX/VIX`).
- Regime classification (percentile‑based, trailing `SCORING_VRP_LOOKBACK_DAYS`, default 720):
  - VRP state: `<20th% = low/negative`, `>80th% = high/positive`, else normal.
  - Vol state (VIX): `<33rd% = low`, `>66th% = high`, else normal.
  - Regime mapping: high vol + low VRP → “crisis / panic”; high vol + high VRP → “stressed but hedged”; low vol + high VRP → “carry / complacency”; low vol + low VRP → “calm but fragile”; else neutral.
- Forward‑fill: VIX is ffilled up to `SCORING_VIX_FFILL_LIMIT` trading days for alignment with SPX.
- API: surfaced via `/api/v1/vol-regime` alongside the existing VIX term structure snapshot (`rv_30d_var`, `iv_30d_var`, `vrp_30d`, `vrp_regime`, `vrp_state`, `vol_state`).

## Environment Variables (scorer)
These variables are read from `env/<ENV>/scorer.env` via `apps.scorer.src.settings.Settings`.

- SCORING_MOMENTUM_WINDOW_WEIGHTS (default: `200=1.0,90=1.0,50=1.0,30=1.0`)
  - Comma‑separated `window=weight` pairs. Effective weight per window is:
    `base_weight × (min(1, |t| / SCORING_MOMENTUM_TSTAT_CAP))^2`, where `t` is the trend t‑stat from the log‑price regression.
- SCORING_MOMENTUM_MIN_VALID_FRAC (default: `0.8`)
  - Require at least this fraction of valid price points within a window; otherwise the window is skipped.
- SCORING_MOMENTUM_TSTAT_CAP (default: `3.0`)
  - Cap used in t‑stat weighting. A cap of 3.0 roughly bounds at a “strong” ~3‑sigma trend.
- SCORING_MOMENTUM_MIN_GROUP_SIZE (default: `5`)
  - Minimum group size (Sector for now) for residual neutralization; fallback to market median when smaller.
- SCORING_MOMENTUM_COMPOSITE_MODE (default: `blend`)
  - What to persist as `momentum score`: `residual`, `raw`, or `blend` (residual/raw convex blend).
- SCORING_MOMENTUM_RESIDUAL_WEIGHT (default: `0.7`) and SCORING_MOMENTUM_RAW_WEIGHT (default: `0.3`)
  - Weights used when `SCORING_MOMENTUM_COMPOSITE_MODE=blend`.
- SCORING_ASOF_MIN_COVERAGE (default: `0.5`)
  - Require at least this fraction of eligible symbols to have prices on the as‑of day; else fall back to the next earlier day meeting the threshold (or latest day if none).
- SCORING_ASOF_PASS_MIN_RATIO (default: `0.5`)
  - Hard guard: fail the scorer run when `asof_pass / eligible` falls below this ratio.
- SCORING_MOMENTUM_VALID_MIN_RATIO (default: `0.5`)
  - Hard guard: fail the scorer run when `momentum_valid / asof_pass` falls below this ratio.
  

- SCORING_VALUATION_SECTOR_WEIGHT (default: 0.7)
  - Weight for sector‑relative cheapness when blending with market.
- SCORING_VALUATION_MARKET_WEIGHT (default: 0.3)
  - Weight for market‑relative cheapness.
- SCORING_VALUATION_MIN_SECTOR_SIZE (default: 5)
  - Minimum group size to use sector percentile; otherwise falls back to market percentile for that metric.

Hybrid weights (IC + Risk Parity):
- SCORING_WEIGHT_LAMBDA_RP (default: 0.4)
  - Blend between IC (predictive) and Risk Parity (diversification). 0 = IC only; 1 = RP only.
- SCORING_WEIGHT_WINDOW_DAYS (default: 504)
  - Rolling window in trading days for IC and factor‑return statistics.
- SCORING_WEIGHT_HORIZON_DAYS (default: 21)
  - Forward return horizon (trading days) used in IC calculation.
- SCORING_WEIGHT_FORCE (default: false)
  - Force recompute weights on next scorer run (overrides monthly cache). Also available as admin flag `force_recompute_weights`.

- SCORING_MF_COMPONENT_WEIGHTS (default: `cmf20=0.4,cmf5=0.2,vol_surp=0.3,ret20=0.1`)
  - Weights for the money-flow composite (all inputs are z-scored cross-sectionally).
- SCORING_MF_MIN_VALID_FRAC (default: 0.8)
  - Coverage required within each component window (CMF, volume surprise, return).

- SCORING_VIX_FFILL_LIMIT (default: 2)
  - Forward-fill tolerance (trading days) for missing VIX tenors and VRP VIX alignment.

- SCORING_VRP_TRADING_DAYS (default: 21)
  - Trading-day window for RV (Rogers–Satchell) rolling sum (~1 month).
- SCORING_VRP_LOOKBACK_DAYS (default: 720)
  - Rolling window for VRP/VIX percentile thresholds (≈ 3 trading years).
- SCORING_VRP_VRP_LOW_PCT / SCORING_VRP_VRP_HIGH_PCT (defaults: 0.20 / 0.80)
  - Percentiles for VRP state (low/negative vs high/positive).
- SCORING_VRP_VIX_LOW_PCT / SCORING_VRP_VIX_HIGH_PCT (defaults: 0.33 / 0.66)
  - Percentiles for VIX state (low / high).

Setup tip: copy `env/example/scorer.env.example` to your active profile, e.g. `env/local/scorer.env`, and adjust as needed.

## Observability
- Scorer metrics (`rankalpha_scorer_runs_total`, `rankalpha_scorer_run_seconds_bucket`, `rankalpha_scorer_symbols_processed`) are exposed via Prometheus on `OBSERVABILITY_METRICS_PORT` (default 9101).
- Data quality metrics:
  - `rankalpha_scorer_required_score_missing_ratio` – fraction of symbols missing either required score: **Momentum** + **Value**.
  - `rankalpha_scorer_required_score_missing_symbols` – missing symbol count for the same check.
  - `rankalpha_scorer_required_score_coverage_ratio` – 1 - missing ratio.
  - `rankalpha_scorer_asof_pass_ratio` – as-of freshness pass-rate over eligible symbols.
  - `rankalpha_scorer_momentum_valid_ratio` – momentum-valid rate over as-of-passing symbols.
  - `rankalpha_scorer_parquet_to_momentum_ratio` – momentum-valid rate over eligible symbols.
  - `rankalpha_scorer_drift_violations_total{check}` – hard-guard violation counter.
- Universe semantics: the denominator is the active+eligible universe (`dim_stock.is_active=TRUE` ∩ `mv_universe_eligible.eligible=TRUE`) when that DB query succeeds; otherwise it falls back to all Parquet symbols for metrics, but skips Sentry paging to avoid false alerts.
- OpenTelemetry spans (`scorer.run`, per-run insert summaries) flow to the shared collector (`otel-collector`) by default. Override `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, or `OTEL_SERVICE_NAME` in `scorer.env` when pointing at a different backend.
- Grafana dashboards (see `docs/observability.md`) chart scorer runtimes alongside ingestion and API latency, making it easy to add alerts on failures or slow runs.

### Note on LINREG_* technicals
- As of 2025‑10‑14, the LINREG_200/90/50/30 technicals written to `fact_score_history` are computed from log‑price slope and stored as percent per trading day (log_slope × 100). Prior rows were raw‑price slope (price units per day). Downstream consumers using percentile scaling remain robust.

### Quality Scores
```python
# Company Quality Components
- Return on equity (ROE)
- Return on assets (ROA)
- Gross margin trends
- Debt/equity ratio (inverse)
- Current ratio
- Revenue growth stability
- Earnings consistency
- Cash flow quality
```

### Sentiment Integration
```python
# Sentiment Components (from sentiment service)
- News sentiment score
- Analyst recommendations
- Social media sentiment
- Insider trading signals
- Options flow indicators
```

## Universe Eligibility
The scoring universe is restricted to listings that are both active and eligible by price/liquidity policy. Eligibility is computed in `rankalpha.mv_universe_eligible` (driven by `rankalpha.universe_policy`) and includes ETFs that meet the same thresholds as equities. See apps/ingestion/README.md for policy details.

This reduces compute and noise while keeping liquid ETFs in scope. The scorer loads symbols from `dim_stock` ∩ `mv_universe_eligible (eligible = TRUE)` at runtime.

## Calculation Pipeline

### Daily Processing Flow
1. **Data Retrieval**: Load latest prices and fundamentals
2. **Preprocessing**: Clean and normalize data
3. **Feature Engineering**: Technical indicators are computed centrally during ingestion from canonical Parquet OHLCV and stored in Postgres (`fact_technical_indicator`). The scorer reuses these values (via DB/API) rather than recalculating them.
4. **Score Calculation**: Apply scoring algorithms
5. **Normalization**: Z-score or percentile normalization
6. **Ranking**: Generate relative rankings
7. **Composite Scoring**: Weight and combine sub-scores
8. **Validation**: Quality checks and anomaly detection
9. **Storage**: Save to `fact_score_history` (scores). Technical indicators are saved by ingestion in `fact_technical_indicator` and exposed via `vw_latest_technicals`.
10. **Notification**: Alert downstream services

## Debug Harness: Momentum Trace
Use the built-in helper to explain the per-window momentum inputs and blended result for a single symbol. It writes a CSV with window-level details plus a JSON summary you can inspect or diff.

- Script: `apps/scorer/src/tools/explain_momentum.py`
- Run (from repo root):
  - `uv run python -m apps.scorer.src.tools.explain_momentum --symbol AAPL --prices-dir /data/prices --asof 2025-01-31 --out ./debug/momentum_AAPL.csv`

Outputs
- CSV: `./debug/momentum_<SYMBOL>_<TIMESTAMP>.csv` (or the path you pass via `--out`)
  - Columns: `window, slope_%_per_day, R2, n_valid, r_sign, t_stat, t_factor, eff_weight, used`
- JSON: sidecar next to the CSV with parsed settings and the blended `%/day` slope

Options
- `--base-weights '200=1,90=1,50=1,30=1'` (else reads SCORING_MOMENTUM_WINDOW_WEIGHTS from env)
- `--min-valid-frac 0.8` and `--tstat-cap 3.0` (or use env: SCORING_MOMENTUM_MIN_VALID_FRAC / SCORING_MOMENTUM_TSTAT_CAP)
- `--asof YYYY-MM-DD` to truncate the series to the given trading day (recommended to match scorer’s as-of logic)

## Backfill Job: Momentum Raw/Residual/Composite
Backfill the last N price days that meet the universe coverage threshold. The job reuses the scorer’s logic (coverage-gated windows, t‑stat weighting, sector‑median residual) and writes three series: `momentum raw score`, `momentum residual score`, and the composite `momentum score`.

- Script: `apps/scorer/src/tools/backfill_momentum.py`
- Run (from repo root):
  - `uv run python -m apps.scorer.src.tools.backfill_momentum --days 21`
  - Options:
    - `--min-coverage 0.5` (default from `SCORING_ASOF_MIN_COVERAGE`)
    - `--prices-dir /data/prices` (defaults to `/data/prices`)
    - `--dry-run` (compute counts without inserting)

Notes
- Inserts are idempotent per (date_key, stock_key, score_type_key) using a NOT EXISTS guard.
- Filters parquets to active, eligible universe when available.
- Uses the same env knobs as the daily scorer for window weights and thresholds.

## Diagnostic: Overview Playbook Sanity Check
This is a quick, read-only diagnostic for the Home/Overview “Implication” playbook copy (Trend vs Chop vs Risk-Off context + Nowcast risk dial).

- Script: `apps/scorer/src/tools/check_overview_playbook.py`
- What it does:
  - Joins Nowcast snapshots (`rankalpha.vw_nowcast_snapshot_series_with_deltas`) + flow-based regime rules (`rankalpha.fact_regime_rules`) + a market proxy price series (`rankalpha.vw_stock_price_history`, e.g. `$SPX`).
  - Builds simple forward returns and prints summary stats by playbook “bias” (defensive / momentum / mean_reversion / balanced).
- Not part of the scorer DAG: it does not run in Airflow or during `apps/scorer/main.py`; run it manually when you want to sanity-check the mapping.

Run (local, from repo root)
- `cd apps/scorer && uv run python src/tools/check_overview_playbook.py --symbol '$SPX' --days 750 --horizon 5`

Run (Docker Compose)
- `docker compose -f compose/docker-compose.yml run --rm scorer python apps/scorer/src/tools/check_overview_playbook.py --symbol '$SPX' --days 750 --horizon 5`

Notes
- Quote `'$SPX'` (or escape it as `\\$SPX`) so your shell doesn’t treat `$SPX` as an env var.
- This is intentionally not a “real backtest” (no costs, no portfolio construction); it’s a fast calibration/sanity check for regime-conditioned heuristics.

### Score Normalization
```python
def normalize_scores(scores: pd.Series) -> pd.Series:
    """Normalize scores to 0-100 scale"""
    # Z-score normalization
    z_scores = (scores - scores.mean()) / scores.std()
    
    # Convert to percentiles
    percentiles = stats.norm.cdf(z_scores) * 100
    
    return percentiles
```

### Weighting Schemes
```python
# Default weight configuration
SCORE_WEIGHTS = {
    'momentum': 0.30,
    'value': 0.25,
    'quality': 0.25,
    'sentiment': 0.20
}

## Screener Change Tracking ("What's New")

The scorer also maintains the delta dataset that powers the "What's New" screener view. The orchestration in `apps/scorer/src/main.py` follows this sequence every run:

1. **Source history** – Screener snapshots land in `rankalpha.fact_screener_rank` (per `(date_key, stock_key, source_key, style_key)`).
2. **Materialized view refresh** – `capture_screener_changes()` refreshes `rankalpha.mv_screener_changes`, which diffs the latest trading day against the prior three trading days to classify rows as `entered`, `reentered`, or `dropped`. The view enriches records with symbol metadata and computes recency fields (`days_since_last_seen`, `absent_trading_days`).
3. **Breadth aggregation** – The same helper also refreshes `rankalpha.mv_screener_breadth`, aggregating per‑style counts, normalized percentages, and 5‑day averages (using the eligible universe from `fact_screener_rank`). As of V74+/API update, breadth consumption is sign‑aware in the API: bullish styles contribute positively to “net %” while bearish styles subtract (see “Signed Breadth” below).
4. **Fact persistence** – After the refresh, the scorer inserts any new rows into `rankalpha.fact_screener_rank_change`, a narrow fact table that stores change events long term.
5. **API surface** – `GET /api/v1/screener/changes` queries the fact table (joined to dimensions), while `GET /api/v1/screener/breadth` reads directly from the breadth view. No additional diffing happens outside this pipeline.
6. **Concurrent refresh support** – Migration V53 provides a plain unique index on `(change_date_key, stock_key, source_key, style_key, change_type)` so `mv_screener_changes` refreshes concurrently; `mv_screener_breadth` carries a unique index on `(change_date, style_key)` for the same reason.

This keeps the 3-business-day change logic centralized in the scorer and ensures consumers always read from durable tables/views instead of recalculating deltas client-side.


# Regime (US Screener‑Based Market State)

This feature measures the market “regime” from screener breadth and intensity across styles, standardized per style and blended into Risk‑On/Risk‑Off cores. It runs as part of the daily scorer and exposes API endpoints for the UI.

**Database artifacts**
- `mv_universe_regime_us` – as‑of daily US universe (per trading day):
  - Includes only listings whose day‑t price/volume meet floors: Close ≥ $10; AvgVol(63d) ≥ 1,000,000; ≥15/22 bars.
  - Exchange whitelist: NYSE%, NASDAQ%, AMEX%, CBOE%; OTC excluded.
  - `asset_type_name ILIKE 'equity'` (ADRs allowed; ETFs/ETNs/CEFs/prefs out if typed).
  - Built as day × stock with point‑in‑time checks (no `dim_stock.is_active` filter; delisted names naturally fall out after last bar).
- `dim_style_regime_map` – canonical style names + regime weights (idempotent seeds):
  - Risk‑On: Momentum +1.0, Pullback +0.6, QualityGrowth +0.9, ValueGARP +0.4, IPO +0.5, EarningsPost +0.6, Squeeze +0.3.
  - Risk‑Off: Short +1.0, MeanRev +0.6, Defensive +0.5, EarningsPre +0.3.
- `mv_style_intensity_us` – per‑day, per‑style intensity using max tier per symbol and US universe denominator; emits 0‑intensity rows for all styles every day.
- `fact_style_z_us` – robust Z per style/day (output of scorer).
- `fact_regime_series` – RiskOnCore, RiskOffCore, RegimeRaw, EMA10/EMA50, label, index (output of scorer).
- `vw_regime_series` – convenience view joining dates.

**Computation overview (daily)**
1) Universe U(t): from `mv_universe_regime_us`, universe_count per day.
2) Style intensity I_f(t):
   - From `fact_screener_rank` join `dim_source.screener_weight ∈ {1.2, 1.0, 0.8}`; map `dim_style` to canonical via `dim_style_regime_map`.
   - Per (symbol, style) take max tier for day t; sum across symbols; divide by U(t).
   - `mv_style_intensity_us` produces one row for every canonical style every day (0 when no hits).
3) Robust standardization (scorer):
   - For each style f, take a rolling window (default up to 252 trading days; fallback 90 when history < 120).
   - Location = median; scale = 1.4826·MAD, else 0.7413·IQR, else stdev (guarded). Clip Z to [−4, +4].
   - Persist Z_f(t) to `fact_style_z_us`.
4) Regime cores and composite (scorer):
   - RiskOnCore(t) = Σ w_R(f)·Z_f(t) over Risk‑On canonicals.
   - RiskOffCore(t) = Σ w_R(f)·Z_f(t) over Risk‑Off canonicals.
   - RegimeRaw(t) = RiskOnCore − RiskOffCore.
   - EMA10/EMA50: computed over the most recent history (fetch DESC LIMIT 1000, then reverse to ascending before EWM).
   - Labels with hysteresis: Risk‑On if EMA10 > +0.5 for ≥3 consecutive days; Risk‑Off if EMA10 < −0.5 for ≥3; else Neutral.
   - RegimeIndex (0–100): `50 + 10*zscore(EMA10 over trailing ≤252)` clipped to [0, 100].
   - Persist to `fact_regime_series`.

**Operational details**
- Dependency‑ordered refresh: scorer refreshes `mv_universe_regime_us` first, then `mv_style_intensity_us` before computing Z/cores.

## Signed Breadth (Bullish vs Bearish styles)

Motivation: Raw breadth treats each style’s net percentage equally positive when entries exceed drops, which is misleading for risk‑off styles (e.g., Short, MeanReversion, Defensive, EarningsPre). The API now signs breadth by style bias so that risk‑off strength detracts from aggregate breadth.

Data pipeline
- View: `mv_screener_breadth` (unchanged) emits, per (change_date, style):
  - `entered_count`, `reentered_count`, `dropped_count`, `eligible_count`
  - `entered_pct`, `dropped_pct`, `net_pct = (entered - dropped)/eligible`
  - 5‑day rolling averages for the same pcts
- Bias map (authoritative): stored centrally in the API as `STYLE_REGIME_MAP` with fallback to `dim_style.position_side` for unknown styles.

API outputs (GET `/api/v1/screener/breadth`)
- Adds the following fields to each item:
  - `regime_bias`: `'Bullish' | 'Bearish'`
  - `net_pct_signed`: `+net_pct` for Bullish styles, `-net_pct` for Bearish
  - `net_pct_avg_5d_signed`: signed 5‑day average

Client‑side aggregation (UI example)
- Weighted net breadth for the day:
  - `weighted = sum_i(net_pct_signed_i * eligible_count_i) / sum_i(eligible_count_i)`
  - Baseline vs 5‑day uses the signed average analogously.
- Result: dominance of risk‑off styles lowers the aggregate and renders as red; broadening in risk‑on styles lifts it and renders as green.

## Dynamic Pullback Regime Weight (context‑aware)

Pullbacks are bullish when they are buy‑the‑dip within strong breakout regimes, but can indicate distribution when breakouts stall and stress rises. The scorer now adjusts the Pullback regime weight daily before composing cores.

Definitions
- Standardized per‑style intensities from `fact_style_z_us`: `Z_momo(t), Z_pull(t), Z_mr(t), Z_short(t)`.
- Breakout–pullback spread: `Δ(t) = Z_momo(t) − Z_pull(t)`.
- Stress overlay (risk‑off composite): `Stress(t) = max(0, 0.5·Z_mr(t) + 0.5·Z_short(t))`.

Effective Pullback weight
```
g(t) = tanh( Δ(t) / 0.75 ) − 0.3 · max(0, Stress(t) − 0.25)
g(t) ∈ [−1, +1]
w_pull,eff(t) = w_pull,base · g(t)
```
- When Momentum leads and stress is low: `g > 0` ⇒ Pullback contributes positively to Risk‑On.
- When Pullback dominates and stress is elevated: `g < 0` ⇒ Pullback contribution attenuates or flips negative (distribution signal).

Persistence & API
- Persisted daily to `rankalpha.fact_regime_effective_weight(date_key, canonical_name, effective_weight, g_factor, base_weight)` (see migration V81).
- Exposed via `GET /api/v1/screener/regime/latest` as `effective_weights` for transparency.
- Missing/quiet styles: the MV emits zero‑intensity rows so quiet styles remain present and contribute large negative Z if applicable; no silent drops.
- Numerical safety: the robust Z path guards against NaN/zero scales (MAD/IQR/stdev fallbacks) and finite z enforcement.
- Backfilling: recommended to compute ≥252 trading days so EMAs and labels stabilize.

## Flow-Based Regime Rules (no HMM)

New in V93: alongside the intensity-based regime, the scorer now emits a purely rules-driven regime that relies on flow features (entrants, exits, continuers, churn) and transition bias—no Hidden Markov Model required. This powers `/api/v1/screener/regime-rules/*`.

**Database artifacts**
- `mv_screener_flow_us` – daily per-canonical style counts:
  - `entered_count` (entered + reentered), `dropped_count`, `continuers_count`, `eligible_count`.
  - Only symbols meeting the US eligibility policy (same as `mv_universe_regime_us`) are counted; metrics are cross-joined with every canonical style so rows exist even on quiet days.
- `mv_style_transition_us` – Pullback transition telemetry (t → t+1):
  - `pullback_count`, `pull_to_momentum`, `pull_to_short` for the next trading session.
  - Used to derive Transition Bias (TB).
- `regime_rules_config` – single-row table holding tunable constants (windows, RS weights, thresholds, hysteresis, tagging percentiles).
- `fact_regime_rules` – daily composites persisted by the scorer:
  - Components: `mb`, `bb`, `mri`, `db`, Trend Thrust (TT), Mean-Reversion Pressure (MRP), Risk-Off Pressure (ROP), Defensive Tilt (DT), Persistence Score (PS), Transition Bias (TB), composite `rs`, smoothed `rs_smooth`, label, and tags.

**Computation overview**
1. Refresh supporting MVs (`mv_universe_regime_us`, `mv_screener_flow_us`, `mv_style_transition_us`) in that order.
2. Build normalized flow series per canonical style: entrants/eligible, dropped/eligible, continuers/eligible, churn.
3. Compute robust rolling Z-scores (MAD/IQR fallback, ±4 clamp):
   - `MB = z_rs_window(entered_pct_Momentum) + 0.3·z_rs_window(entered_pct_Squeeze)`
   - `BB = z_rs_window(entered_pct_Short)`
   - `MRI = z_rs_window(churn_{Pullback,MeanRev})`
   - `DB = z_rs_window(entered_pct_Defensive)`
   - Long-window overlays (default 252d) for MRP, DT, PS, TB.
4. Composite & veto:
   - `RS = w_mb·MB + w_bb·BB + w_mri·MRI + w_db·DB`
   - Persistence veto caps RS at +0.25 whenever `PS < ps_veto_threshold`.
   - `RS_smooth = rolling_mean(RS, hysteresis_days)` (default 3).
5. Labeling (rules, no HMM):
   - Trend if `RS_smooth > rs_trend_threshold` for `hysteresis_days` consecutive.
   - Risk-Off if `RS_smooth < rs_riskoff_threshold` for `hysteresis_days`.
   - Else Chop (with optional `MeanReversionFavored` tag when MRI > 0).
6. Tagging:
   - `DefensiveDrift` if Defensive inflow ≥ rolling `defensive_pct_threshold` percentile and MB < 0.
   - `SpeculativeMania` if Squeeze inflow ≥ `mania_pct_threshold` percentile and IPO inflow elevated.
7. Persist to `fact_regime_rules` (UPSERT on date_key). Config version string (`config_key@updated_at`) is stored for traceability.

**API**
- `GET /api/v1/screener/regime-rules/latest` – exposes latest composites, label, tags, config version.
- `GET /api/v1/screener/regime-rules/series` – paginated history with optional date filters.

**Notes**
- Flow MVs dedupe at (stock, canonical style, day) so multiple sources within the same style do not double-count entrants/continuers.
- `mv_style_transition_us` only tracks Pullback transitions today; extendable if we add more state-machine logic.
- Backfill ≥252 trading days before trusting RS percentiles/tags; rolling quantiles fall back gracefully but need history for stable percentiles.

**API (read-only)**
- `GET /api/v1/screener/regime/latest` – latest row (cores, raw, EMA10/50, label, index, participation).
- `GET /api/v1/screener/regime/series` – time series with paging and date filters.
- `GET /api/v1/screener/regime/styles` – per-style Z snapshot for the latest (or requested) date.

## Market Structure (CVD) Regime (Market Mode)

This regime watches tape structure instead of flows or factor migrations.

- Components (per US eligible universe from `mv_universe_regime_us`):
  - **Trend**: equal-weight index return t-stat over `SCORING_MARKET_STRUCTURE_TREND_WINDOW` days (default 50d).
  - **RV20**: 20d realized volatility (annualized) of that EW index.
  - **Correlation (PC1 share)**: share of variance explained by the first principal component of the 20d returns matrix (stocks × days).
  - **Dispersion**: robust MAD (×1.4826) of today’s cross-sectional single-day returns.
- Robust rolling z-scores (252d default) feed a rule grid:
  - CalmUptrend, FragileUptrend, Choppy, Risk-Off, Neutral.
  - Thresholds tunable via `SCORING_MARKET_STRUCTURE_TREND_UP_Z`, `SCORING_MARKET_STRUCTURE_TREND_DOWN_Z`, `SCORING_MARKET_STRUCTURE_VOL_THRESHOLD`, `SCORING_MARKET_STRUCTURE_CORR_THRESHOLD`, `SCORING_MARKET_STRUCTURE_DISP_THRESHOLD`.
- Persistence: `fact_regime_market_structure` + view `vw_regime_market_structure` (includes `as_of_date`).
- API: `GET /api/v1/market-structure/latest` and `/series`.
- Env knobs (defaults shown):
  - `SCORING_MARKET_STRUCTURE_LOOKBACK_DAYS=320`
  - `SCORING_MARKET_STRUCTURE_TREND_WINDOW=50`
  - `SCORING_MARKET_STRUCTURE_RV_WINDOW=20`
  - `SCORING_MARKET_STRUCTURE_CORR_WINDOW=20`
  - `SCORING_MARKET_STRUCTURE_Z_WINDOW=252`
  - Label thresholds listed above.
- Operational notes:
  - Requires ≥corr_window valid days with non-null returns for ≥5 symbols; SVD runs on tall-skinny (20 × N) matrix.
  - Dispersion uses current-day eligible symbols only; winsorize upstream if you expect extreme single-name moves.
  - Keep lookback ≥ z-window for stable z-scores.

**Implementation pointers**
- SQL: see migrations V79 (universe/intensity, mapping seeds) and V80 (regime facts & view).
- Scorer: `ScoreRepository.update_regime_series_us()` computes robust Z, cores, EMA, labels, index, and persists.
- Models: `MvUniverseRegimeUs`, `MvStyleIntensityUs`, `FactStyleZUs`, `FactRegimeSeries`, `VwRegimeSeries` in apps/common/src/models.py.

**FAQ / Troubleshooting**
- Universe looks too small or empty:
  - Inspect `mv_universe_regime_us` for the date: `SELECT * FROM rankalpha.mv_universe_regime_us WHERE date_key = :dk AND eligible IS TRUE LIMIT 5;`
  - Check close ≥ $10, avg_vol_63 ≥ 1,000,000, ≥15/22 continuity, and exchange whitelist (NYSE/NASDAQ/AMEX/CBOE). If policy needs tuning, update V79 and re‑migrate.
- Latest regime isn’t updating today:
  - Ensure we refresh MVs in order (universe then style). The scorer does this inside `update_regime_series_us()`; verify logs for both refreshes.
  - If `mv_style_intensity_us` is missing today, re‑run refresh manually: `REFRESH MATERIALIZED VIEW rankalpha.mv_universe_regime_us; REFRESH MATERIALIZED VIEW rankalpha.mv_style_intensity_us;` then re‑run the scorer.
- Styles disappear from `/regime/styles` on quiet days:
  - Fixed: `mv_style_intensity_us` emits a 0‑intensity row for every canonical style every day. If a style is missing, verify `dim_style_regime_map` contains it and that the MV is up to date.
- NaNs or 500s from regime endpoints:
  - The robust Z path guards against zero/NaN scales (MAD → IQR → stdev → 1.0) and forces finite Z. If you still see issues, backfill more history so each style has ≥90 days.
- Short history / cold start behavior:
  - With <120 days, the scorer uses a 90‑day fallback for Z; EMAs stabilize after ~50 days. For best results, backfill ≥252 trading days (intensity + regime series).
- EMA ignores recent history after long runs:
  - We fetch the most recent 1000 rows in DESC order and reverse in Python before EWM; adjust the window if you need more history.
- Participation overlay is null:
  - It’s optional; populate using existing RVOL‑gated Momentum/Pullback sources by computing Z on those filtered sources and storing in `fact_regime_series.participation`.
- As‑of universe vs. `is_active`:
  - `mv_universe_regime_us` is point‑in‑time (no `is_active`); delisted names drop naturally once they stop trading. Do not add `is_active` to the MV or history will be biased.
- Performance tips:
  - Ensure indexes on `fact_security_price(stock_key, date_key)` and MV unique indexes (`mv_universe_regime_us_pk`, `mv_style_intensity_us_pk`). Prefer CONCURRENTLY refresh in production.
- Verifying a day end‑to‑end:
  - Check U(t): `SELECT date_key, COUNT(*) FROM mv_universe_regime_us WHERE eligible IS TRUE AND date_key=:dk GROUP BY 1;`
  - Check intensity for a style: `SELECT * FROM mv_style_intensity_us WHERE date_key=:dk AND style_name='Momentum';`
  - Check Zs: `SELECT * FROM fact_style_z_us WHERE date_key=:dk ORDER BY style_name;`
  - Check regime: `SELECT * FROM vw_regime_series ORDER BY as_of_date DESC LIMIT 5;`

## Backfill How‑To (Regime) — Fast Path

Backfilling the regime series can be I/O bound if done day‑by‑day. The fastest path is to refresh the MVs once, pull intensities in bulk, compute Z and cores vectorized, then bulk‑insert.

**0) One‑time MV refresh (historical)**
```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_universe_regime_us;
REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_style_intensity_us;
```

**1) Export intensity window (e.g., last 600 trading days)**
```sql
-- Example: write out as CSV from psql (adjust paths)
\copy (
  SELECT d.full_date, i.date_key, i.style_name, i.intensity_raw, i.universe_count
  FROM   rankalpha.mv_style_intensity_us i
  JOIN   rankalpha.dim_date d ON d.date_key = i.date_key
  WHERE  d.full_date >= (CURRENT_DATE - INTERVAL '900 day')
  ORDER  BY i.date_key, i.style_name
) TO '/tmp/style_intensity_us.csv' WITH CSV HEADER
```

**2) Vectorized compute (Python) — robust Z + cores + EMA**
```python
import pandas as pd, numpy as np

# Load intensities
df = pd.read_csv('/tmp/style_intensity_us.csv', parse_dates=['full_date'])

# Pivot to wide: rows=full_date, cols=style, vals=intensity
wide = df.pivot_table(index='full_date', columns='style_name', values='intensity_raw', aggfunc='first').sort_index()

# Robust Z per style with rolling median/MAD (252d; 90d fallback)
def robust_z_series(x: pd.Series, win=252):
    x = x.astype(float)
    med = x.rolling(win, min_periods=90).median()
    mad = (x.rolling(win, min_periods=90)
             .apply(lambda a: np.median(np.abs(a - np.median(a))), raw=False))
    scale = 1.4826 * mad
    # IQR fallback when MAD==0
    iqr = (x.rolling(win, min_periods=90)
             .quantile(0.75) - x.rolling(win, min_periods=90).quantile(0.25))
    scale = np.where((scale<=1e-8) | ~np.isfinite(scale), 0.7413 * iqr, scale)
    # stdev fallback
    st = x.rolling(win, min_periods=2).std()
    scale = np.where((pd.Series(scale, index=x.index)<=1e-8) | ~np.isfinite(scale), st.clip(lower=1e-6), scale)
    z = (x - med) / pd.Series(scale, index=x.index)
    z = z.replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-4, 4)
    return z

zwide = wide.apply(robust_z_series)

# Regime weights (must match dim_style_regime_map canonical names)
risk_on  = {
  'Momentum':1.0, 'Pullback':0.6, 'QualityGrowth':0.9,
  'ValueGARP':0.4, 'IPO':0.5, 'EarningsPost':0.6, 'Squeeze':0.3
}
risk_off = {'Short':1.0, 'MeanRev':0.6, 'Defensive':0.5, 'EarningsPre':0.3}

risk_on_core  = sum(zwide.get(k, 0.0) * w for k, w in risk_on.items())
risk_off_core = sum(zwide.get(k, 0.0) * w for k, w in risk_off.items())
regime_raw = risk_on_core - risk_off_core
ema10 = regime_raw.ewm(span=10, adjust=False).mean()
ema50 = regime_raw.ewm(span=50, adjust=False).mean()

# Hysteresis label (3 days)
e10 = ema10
last3 = e10.rolling(3).apply(lambda a: float((a>0.5).all()) - float((a<-0.5).all()))
label = np.where(last3==1.0, 'Risk-On', np.where(last3==-1.0, 'Risk-Off', 'Neutral'))

# UI index (z of EMA10 over trailing 252)
mu = ema10.rolling(252, min_periods=20).mean()
sd = ema10.rolling(252, min_periods=20).std().replace(0, 1.0)
zidx = (ema10 - mu) / sd
regime_index = (50 + 10*zidx).clip(0, 100)

out = pd.DataFrame({
    'as_of_date': wide.index,
    'risk_on_core': risk_on_core,
    'risk_off_core': risk_off_core,
    'regime_raw': regime_raw,
    'ema10': ema10,
    'ema50': ema50,
    'regime_label': label,
    'regime_index': regime_index,
}).reset_index(drop=True)

out.to_csv('/tmp/regime_series.csv', index=False)

# Optional: write per-style Zs as well
zout = zwide.reset_index().melt(id_vars='full_date', var_name='style_name', value_name='z_value')
zout.rename(columns={'full_date':'as_of_date'}).to_csv('/tmp/style_z.csv', index=False)
```

**3) Bulk‑load into facts (UPSERT)**
```sql
-- Load style Z into a temp table and upsert
CREATE TEMP TABLE tmp_style_z (as_of_date date, style_name text, z_value numeric);
\copy tmp_style_z FROM '/tmp/style_z.csv' WITH CSV HEADER
INSERT INTO rankalpha.fact_style_z_us (date_key, style_name, z_value)
SELECT d.date_key, t.style_name, t.z_value
FROM tmp_style_z t
JOIN rankalpha.dim_date d ON d.full_date = t.as_of_date
ON CONFLICT (date_key, style_name) DO UPDATE SET z_value = EXCLUDED.z_value;

-- Load regime series
CREATE TEMP TABLE tmp_regime (
  as_of_date date, risk_on_core numeric, risk_off_core numeric,
  regime_raw numeric, ema10 numeric, ema50 numeric,
  regime_label text, regime_index numeric
);
\copy tmp_regime FROM '/tmp/regime_series.csv' WITH CSV HEADER
INSERT INTO rankalpha.fact_regime_series (
  date_key, risk_on_core, risk_off_core, regime_raw, ema10, ema50, regime_label, regime_index
)
SELECT d.date_key, t.risk_on_core, t.risk_off_core, t.regime_raw, t.ema10, t.ema50, t.regime_label, t.regime_index
FROM tmp_regime t
JOIN rankalpha.dim_date d ON d.full_date = t.as_of_date
ON CONFLICT (date_key) DO UPDATE SET
  risk_on_core = EXCLUDED.risk_on_core,
  risk_off_core = EXCLUDED.risk_off_core,
  regime_raw = EXCLUDED.regime_raw,
  ema10 = EXCLUDED.ema10,
  ema50 = EXCLUDED.ema50,
  regime_label = EXCLUDED.regime_label,
  regime_index = EXCLUDED.regime_index;
```

**Performance tips**
- Prefer `\copy`/COPY over row‑wise ORM inserts; use temp tables + single UPSERT.
- Keep `mv_universe_regime_us` and `mv_style_intensity_us` refreshed once upfront.
- If memory is tight, backfill in chunks (e.g., 300‑day windows) and append; EMA continuity is preserved across concatenated chunks if you seed the first period with prior EMA values.

### One‑liner Tool (preferred)
Use the built‑in tool which performs the same steps (vectorized) and bulk‑upserts via `psycopg2.extras.execute_values`.

```bash
# Last 600 trading days (default)
uv run python -m apps.scorer.src.tools.backfill_regime --days 600

# Explicit window
uv run python -m apps.scorer.src.tools.backfill_regime --window 2023-01-01 2025-10-21

# Skip MV refresh if you have just refreshed
uv run python -m apps.scorer.src.tools.backfill_regime --days 600 --no-refresh
```

# Sector-specific adjustments
SECTOR_ADJUSTMENTS = {
    'Technology': {'momentum': 1.2, 'value': 0.8},
    'Utilities': {'momentum': 0.8, 'value': 1.2}
}
```

## Performance Optimization

### Vectorized Operations
```python
# Efficient calculation using NumPy
def calculate_returns(prices: np.array, periods: list) -> dict:
    returns = {}
    for period in periods:
        returns[f'{period}d'] = (prices[-1] / prices[-period] - 1) * 100
    return returns
```

### Database Query Optimization
```python
# Efficient bulk fetch with joins (example view + fundamentals)
def fetch_scoring_data(symbols: list):
    return session.query(
        VwStockPriceHistory,
        FactFinFundamentals
    ).join(
        FactFinFundamentals,
        VwStockPriceHistory.symbol == FactFinFundamentals.symbol
    ).filter(
        VwStockPriceHistory.symbol.in_(symbols)
    ).all()
```

### Caching Strategy
- **Redis Cache**: Store intermediate calculations
- **Memory Cache**: Keep frequently used data in RAM
- **Result Cache**: Cache final scores for quick retrieval

## Configuration Management

### Scoring Parameters
```yaml
# config/scoring.yaml
momentum:
  lookback_periods: [20, 60, 120, 252]
  volume_weight: 0.2
  volatility_adjustment: true

value:
  metrics:
    - pe_ratio
    - pb_ratio
    - ps_ratio
  outlier_cap: 3  # Cap at 3 standard deviations

quality:
  min_history_days: 252
  growth_smoothing: 0.8
```

### Environment Variables
```env
# Scoring configuration
SCORING_MODE=production
PARALLEL_WORKERS=4
BATCH_SIZE=100

# Feature flags
ENABLE_ML_SCORING=false
ENABLE_SECTOR_ADJUST=true
```

## Quality Assurance

### Validation Checks
```python
def validate_scores(scores: pd.DataFrame) -> bool:
    """Validate score integrity"""
    checks = [
        scores['total_score'].between(0, 100).all(),
        scores['rank'].is_unique,
        scores.isnull().sum().sum() == 0,
        (scores['percentile'] >= 0).all()
    ]
    return all(checks)
```

### Backtesting Integration
- Historical score calculation
- Performance attribution
- Factor analysis
- Regime testing

## Monitoring & Alerts

### Key Metrics
- **Score Distribution**: Mean, std dev, skewness
- **Coverage**: Percentage of stocks scored
- **Calculation Time**: Pipeline performance
- **Score Stability**: Day-over-day changes
- **Anomalies**: Outlier detection

### Health Checks
```python
def health_check():
    return {
        "status": "healthy",
        "last_calculation": last_run_time,
        "stocks_scored": total_scored,
        "average_score": avg_score,
        "calculation_time_ms": calc_time
    }
```

## Running the Service

### Local Development
```bash
cd apps/scorer
uv venv
uv sync --locked
uv run python src/main.py
```

### Docker Deployment
```bash
# Part of docker-compose stack
docker compose -f compose/docker-compose.yml up scorer
```

### Manual Scoring
```python
# Score specific symbols
python src/main.py --symbols AAPL,MSFT,GOOGL

# Recalculate all scores
python src/main.py --full-refresh

# Debug mode with detailed output
python src/main.py --debug --symbol AAPL
```

## Testing Strategy

### Unit Tests
```bash
pytest tests/scorer/
```

### Test Coverage
- Score calculation accuracy
- Ranking algorithm correctness
- Edge case handling
- Performance benchmarks

## Advanced Features

### Machine Learning Integration
```python
# Optional ML-based scoring
class MLScorer:
    def __init__(self):
        self.model = load_model('models/score_predictor.pkl')
    
    def predict_score(self, features):
        return self.model.predict(features)
```

### Factor Analysis
```python
# Analyze factor contributions
def factor_attribution(symbol: str):
    scores = get_component_scores(symbol)
    return {
        'momentum_contribution': scores['momentum'] * WEIGHTS['momentum'],
        'value_contribution': scores['value'] * WEIGHTS['value'],
        # ... other factors
    }
```

## Future Enhancements

### Planned Features
- Machine learning score predictions
- Real-time scoring updates
- Custom scoring models per user
- Alternative data integration
- Factor timing models
- Risk-adjusted scoring
- Peer group comparisons
- ESG score integration

## Dependencies

### Internal
- `common`: Database models and CRUD operations

### External
- numpy>=1.24.0
- pandas>=2.0.0
- scipy>=1.10.0
- scikit-learn>=1.3.0 (optional)

## Troubleshooting

### Common Issues

1. **Missing Data**
   - Check data ingestion completeness
   - Verify symbol coverage
   - Review data quality filters

2. **Score Anomalies**
   - Validate input data ranges
   - Check for calculation overflows
   - Review normalization parameters

3. **Performance Issues**
   - Increase batch size
   - Enable parallel processing
   - Optimize database queries

4. **Inconsistent Rankings**
   - Verify sort stability
   - Check tie-breaking rules
   - Review score precision

## Contributing

### Adding New Metrics
1. Define metric in `metrics/` module
2. Add calculation function
3. Update scoring weights
4. Create unit tests
5. Document methodology
6. Validate with backtesting
