# Airflow Operations

This directory contains the Airflow image, DAGs, and startup scripts used by the stack.

Key services (docker-compose):
- `airflow-web` – Airflow UI at port `${AIRFLOW_WEB_PORT:-8080}`
- `airflow-scheduler` – schedules DAG runs
- `airflow-worker` – Celery worker executing tasks

## DockerOperator Wiring

We run application containers (ingestion, scorer, sentiment) via `DockerOperator` from the Airflow worker. For this to work:

- The worker must talk to Docker: compose mounts the host socket into the worker
  - `volumes: - /var/run/docker.sock:/var/run/docker.sock`
  - If your host docker socket group is non‑root, set `DOCKER_GID` before `up`:
    - `export DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)`
- Images must be built and tagged with names used by the DAG:
  - `rankalpha_ingestion`, `rankalpha_scorer`, `rankalpha_sentiment`
  - Build: `docker compose -f compose/docker-compose.yml build ingestion scorer sentiment`
- Network and volumes must be project-scoped when running multiple stacks:
  - Compose auto‑prefixes resource names by project (e.g., `rankalpha-test_rankalpha_backend_network`, `rankalpha-test_prices_data`).
  - The Compose file passes these into Airflow as environment variables so DockerOperator containers attach to the right resources:
    - `DOCKER_NETWORK=${COMPOSE_PROJECT_NAME}_rankalpha_backend_network`
    - `PRICES_DATA_VOLUME=${COMPOSE_PROJECT_NAME}_prices_data`
    - `COMPANY_REPORTS_VOLUME=${COMPOSE_PROJECT_NAME}_company_reports`
    - `ANALYSIS_SCHEDULE_VOLUME=${COMPOSE_PROJECT_NAME}_analysis_schedule`
  - Ensure your `.compose.env` sets `COMPOSE_PROJECT_NAME` to the same value you use with `-p` (see DEPLOYMENT.md).
- Environment files used by tasks are baked into the Airflow image under `/opt/rankalpha/env/<profile>`.
  - The active profile is `ENV_PROFILE` (Airflow Variable) or `RANKALPHA_ENV` env; default `local`.

## Logging Setup

- We share logs on disk across web/scheduler/worker via the `airflow_logs` volume mounted at `/opt/airflow/logs`.
- “Served logs” are disabled to avoid hostname resolution issues between containers:
  - `AIRFLOW__LOGGING__ENABLE_WORKER_LOG_SERVER=False`
  - Web reads logs directly from the shared volume.
- To re‑enable served logs later, set the flag to `True` and ensure the worker has a stable hostname (`hostname: airflow-worker`).
- Daily log cleanup runs via the `log_cleanup` DAG (04:30 UTC by default):
  - Deletes Airflow task logs older than `AIRFLOW_LOG_RETENTION_DAYS` (or Airflow Variable `LOG_RETENTION_DAYS`).
  - Deletes sentiment service logs (volume `SENTIMENT_LOGS_VOLUME`) older than `SENTIMENT_LOG_RETENTION_DAYS` (falls back to the Airflow log retention). Default retention is 30 days.
  - Prunes company reports (volume `COMPANY_REPORTS_VOLUME`): keeps the newest file per company, deletes older ones beyond `COMPANY_REPORT_RETENTION_DAYS`, and drops even the newest if it exceeds `COMPANY_REPORT_MAX_AGE_DAYS` (default 365 days).

## Quick Debug Commands

General:
- List DAGs: `docker compose exec airflow-web airflow dags list`
- Trigger DAG: `docker compose exec airflow-web airflow dags trigger rankalpha_pipeline`
- Follow worker: `docker compose logs -f airflow-worker`

DockerOperator sanity:
- Worker can talk to Docker: `docker compose exec airflow-worker docker info`
- Images present: `docker images | egrep 'rankalpha_(ingestion|scorer|sentiment)'`
- Network exists: `docker network ls | grep rankalpha_backend_network`
- See containers spawned by a task: `docker compose exec airflow-worker docker ps -a | grep run_ingestion`
- Container logs: `docker compose exec airflow-worker docker logs <container_id>`

Connectivity checks (from the worker):
- Postgres: `docker compose exec airflow-worker bash -lc "pg_isready -h database -p ${DB_PORT_CONTAINER:-5432} -U rankalpha || true"`
- API via application network: `docker compose exec airflow-worker bash -lc "wget -qO- http://api:6080/ | head -n1 || true"`

## Sentiment Queue Enqueues (rankalpha_pipeline)

The pipeline DAG can enqueue sentiment work into `rankalpha.sentiment_analysis_queue`:

- Post-earnings queue (next-day follow-up):
  - `SENTIMENT_EARNINGS_QUEUE_ENABLED` (default true)
  - `SENTIMENT_EARNINGS_RUN_HOUR_UTC`, `SENTIMENT_EARNINGS_RUN_MINUTE_UTC`
  - `SENTIMENT_EARNINGS_PRIORITY`, `SENTIMENT_EARNINGS_SOURCE_LABEL`
- Consensus “new entrants” queue (latest vs previous consensus day):
  - `SENTIMENT_CONSENSUS_QUEUE_ENABLED` (default true)
  - `SENTIMENT_CONSENSUS_QUEUE_MIN_APPEARANCES`, `SENTIMENT_CONSENSUS_QUEUE_MIN_STYLES`
  - `SENTIMENT_CONSENSUS_QUEUE_LIMIT`
  - `SENTIMENT_CONSENSUS_QUEUE_PRIORITY`, `SENTIMENT_CONSENSUS_QUEUE_SOURCE_LABEL`

Fix for NameResolutionError in logs:
- We avoid this entirely by sharing the logs directory and disabling served logs. If you re‑enable served logs, also set a stable worker hostname (compose sets `hostname: airflow-worker`).

## Common Issues

- DockerOperator Permission denied opening /var/run/docker.sock
  - Map the docker group: `export DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)` then `docker compose up -d airflow-worker`
- DockerOperator container can’t reach services by name
  - Ensure the task uses the correct project network (e.g., `<project>_rankalpha_backend_network`).
- DAG can’t find env files
  - Airflow image copies `env/` into `/opt/rankalpha/env`; confirm files exist there inside `airflow-worker`.
- Logs not visible in UI
  - Confirm `airflow_logs` volume is mounted for web/scheduler/worker and that UI path `/opt/airflow/logs` matches.

## Test DAG

A `test_docker_operator` DAG is included to validate DockerOperator + networking:
- `docker_hello` uses `hello-world` image
- `pg_isready_db` checks connectivity to the `database` service
- `curl_api` fetches the API root via `busybox` `wget`

Trigger via UI or:

```
docker compose exec airflow-web airflow dags trigger test_docker_operator
```

## RankAlpha Pipeline Schedule & Timezone

- The `rankalpha_pipeline` DAG runs by default at 05:00 Mountain Time (`America/Denver`), with DST handled automatically.
- Override without code changes via Airflow Variables (preferred):
  - `PIPELINE_SCHEDULE` – cron string (e.g., `0 5 * * *`).
  - `PIPELINE_TIMEZONE` – IANA tz name (e.g., `America/Denver`).
- As a fallback, the same names can be provided as environment variables on Airflow containers.
- See `infra/airflow/dags/pipeline.py` for the timezone-aware configuration.

## Pipeline Cache Warming

The pipeline includes two cache-warming steps to keep the UI snappy after a publish/refresh:

- **Price history cache warm (Redis, API):** `price_cache_refresh` loads active symbols from Postgres and calls `POST /api/v1/admin/prices/cache-refresh` to warm the API’s per-symbol price-history cache (used heavily by charts).
- **Frontend/BFF cache warm:** `warm_default_page_caches` issues GET requests to `frontend:/api/*` endpoints to prefill Next.js route caches and upstream API caches for common pages (rankings, screener, AI analysis, macro dashboard “latest” tiles). It can also warm the stock-detail modal endpoints for the top-ranked symbols.

## Nowcast Snapshot (Daily “What Changed”)

The `rankalpha_pipeline` DAG includes a lightweight Postgres upsert step:

- Task: `compute_nowcast_snapshot`
- Purpose: Persist the **daily Risk Nowcast snapshot** (overall + pillar scores) so the Home page can render from DB and show **Δ1 trading day** and **Δ5 trading days** consistently (no client-side window drift).

Configuration (Airflow Variables preferred; env fallback; see `env/example/airflow.env.example`):
- `NOWCAST_MODEL_VERSION` (default `nowcast_v2`) – version key written to `rankalpha.fact_nowcast_snapshot` / `rankalpha.fact_nowcast_pillar_snapshot`.
- `NOWCAST_BACKFILL_DAYS` (default `0`) – when > 0, backfills that many trading days (recommended: set to ~252 once, then revert to 0).

Stock-detail modal warm behavior (when enabled) warms, per symbol:
- `GET /api/grading/asset/{SYMBOL}`
- `GET /api/technicals/latest?symbol={SYMBOL}`
- `GET /api/technicals/series?symbol={SYMBOL}&indicators=RSI14,MACD_HIST,ATR14&days=<STOCK_DETAIL_TECHNICAL_SERIES_DAYS>`

Toggles/limits (Airflow Variables or env; see `env/example/airflow.env.example`):
- `CACHE_WARM_TIMEOUT_SECONDS` (default `15`)
- `STOCK_DETAIL_CACHE_WARM_ENABLED` (default `true`)
- `STOCK_DETAIL_CACHE_WARM_ALL_ACTIVE` (default `false`; when true, warm all active symbols from `dim_stock`)
- `STOCK_DETAIL_CACHE_WARM_LIMIT` (default `25`)
- `STOCK_DETAIL_CACHE_WARM_TIMEOUT_SECONDS` (default `CACHE_WARM_TIMEOUT_SECONDS`)
- `STOCK_DETAIL_TECHNICAL_SERIES_DAYS` (default `400`)

## Full Price Backfill DAG

The `rankalpha_price_backfill` DAG runs a full Parquet-to-Postgres resync for `fact_security_price`.
It is disabled by default (manual trigger only) and is intended as a recovery tool when price
history needs to be rebuilt from Parquets.

Steps:
- `price_backfill`: runs `apps/ingestion/src/price_backfill.py` inside the ingestion image.
- `refresh_mv_direct`: refreshes all `rankalpha.mv_%` materialized views.
- `purge_api_cache`: clears Redis prefixes for price/grades/AI/news/http caches (best-effort).
- `price_cache_refresh`: re-warms per-symbol price history caches via the API admin endpoint.

Configuration (Airflow Variables or env; see `env/example/airflow.env.example`):
- `PRICE_BACKFILL_ENABLED` (default `false`)
- `PRICE_BACKFILL_SCHEDULE` (default `0 4 * * 0`)
- `PRICE_BACKFILL_TIMEZONE` (defaults to `PIPELINE_TIMEZONE`)
- `PRICE_BACKFILL_SYMBOLS` (optional comma-separated symbols)
- `PRICE_BACKFILL_LIMIT` (default `0`)
- `PRICE_BACKFILL_DRY_RUN` (default `false`)
- `PRICE_BACKFILL_REPAIR_OUTLIERS` (default `true`)
- `PRICE_BACKFILL_MAX_RATIO` (default `100`)
- `PRICE_BACKFILL_MAX_ABS` (default `10000000`)

## Broker Daily Report DAG

- The `broker_daily_report` DAG triggers the broker email report at 06:30 Mountain Time by default.
- It skips weekends and US equity holidays via `apps.broker.tradeexec.utils.market_calendar.is_trading_day`.
- Each configured account is reported by calling `POST /report/{account}` on the broker service.
- Account discovery:
  - Uses `BROKER_REPORT_ACCOUNTS` (Airflow Variable or env) if set.
  - Otherwise reads `ACCOUNTN_ACCOUNT_NUMBER` values from `/opt/rankalpha/env/<profile>/broker.env`.
- Override without code changes via Airflow Variables (preferred):
  - `BROKER_REPORT_SCHEDULE` – cron string (default `30 6 * * *`).
  - `BROKER_REPORT_TIMEZONE` – IANA tz name (default `America/Denver`).
  - `BROKER_REPORT_ACCOUNTS` – comma/space-separated account list (optional).
  - `BROKER_API_URL` – broker base URL (default `http://broker:8000`).
  - `BROKER_REPORT_CONNECT_TIMEOUT` – seconds (default `10`).
  - `BROKER_REPORT_READ_TIMEOUT` – seconds (default `300`).
