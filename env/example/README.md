# Environment Profiles and Example Files

This folder contains commented `.env.example` templates for each service. Copy the examples to `env/<ENV>/` (e.g., `env/local/`) and rename to `.env` to activate them for a given profile.

- How profiles are selected
  - Docker Compose sets `ENV` (e.g., `ENV=local`, `ENV=test`, `ENV=prod`) and mounts `../env` into the containers.
  - Most Python services read `RANKALPHA_ENV` inside the container and load `env/<ENV>/*.env` via pydantic Settings.
  - See root README (Env Profiles) for details.

- Where to start
  - Copy all examples to your profile:
    - `cp env/example/*.env.example env/local/`
    - Rename to `*.env` and fill values.
  - For multi‑stack on a single host, also create a top‑level `.compose.env` per stack (see `DEPLOYMENT.md`).

## Files

- `shared.env.example`
  - Used by: All Python services via `BaseAppSettings` (db/redis/openai/logging/budget alerts).
  - Put here: Postgres connection (DATABASE_NAME, DB_USERNAME, PASSWORD, HOST, DB_PORT), Redis (REDIS_*), OpenAI keys/models, shared service tokens (`AUTH_SERVICE_TOKEN`, `BROKER_SERVICE_TOKEN`), Gmail/BUDGET_ALERT recipients.
  - Email: `GMAIL_SENDER`, `GMAIL_RECIPIENT`, and `GMAIL_APP_PASSWORD` are required if you want broker daily reports to send email.
  - Keep service-specific knobs in each service env file to avoid collisions.

- `api.env.example`
  - Used by: API service (apps/api) only.
  - Put here: API_PORT, admin/trading tokens, broker bridge settings, cache TTLs, CORS.
  - Optional: telemetry overrides (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `OTEL_SERVICE_NAME`) if you point at a non-default collector.
  - Docs: apps/api/README.md, DOCKER_DEPLOYMENT.md.

- `broker.env.example`
  - Used by: Broker service (apps/broker FastAPI) and per‑account runner.
  - Put here: IBKR OAuth (single or `ACCOUNT{N}_*`), MARKET_OPEN_TIME/CLOSE_TIME.
  - Do NOT put DB/Gmail/Telegram here (they live in `api.env`).
  - PEM keys should be stored on disk (not committed), ideally in `env/<ENV>/broker/`, and referenced by filename.
  - Optional: telemetry overrides (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `OTEL_SERVICE_NAME`).
  - Docs: apps/broker/README.md.

- `ingestion.env.example`
  - Used by: Ingestion (apps/ingestion).
  - Put here: ingestion thresholds, price cache warmer knobs, Finnhub key, DXY/HY stress toggles.
  - Optional: `OBSERVABILITY_METRICS_PORT` (default 9100 inside container) and OTLP settings for custom collectors.
  - Docs: apps/ingestion/README.md, apps/newswire/README.md (if present).

- `newswire.env.example`
  - Used by: Newswire (apps/newswire) alongside `shared.env`.
  - Put here: polling cadence, sources, Serper/GDELT/RSS config, LLM toggles, sentiment handoff settings.

- `scorer.env.example`
  - Used by: Scorer (apps/scorer).
  - Put here: Postgres connection, scoring weights and toggles.
  - Optional: `OBSERVABILITY_METRICS_PORT` (default 9101 inside container) and OTLP settings.
  - Docs: apps/scorer/README.md.

- `sentiment.env.example`
  - Used by: Sentiment (apps/sentiment).
  - Put here: OpenAI keys/models, sentiment toggles, Redis (if tool cache used).
  - Optional: OTLP overrides (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `OTEL_SERVICE_NAME`).
  - Docs: apps/sentiment/README.md.

- `airflow.env.example`
  - Used by: Airflow services (`airflow-web`, `airflow-scheduler`, `airflow-worker`, `airflow-init`).
  - Put here: Airflow core config plus pipeline toggles and cache warmer knobs used by `infra/airflow/dags/pipeline.py`.
  - Includes Nowcast snapshot knobs: `NOWCAST_MODEL_VERSION`, `NOWCAST_BACKFILL_DAYS` (persist nightly Nowcast state for Δ1d/Δ5d).
  - Docs: `infra/airflow/README.md`.

- `database.env.example`
  - Used by: Postgres container (docker/database).
  - Put here: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.
  - Docs: DOCKER_DEPLOYMENT.md.

- `cache.env.example`
  - Used by: Redis container.
  - Put here: host/port overrides if needed.
  - Docs: DOCKER_DEPLOYMENT.md.

- `flyway.env.example`
  - Used by: Flyway migrations container.
  - Put here: JDBC URL, DB username/password (typically points at `database:5432`).
  - Docs: docker/database/README.md (if present) or DOCKER_DEPLOYMENT.md.

- `frontend.env.example`
  - Used by: Next.js frontend.
  - Put here: `NEXT_PUBLIC_API_URL` (internal URL when in Docker, e.g., `http://api:6080`).
  - Docs: apps/frontend/README.md.

- `compose.env.example`
  - Used by: Docker Compose via `--env-file` for stack-level overrides.
  - Put here: SFTP credentials (`SFTP_USER`, `SFTP_PASS`) and any host/container port overrides.
  - Docs: DEPLOYMENT.md.

## Compose‑time overrides per stack

- Create a top‑level `.compose.env` next to `compose/` to pin host/container ports per stack:
  - `API_PORT`, `FRONTEND_PORT`, `BROKER_PORT`, `BROKER_RUNNER_HEALTH_PORT`, `BROKER_RUNNER_HEALTH_PORT_HOST`, `SFTP_USER`, `SFTP_PASS`, telemetry ports (`PROMETHEUS_PORT`, `GRAFANA_PORT`, `OTEL_COLLECTOR_*`, `LOKI_PORT`, `CADVISOR_PORT`, `INGESTION_METRICS_PORT`, `SCORER_METRICS_PORT`), etc.
  - See `DEPLOYMENT.md` for a complete example and port map.
