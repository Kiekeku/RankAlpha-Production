# RankAlpha API Service

## Purpose
The API service provides a RESTful interface for the RankAlpha platform, serving as the primary backend for the frontend application and external integrations. It exposes endpoints for stock grading, signal analysis, backtesting, pipeline monitoring, and data refresh operations.

## Architecture Overview (Where grades live)
- Grades are computed in the database, not in the API.
  - The scorer app writes raw factor scores (e.g., momentum, value, sentiment) to `fact_score_history`.
  - The scorer also computes model combination weights monthly (hybrid IC + risk‑parity) and upserts to `rankalpha.dim_model_weight`.
  - The database materialized view `rankalpha.mv_latest_grades` combines factors using the latest weights, requires Momentum and Value (Sentiment optional, re‑normalized), and maps the composite to [1..100] and A–F.
- The API reads these grades and weights and serves them; it does not re‑compute grades.
- The frontend renders the API results (Overview KPIs, Rankings, and an About page with current weights & pipeline status).

Quick links
- Weights: `GET /api/v1/grading/weights`
- Grades listing: `GET /api/v1/grading/grades` (supports `tracked_only=true` to require Momentum & Value)
- Nowcast (DB snapshot + deltas): `GET /api/v1/nowcast/latest` (pillars + Δ1d/Δ5d; source-of-truth is Postgres snapshots)
- HY stress: `GET /api/v1/hy-stress/latest` (or `/series` for history)
- FRA–OIS: `GET /api/v1/fra-ois/latest` (or `/series` for history)
- Liquidity (ON RRP & TGA): `GET /api/v1/macro/liquidity/latest` (regime + latest levels/deltas) and `/liquidity/series?series=on_rrp|tga`
- Net Liquidity (WALCL − TGA − RRP): `GET /api/v1/macro/liquidity/net-liquidity/latest` and `/liquidity/net-liquidity/series`
- Fed balance sheet (FRED): `GET /api/v1/macro/fed-balance-sheet/latest` (WALCL/WSHOSHO/TREAST/MBST; WSHOSHO is a SOMA proxy) and `/fed-balance-sheet/series?series=walcl|wshosho|treast|mbst`
- Put/Call ratios (CBOE, context): `GET /api/v1/macro/put-call/latest` and `/put-call/series?series=equity|spx|total|index`
- Treasury curve (constant maturity): `GET /api/v1/rates/treasury/latest` and `/api/v1/rates/treasury/series?tenor=10Y`
- FX rates (context): `GET /api/v1/fx/latest?pairs=USDJPY,CNYUSD` and `/api/v1/fx/series?pair=CNYUSD` (the dashboard may display **USDCNY** as the inverse of stored `CNYUSD`; API also accepts `CNHUSD` as an alias when the DB stores onshore CNY).
- USDX / DXY signals & regime: `GET /api/v1/macro/dxy/latest` and `/dxy/series?series=level|ma50|ma100|ma200|roc_1m|roc_3m|roc_6m|z_3y|pctl_5y|regime_state|shock_up_flag|shock_down_flag|risk_score`
- Money Flow (price × volume rotation):
  - `GET /api/v1/money-flow/sectors` – sector snapshot (equities only; labels include SPDR sector ETF proxy)
  - `GET /api/v1/money-flow/sectors/series?days=90` – sector money-flow time series (trailing trading days; long-form by date×sector)
  - `GET /api/v1/money-flow/sectors/{sector}` – per-stock money-flow scores within a sector (latest date)
- News suggestions (admin/service token):
  - `POST /api/v1/news/suggestions` – submit or replay partner news items (idempotent); returns queue status.
  - `GET /api/v1/news/suggestions` / `GET /api/v1/news/suggestions/{id}` – inspect suggestion lifecycle and queue attempts.
  - `POST /api/v1/news/suggestions/dedupe-check` – check for existing raw/events/suggestions before posting.
  - OpenAPI snippet: `apps/api/docs/news_suggestions.openapi.yaml`
- Trading ingestion: `POST /api/v1/trading/signals` (Bearer token required)
  - OpenAPI snippet: `apps/api/docs/trading_recommendations.openapi.yaml`
- Rank Regime (Momentum↔Value):
  - `GET /api/v1/signals/rank-regime` – latest daily factor‑rotation snapshot with FRI_z, breadth, hazards, tenure, label, and confidence.
  - `GET /api/v1/signals/rank-regime/history?days=252` – recent history for charting.
  - Smoothing note: flows are smoothed with a 10‑day simple moving average (SMA), not EMA. SMA is intentionally slower/lagging than EMA for added stability; downstream z‑scores and labels reflect the SMA‑smoothed series.
- Vol Regime (VIX term structure + VRP):
  - `GET /api/v1/vol-regime` – latest VIX curve snapshot (`SPX/VIX` by default) from `vw_vix_term_structure_latest`, including levels, slopes/ratios, contango/backwardation flags, regime label, and `risk_flag`, plus SPX/VIX variance risk premium fields (`rv_30d_var`, `iv_30d_var`, `vrp_30d`, `vrp_regime`, `vrp_state`, `vol_state`). `rv_30d_var` uses a 21-trading-day rolling sum of daily Rogers–Satchell variance from SPX OHLC.
- Breadth (derived indicators):
  - `GET /api/v1/breadth/latest` – latest derived breadth signals for NYSE (Hindenburg/HLLI) and SPX/NDX (Whaley ADT‑5, Deemer BAM10 up/down, McClellan thrust/breakdown, persistent new lows, %>200d thrust/collapse, TRIN stress, A/D bearish divergence). Returns a single `as_of_date` plus per‑universe fields.
  - `GET /api/v1/breadth/series?universe=SPX&indicator=whaley&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` – time series for one indicator/universe with pagination. Universes: `SPX`, `NDX`, `NYSE`. Indicators: `hindenburg_raw`, `hindenburg_confirmed`, `hlli`, `net_new_highs`, `whaley`, `whaley_bull`, `whaley_capitulation`, `bam_up`, `bam_down`, `mcclellan_thrust`, `mcclellan_sum_breakdown`, `persistent_new_lows`, `pct_above_200d_thrust`, `pct_below_200d_collapse`, `trin_stress`, `ad_bearish_divergence`, plus regime outputs `thrust_score`, `frag_score`, `net_score`, `regime_state`, `regime_label`, `target_exposure`.
- Caching knobs (Redis HTTP cache middleware):
  - Macro/dashboard endpoints are cached by path via `apps/api/src/http_cache.py`; tune via `apps/api/src/settings.py` (env vars) including `cache_ttl_macro`, `cache_ttl_benchmarks`, `cache_ttl_rates`, `cache_ttl_fx`, and `cache_ttl_prices_history`.
  - The middleware varies cache keys by `Authorization`/`Cookie`/`X-API-Key` (hashed) so authenticated responses do not leak to anonymous callers.
- Caching behavior (key endpoints):
  - `GET /api/v1/grading/asset/{symbol}` caches per `(symbol,days)` using `CACHE_TTL_STOCK_DETAIL` (and is also cached by the HTTP cache middleware).
  - `GET /api/v1/prices/history` uses a per-symbol Redis “price history” cache (`PriceHistoryCache`) which is warmed by `POST /api/v1/admin/prices/cache-refresh` (and by the Airflow pipeline).
  - `GET /api/v1/prices/live/{symbol}`:
    - Anonymous callers never fan out to the broker/IBKR; they receive an EOD close snapshot when available (otherwise `401`).
    - Authenticated/internal callers may fetch realtime quotes via the broker service; results are cached in Redis for `BROKER_PRICE_CACHE_SECONDS` (default `90`) and keyed per `(symbol,account,exchange)` and auth identity (via the HTTP cache middleware).
- Admin (not linked in UI):
  - `POST /api/v1/admin/weights/recompute` – force next scorer run to recompute weights for the month
  - `POST /api/v1/grading/refresh` – operator refresh; refreshes `mv_universe_eligible` then `mv_latest_grades`, and invalidates grade-related caches
  - `POST /api/v1/admin/grades/refresh` – admin refresh; same behavior as above, behind admin guard
  - `GET /api/v1/admin/budget` – Redis-backed AI/search budget snapshot (per service)
  - `POST /api/v1/admin/budget/reset` – reset today’s token/cost counters and/or RPM for selected services

## Hardening & Exposure Settings

These settings are defined in `apps/api/src/settings.py` and read from `env/<ENV>/api.env` (plus `env/<ENV>/shared.env`).

- **Docs / schema**
  - `API_DOCS_ENABLED` (default `false`): enable Swagger UI at `GET /` when true.
  - `API_OPENAPI_ENABLED` (default `false`): enable OpenAPI schema at `GET /openapi.json` when true.
  - Note: Swagger depends on OpenAPI. If `API_DOCS_ENABLED=true` and `API_OPENAPI_ENABLED=false`, the API will still expose `/openapi.json`.
- **Internal auto-CRUD (`/internal/*`)**
  - `API_INTERNAL_CRUD_ENABLED` (default `false`): mount auto-generated CRUD under `/internal/<table>/...`.
  - `API_INTERNAL_CRUD_INCLUDE_IN_SCHEMA` (default `false`): include `/internal/*` routes in OpenAPI (recommended `false`).
  - `API_READ_ONLY` (default `false`): if `true`, auto-generated CRUD becomes GET-only (POST/PUT/DELETE removed). This does not affect domain routers like `/api/v1/trading/*`.
  - All `/internal/*` routes still require operator/admin/service token auth.
- **Middleware toggles**
  - `HTTP_CACHE_ENABLED` (default `true`): enable the Redis-backed GET cache middleware (`apps/api/src/http_cache.py`).
  - `SECURITY_HEADERS_ENABLED` (default `true`): add baseline security headers (nosniff, frame deny, etc.).
- **DoS / resource guards**
  - `AI_PREVIEW_MAX_SYMBOLS` (default `200`): cap symbols accepted by `GET /api/v1/ai-analysis/preview`.
  - `BACKTEST_MAX_RANGE_DAYS` (default `1825`): cap date span for `POST /api/v1/backtest/*`.
  - `BACKTEST_MAX_REBALANCE_POINTS` (default `1000`): cap rebalance iterations for backtest requests.
  - `PRICES_LIVE_PREFETCH_MAX_TASKS` (default `250`): cap in-memory background prefetch tasks for `GET /api/v1/prices/live/{symbol}`.
- **Prices cache performance**
  - `PRICE_HISTORY_CACHE_HEAD_ITEMS` (default `800`): when warming the per-symbol history cache, also store a truncated "recent history" key used by `GET /api/v1/prices/history` for common `skip/limit` and recent `date_from` queries (set `0` to disable).
- **CORS safety**
  - The API refuses to start if `CORS_ALLOW_CREDENTIALS=true` and `CORS_ORIGINS` contains `"*"`, because browsers disallow that combination.

## Authentication & RBAC

- **Anonymous read access remains:** all public routers (grading, prices, screener, etc.) stay open. The frontend only attaches a bearer token when a user signs in with Google via NextAuth.
- **Shared JWT secret:** set `NEXTAUTH_SECRET` in both API and frontend environments. The frontend signs session JWTs; the API verifies them for optional role-aware access (`apps/api/src/security/dependencies.py`).
- **Service bridge token:** `AUTH_SERVICE_TOKEN` authorises trusted server-to-server calls (e.g. the frontend syncing user profiles through `/api/v1/auth/sync`). You may reuse `ADMIN_BEARER_TOKEN`, but keeping them distinct lets you revoke automation separately.
- **Admin guard:** `/api/v1/admin/*`, `/api/v1/ops/*`, the new `/api/v1/auth/users*`, and trading routes accept either an admin-role JWT, `ADMIN_BEARER_TOKEN`, or `AUTH_SERVICE_TOKEN` (prefer setting in `env/<env>/shared.env`; `api.env` can override).
- **RBAC storage:** migration `V84__auth_role_based_access.sql` introduces `rankalpha.auth_user`, `auth_role`, and `auth_user_role`. New Google logins are auto-created with `AUTH_DEFAULT_ROLE` (defaults to `viewer`). Manage assignments through `/api/v1/auth/users` (admin-only) or direct SQL (examples below).
- **Endpoints:**
  - `POST /api/v1/auth/sync` – internal endpoint used by NextAuth to upsert users (requires service token)
  - `GET /api/v1/auth/me` – return the authenticated profile (requires session JWT)
  - `GET /api/v1/auth/users` / `GET /api/v1/auth/users/{id}` – list or fetch users (admin/service token)
  - `PUT /api/v1/auth/users/{id}/roles` – replace role assignments (admin/service token)
  - `GET /api/v1/vol-regime` – public; returns latest VIX term structure/regime snapshot from `vw_vix_term_structure_latest` (default underlying `SPX/VIX`; optional `underlying_symbol` query param)

> ⚠️ Remember to apply migration **V84** before enabling OAuth in environments other than local development.

### Direct SQL assignments

Use these tables when you need to seed or adjust roles outside the API:

```sql
-- Add a custom role if needed
INSERT INTO rankalpha.auth_role (role_name, description)
VALUES ('research', 'Read-only access to AI research dashboards')
ON CONFLICT (role_name) DO NOTHING;

-- Create a user (normally populated by /api/v1/auth/sync)
INSERT INTO rankalpha.auth_user (email, full_name)
VALUES ('analyst@example.com', 'Sample Analyst')
ON CONFLICT (email) DO NOTHING;

-- Assign roles to an existing user
WITH u AS (
  SELECT user_id FROM rankalpha.auth_user WHERE email = 'analyst@example.com'
), r AS (
  SELECT role_id FROM rankalpha.auth_role WHERE role_name = 'analyst'
)
INSERT INTO rankalpha.auth_user_role (user_id, role_id, assigned_by)
SELECT u.user_id, r.role_id, NULL
FROM u CROSS JOIN r
ON CONFLICT (user_id, role_id) DO NOTHING;

-- Inspect current assignments
SELECT * FROM rankalpha.vw_auth_user_roles ORDER BY email, role_name;
```

## Technologies & Tools

### Core Framework
- **FastAPI**: Modern, high-performance Python web framework with automatic OpenAPI documentation
- **Pydantic**: Data validation and settings management using Python type annotations
- **Uvicorn**: Lightning-fast ASGI server for production deployment

### Database & ORM
- **SQLAlchemy 2.0**: SQL toolkit and ORM for database operations
- **PostgreSQL**: Primary database (via psycopg2-binary)
- **Database Partitioning**: Leverages PostgreSQL table partitions for performance

### Additional Libraries
- **NumPy**: Numerical computing for financial calculations
- **Python-multipart**: Form data parsing support

## Observability
- The API auto-instruments with OpenTelemetry and Prometheus. Exported metrics include request counters, in-flight gauges, latency histograms, and error totals exposed at `GET /metrics`.
- Endpoint/scrape metrics are exported as `rankalpha_api_endpoint_requests_total{handler,method}` and `rankalpha_api_endpoint_requests_by_client_total{handler,method,client_class}` (`client_class=bot|browser|other|unknown`).
- API logging can run through an async queue listener (`API_ASYNC_LOGGING_ENABLED=true`, `API_ASYNC_LOGGING_QUEUE_MAXSIZE=10000` by default) to reduce request-thread logging overhead under load while keeping queue growth bounded.
- Compose sets `OTEL_EXPORTER_OTLP_ENDPOINT` to the shared collector (`otel-collector`). Override it (and optional `OTEL_SERVICE_NAME`) via `api.env`.
- Traces flow to Grafana Tempo; dashboards in Grafana (datasource: `prometheus`) cover request throughput/latency. See `docs/observability.md` for wiring, dashboards, and alerting.

## Design Principles

### 1. **RESTful Architecture**
- Resource-based URLs following REST conventions
- Standard HTTP methods (GET, POST, PUT, DELETE)
- JSON request/response format
- Consistent error handling and status codes

### 2. **Modular Router Design**
- Domain-specific routers for logical separation
- Each router handles a specific business domain
- Shared database session management via dependency injection

### 3. **Auto-Generated CRUD Operations**
- `router_factory.py` automatically generates CRUD endpoints from SQLAlchemy models
- Reduces boilerplate code and ensures consistency
- Supports pagination, filtering, and sorting out of the box

### 4. **Type Safety & Validation**
- Pydantic models for request/response schemas
- Automatic request validation and serialization
- Type hints throughout for better IDE support and runtime validation

### 5. **Database Connection Pooling**
- Efficient connection management via SQLAlchemy
- Session-per-request pattern with automatic cleanup
- Transaction support with proper rollback handling

## Project Structure

### Core Files

#### `main.py`
- FastAPI application initialization
- CORS configuration for frontend integration
- Router registration and mounting
- Automatic OpenAPI documentation setup
- Health check endpoints

#### `database.py`
- SQLAlchemy engine and session configuration
- Database connection management
- Session factory with dependency injection support

#### `schemas.py`
- Pydantic models for API request/response validation
- Data transfer objects (DTOs) for API contracts
- Complex type definitions for financial data structures

#### `router_factory.py`
- Generic CRUD endpoint generator
- Automatic pagination, filtering, and sorting
- Model-to-schema mapping
- Error handling and validation

### Routers Directory (`routers/`)

#### `grading.py`
- **Purpose**: Stock grading and ranking endpoints
- **Key Endpoints**:
  - `GET /grades`: Retrieve stock leaderboard with A-F grades
  - `GET /grades/{symbol}`: Individual stock grade details
  - `GET /asset/{symbol}`: Comprehensive asset analysis
  - `GET /weights`: Current model weights (hybrid IC + risk‑parity)
- **Features**: Grade calculation, percentile rankings, sector comparisons
  - Scoring methodology: see docs/SCORING.md for Value/Momentum/Grade definitions

#### `signals.py`
- **Purpose**: Trading signal analysis and comparison
- **Key Endpoints**:
  - `GET /leaderboard`: Signal strength rankings
  - `GET /compare`: Multi-signal comparison
  - `GET /historical/{symbol}`: Historical signal data
- **Features**: Signal aggregation, trend analysis, performance metrics

#### `backtest.py`
- **Purpose**: Strategy backtesting and performance analysis
- **Key Endpoints**:
  - `POST /quick`: Fast strategy testing with basic metrics
  - `POST /full`: Comprehensive backtesting with detailed analytics
  - `GET /strategies`: Available strategy configurations
- **Features**: Risk metrics, Sharpe ratio, maximum drawdown calculations

#### `pipeline.py`
- **Purpose**: Data pipeline monitoring and management
- **Key Endpoints**:
  - `GET /health`: Overall system health status
  - `GET /status/{component}`: Component-specific health checks
  - `GET /data-quality`: Data completeness and quality metrics
- **Features**: Real-time monitoring, error tracking, performance metrics

#### `admin.py`
- **Purpose**: Operational endpoints for admins and schedulers
- **Key Endpoints**:
  - `POST /api/v1/admin/weights/recompute`: Set/clear a force‑recompute flag for scorer weights
  - `POST /api/v1/grading/refresh`: Operator refresh of universe + latest grades; invalidates caches (GET is deprecated)
  - `POST /api/v1/admin/grades/refresh`: Admin refresh of latest grades (same behavior as grading refresh; behind admin guard)
  - `POST /api/v1/admin/ai-analysis/refresh`: Refresh AI scenario proximity MV and invalidate related caches
  - `POST /api/v1/admin/prices/cache-refresh`: Warm Redis price history caches for the provided (or active) symbols
  - `POST /api/v1/admin/ai-analysis/cache-refresh`: Invalidate + warm AI analysis caches for symbols and/or specific analysis IDs
  - `GET /api/v1/admin/budget`: Redis-backed budget snapshot for guardrails
  - `POST /api/v1/admin/budget/reset`: Reset counters for today (tokens, cost) and/or RPM

#### `news_ingest.py`
- **Purpose**: Partner-facing news suggestion intake and queue visibility
- **Key Endpoints**:
  - `POST /api/v1/news/suggestions`: Submit or replay suggestions (idempotent per source/idempotency key) and set queue priority/run-after.
  - `GET /api/v1/news/suggestions` / `GET /api/v1/news/suggestions/{id}`: Inspect suggestion lifecycle, queue attempts, and linked events/clusters.
  - `PUT /api/v1/news/suggestions/{id}`: Update snippet/body/status metadata.
  - `POST /api/v1/news/suggestions/dedupe-check`: Preflight duplicates against stored raw/events/suggestions.
- **Notes**: Requires admin bearer token or service token. Successful submissions enqueue work in `rankalpha.news_ingest_queue` processed by the Newswire worker.

#### `ops.py`
- **Purpose**: Operational endpoints
- **Key Endpoints**:
  - `POST /api/v1/ops/email`: Admin-protected email send via shared SMTP/Gmail config
-  - `GET /api/v1/admin/budget`: Redis-backed budget snapshot for guardrails
-  - `POST /api/v1/admin/budget/reset`: Reset counters for today (tokens, cost) and/or RPM
- `GET /api/v1/admin/activity`: Anchor‑based market activity overview used by the admin UI
- **Notes**: Not exposed in the UI; protect with `ADMIN_BEARER_TOKEN` and/or upstream auth.

#### `hy_stress.py`
- **Purpose**: Expose high‑yield stress metrics (raw OAS, 10‑day MA, 750‑day z‑score) sourced from the CCC HY OAS benchmark.
- **Key Endpoints**:
  - `GET /api/v1/hy-stress/latest?benchmark_name=%25CCCHYS` – latest snapshot with a qualitative label (`risk_on`, `neutral`, `risk_off`).
  - `GET /api/v1/hy-stress/series?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&benchmark_name=%25CCCHYS&sort_order=asc&limit=1000&skip=0` – paged history with labels.

#### `fra_ois.py`
- **Purpose**: Serve FRA–OIS spreads derived from SOFR futures (ingestion step) plus a rolling funding‑stress regime label.
- **Key Endpoints**:
  - `GET /api/v1/fra-ois/latest?fra_source=SR3&start_months=3&end_months=6` – latest rows per tenor/source (defaults to SR3; omit tenor params to return all latest rows) returning `fra_rate`, `ois_forward`, `spread_bp`, `fra_ois_z`, and `regime` (`easy`, `normal`, `stressed`, `crisis`).

#### `macro.py`
- **Purpose**: Expose macro liquidity series captured from FRED (ON RRP usage, Treasury General Account balance, Net Liquidity, and selected Fed balance sheet/SOMA proxy series) and derived USDX/DXY regime signals.
- **Key Endpoints**:
  - `GET /api/v1/macro/liquidity/latest` – latest ON RRP (`US_ON_RRP`) and TGA (`US_TGA_BAL`) values with shared `as_of_date`, level deltas vs prior observation, and a derived liquidity regime:
    - `Amplified Easing`: RRP > 300B, ΔRRP < 0, ΔTGA <= 0
    - `Neutral / Cushioning Phase`: 100B < RRP <= 300B
    - `Reserve Drain / Tightening`: RRP <= 100B and ΔTGA > 0
    - `Liquidity Inflection / Easing`: RRP <= 100B and ΔTGA < 0
  - Returns convenience fields in both millions (`rrp_change_mn`, `tga_change_mn`) and billions (`rrp_value_bil`, `tga_value_bil`).
  - `GET /api/v1/macro/liquidity/series?series=on_rrp|tga&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&sort_order=asc|desc&limit=1000&skip=0` – paged time series for one liquidity stream.
  - `GET /api/v1/macro/liquidity/net-liquidity/latest` – Net Liquidity snapshot anchored to WALCL observation dates:
    - Definition (levels): `net_liquidity = WALCL − TGA − ON_RRP` (all in millions USD)
    - Returns `delta_4w_z` and `delta_13w_z` (z-scores of the 4w/13w changes over the lookback window) plus convenience trillions fields.
  - `GET /api/v1/macro/liquidity/net-liquidity/series?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&sort_order=asc|desc&limit=520&skip=0` – weekly series (WALCL-anchored) with component levels and `net_liquidity_trn`.
  - `GET /api/v1/macro/fed-balance-sheet/latest` – latest weekly Fed balance sheet/wshosho composition series captured from FRED:
    - `walcl` → `US_FED_WALCL` (Total assets)
    - `wshosho` → `US_FED_WSHOSHO` (Securities Held Outright: SOMA proxy)
    - `treast` → `US_FED_TREAST` (SOMA Treasuries held outright)
    - `mbst` → `US_FED_MBST` (SOMA MBS held outright)
  - Returns both raw levels (in millions USD as `value`) and convenience fields in trillions (`*_trn`) plus composition shares (`wshosho_share_of_walcl`, `treast_share_of_wshosho`, `mbst_share_of_wshosho`).
  - `GET /api/v1/macro/fed-balance-sheet/series?series=walcl|wshosho|treast|mbst&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&sort_order=asc|desc&limit=1000&skip=0` – paged history for any Fed balance sheet series above.
  - `GET /api/v1/macro/dxy/latest` – latest values for all DXY-derived series (`US_DXY_LEVEL`, MAs, ROC, z/pctl, regime state, shock flags, risk score) plus a convenience `regime_label` (USD_BULL/USD_BEAR/USD_TRANSITION).
  - `GET /api/v1/macro/dxy/series?series=level|ma50|ma100|ma200|roc_1m|roc_3m|roc_6m|z_3y|pctl_5y|regime_state|shock_up_flag|shock_down_flag|risk_score&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&sort_order=asc|desc&limit=1000&skip=0` – paged history for any DXY feature.
  - `GET /api/v1/macro/put-call/latest` – latest values for CBOE put/call ratios (Total, Equity-only, SPX index options, Index options).
  - `GET /api/v1/macro/put-call/series?series=total|equity|spx|index&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&sort_order=asc|desc&limit=1000&skip=0` – paged history for any put/call ratio.
  - `GET /api/v1/fra-ois/series?fra_source=SR3&start_months=3&end_months=6&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&sort_order=asc&limit=500&skip=0` – paged time series with optional date/tenor filters; includes z-score and regime label on each row.

#### `rates.py`
- **Purpose**: Expose US Treasury constant-maturity yields (1Y/2Y/5Y/10Y/20Y) used for curve context and regime dashboards.
- **Key Endpoints**:
  - `GET /api/v1/rates/treasury/latest?tenors=1Y,2Y,5Y,10Y,20Y` – latest rates per tenor plus curve convenience fields (currently `2s10s` slope in pct points and bps).
  - `GET /api/v1/rates/treasury/series?tenor=10Y&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&sort_order=asc|desc&limit=1000&skip=0` – paged history for one tenor.
- **DB lineage**:
  - `rankalpha.vw_risk_free_rate` (tenor_label, rate_pct, rate_date)

#### `fx.py`
- **Purpose**: Expose spot FX mid rates used as peripheral context for the macro dashboard (e.g., USDJPY, CNHUSD).
- **Key Endpoints**:
  - `GET /api/v1/fx/latest?pairs=USDJPY,CNHUSD` – latest mid rate per requested FX pair.
  - `GET /api/v1/fx/series?pair=USDJPY&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&sort_order=asc|desc&limit=1000&skip=0` – paged history for one FX pair.
- **DB lineage**:
  - `rankalpha.fact_fx_rate` joined to `rankalpha.dim_date` (fields: `from_ccy`, `to_ccy`, `mid_px`)

## Operations: Refresh Endpoints (Examples)

Refresh universe + latest grades (requires operator access via `AUTH_SERVICE_TOKEN` / `ADMIN_BEARER_TOKEN`):

```bash
curl -fsS -X POST \
  -H "X-RA-Service-Token: ${AUTH_SERVICE_TOKEN}" \
  "http://localhost:6080/api/v1/grading/refresh"
```

Admin: refresh grades (same behavior; behind ADMIN_BEARER_TOKEN):

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer ${ADMIN_BEARER_TOKEN}" \
  "http://localhost:6080/api/v1/admin/grades/refresh"
```

Admin: refresh AI scenario proximity MV + invalidate related caches:

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer ${ADMIN_BEARER_TOKEN}" \
  "http://localhost:6080/api/v1/admin/ai-analysis/refresh"
```

Admin: warm price history cache for all active symbols (chunked automatically):

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer ${ADMIN_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"reason":"manual","force":true}' \
  "http://localhost:6080/api/v1/admin/prices/cache-refresh"
```

Admin: invalidate + warm AI analysis cache for selected symbols:

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer ${ADMIN_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"symbols":["AAPL","MSFT"],"include_proximity":true,"reason":"manual"}' \
  "http://localhost:6080/api/v1/admin/ai-analysis/cache-refresh"
```

#### `trading.py`
- **Purpose**: Authenticated ingestion of external trade recommendations
- **Key Endpoint**:
  - `POST /api/v1/trading/signals`: Upsert a trade recommendation (requires Bearer token)
- **Auth**: Requests must include `Authorization: Bearer ${TRADING_BEARER_TOKEN}`. If the token is unset, the route responds with `503 Trading ingestion disabled`.
- **Payload**:
  - Required: `symbol`, `action`, `as_of_date` (`YYYY-MM-DD`), `recommended_price`.
    - `action` must be one of `BUY`, `SELL`, `SHORT`, `COVER` (same enum enforced in Postgres and the scorer).
  - Optional execution data: `order_type`, `time_in_force`, `limit_price`, `stop_trigger_price`, `stop_loss_price`, `take_profit_price`, `valid_from_ts`, `expiry_ts`.
    - `order_type` is stored verbatim (upper‑cased). Downstream automation currently recognises `MARKET` (default), `LIMIT`, `STOP`, and `STOP_LIMIT`. Reach out before introducing exotic types so dashboards/OMS integrations stay in sync.
    - Use `stop_trigger_price` to represent stop or stop‑limit entry triggers.
    - Use `stop_loss_price` / `take_profit_price` to publish risk exits and profit targets for monitoring; they don’t auto‑place orders but are persisted for analytics/UI.
  - Optional sizing metadata: `size_shares`, `size_percent`, `risk_budget_bps`.
  - Context & lineage: `source_name`, `source_version`, `strategy_name`, `signal_version`, `model_run_id`, `portfolio_id`, `routing_hint`, `preconditions` (JSON object), `auto_hedge`.
- **Sample request**:
  ```bash
  curl -X POST http://localhost:6080/api/v1/trading/signals \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${TRADING_BEARER_TOKEN}" \
    -d '{
      "symbol": "AAPL",
      "action": "BUY",
      "as_of_date": "2025-10-07",
      "recommended_price": "182.45",
      "order_type": "LIMIT",
      "limit_price": "182.55",
      "time_in_force": "DAY",
      "stop_loss_price": "175.00",
      "take_profit_price": "195.00",
      "size_percent": "2.5",
      "source_name": "Quant-Signal-01",
      "strategy_name": "Breakout-Oct",
      "portfolio_id": "5e1f79a2-4c64-4d65-b3d0-07f9c9c35321",
      "preconditions": {"max_bid_ask_spread_bps": 8}
    }'
  ```
- **Sample response**:
  ```json
  {
    "recommendation_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "status": "accepted"
  }
  ```

#### `prices.py`
- **Purpose**: Price history endpoints backed by read‑only views
- **Key Endpoints**:
  - `GET /api/v1/prices/history?symbol=SYM&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`
  - `GET /api/v1/prices/latest?symbol=SYM` (list/latest Adj Close)
- `GET /api/v1/prices/live/{symbol}` – live snapshot via the broker service (`BROKER_SERVICE_URL` must be set)
  - Realtime broker fan-out is restricted to authenticated users; anonymous callers receive an EOD close snapshot when available.
  - Live price troubleshooting:
    - In Docker Compose, set `BROKER_SERVICE_URL=http://broker:8000` in `env/<ENV>/api.env`, set `BROKER_SERVICE_TOKEN=<change_me>` in `env/<ENV>/shared.env`, and ensure the `broker` service is up (`docker compose ps broker`).
    - This repo’s compose now sets `api.depends_on.broker.condition=service_healthy` to help startup order, but you still need the broker container running.
    - When running the API outside Compose, set `BROKER_SERVICE_URL=http://localhost:8000`, set `BROKER_SERVICE_TOKEN=<change_me>`, and start the broker locally: `cd apps/broker && uv venv && uv sync --locked && uv run uvicorn tradeexec.service:app --reload --port 8000`.

#### `technicals.py`
- **Purpose**: Technical indicators (snapshot + series)
- **Key Endpoints**:
  - `GET /api/v1/technicals/latest?symbol=SYM` – from `vw_latest_technicals`
  - `GET /api/v1/technicals/series?symbol=SYM&indicators=SMA20,RSI14&days=120` – from `fact_technical_indicator`

#### `screener.py`
- **Purpose**: Latest‑day consensus, change events, and breadth
- **Key Endpoints**:
  - `GET /api/v1/screener/consensus`
  - `GET /api/v1/screener/changes`
  - `GET /api/v1/screener/breadth`

#### `ai_analysis.py`
- **Purpose**: Serve denormalized AI analyses with optional scenario proximity
- **Key Endpoints**:
  - `GET /api/v1/ai-analysis` – paginated list (optionally one latest per symbol)
  - `GET /api/v1/ai-analysis/latest` – latest rows with optional proximity attachment
  - `GET /api/v1/ai-analysis/{symbol}` and `/id/{analysis_id}` – detail lookups

## API Patterns & Best Practices

### Error Handling
```python
- HTTPException for client errors (4xx)
- Detailed error messages with proper status codes
- Structured error responses with error codes and descriptions
```

### Pagination
```python
- Limit/offset based pagination
- Default limits to prevent overwhelming responses
- Total count included in paginated responses
```

### Database Sessions
```python
- Session per request pattern
- Automatic session cleanup on request completion
- Transaction rollback on errors
```

### Response Models
```python
- Consistent response structure across endpoints
- Nested models for complex data relationships
- Optional fields with sensible defaults
```

## Running the Service

### Local Development
```bash
cd apps/api
uv venv
uv sync --locked

# Set Python path for imports
export PYTHONPATH=../..  # Linux/macOS
$env:PYTHONPATH = '../..'  # PowerShell

# Run with auto-reload
uv run uvicorn src.main:app --reload --port 6080
```

### Docker Deployment
```bash
# From project root
docker compose -f compose/docker-compose.yml up api

## Scoring & Grades Reference
- For the quant definitions of Value, Momentum, and the Final Grade (including weighting), see docs/SCORING.md and docs/architecture.md.
```

### Environment Configuration
- Configuration loaded from `/env/{RANKALPHA_ENV}/api.env`.
- Supports multiple environments (local, localws, production).
- Key variables and conventions:
  - Database (Postgres):
    - `DATABASE_NAME`, `DB_USERNAME`, `PASSWORD`, `HOST`, `DB_PORT`.
    - Do not set `PORT` for the database; it is reserved for the HTTP listener inside the container. Use `DB_PORT`.
    - Compose defaults: `HOST=database`, `DB_PORT=5432` (internal container port).
    - Local API + Compose DB on host: `HOST=localhost`, `DB_PORT=6543` (compose maps 6543→5432 by default).
  - HTTP server:
    - `API_PORT` controls the FastAPI listen port in local dev and Compose.
    - In Docker, `API_PORT` is injected as `PORT` so `uvicorn` binds correctly; you typically do not set `PORT` directly.
  - Hardened runtime:
    - `API_READ_ONLY=true` turns off auto‑generated POST/PUT/DELETE for safety
    - `ADMIN_BEARER_TOKEN=<change_me>` protects `/api/v1/admin/*` routes
    - `TRADING_BEARER_TOKEN=<change_me>` enables + protects `/api/v1/trading/*` ingestion routes (required)
  - Cache (HTTP GET):
    - `CACHE_TTL_DEFAULT` – fallback TTL for GET endpoints not explicitly mapped in the HTTP cache middleware (default 3600s)
    - `CACHE_TTL_RANKINGS` – `/api/v1/grading/grades` and `/api/v1/grading/grades/batch`
    - `CACHE_TTL_STOCK_DETAIL` – `/api/v1/grading/asset/{symbol}`
    - `CACHE_TTL_TOP_PERFORMERS` – `/api/v1/grading/top-performers`
    - `CACHE_TTL_SECTORS` – `/api/v1/grading/sectors`
  - Broker integration:
    - `BROKER_SERVICE_URL` – base URL for the broker FastAPI service (e.g., `http://broker:8000`)
    - `BROKER_SERVICE_TOKEN` – token sent as `X-RA-Service-Token` when calling broker endpoints
    - `BROKER_SERVICE_TIMEOUT_SECONDS` – outbound timeout in seconds when proxying live prices (default 4)
    - `BROKER_LIVE_DOWN_TTL_SECONDS` – cooldown in seconds after broker failures before retrying live price calls (default 30; set 0 to disable)
    - `BROKER_PRICE_CACHE_SECONDS` – Redis TTL for cached live quotes (default 90; set 0 to disable)
  - Redis cache (optional): `REDIS_HOST`, `REDIS_PORT`.
  - Email (shared SMTP for ops and alerts):
    - Preferred: `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_SECURE` (false for 587), `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, `SMTP_TO_ALERTS`
    - Legacy Gmail alias (used if `SMTP_HOST` unset): `GMAIL_SENDER`, `GMAIL_APP_PASSWORD`, `GMAIL_RECIPIENT`
    - Budget alert override recipients: `BUDGET_ALERT_RECIPIENTS` (comma-separated)

## API Documentation

### Interactive Documentation
- Swagger UI: http://localhost:6080/ (root)
- OpenAPI Schema: http://localhost:6080/openapi.json

### Notes on Views
- The API exposes read‑only models for:
  - `vw_ai_analysis_full` – denormalized AI output for easy consumption.
  - `v_latest_screener_consensus` – consensus aggregation across screener styles/sources.

### Authentication
- JWT tokens with Google OAuth integration (planned)
- API key authentication for service-to-service communication
- Rate limiting and request throttling

## Testing

### Unit Tests
```bash
pytest tests/api/
```

### Integration Tests
- Test database connections
- Verify endpoint responses
- Validate data transformations

## Performance Considerations

### Optimizations
- Database query optimization with proper indexing
- Lazy loading for related objects
- Response caching for frequently accessed data
- Connection pooling for database efficiency

### Monitoring
- Request/response logging
- Performance metrics tracking
- Error rate monitoring
- Database query performance analysis

## Future Enhancements

### Planned Features
- WebSocket support for real-time updates
- GraphQL endpoint for flexible queries
- Enhanced caching with Redis integration
- API versioning strategy
- Rate limiting per user/API key
- Webhook support for event notifications

## Dependencies

### Internal
- `common`: Shared models, CRUD operations, and utilities

### External
See `pyproject.toml` for complete dependency list with versions.

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   - Verify PostgreSQL is running
   - Check connection string in environment variables
   - Ensure database migrations have run

2. **Import Errors**
   - Set PYTHONPATH correctly
   - Ensure common package is installed in editable mode

3. **CORS Issues**
   - Verify frontend URL in CORS configuration
   - Check allowed origins in environment variables

## Contributing

- Follow existing code patterns and style
#### `ai_analysis.py`
- Purpose: Serve consolidated AI analysis snapshots from the denormalized view
- Key Endpoints:
  - `GET /api/v1/ai-analysis` – list with filters (symbol, date range, pagination)
  - `GET /api/v1/ai-analysis/{symbol}` – latest for a symbol
  - `GET /api/v1/ai-analysis/id/{analysis_id}` – specific record by UUID

#### `screener.py`
- Purpose: Latest-day screener consensus and change analytics across styles/sources
- Key Endpoints:
  - `GET /api/v1/screener/consensus` – one row per symbol with appearances, styles, and `consensus_score`
  - `GET /api/v1/screener/changes` – lists entered/reentered/dropped events sourced from `fact_screener_rank_change`
  - `GET /api/v1/screener/breadth` – aggregated daily breadth per style from `mv_screener_breadth` (raw counts, percent-of-universe, and 5-day averages). Adds sign-aware fields:
    - `regime_bias`: `'Bullish' | 'Bearish'` (from an authoritative style→bias map with fallback to `position_side`)
    - `net_pct_signed`: `+net_pct` for Bullish styles; `-net_pct` for Bearish
    - `net_pct_avg_5d_signed`: signed 5-day average
    - Recommended aggregate: `sum(net_pct_signed * eligible_count) / sum(eligible_count)`
  - `GET /api/v1/screener/regime-rules/latest` – latest flow-based composites (RS, TT, MRP, ROP, DT, PS, TB) + labels/tags from `fact_regime_rules`
  - `GET /api/v1/screener/regime-rules/series` – paged history of the same composites with optional date filters
 - Market Structure (CVD-style):
   - `GET /api/v1/market-structure/latest` – latest CVD components (Trend, RV20, Corr PC1 share, Dispersion) with z-scores and label.
   - `GET /api/v1/market-structure/series` – historical series with filters and paging.

#### `regime.py`
- Adds `effective_weights` to `GET /api/v1/screener/regime/latest` – per-canonical daily effective regime weights persisted by the scorer:
  - `[ { canonical_name, effective_weight, base_weight, g_factor } ]`
  - Pullback’s `g_factor` reflects the dynamic overlay `tanh(Δ/0.75) − 0.3·max(0, Stress − 0.25)`; others report `g_factor = 1.0`.

#### `technicals.py`
- Purpose: Serve technical indicators computed from ingested OHLCV
- Key Endpoints:
  - `GET /api/v1/technicals/latest?symbol=SYM` – latest snapshot (SMA/EMA/RSI/ATR/MACD/Bollinger/returns, etc.) from `vw_latest_technicals`
  - `GET /api/v1/technicals/series?symbol=SYM&indicators=SMA20,RSI14&days=120` – timeseries of selected indicators from `fact_technical_indicator`
- Add type hints to all functions
- Update OpenAPI schemas when adding endpoints
- Write tests for new functionality
- Document complex business logic
