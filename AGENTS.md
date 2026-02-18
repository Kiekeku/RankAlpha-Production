# Repository Guidelines

## Project Structure & Module Organization
- `apps/ingestion`: Fetches historical prices (yfinance), normalizes columns, and writes Parquet to `/data/prices`.
- `apps/scorer`: Reads Parquet, writes technical/momentum scores to Postgres, and computes/upserts model weights.
- `apps/sentiment`: Multi‑agent AI/sentiment analysis. Writes denormalized AI outputs and sentiment to Postgres; optional consensus batch mode using screener views.
- `apps/api`: FastAPI backend exposing domain routers plus auto-generated CRUD over data models.
- `apps/frontend`: Next.js 14 web UI that consumes the API; runs on port 3000.
- `apps/broker`: Trade execution service (IBKR Web API). Exposes a FastAPI control plane (signals, health) and a per‑account runner that places orders and ingests fills.
- `apps/portfolio`: Portfolio engine (model construction, broker rebalance run generation, NAV/performance sync). Shared engine code lives under `apps/common/src/portfolio/`.
- `infra/airflow/dags/pipeline.py`: Orchestrates ingestion and scorer containers.
- `docker/`: Dockerfiles; DB migrations in `docker/database/sql/migrations`.
- `compose/docker-compose.yml`: Builds and connects services.
- `tests/`: Pytest suite (light but present) covering common settings/models, scorer utils, and sentiment planner.

## Build, Test, and Development Commands
- Environment: Python 3.12; manage deps with `uv` per app.
- Bootstrap a service: `cd apps/<service> && uv venv && uv sync --locked`.
- Run full stack: `docker compose -f compose/docker-compose.yml up --build`.
- Tests (preferred): run with an app venv + `PYTHONPATH=.` so shared `apps.*` imports resolve.
  - Portfolio tests: `PYTHONPATH=. apps/portfolio/.venv/bin/pytest -q tests/portfolio`
  - API tests: `PYTHONPATH=. apps/api/.venv/bin/pytest -q tests/api`
  - Full suite: `PYTHONPATH=. apps/api/.venv/bin/pytest -q tests`
  - If you prefer `uv run`, run from the app directory (example: `cd apps/portfolio && uv run pytest -q ../../tests/portfolio`).

### Service development (local)
- API (FastAPI):
  - `cd apps/api && uv venv && uv sync --locked`
  - Ensure imports resolve: `export PYTHONPATH=../..` (Linux/macOS) or `$env:PYTHONPATH='../..'` (PowerShell)
  - Run: `uv run uvicorn src.main:app --reload --port 6080`
- Newswire:
  - `cd apps/newswire && uv venv && uv sync --locked`
  - Collector loop: `uv run python -m newswire.main`
  - Queue worker: `uv run python -m newswire.queue_worker`
  - Uses `env/<env>/ingestion.env` for shared DB credentials and `env/<env>/newswire.env` for per-service knobs (poll cadence, Serper/OpenAI keys, queue settings).
- Frontend (Next.js):
  - `cd apps/frontend && pnpm install`
  - Ensure backend is reachable: `NEXT_PUBLIC_API_URL=http://localhost:6080`
  - Run: `pnpm dev` (opens http://localhost:3000)
- Broker (TradeExec):
  - `cd apps/broker && uv venv && uv sync --locked`
  - Service API (dev): `uv run uvicorn tradeexec.service:app --reload --port 8000`
  - Runner (single account): `uv run -m tradeexec.trade_execution <ACCOUNT_NUMBER>`
- Portfolio (engine CLI):
  - `cd apps/portfolio && uv venv && uv sync --locked`
  - Ensure imports resolve: `export PYTHONPATH=../..`
  - Commands: `uv run python main.py sync-nav`, `uv run python main.py build-model-run`, `uv run python main.py build-broker-run`

## Coding Style & Naming Conventions
- Style: PEP 8; write small, single-purpose functions with clear docstrings.
- Types: Prefer type hints for public functions and data models.
- Naming: modules `lower_snake_case`; classes `CamelCase`; functions/vars `lower_snake_case`.
- Structure: Keep app services independent; shared backend code lives under `src/`.
- Frontend: Use TypeScript with React; follow Next.js App Router conventions; keep components small and typed.

## Testing Guidelines
- Framework: `pytest`.
- Location & names: place tests in `tests/` and name files `test_*.py`. Prefer per-app folders like `tests/<app>/` (e.g. `tests/portfolio/`) to keep the root from becoming a grab bag.
- Expectations: keep the suite passing; add focused tests when introducing new logic or pipelines.
- Scope: favor fast unit tests; mark slow/integration cases explicitly if added.
- Invocation note: avoid `uv run pytest` from repo root in this workspace. It may resolve `pytest` from a global env instead of the project/app env. Prefer either:
  - `PYTHONPATH=. apps/<service>/.venv/bin/pytest ...` from repo root, or
  - `cd apps/<service> && uv run pytest ...` from that app directory.

Frontend:
- Type checking: `pnpm type-check`.
- Linting: `pnpm lint`.

## Repository layout
- `apps/`
  - `api/` – FastAPI service exposing domain routers and auto‑generated CRUD endpoints over data models.
  - `common/` – shared utilities and data models used across apps.
  - `ingestion/` – downloads historical prices with yfinance and saves them to `/data/prices`.
  - `scorer/` – reads Parquet, writes linear‑regression momentum and factor scores to Postgres, computes hybrid weights (IC + RP), and maintains screener deltas.
  - `sentiment/` – multi‑agent analysis (OpenAI‑driven) writing AI factors, scenarios and sentiment to Postgres.
  - `frontend/` – Next.js application (UI) consuming the API.
  - `portfolio/` – portfolio engine service (CLI + container); core engine logic: `apps/common/src/portfolio/construction.py`.
- `src/` – shared code for other services (no standalone backend container).
- `infra/airflow/` – Airflow DAG (`dags/pipeline.py`) orchestrating the `ingestion` and `scorer` containers.
- `docker/` – Dockerfiles for the backend, Redis cache, and Postgres database. Migrations live in `docker/database/sql/migrations`.
- `compose/` – `docker-compose.yml` that builds and connects all services including Airflow.
- `tests/` – pytest test suite with basic coverage (common, scorer, sentiment, portfolio).
- `docs/PORTFOLIO_CONSTRUCTION.md` – canonical spec/runbook for portfolio construction and approvals.

## Running
- There is no single top-level `main.py`. Run services individually from their app directories or run the full stack with Docker.
- Full stack via Docker Compose:
  ```bash
  docker compose -f compose/docker-compose.yml up --build
  ```
- Local examples (per app), after `uv venv && uv sync --locked` in that app directory:
  - Ingestion: `uv run python src/main.py`
  - Scorer: `uv run python src/main.py`
  - Sentiment: `uv run python src/main.py`
  - API (dev): `uv run uvicorn src.main:app --reload --port 6080` (ensure your `PYTHONPATH` includes the repo root so imports like `apps.common` resolve; running from the project root with `PYTHONPATH=.` is one option.)
  - Frontend (dev): from `apps/frontend`, set `NEXT_PUBLIC_API_URL=http://localhost:6080` and run `pnpm dev`.
  - Portfolio (CLI): `uv run python main.py sync-nav` (see `apps/portfolio/README.md` for schema/config expectations).

### Docker Compose services
- `api`: FastAPI on `6080` (docs at `/`). Auto‑CRUD plus domain routers: grading, signals, screener, prices, technicals, backtest, ai‑analysis, admin.
- `frontend`: Next.js on `3000`, depends on `api` and uses `NEXT_PUBLIC_API_URL=http://api:6080` inside the network.
- `broker`: TradeExec FastAPI on `${BROKER_PORT:-8000}`; endpoints: `/health`, `/signal`, `/accounts`, `/report/{account}`.
- `broker-runner`: Per‑account executor (no HTTP API). Health endpoint at `:${BROKER_RUNNER_HEALTH_PORT:-8795}/health` (published on host via `${BROKER_RUNNER_HEALTH_PORT_HOST:-8795}`).
- `portfolio`: portfolio engine worker (CLI container; runs `sync-nav` by default; can be changed to run engine jobs).
- `database`: PostgreSQL with Flyway migrations via `flyway` service.
- `cache`: Redis for caching.
- `airflow-*`: Orchestrates the pipeline and can trigger frontend refresh via internal hooks.

## Commit & Pull Request Guidelines
- History shows mixed styles; adopt Conventional Commits going forward (e.g., `feat:`, `fix:`, `docs:`, `test:`).
- Messages: imperative subject (≤ 50 chars), optional body explaining what/why; reference issues (e.g., `#123`).
- PRs: include summary, scope of changes, local run/test instructions, and DB migration notes if applicable; ensure `pytest` passes and services build.

## Security & Configuration Tips
- Secrets: never commit credentials; use env vars or Docker secrets.
- When introducing new environment variables or config knobs, also update:
  - the relevant `env/example/*.env.example` (or service-specific `.env.example`),
  - any active profile example if applicable (e.g., `env/local/*.env`), and
  - the most relevant README/docs (service README or `infra/airflow/README.md` for DAG settings).
- Data: ingestion writes to `/data/prices`; mount volumes accordingly when running containers. Ingestion also computes technical indicators and syncs canonical Adj Close/price history into Postgres for API views.
- Database: apply migrations from `docker/database/sql/migrations`; verify schema updates before deploys.
- Airflow: update `infra/airflow/dags/pipeline.py` when adding or reordering pipeline steps.
- CORS: ensure API `allow_origins` includes frontend URLs (e.g., http://localhost:3000). In Docker, the compose file sets frontend’s `NEXT_PUBLIC_API_URL` to `http://api:6080`.

## Notes on API & Frontend Integration
- API docs available at `http://localhost:6080/` (Swagger UI) when running locally.
- Frontend expects `NEXT_PUBLIC_API_URL` to point at the API base URL.
- To generate frontend API types from OpenAPI: `pnpm generate-types` (requires API running at the configured URL).

## Architecture: Scoring, Weights, and Grades (Design Direction)

- Responsibility split (single‑source of truth in DB):
  - Ingestion app
    - Downloads OHLCV via yfinance and writes `/data/prices/<SYMBOL>.parquet`.
    - Enforces canonical Parquet schema before write/update: columns exactly `Open, High, Low, Close, Adj Close, Volume` (floats), DatetimeIndex tz‑naive, sorted/unique. Legacy files are opportunistically rewritten to canonical on refresh even when up‑to‑date.
    - Computes and upserts daily technical indicators into `rankalpha.fact_technical_indicator`; `rankalpha.vw_latest_technicals` provides a pivoted snapshot for API/clients.
    - Syncs canonical Adj Close/OHLCV into `rankalpha.fact_security_price` and adjusts `dim_stock.is_active` based on peer‑date heuristics (configurable via Settings).
  - Scorer app
    - Reads Parquet robustly (prefers `Adj Close`, falls back to `Close`) and writes momentum/linear‑regression metrics into `fact_score_history`; also upserts AI factor scores and fundamentals‑based valuation when available.
    - Maintains screener deltas: refreshes `rankalpha.mv_screener_changes` and `rankalpha.mv_screener_breadth`, persisting new events to `rankalpha.fact_screener_rank_change`.
    - Computes model weights monthly using a Hybrid approach:
      - Predictive leg: Information Coefficient (Spearman rank) between factor exposures and true forward K‑day returns.
      - Diversification leg: risk‑parity (inverse vol) on factor‑mimicking returns.
      - Blends IC and risk‑parity, with shrinkage toward baseline 0.40/0.40/0.20; persists to `rankalpha.dim_model_weight`. A versioned path writes `rankalpha.dim_model_weight_version` + `rankalpha.dim_model_weight_item` rows.
    - Operational toggles:
      - Monthly recompute auto‑skips if the current month exists.
      - Force recompute via env `SCORING_WEIGHT_FORCE=true` or admin flag `admin_flag('force_recompute_weights')` (reset after success).
  - Database layer (materialized view):
    - `rankalpha.mv_latest_grades` builds the final composite using the latest model weights:
      - Requires both Momentum and Value present. Sentiment is optional; weights are re‑normalized over available signals.
      - Maps composite to a 1..100 percentile and letter grade A–F.
    - Weights default to 0.40/0.40/0.20 if no row exists.
    - Related views/tables used by API: `vw_stock_price_history`, `vw_latest_adj_close`, `vw_latest_technicals`, `fact_technical_indicator`, screener consensus/changes/breadth views, AI analysis views (`vw_ai_analysis_full`, `vw_ai_analysis_latest`, `mv_ai_scenario_proximity`).
  - API service
    - Read‑only for grades/weights; reads from DB and adds explanations. Key endpoints (non‑exhaustive):
      - Grading: `GET /api/v1/grading/grades`, `GET /api/v1/grading/weights`, `GET /api/v1/grading/sectors`, `POST /api/v1/grading/refresh` (GET deprecated).
      - Prices: `GET /api/v1/prices/history`, `GET /api/v1/prices/latest`.
      - Technicals: `GET /api/v1/technicals/latest`, `GET /api/v1/technicals/series`.
      - News suggestions: `POST /api/v1/news/suggestions` (idempotent partner submissions), `GET /api/v1/news/suggestions` (admin list/detail), `POST /api/v1/news/suggestions/dedupe-check` (preflight duplicates).
      - Signals: `GET /api/v1/signals/leaderboard`, `GET /api/v1/signals/compare`.
      - Screener: `GET /api/v1/screener/consensus`, `GET /api/v1/screener/changes`, `GET /api/v1/screener/breadth`.
      - AI Analysis: `GET /api/v1/ai-analysis`, `GET /api/v1/ai-analysis/latest`, `GET /api/v1/ai-analysis/{symbol}`, `GET /api/v1/ai-analysis/id/{analysis_id}`.
      - Admin (protect with `ADMIN_BEARER_TOKEN` or upstream): `POST /api/v1/admin/weights/recompute`, `POST /api/v1/admin/grades/refresh`, `POST /api/v1/admin/ai-analysis/refresh`, `GET /api/v1/admin/activity`.
  - Frontend app
    - Renders API data only; no local scoring/weight logic.
    - Overview (Home) focuses on KPIs and rankings; pipeline status moved to the “About” page.
    - About page includes: Current model weights (live), model explanation, and pipeline status/components.

## Operational Notes & Conventions

- Parquet hygiene (ingestion):
  - Always write canonical columns and tz‑naive DatetimeIndex; auto‑repair legacy Parquets on touch.
  - Prefer `Adj Close` for downstream scoring; API/scorer fall back safely.
- Momentum/value requirement:
  - Everywhere grades or “tracked” counts are shown, Momentum and Value must be present; Sentiment is optional and never penalizes when missing.
- Caching & refresh:
  - API wraps GETs with a Redis HTTP cache. `POST /api/v1/grading/refresh` and admin refresh endpoints clear relevant keys and refresh materialized views where applicable (grades, AI proximity, screener).
  - Airflow DAG calls grading refresh (and AI analysis refresh when enabled) after scorer/AI completes.
- Environment variables (scorer weights):
  - `SCORING_WEIGHT_LAMBDA_RP` (blend, default 0.4), `SCORING_WEIGHT_WINDOW_DAYS` (default 504), `SCORING_WEIGHT_HORIZON_DAYS` (default 21), `SCORING_WEIGHT_FORCE` (default false).
  - Momentum/valuation knobs: `SCORING_MOMENTUM_WINDOW_WEIGHTS` (e.g., `200=1.0,90=1.0,50=1.0,30=1.0`), `SCORING_VALUATION_SECTOR_WEIGHT` (0.7), `SCORING_VALUATION_MARKET_WEIGHT` (0.3), `SCORING_VALUATION_MIN_SECTOR_SIZE` (5).

## Tips for Future AI Agents

- When adding new factors:
  - Ingest or compute factor exposures centrally (scorer), store per‑stock per‑date in `fact_score_history` (or a dedicated fact table), and extend the weights computation to include the factor if coverage and stability are adequate.
  - Update `mv_latest_grades` (new migration) to use the factor with weights; keep Momentum/Value as required unless explicitly changed.
- When changing composite logic:
  - Prefer implementing changes in a DB migration (new MV revision) and keep the API read‑only for grades.
- When touching ingestion/scorer data contracts:
  - Preserve Parquet and DB schema compatibility. If schema breaks are necessary, add repair scripts and migrations.
- Operational flags & safety:
  - Prefer admin flags in `rankalpha.admin_flag` for one‑shot behaviors; ensure scorers/APIs reset flags after successful execution.

## Observability & Telemetry
- All long-running Python services import `apps.common.src.observability` to configure OpenTelemetry tracing and Prometheus metrics. FastAPI apps expose `/metrics`; ingestion/scorer export batch counters and histograms.
- Docker Compose deploys `otel-collector`, `prometheus`, `grafana`, `tempo`, `loki`, `promtail`, and `cadvisor` by default. Configuration lives under `docker/observability/`.
- Grafana auto-provisions Prometheus/Loki/Tempo datasources and a starter dashboard (`rankalpha-overview.json`) covering API latency/throughput plus ingestion/scorer runtimes.
- When running multiple stacks on one host, override telemetry ports (e.g., `PROMETHEUS_PORT`, `GRAFANA_PORT`, `OTEL_COLLECTOR_GRPC_PORT`, `INGESTION_METRICS_PORT`, `SCORER_METRICS_PORT`) via per-stack `.compose.env` files.
- Docs for setup, dashboards, and alerting live in [docs/observability.md](docs/observability.md).
