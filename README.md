## 🖥  Local development (Windows)

# 1. Hardware
* **CPU**  ≥ 8 cores  
* **RAM**  32 GB  
* **Disk**  1 TB SSD  

# 2. Base software
* **WSL 2** (Ubuntu recommended)
* **Docker Desktop** with WSL integration enabled
* **VS Code** + extensions  
  * Python (ms-python)  
  * Mermaid Preview (bierner.mermaid-markdown)
* **Node.js 18+** (for frontend dev)

# 3. Python toolchain
All services target Python 3.12 and use Astral `uv` for dependency management.

```
powershell
# Install Astral uv  (~3 s, no admin)
irm https://astral.sh/uv/install.ps1 | iex
```

# Pre-commit hooks (recommended)

Install repo-managed git hooks (includes a secret-leak guard):

```bash
./scripts/install-githooks.sh
```

PowerShell:

```powershell
./scripts/install-githooks.ps1
```

# 4. Quick Start with Docker (Recommended)

For the fastest setup, use Docker Compose to run the complete stack:

```powershell
# Navigate to compose directory
cd compose

# Start all services (API, Frontend, Database, etc.)
docker compose up --build

# Access the applications (defaults; override via `compose/.env`, exported vars, or `--env-file`):
# Frontend: http://localhost:${FRONTEND_PORT:-3000}
# API:      http://localhost:${API_PORT:-6080}  (Swagger at /)
# Broker:   http://localhost:${BROKER_PORT:-8000} (FastAPI service; /health)
```

See [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) for detailed Docker instructions.

### Observability & Telemetry
- Default Compose stack now includes Prometheus, Grafana, Tempo (traces), Loki + Promtail (logs), cAdvisor, and an OpenTelemetry collector. See [docs/observability.md](docs/observability.md) for wiring details.
- API and broker expose `/metrics` automatically; ingestion and scorer publish Prometheus counters/histograms on configurable ports (`INGESTION_METRICS_PORT`, `SCORER_METRICS_PORT`).
- Override telemetry ports per stack via `compose/.env` (if you run from `compose/`), exported vars, or `--env-file` (e.g., `PROMETHEUS_PORT`, `GRAFANA_PORT`, `OTEL_COLLECTOR_GRPC_PORT`) when running multiple environments on one host.

## Broker Quick Start (Compose)

Start the broker service API and a per‑account runner:

```bash
# Required for broker endpoints (everything except /health)
# Set BROKER_SERVICE_TOKEN in env/<ENV>/shared.env (Compose reads env files for container env).
# Example: BROKER_SERVICE_TOKEN=$(openssl rand -hex 32)
#
# Recommended for internal automation (Airflow, ingestion cache warmers, frontend server routes):
# AUTH_SERVICE_TOKEN=$(openssl rand -hex 32)

# Start only the broker FastAPI service
make broker-up

# Start a dedicated runner for one IB account (no HTTP service)
make BROKER_ACCOUNT=DU-changeme broker-runner-up

# Post a test signal to the service API (ACC required)
make ACC=DU-changeme SYMBOL=AAPL ACTION=buy QTY=10 broker-signal

# Tail logs
make broker-logs
make broker-runner-logs
```

Ports are overridable per stack via `compose/.env`, exported vars, or `--env-file`:
- `BROKER_PORT` (service API, default 8000)
- `BROKER_RUNNER_HEALTH_PORT` (inside container) and `BROKER_RUNNER_HEALTH_PORT_HOST` (host publish) for runner health

Trading + portfolio docs
- Trading signal ingestion (external strategies → RankAlpha broker): `docs/TRADING_SIGNAL_INGESTION.md`
- Portfolio construction + approvals + deployments (model → broker): `docs/PORTFOLIO_CONSTRUCTION.md`

Scoring methodology
- High‑level overview and configuration: see docs/SCORING.md
- Service‑level details: apps/scorer/README.md

Regime & breadth (new, HMM‑free)
- Flow‑based regime rules: alongside the legacy intensity cores, the scorer now emits a rules‑driven regime using entrants/exits/continuers, churn, a persistence score (PS), and a pullback transition bias (TB). No HMM required.
  - API endpoints: `GET /api/v1/screener/regime-rules/latest`, `GET /api/v1/screener/regime-rules/series`.
  - Frontend defaults to the new rules regime on the Screener page (opt‑out via `?regime=intensity`).
- Flow‑aligned breadth: universe‑normalized “flow breadth” per canonical style with continuers% and churn%.
  - API endpoint: `GET /api/v1/screener/breadth/flow`.
  - Frontend defaults to flow breadth on the Screener page (opt‑out via `?breadth=legacy`).
  - Legacy breadth (`/api/v1/screener/breadth`) remains available for compatibility.

**Secure Production (Cloudflared)**
- Use the hardened override `compose/docker-compose.prod.yml` to avoid publishing internal ports.
- Frontend binds to `127.0.0.1:3000`; point your Cloudflare Tunnel to `http://localhost:3000` and set a 404 fallback.
- API hardening env:
  - `API_READ_ONLY=true` disables auto‑generated POST/PUT/DELETE in production.
  - `ADMIN_BEARER_TOKEN=<change_me>` protects `/api/v1/admin/*` with a Bearer token.
  - `CORS_ORIGINS=["https://your.cloudflare.domain"]` restricts allowed origins.

Run (hardened):

```
export ADMIN_BEARER_TOKEN=$(openssl rand -hex 32)
export CORS_ORIGINS='["https://your.cloudflare.domain"]'
make up-prod
```

Cloudflared ingress example (`/etc/cloudflared/config.yml`):

```
ingress:
  - hostname: your.cloudflare.domain
    service: http://localhost:3000
  - service: http_status:404
```

Verify exposure (only 127.0.0.1:3000 should listen):

```
docker ps
ss -tulpen | rg ':3000 '| rg 'LISTEN'
```

Use admin endpoints with Bearer (inside the API container since it’s not published):

```
docker compose -f compose/docker-compose.yml -f compose/docker-compose.prod.yml exec api \
  sh -lc 'curl -s -H "Authorization: Bearer '$ADMIN_BEARER_TOKEN'" -X POST http://localhost:6080/api/v1/admin/grades/refresh'
```

Stop hardened stack:

```
make down-prod
```

Local/dev safety
- To keep dev/test stacks private by default, use the loopback override:

```
make up-local
# ... run your tests ...
make down-local
```

More docs
- Cloudflared example: docs/cloudflared.config.example.yml
- UFW lockdown: docs/UFW_EXAMPLE.md
- Architecture diagram: docs/architecture.md
- Server hardening (self-hosting): DEPLOYMENT.md#security-hardening-self-hosting-on-a-public-server

<a id="env-profiles"></a>
# Env Profiles

The repo organizes environment variables by profile under `env/<ENV>/*.env`.

- Profiles
  - `env/example/*.env.example` – templates with comments; copy from here.
  - `env/local/*` – default local profile used when `RANKALPHA_ENV` is unset.
  - `env/localws/*` – "outside looking in" profile for running apps on the host that connect to services in Docker (e.g., DB on `localhost:6543`).
- Selecting a profile
  - CLI: `export RANKALPHA_ENV=local` (or `localws`); PowerShell: `$env:RANKALPHA_ENV='localws'`.
  - Docker Compose uses the files under `env/${ENV:-local}/` via `env_file` entries.
  - Compose also sets `RANKALPHA_ENV=${ENV:-local}` for API/ingestion/scorer/sentiment and mounts `../env` at `/app/env` inside containers so Python Settings can resolve `env/<ENV>/*.env` consistently.
- Which files are read
  - Base settings read `env/<ENV>/shared.env` (db/redis/openai/logging). Each service has its own settings class under `apps/<service>/src/settings.py` with an explicit `env_file` list.
  - API service loads `env/<ENV>/api.env` (+ `shared.env`); ingestion/scorer/sentiment load their respective env files (+ `shared.env`).
  - Broker daily reports require `GMAIL_SENDER`, `GMAIL_RECIPIENT`, and `GMAIL_APP_PASSWORD` in `shared.env` when email delivery is enabled.
- Bootstrapping
  1) Copy templates: `cp env/example/*.env.example env/local/ && rename 's/\.env\.example$/.env/' env/local/*.env.example` (Windows: copy/rename manually).
  2) Fill required values (e.g., DB creds, `OPENAI_API_KEY`).
  3) Optional cost-safety for sentiment: set `SENTIMENT_MAX_ANALYSES=2` while testing.

Docker tip
- When running with Docker Compose, you can choose a profile for all services by exporting `ENV` before `docker compose up`:
  - Bash: `export ENV=local` (or `localws`)
  - PowerShell: `$env:ENV='local'`
- API, Ingestion, Scorer, and Sentiment read `RANKALPHA_ENV` inside the container and load `/app/env/<ENV>/*.env` (mounted from the repo’s `env/` folder).
- Frontend does not use `/app/env`; configure it via its `environment:` stanza (e.g., `NEXT_PUBLIC_API_URL`).

Ports (multi‑stack overrides)
- Use a per‑stack `.compose.env` (passed via `docker compose --env-file ...` or `make envfile=...`) to set distinct host/container ports and avoid collisions:
  - `API_PORT` (default `6080`)
  - `FRONTEND_PORT` (default `3000`)
  - `BROKER_PORT` (default `8000`)
  - `BROKER_RUNNER_HEALTH_PORT` (default `8795`, container) and `BROKER_RUNNER_HEALTH_PORT_HOST` (host publish)
See DEPLOYMENT.md for a full example of running test + prod on one host.

Tip: In Docker, use container service names (e.g., `HOST=database`, `PORT=5432`). For host‑run apps (localws), use `HOST=localhost`, `PORT=6543` (Compose maps `6543:5432`).

# First Run: Load Initial Data

On a fresh database, the API’s grading endpoints return HTTP 200 with an empty result until the pipeline ingests data. Choose one of the following to seed data:

- Full stack (recommended):
  - `docker compose -f compose/docker-compose.yml up --build`
  - Airflow auto‑triggers the initial pipeline; first run can take several minutes.
  - Check Airflow UI at http://localhost:8080 for DAG progress.

- API‑only development (minimal services):
  1) Start DB and apply migrations
     - `docker compose -f compose/docker-compose.yml up -d database flyway`
  2) Run ingestion to populate price data volume
     - `docker compose -f compose/docker-compose.yml up ingestion`
  3) Run scorer to write scores to Postgres
     - `docker compose -f compose/docker-compose.yml up scorer`

Once ingestion/scorer complete, refresh the frontend (http://localhost:3000). The grading and pipeline views will populate.

Optional – run Sentiment to enrich data:
- Sentiment adds AI factor scores (value/sentiment), news analysis, and richer asset detail. Without it, those fields show as N/A and the pipeline may show a warning for the sentiment component.
- Start it anytime:
  - `docker compose -f compose/docker-compose.yml up sentiment`

Technical indicators
- Ingestion writes price Parquets under `/data/prices` and keeps them fresh by incrementally updating from yfinance when needed (weekends/holidays create no new rows; files remain as-is).
- After ensuring Parquet freshness, ingestion computes daily technical indicators and upserts them to Postgres (`rankalpha.fact_technical_indicator`).
- A convenience view `rankalpha.vw_latest_technicals` provides a pivoted snapshot per symbol.

# 5. Manual Development Setup

This repo is multi-service. Each app under `apps/` has its own `pyproject.toml`, `uv.lock`, and virtual environment. Set up the ones you plan to work on:

```powershell
# API (FastAPI backend)
cd apps\api
uv venv
uv sync --locked

# Frontend (Next.js)
cd ..\frontend
pnpm install

# Ingestion
cd ..\ingestion
uv venv
uv sync --locked

# Scorer
cd ..\scorer
uv venv
uv sync --locked

# Sentiment (optional)
cd ..\sentiment
uv venv
uv sync --locked
```

Activating is optional when using `uv run`, but you can still activate a venv if preferred:

```
.venv\Scripts\Activate   # Windows (from each app directory)
# or
source .venv/bin/activate # WSL/Linux/macOS
```

# 5. VS Code 
Ctrl ⇧ P → Python: Select Interpreter → choose
the `.venv\Scripts\python.exe` inside the specific app you’re working on (e.g., `apps\ingestion\.venv\Scripts\python.exe`).

# 6. Day-to-day package management (per app)
Run dependency commands inside the target app directory so its `uv.lock` is updated correctly.

```
uv add <pkg>
uv remove <pkg>
git add pyproject.toml uv.lock
git commit -m "deps: update <app>"
```

# 7. House-Keeping
`uv sync`            # refresh env after pulling changes

`uv self update`     # update uv itself


# Running locally (per app)

There is no single top-level `main.py`. Examples:

- Ingestion: from `apps/ingestion` → `uv run python src/main.py`
- Scorer: from `apps/scorer` → `uv run python src/main.py`
- Sentiment: from `apps/sentiment` → `uv run python src/main.py`
- API (dev): from `apps/api` → set `PYTHONPATH` to the repo root, then run uvicorn
  - PowerShell: `$env:PYTHONPATH = '..\\..' ; uv run uvicorn src.main:app --reload`
  - Bash: `export PYTHONPATH=../.. && uv run uvicorn src.main:app --reload`
- Frontend (dev): from `apps/frontend` → set `NEXT_PUBLIC_API_URL` to the API base URL, then run
  - PowerShell: `$env:NEXT_PUBLIC_API_URL='http://localhost:6080' ; pnpm dev`
  - Bash: `NEXT_PUBLIC_API_URL=http://localhost:6080 pnpm dev`

## Frontend (pnpm quick reference)

Prerequisite: Node.js 18+.

Enable pnpm via Corepack (recommended):

```
# Bash / WSL / macOS
corepack enable && corepack prepare pnpm@9.12.3 --activate

# PowerShell
corepack enable; corepack prepare pnpm@9.12.3 --activate
```

Common commands (run in `apps/frontend`):

```
pnpm install                  # install deps
pnpm dev                      # start Next.js dev server (http://localhost:3000)
pnpm build && pnpm start      # production build and start
pnpm type-check               # TypeScript check
pnpm lint                     # ESLint
pnpm generate-types           # generate API types from FastAPI OpenAPI
```

# Docker build

1. Start command line / terminal
2. Go to the project root folder (e.g.`c:\...\rankalpha`)
3. Build and start the services:
 ```docker compose -f compose\docker-compose.yml up --build```
4. If need to force a full rebuild of the images, including remove volumes: 
```docker compose -f compose\docker-compose.yml down -v
docker compose -f compose\docker-compose.yml up --build
```
5. To update the database
`docker compose -f compose\docker-compose.yml up flyway`

## Database:
- Schema is `rankalpha`

## To set the correct env folder on local dev:

On your local dev machine, some services (e.g., the database) use different host/port (e.g., `localhost:6543`) versus Docker-internal names (e.g., `database:5432`). There is a folder under `/env` called `localws` for “outside looking in” development.

For development/debugging outside Docker, set the environment folder as below to ensure your code targets the running containers. The settings classes look under `/env`. If `RANKALPHA_ENV` is not specified, `local` is used by default.

- run on bash:  
      export RANKALPHA_ENV=localws
       
 - run on powershell: 
      $env:RANKALPHA_ENV = "localws"
        
## Ingestion app

From `rankalpha\apps\ingestion`:

```
uv run python src/main.py

Notes:
- Parquet freshness check: existing files are updated incrementally from the last available date to today.
- Daily technical indicators are computed from Parquet and upserted to Postgres (see `vw_latest_technicals`).
```

## Sentiment app (local setup)

Recommended: run via Docker Compose (no local installs required)

- Set your OpenAI key in `env/local/sentiment.env` (or the env folder you use):
  - `OPENAI_API_KEY=<change_me>`
- Start the service:
  - `docker compose -f compose/docker-compose.yml up sentiment`

Local run (outside Docker)

Prerequisites:
- Python 3.12 and Astral uv
- Node.js 18+
- Global MCP server for Google Search: `npm install -g g-search-mcp`
- Playwright Chromium browser: from `apps/sentiment`, run `uv run python -m playwright install chromium`

Environment:
- Copy `env/example/sentiment.env.example` to your env folder and fill values (at minimum `OPENAI_API_KEY`).
- Ensure your Settings target the right env folder: `export RANKALPHA_ENV=local` (or `localws`).
- For DB outside Docker, host is usually `localhost` and port `6543` (Compose maps `6543:5432`).
 - Model selection: set the default model in `apps/sentiment/src/mcp_agent.config.yaml` under `openai.default_model`, and optionally override with `OPENAI_MODEL` in your env (env precedence beats config; there is no hardcoded fallback).

Data directories (Linux/macOS): the app writes to `/data/company_reports` and `/data/analysis_schedule`.
Create them once with write permissions:
```
sudo mkdir -p /data/company_reports /data/analysis_schedule
sudo chmod -R 777 /data
```

Run locally:
```
cd apps/sentiment
uv venv && uv sync --locked
uv run python src/main.py
```

Notes:
- The app warns if `OPENAI_API_KEY` is not set and will skip AI analysis.
- In Compose, volumes for `/data/company_reports` and `/data/analysis_schedule` are mounted automatically.
