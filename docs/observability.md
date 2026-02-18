# Observability Stack

This repository now ships with a batteries-included observability stack in `compose/docker-compose.yml`. Stand up the full suite with:

```bash
docker compose -f compose/docker-compose.yml up --build prometheus grafana loki promtail tempo otel-collector cadvisor
```

The monitoring services connect to the existing `rankalpha_backend_network`. API/broker/sentiment are scraped as stable service targets, while ingestion/scorer are discovered dynamically from Docker metadata labels.

## Components

| Service | Purpose | Default Port | Notes |
| ------- | ------- | ------------ | ----- |
| `otel-collector` | Receives OTLP traces/metrics from the apps, forwards traces to Tempo and exposes OTLP metrics to Prometheus. | gRPC `4317`, HTTP `4318`, Prometheus `9464` | Config: `docker/observability/otel-collector/config.yaml` |
| `tempo` | Trace backend (Grafana Tempo). | 3200 (HTTP), 4317 (gRPC inside network) | Stores trace blocks on the `tempo_data` volume. |
| `prometheus` | Metrics datastore and alerting engine. | 9090 | Scrapes API, broker, sentiment, cadvisor, and the collector; discovers ingestion/scorer batch containers via `docker_sd` labels. Config: `docker/observability/prometheus/prometheus.yml`. |
| `postgres-exporter` | PostgreSQL database metrics (connections, cache hit, TPS, locks). | 9187 (inside network) | Reads `DATA_SOURCE_NAME` from `env/<profile>/database.env`. Scraped by Prometheus. |
| `node-exporter` | Host-level CPU/RAM/disk/network metrics. | 9100 (inside network) | Runs on the Docker host and is scraped by Prometheus. Prefer infra-scoped alerts (disk free, memory pressure, node down). |
| `grafana` | Dashboards and alerting UI. | 3101 | Default credentials `<change_me>/<change_me>` (override with `GRAFANA_ADMIN_USER/PASSWORD`). Pre-provisioned with Prometheus, Loki, Tempo datasources and a starter dashboard. |
| `loki` | Centralised log storage. | 3100 | Stores chunk/index data on the `loki_data` volume. |
| `promtail` | Ships Docker container logs to Loki. | 9080 (metrics) | Reads from `/var/lib/docker/containers`. |
| `cadvisor` | Container-level CPU/memory/disk metrics. | 8085 | Prometheus scrapes this target. |

All configuration files live under `docker/observability/`.

Prometheus retention:
- Default retention is 15 days via `PROMETHEUS_RETENTION_TIME`.
- Optional size cap via `PROMETHEUS_RETENTION_SIZE` (set e.g. `5GB`); `0` disables size-based pruning.
- Prometheus deletes expired blocks automatically; no manual cleanup job is required.

## Application Instrumentation

### FastAPI services

- `apps/api` and `apps/broker` now expose `/metrics` (Prometheus format) and emit OpenTelemetry traces via the shared helper in `apps/common/src/observability.py`.
- Metrics include grouped request counters, in-flight gauges, and latency histograms. Prometheus scrapes them on ports `6080` and `8000`.
- API-specific counters for endpoint tracking and scrape monitoring:
  - `rankalpha_api_endpoint_requests_total{handler,method}`
  - `rankalpha_api_endpoint_requests_by_client_total{handler,method,client_class}` where `client_class` is `bot|browser|other|unknown`.

### Frontend admin security logs

- The Next.js frontend emits async JSON events for admin-route access attempts (`/admin*`, frontend `/api/admin/*`, including unknown `/api/admin/*` probes) to stdout:
  - `event="frontend_admin_access"` with fields: `surface`, `path`, `method`, `outcome`, `status_code`, `client_class`, `client_ip`.
  - `event="frontend_admin_access_log_dropped"` when the async queue drops events under pressure.
- Logging is non-blocking and queue-backed (batch flush) and controlled by frontend env:
  - `FRONTEND_ADMIN_SECURITY_LOG_ENABLED`
  - `FRONTEND_ADMIN_SECURITY_LOG_AUTHORIZED`
  - `FRONTEND_ADMIN_SECURITY_LOG_QUEUE_MAX`
  - `FRONTEND_ADMIN_SECURITY_LOG_BATCH_SIZE`
  - `FRONTEND_ADMIN_SECURITY_LOG_FLUSH_MS`
  - `FRONTEND_ADMIN_SECURITY_LOG_INCLUDE_USER_AGENT`

### Batch services

- `apps/ingestion` and `apps/scorer` initialise OTLP tracing and expose Prometheus metrics on `9100` and `9101`. Key metrics:
  - `rankalpha_ingestion_runs_total`, `rankalpha_ingestion_run_seconds_bucket`
  - `rankalpha_scorer_runs_total`, `rankalpha_scorer_run_seconds_bucket`
  - `rankalpha_ingestion_symbols_tracked`, `rankalpha_scorer_symbols_processed`
  - Ingestion drift guards: `rankalpha_ingestion_symbol_coverage_ratio`, `rankalpha_ingestion_symbol_drift_ratio`, `rankalpha_ingestion_drift_violations_total`
  - Scorer drift guards: `rankalpha_scorer_asof_pass_ratio`, `rankalpha_scorer_momentum_valid_ratio`, `rankalpha_scorer_parquet_to_momentum_ratio`, `rankalpha_scorer_drift_violations_total`
- Each run records spans (`ingestion.run`, `scorer.run`) with counts and timing, plus per-symbol failure events (`ingestion.symbol_failure`).
- Airflow sets Docker labels on those batch containers (`rankalpha.prometheus.*`) so Prometheus can discover and scrape ephemeral task containers without relying on container hostnames.

### Sentiment service

- The sentiment entrypoint initialises tracing (`rankalpha-sentiment`) and exposes Prometheus metrics on `OBSERVABILITY_METRICS_PORT` (Compose default `9102`).
- Key metrics:
  - `rankalpha_sentiment_reports_total{status="success|error"}`
  - `rankalpha_sentiment_tool_calls_total{tool, outcome="ok|error"}`
  - AI budget tracking (for Grafana alerting): `rankalpha_ai_budget_usage_ratio{service="sentiment_llm",metric="cost"}`

### Shared helper

- `apps/common/src/observability.py` wraps OpenTelemetry initialisation, FastAPI instrumentation, Prometheus metrics server bootstrap, and a small span helper (`start_span`).
- All services set `OTEL_RESOURCE_ATTRIBUTES` and `OTEL_SERVICE_NAME` via Docker Compose, so traces carry consistent metadata (`deployment.environment=<ENV>`).
- Optional: services can also emit exceptions to Sentry by setting `SENTRY_DSN` (see `env/example/shared.env.example`).

## Database Monitoring

The stack includes `postgres-exporter` for PostgreSQL internals (connections, TPS, cache hit, deadlocks) and optional per-query performance via `pg_stat_statements`.

- Exporter: `compose/docker-compose.yml` runs `prometheuscommunity/postgres-exporter` and Prometheus scrapes it under the `postgres` job.
- DSN: set `DATA_SOURCE_NAME` in `env/<profile>/database.env` (example: `env/example/database.env.example`).
- Query performance: `compose/docker-compose.yml` enables `pg_stat_statements` and `docker/database/sql/migrations/V120__pg_stat_statements.sql` installs the extension so the exporter can expose `pg_stat_statements_*` metrics (queryid-level, no SQL text).
- I/O timing: `compose/docker-compose.yml` sets `track_io_timing=on` so `pg_stat_statements_block_*_seconds_total` is populated.

## Grafana

- Datasources are provisioned automatically (`prometheus`, `loki`, `tempo`).
- `docker/observability/grafana/dashboards/rankalpha-overview.json` provides a starter dashboard showing API/broker throughput and latency, plus ingestion/scorer runtimes.
- `docker/observability/grafana/dashboards/rankalpha-scheduled-tasks.json` tracks batch task health for ingestion/scorer (run counts, durations, coverage/drift ratios, symbol counts, and warning/error log rates).
- `docker/observability/grafana/dashboards/rankalpha-api-calls.json` tracks API endpoint call volume and suspected bot traffic (top endpoints, bot share, and 4xx/5xx hotspots).
- `docker/observability/grafana/dashboards/rankalpha-frontend-security.json` tracks frontend admin-route access attempts and suspected bot scraping via Loki logs.
- `docker/observability/grafana/dashboards/rankalpha-errors.json` charts initial “data quality” signals (stale prices, missing required scores, sentiment tool/report failures).
- `docker/observability/grafana/dashboards/rankalpha-host-health.json` charts host CPU/RAM/disk/network via `node-exporter` (recommended for infra alerting).
- Alert rules and contact points can be provisioned via `docker/observability/grafana/provisioning/alerting/` (including sentiment LLM budget warnings).
- The default alert templates now include ingestion/scorer drift guards:
  - Ingestion: symbol drift ratio warning (`>15%`) and hard-guard violation detection.
  - Scorer: as-of pass ratio warning (`<65%`), momentum-valid ratio warning (`<65%`), and hard-guard violation detection.

### Email alerts

- The base Compose file wires Grafana SMTP settings from `SMTP_*` when `GF_SMTP_ENABLED=true` is set in your Compose env.
- You still need to configure **Grafana Alerting contact points** (email recipients) and **alert rules** in the Grafana UI.

## Promtail Notes

Promtail tails host Docker logs through `/var/lib/docker/containers`. If you are on macOS or Windows with Docker Desktop, ensure the path is shared with Docker. On Linux, the mount is available by default.

## Extending

- Add more scrape targets by editing `docker/observability/prometheus/prometheus.yml`.
- Instrument additional services by importing `init_service_observability` and exposing custom counters/histograms with `prometheus_client`.
- Use Grafana to create alerts (e.g., ingestion run failures, 5xx spikes) and send them to Slack/Email via Contact Points.

## Environment Variables & Port Overrides

When you run multiple stacks on the same host, set per-project overrides in `.compose.env` or export them before `docker compose up`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `PROMETHEUS_PORT` | Host port mapped to Prometheus UI/API | `9090` |
| `PROMETHEUS_RETENTION_TIME` | Prometheus TSDB retention window | `15d` |
| `PROMETHEUS_RETENTION_SIZE` | Prometheus TSDB max on-disk size (0 disables size cap) | `0` |
| `GRAFANA_PORT` | Host port mapped to Grafana (`3000` inside container) | `3101` |
| `OTEL_COLLECTOR_GRPC_PORT` | Host port mapped to OTLP gRPC (`4317` inside container) | `4317` |
| `OTEL_COLLECTOR_HTTP_PORT` | Host port mapped to OTLP HTTP (`4318` inside container) | `4318` |
| `OTEL_COLLECTOR_PROM_PORT` | Host port mapped to collector Prometheus exporter (`9464` inside container) | `9464` |
| `LOKI_PORT` | Host port for Loki API | `3100` |
| `CADVISOR_PORT` | Host port for cAdvisor UI/metrics | `8085` |
| `GF_SMTP_ENABLED` | Enable Grafana SMTP for email alerting | `false` |

Note: ingestion/scorer/sentiment metrics use fixed internal ports (`9100/9101/9102`). If you change these ports, update the corresponding Airflow DockerOperator labels and `docker/observability/prometheus/prometheus.yml`.

Inside containers, the services honour these optional overrides:

| Variable | Scope | Description |
|----------|-------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | API/Broker/Ingestion/Scorer/Sentiment | OTLP endpoint (default `http://otel-collector:4317`) |
| `OTEL_EXPORTER_OTLP_INSECURE` | same | Set `true` when using plain HTTP/gRPC |
| `OTEL_SERVICE_NAME` | same | Overrides default service name sent to OTLP |
| `OBSERVABILITY_METRICS_PORT` | Ingestion/Scorer/Sentiment | Internal Prometheus scrape port (Compose sets fixed defaults; Prometheus config must match) |
| `OBSERVABILITY_METRICS_FLUSH_SECONDS` | Ingestion/Scorer | Optional sleep-before-exit window so Prometheus can scrape final counters/histograms |
| `SENTRY_DSN` | All Python services | Enables Sentry exception reporting when set (can be disabled with `SENTRY_ENABLED=false`) |

Document these settings in the relevant `env/<environment>/*.env` files to keep expectations clear for operators.
