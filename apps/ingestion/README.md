# RankAlpha Data Ingestion Service

## Purpose
Refresh daily OHLCV into canonical Parquets under `/data/prices` and keep the database in sync for downstream APIs. The service prefers existing Parquets and broker previous‑close snapshots when available; yfinance is used as a fallback for initial fills or tail repairs when enabled. After each symbol refresh, it computes daily technical indicators and upserts them, and it maintains a minimal copy of price history (Adj Close preferred) in Postgres for read‑optimized views.

What this service does today (as implemented in `src/main.py`):
- Writes/repairs canonical Parquets at `/data/prices/<SYMBOL>.parquet`.
- Computes and upserts technical indicators to `rankalpha.fact_technical_indicator` and exposes a pivoted snapshot via `rankalpha.vw_latest_technicals`.
- Syncs price history to `rankalpha.fact_security_price` (Adj Close as close_px; O/H/L/Vol when present) using an anchor/tail strategy.
- Auto‑marks `dim_stock.is_active` FALSE for stale symbols and TRUE for recently reactivated symbols based on peer last‑date heuristics.
- (Optional) Pulls the next seven days of earnings from Finnhub and persists the earliest upcoming date per stock in `rankalpha.fact_stock_next_earnings`.
- (Optional) Captures SOFR futures (SR1/SR3) via the Broker service and persists daily snapshots to `rankalpha.fact_sofr_futures`; derives FRA–OIS for common windows (3x6, 6x9, 9x12) into `rankalpha.fact_fra_ois`.
  - Toggle via `INGESTION_RATES_ENABLED=true|false` (default true). If `BROKER_SERVICE_URL` is not set or data is unavailable, the job logs a warning and ingestion continues.
- (Optional) Derives a HY stress tape from the CCC HY OAS benchmark (`%CCCHYS`): computes raw OAS, 10‑day MA, and a 750‑day z‑score, and upserts to `rankalpha.fact_hy_stress`.
  - Toggle via `INGESTION_HY_STRESS_ENABLED=true|false` (default true). Uses trading days only; rows remain null until windows are satisfied.
- (Optional) Derives USDX / DXY regimes from the `$USDX` benchmark in `dim_benchmark` and writes daily features + regime flags to `fact_macro_series` (`US_DXY_*` series).
  - Toggle via `INGESTION_DXY_ENABLED=true|false` (default true). Uses configured benchmark name and windows set via `INGESTION_DXY_*` envs.
- (Optional) Derives breadth indicators (SPX/NDX/NYSE) from existing data vendor breadth series and upserts to `fact_macro_series` under source `RankAlphaDerived`. Outputs include:
  - Hindenburg Omen (raw + 36‑day confirmed cluster) and Fosback HLLI (NYSE).
  - Whaley ADT‑5 (value + bull/capitulation flags), Deemer BAM10 up/down, net new highs, McClellan thrust (10‑day, −100/+100), McClellan Summation breakdown, persistent new lows, %>200d thrust (+20pp/10d), %<200d collapse (+20pp/10d), TRIN stress, A/D bearish divergence for SPX and NDX.
  - TRIN stress and persistent new lows for NYSE; Hindenburg uses NYSE highs/lows and NYA price (uptrend filter bypassed with a warning if NYA price is absent).
  - Breadth regime layer: thrust/fragility/net scores, regime state (-1/0/1), and target exposure for SPX and NDX using a half-life=10d smoother, expanding z-scores, hysteresis (enter_on=+2, enter_off=-2, hold_band=0.5, min_state_days=10), and optional 200‑DMA trend gate. Series codes: `US_SPX_BREADTH_{THRUST,FRAG,NET}_SCORE`, `US_SPX_BREADTH_REGIME_STATE`, `US_SPX_BREADTH_TARGET_EXPOSURE` and NDX equivalents.
  - View: `rankalpha.vw_breadth_signals` filters all derived series (including regime outputs) for convenient API access.
- (Optional) Pulls FRED ON RRP usage (`RRPONTSYD`) and Treasury General Account balance (`WTREGEN`) into `dim_macro_series` / `fact_macro_series` under source `FRED`.
  - Toggle via `INGESTION_RRP_TGA_ENABLED=true|false` (default true); requires `FRED_API_KEY` in `env/<ENV>/ingestion.env`.
- (Optional) Pulls Fed balance sheet / SOMA composition series from FRED into `dim_macro_series` / `fact_macro_series` under source `FRED`.
  - Series: `WALCL`, `WSHOSHO` (SOMA proxy), `TREAST`, `MBST` (stored as `US_FED_{WALCL,WSHOSHO,TREAST,MBST}`).
  - Toggle via `INGESTION_FED_BALANCE_SHEET_ENABLED=true|false` (default true); requires `FRED_API_KEY`.
- (Optional) Pulls 10Y TIPS real yield (`DFII10`) from FRED into `dim_macro_series` / `fact_macro_series` under source `FRED`.
  - Stored as `US_TIPS_10Y_REAL_YIELD` (units: `%`).
  - Toggle via `INGESTION_TIPS_REAL_YIELD_ENABLED=true|false` (default true); requires `FRED_API_KEY`.
- FRED macro pulls re-fetch a rolling lookback window (default 5 days) to capture revisions; configure via `INGESTION_FRED_LOOKBACK_DAYS`.

### HY stress: what it does
- Source: the CCC HY OAS benchmark in `rankalpha.fact_benchmark_price` (lookup by `ingestion_hy_stress_benchmark`, default `%CCCHYS`).
- Computation (see `apps/ingestion/src/hy_stress.py`):
  - For each trading day: store raw OAS, a 10‑day simple moving average, and a 750‑day z‑score of that MA.
  - Z‑score stays null until both windows are filled; inputs tolerate missing raw values.
- Persistence:
  - Joins `dim_date` on `full_date` and upserts into `rankalpha.fact_hy_stress (date_key, benchmark_key, hy_stress_raw, hy_stress_ma, hy_stress_z)`.
  - Conflict target `(date_key, benchmark_key)` updates all three metrics and `load_ts`.
  - Values are explicitly cast to `numeric` to match the table schema.
- Control/tuning:
  - `INGESTION_HY_STRESS_ENABLED` (bool) to skip the job entirely.
  - `INGESTION_HY_STRESS_BENCHMARK` to point at a different OAS series in `dim_benchmark`.
  - `INGESTION_HY_STRESS_MA_WINDOW` and `INGESTION_HY_STRESS_Z_WINDOW` set the MA and z-score windows (defaults 10 and 750 trading days).
- Behavior:
  - Skips if no benchmark row is found or if no new dates beyond the latest fact row.
  - Operates as a guarded step; failures log a warning but do not abort the overall ingestion run.

## Technologies & Tools

### Core Technologies
- **Python 3.12**
- **pandas**, **numpy**, **pyarrow** (Parquet IO)
- **yfinance** (optional fallback price download)
- **psycopg2** (direct Postgres upserts)
- Shared settings/logging from `apps/common`

## Canonical Parquet Schema
Parquets are normalized before write/update:
- Columns and order: `Open, High, Low, Close, Adj Close, Volume` (floats)
- Index: tz‑naive `DatetimeIndex`, sorted, unique
- Legacy vendor/multi‑index columns are collapsed (e.g., `Close_AAPL` → `Close`)
- Adjusted close mapping: if the source schema includes both `Close` and `Unadjusted close`, the service treats `Close` as the adjusted close and sets `Adj Close := Close`. If `Adj Close` is absent in general, it is mirrored from `Close` for downstream safety.

### Refresh nuances (retention and official close)
- Retention: the service retains only the last `INGESTION_HISTORY_DAYS` trading days (default 760) in Parquet and in Postgres. Older DB rows for each symbol are pruned during sync.
- Tail repair: on every refresh, a sufficiently long tail window is re‑downloaded and merged to repair recent gaps/nulls before trimming to the configured retention.
- Official close only: downloads use `interval=1d`, `prepost=false`, and an explicit end bound of US/Eastern midnight for “today”. This excludes in‑session/off‑hours prices so the latest row corresponds to the prior trading day’s official close.
- Broker previous-close preference: when a local Parquet is missing the prior US trading day, ingestion first calls the broker endpoint `GET /price/prev-close/{symbol}` (set `BROKER_SERVICE_URL`, e.g., `http://broker:8000`, and `BROKER_SERVICE_TOKEN`). If available, a single row is appended with `Close` and `Adj Close` set to the broker previous close (O/H/L/Vol left null). If the broker call fails, ingestion falls back to a short yfinance tail download when enabled.
- Closed‑day guard: on weekends and US equity holidays, the refresh step skips the tail re‑download to avoid unnecessary requests. The rest of the pipeline (canonicalization, retention trimming, DB sync/prune) still runs.
  - Weekend re‑evaluation: when run on Saturday/Sunday (or any closed day), ingestion forces a full re‑upsert of the last `INGESTION_HISTORY_DAYS` into Postgres from the existing Parquet. This re‑applies dividend/split adjustments without making network calls.

## Technical Indicators
After writing/refreshing a Parquet, the service computes snapshot indicators and upserts to `rankalpha.fact_technical_indicator (date_key, stock_key, indicator_code, value)`; the API serves:
- `GET /api/v1/technicals/latest?symbol=SYM` (from `vw_latest_technicals`)
- `GET /api/v1/technicals/series?symbol=SYM&indicators=SMA20,RSI14&days=120` (from `fact_technical_indicator`)

Included indicators: SMA20/50/200, EMA12/26, RSI14, ATR14, Bollinger(20,2σ), MACD(12,26,9), returns (5/20/60/120d), VOL_Z20, DIST_52W_HIGH.

## Activity Heuristics (is_active)
The service derives an anchor trading date from a reference symbol (e.g., `SPY`) or the modal last date across peers. It then:
- Marks tickers inactive if their last available date is ≥ N business days behind the anchor (default 5).
- Reactivates previously inactive tickers if their parquet last date is within M business days of the anchor (default 1) and not in the delisted suffix pattern (e.g., `-YYYYMM`).

Tunables live in shared Settings (see below).

### Price Cache Warm-Up
- Optional integration with the API admin endpoint allows ingestion to invalidate and warm Redis price history caches immediately after a successful run.
- Configure `PRICE_CACHE_REFRESH_URL` (e.g., `http://api:6080/api/v1/admin/prices/cache-refresh`) and set `AUTH_SERVICE_TOKEN` (recommended in `env/<ENV>/shared.env`).
  - Batch size (`PRICE_HISTORY_CACHE_REFRESH_CHUNK_SIZE`, default 50) and timeout (`PRICE_CACHE_REFRESH_TIMEOUT_SECONDS`, default 15s) guard against overload; failures are logged but do not abort ingestion.

### Price History Backfill (from Parquet)
- Use `apps/ingestion/src/price_backfill.py` to re-sync `fact_security_price` from the Parquet source of truth.
- Example (all symbols): `uv run python src/price_backfill.py`
- Example (subset): `uv run python src/price_backfill.py --symbols AAPL,MSFT --limit 2`
- Add `--dry-run` to inspect row counts without writing.
- Add `--repair-outliers --max-ratio 100 --max-abs 10000000` to replace extreme price spikes with the last valid price.

## Universe Eligibility (Price/Liquidity Policy)
To reduce noise from illiquid micro‑caps while still allowing liquid ETFs, the platform defines a centralized, database‑driven “eligible universe.” This is computed in the materialized view `rankalpha.mv_universe_eligible` using thresholds from the table `rankalpha.universe_policy`.

Policy (defaults for `policy_code = 'default'`):
- Asset types: `['equity','etf']` (ETFs included)
- Exchange exclude: patterns `['OTC%','OTCQB%','OTCMKTS%','PINK%']`
- Price floor: latest adjusted close ≥ $3
- Liquidity: 30‑day median dollar volume ≥ $1,000,000 and 30‑day median shares ≥ 50,000
- Continuity: at least 15 bars present in the last 22 trading days

Where it’s used:
- Scorer selects symbols from `dim_stock` where `is_active = TRUE` and `mv_universe_eligible.eligible = TRUE`.
- API rankings (and `fn_grades_as_of`) join the same MV, so grades and leaderboards reflect the filtered universe.
- Sentiment selection (consensus batch and scheduling) also filters to eligible symbols.

Operational notes:
- The Airflow DAG refreshes `mv_universe_eligible` immediately after ingestion so downstream tasks use up‑to‑date price/liquidity stats.
- You can tune thresholds by updating `rankalpha.universe_policy` (row with `policy_code='default'`); no code changes required. After changing, refresh the MV.

Schema references:
- `rankalpha.universe_policy` – stores thresholds and lists.
- `rankalpha.mv_universe_eligible` – per‑symbol metrics and `eligible` boolean.


## Configuration (Settings)
Settings are loaded via `apps.ingestion.src.settings.Settings` from `env/<ENV>/ingestion.env` (plus `shared.env`). Relevant keys:
- `INGESTION_WORKERS` – per‑symbol thread workers (default 2)
- `INGESTION_PROGRESS_LOG_EVERY` – log symbol-pool progress every N completed symbols (also logs first/last; default 100)
- `INGESTION_INACTIVE_AFTER_MISSING_BDAYS` – business‑day gap to mark inactive (default 30)
- `INGESTION_STALE_AFTER_MISSING_BDAYS` – trading‑day gap to count as “stale” for alerting (default 1)
- `INGESTION_STALE_PRICE_ALERT_RATIO_THRESHOLD` – alert when stale symbols exceed this share (default 0.05)
- `INGESTION_SYMBOL_SUCCESS_MIN_RATIO` – fail the run when active symbol coverage falls below this ratio (default 0.85). Coverage counts symbols with either a resolved last trade date or an expected-missing classification.
- `INGESTION_REACTIVATE_IF_WITHIN_BDAYS` – business‑day gap to reactivate (default 1)
- `INGESTION_PRUNE_AFTER_MISSING_BDAYS` – business‑day gap before deleting the local Parquet for an inactive symbol (defaults to `INGESTION_INACTIVE_AFTER...`)
- `INGESTION_REFERENCE_SYMBOL` – anchor symbol preference (default `SPY`)
- `INGESTION_ANCHOR_MIN_SHARE` – coverage share to accept modal date as anchor (default 0.5)
- `INGESTION_YFINANCE_ENABLED` – enable yfinance fallback downloads (default true)
- `INGESTION_YFINANCE_TIMEOUT_SECONDS` – timeout per yfinance attempt in seconds (default 20)
- `INGESTION_YFINANCE_MAX_RETRIES` – retry count after failures/timeouts (default 2; attempts = retries + 1)
- `INGESTION_YFINANCE_RETRY_BACKOFF_SECONDS` – exponential backoff base between retries (default 0.5s)
- `INGESTION_TRADING_CALENDAR_LOOKBACK_DAYS` / `INGESTION_TRADING_CALENDAR_LOOKAHEAD_DAYS` – rolling window for `dim_date.is_trading_day` refresh (defaults 365/90)
- Earnings calendar: `FINNHUB_KEY`, `INGESTION_FETCH_EARNINGS` (default true), `INGESTION_EARNINGS_WINDOW_DAYS` (default 7 calendar days)
- Liquidity/RRP/TGA: `FRED_API_KEY` (required for ON RRP + TGA); `INGESTION_RRP_TGA_ENABLED` (default true)
- Fed balance sheet (FRED): `FRED_API_KEY` (required); `INGESTION_FED_BALANCE_SHEET_ENABLED` (default true)
- TIPS real yield (FRED): `FRED_API_KEY` (required); `INGESTION_TIPS_REAL_YIELD_ENABLED` (default true)
- FRED refresh lookback: `INGESTION_FRED_LOOKBACK_DAYS` (default 5; applies to all FRED macro series)
- Database: `DATABASE_NAME`, `DB_USERNAME`, `PASSWORD`, `HOST`, `PORT`
- `BROKER_SERVICE_URL` – base URL for broker FastAPI (enables previous‑close fill; e.g., `http://broker:8000`)
- `BROKER_SERVICE_TOKEN` – service token sent as `X-RA-Service-Token` when calling broker endpoints

## Observability
- Ingestion uses the shared observability helper (`apps/common/src/observability.py`) to emit Prometheus metrics (`rankalpha_ingestion_runs_total`, `rankalpha_ingestion_run_seconds_bucket`, etc.) and OpenTelemetry spans (`ingestion.run`, per-symbol events).
- Latency histograms:
  - `rankalpha_ingestion_phase_seconds{phase,status}` tracks major phase durations (universe load, symbol pool, stale metrics, cache refresh, tail jobs, etc.).
  - `rankalpha_ingestion_symbol_process_seconds{status}` tracks per-symbol worker runtime (`success` / `no_data`).
- Data quality metrics:
  - `rankalpha_ingestion_stale_symbol_ratio` – fraction of symbols whose latest price date lags the run’s anchor by `INGESTION_STALE_AFTER_MISSING_BDAYS` trading days (uses `rankalpha.dim_date` when available, so US market holidays don’t inflate the gap).
  - `rankalpha_ingestion_stale_symbols` – stale symbol count for the same check.
  - `rankalpha_ingestion_symbol_coverage_ratio` – run coverage over active symbols (`with_price OR expected_missing`).
  - `rankalpha_ingestion_symbol_drift_ratio` – `1 - coverage_ratio`; alerts and can fail when above the guard implied by `INGESTION_SYMBOL_SUCCESS_MIN_RATIO`.
  - `rankalpha_ingestion_drift_violations_total{check}` – hard-guard violation counter.
- Compose exposes ingestion metrics on the internal Docker network at `:9100` and routes OTLP traffic to `otel-collector`.
- Metrics surface in Prometheus and Grafana dashboards; see `docs/observability.md` for dashboard names and wiring.

## Project Structure

### Core Files

#### `main.py`
- Orchestrates price download/refresh, canonicalization, technicals computation, DB sync, and activity toggles.
- Universe source: `dim_stock` (`is_active IS TRUE`).

#### Utilities
- `repair_parquets.py` – helper to opportunistically fix legacy files to canonical schema.

## Running

### Local Development
```bash
cd apps/ingestion
uv venv && uv sync --locked
uv run python src/main.py
```

### Docker Compose
```bash
docker compose -f compose/docker-compose.yml up ingestion
```

## Notes
- In DB sync, Adj Close is the canonical close; O/H/L/Vol are nullable.
- Price downloads use US/Eastern “today” as an exclusive end date to avoid future rows.
- Parquet schema repair (legacy fixups) runs on Sunday ET as a weekly hygiene step; per-symbol reads/writes still canonicalize and trim.

## Design Principles

### 1. **Reliability First**
- Robust error handling with retries
- Data validation at ingestion point
- Transactional consistency
- Audit trail for all operations

### 2. **Scalability**
- Asynchronous data fetching
- Batch processing capabilities
- Parallel source processing
- Rate limiting and throttling

### 3. **Data Quality**
- Schema validation on input
- Duplicate detection and handling
- Data completeness checks
- Anomaly detection

### 4. **Modularity**
- Separate modules per data source
- Pluggable architecture for new sources
- Common interface for all ingestors
- Configurable transformation pipelines

## Project Structure

### Core Files

#### `main.py`
- Purpose: Orchestrate downloads of historical prices to Parquet under `/data/prices`.
- Current universe source: `dim_stock` filtered to active symbols (`is_active IS TRUE`),
  ordered alphabetically by ticker symbol.
  
### Data Sources
- Prices: existing Parquets; broker previous‑close snapshots when configured; yfinance as a fallback for initial fills/tail repairs.
- FRED: ON RRP/TGA, Fed balance sheet/SOMA, and TIPS real yield series.
- Finnhub: earnings calendar (next‑earnings dates).
- Broker service: SOFR futures and derived FRA–OIS spreads.

> Note: universe selection is now centralized via `dim_stock` so that ingestion remains
> aligned with the active ticker set managed by upstream processes.

### Technical Indicators (new)
After parquet prices are present, the scorer computes daily technical indicators and stores them in Postgres:

- Table: `fact_technical_indicator (date_key, stock_key, indicator_code, value)` with upsert semantics
- View: `vw_latest_technicals` – pivoted snapshot for easy consumption by API/clients
- Indicators included:
  - SMA20/50/200, EMA12/26, RSI14 (Wilder), ATR14
  - Bollinger Bands (20, 2σ): BB_UPPER, BB_MIDDLE, BB_LOWER
  - MACD (12,26,9): MACD, MACD_SIGNAL, MACD_HIST
  - Rolling returns: RET_5D, 20D, 60D, 120D
  - VOL_Z20 (z-score), DIST_52W_HIGH (%)

These are available via the API:
  - `GET /api/v1/technicals/latest?symbol=SYM`
  - `GET /api/v1/technicals/series?symbol=SYM&indicators=SMA20,RSI14&days=120`

1. Create module in `src/sources/`
2. Implement common interface
3. Add configuration options
4. Write validation schemas
5. Create unit tests
6. Document API requirements

**FRA/OIS Pricer**
- Location: `apps/ingestion/src/fra_ois_pricer.py`.
- Purpose: lightweight SOFR OIS curve bootstrap and FRA/OIS checks.
  - Builds an OIS discount curve from par quotes (annual fixed by default).
  - Computes FRA forward for `XxY` windows and PV at par or a supplied strike.
  - Prices receiver‑fixed OIS and prints par rates.
  - If a market FRA quote is supplied, prints FRA–OIS spread `(K − F)` in bp.

- Usage examples:
  - FRA 3x6 with market quote and spread: `python apps/ingestion/src/fra_ois_pricer.py --as-of 2025-11-12 --fra 3x6 --fra-quote 0.0450 --ois "1Y=0.0475,2Y=0.0440,3Y=0.0425,5Y=0.0410"`
  - OIS par and PV: `python apps/ingestion/src/fra_ois_pricer.py --ois "1Y=0.0475,2Y=0.0440" --ois-price 2Y --fixed 0.0460 --notional 10000000`

- OIS bootstrap requirements:
  - The curve must have at least one positive‑time pillar before querying `D(t)` for `t>0`.
  - With annual fixed coupons (`--fixed-freq 12`), the first OIS quote should align with the coupon schedule or include earlier tenors.
    - Example: a first quote of `2Y` needs `D(1Y)` for the intermediate coupon; provide a `1Y` quote, or set `--fixed-freq 24`.
  - The pricer raises a clear error if the first schedule requires earlier discount factors that do not exist yet.

- Conventions:
  - Day count: ACT/360. Fixed‑leg frequency: annual by default (`--fixed-freq 12`).
  - FRA times use actual dates from `--as-of` via ACT/360 (not months/12).
  - FRA–OIS spread is `(strike − OIS‑implied forward)` in basis points.

- FRED API key:
  - Set `FRED_API_KEY` in `env/<ENV>/ingestion.env` (e.g., `env/local/ingestion.env`).
    - Docker Compose: ingestion reads it via `env_file` automatically.
    - Local runs: set `RANKALPHA_ENV=<profile>` so the pricer autoloads `env/<ENV>/*.env`, or `export FRED_API_KEY=...`.
- SOFR futures + FRA–OIS (optional)
  - If `BROKER_SERVICE_URL` is configured (e.g., `http://broker:8000`) and `BROKER_SERVICE_TOKEN` is set, the ingestion run calls the Broker endpoint `GET /rates/sofr-futures` to fetch SR1 (monthly) and SR3 (quarterly) SOFR futures, stores them in `rankalpha.fact_sofr_futures`, builds a SOFR‑based OIS curve, derives market FRA for `3x6`, `6x9`, and `9x12`, and upserts FRA–OIS rows in `rankalpha.fact_fra_ois`.
  - Migrations for these tables live in `docker/database/sql/migrations/V97__sofr_futures_and_fra.sql`.
  - Requires IBKR market data entitlements for CME SOFR.
  - **One-off backfill:** `apps/ingestion/src/fra_ois_backfill.py` pulls SOFR futures *history* from the Broker endpoint `GET /rates/sofr-futures/history` (SR1 + SR3, up to 2y lookback), rebuilds daily OIS curves, derives FRA–OIS for selected windows, and upserts into `fact_fra_ois` (optionally `fact_sofr_futures`). Example:

    ```bash
    cd apps/ingestion
    uv run python src/fra_ois_backfill.py \
      --start-date 2023-01-01 --end-date 2025-12-01 \
      --fra-window 3x6 --fra-window 6x9 --fra-window 9x12 \
      --include-sofr-futures
    ```
