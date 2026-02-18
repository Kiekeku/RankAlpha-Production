# RankAlpha Docker Compose Quick Start (Single Stack)

This guide is the **low‑friction** path to run the full stack with Docker Compose (local dev or a single server).

If you are deploying to a public server:
- Read **DEPLOYMENT.md → Security Hardening** first.
- Use the hardened overrides in `compose/docker-compose.prod.yml` and the Cloudflared runbook in `docs/PROD_RUN.md`.

Running two environments (test + prod) on one host? See [DEPLOYMENT.md](DEPLOYMENT.md) for the multi‑env playbook (project names, `--env-file`, and port maps).

## What Runs (Compose)

- **Frontend**: Next.js UI (`${FRONTEND_PORT:-3000}`)
- **API**: FastAPI (`${API_PORT:-6080}`; Swagger UI at `/`)
- **Broker**: execution control plane (`${BROKER_PORT:-8000}`) + per‑account runner health (`${BROKER_RUNNER_HEALTH_PORT_HOST:-8795}`)
- **Database**: Postgres (`${DB_PORT_HOST:-6543}` → container `5432` by default)
- **Cache**: Redis (`${REDIS_PORT_HOST:-6379}`)
- **Airflow**: web UI (`${AIRFLOW_WEB_PORT:-8080}`) + internal DAG orchestration
- **Supporting**: ingestion/scorer/sentiment/newswire, SFTP uploads
- **Observability**: OTEL collector, Prometheus, Grafana, Loki, Tempo (internal), cAdvisor (ports configurable)

## 🚀 Quick Start

### Prerequisites

- Docker Desktop or Docker Engine
- Docker Compose v2+
- 8GB+ RAM recommended
- PowerShell or CMD (Windows) - **NOT Git Bash**

### Prepare env files (first run)

1) Copy the example env templates:

```bash
cp env/example/*.env.example env/local/
```

2) Rename `*.env.example` → `*.env` and fill required values (DB creds, `OPENAI_API_KEY` if using AI features, etc).

### Deploy the Stack

```bash
# Navigate to compose directory
cd compose

# Start all services
docker compose up --build

# Or run in background
docker compose up --build -d
```

### Local safety (recommended)

To bind all published ports to loopback (so nothing is reachable off‑host), run with the local override:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d
```

Or via Makefile (from repo root):

```bash
make up-local
```

### Verify Deployment

```bash
# Run the test script
../scripts/test-docker.sh

# Or manually check services
curl http://localhost:${API_PORT:-6080}/             # API docs
curl http://localhost:${FRONTEND_PORT:-3000}/        # Frontend (match FRONTEND_PORT)
curl http://localhost:${BROKER_PORT:-8000}/health    # Broker service health
curl http://localhost:${API_PORT:-6080}/api/v1/grading/grades
```

## 📱 Application URLs

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost:${FRONTEND_PORT:-3000} | Web application dashboard (default 3000) |
| API | http://localhost:${API_PORT:-6080} | FastAPI backend |
| Broker (service) | http://localhost:${BROKER_PORT:-8000} | TradeExec FastAPI |
| Broker Runner Health | http://localhost:${BROKER_RUNNER_HEALTH_PORT_HOST:-8795}/health | Per‑account executor health |
| API Docs | http://localhost:${API_PORT:-6080}/ | Interactive API documentation |
| Database | localhost:${DB_PORT_HOST:-6543} | PostgreSQL (use database tools) |
| Airflow | http://localhost:${AIRFLOW_WEB_PORT:-8080} | Pipeline orchestration |
| Redis | localhost:${REDIS_PORT_HOST:-6379} | Cache (default 6379) |
| RabbitMQ | localhost:${RABBITMQ_PORT_HOST:-5672} | AMQP broker (default 5672) |
| RabbitMQ UI | http://localhost:${RABBITMQ_MGMT_PORT_HOST:-15672} | Management console |
| SFTP | localhost:${SFTP_PORT_HOST:-2222} | SFTP uploads (default 2222) |
| Prometheus | http://localhost:${PROMETHEUS_PORT:-9090} | Metrics datastore & UI |
| Grafana | http://localhost:${GRAFANA_PORT:-3101} | Dashboards & alerting |
| Loki | http://localhost:${LOKI_PORT:-3100} | Log aggregation API |
| OpenTelemetry Collector | gRPC ${OTEL_COLLECTOR_GRPC_PORT:-4317} / HTTP ${OTEL_COLLECTOR_HTTP_PORT:-4318} | OTLP ingest |
| cAdvisor | http://localhost:${CADVISOR_PORT:-8085} | Container resource metrics |

## 🔧 Configuration

### Environment Variables

Services are configured via environment files under `env/<ENV>/` (e.g., `env/local/*`). For how `ENV`/`RANKALPHA_ENV` select and load these files inside containers, see [README: Env Profiles](README.md#env-profiles).

- Examples for local: `env/local/api.env`, `env/local/database.env`, `env/local/airflow.env`, etc.

### Key API/Broker Settings

```env
# API Port
API_PORT=6080

# Broker service port (FastAPI)
BROKER_PORT=8000

# Runner health (internal/external)
BROKER_RUNNER_HEALTH_PORT=8795
BROKER_RUNNER_HEALTH_PORT_HOST=8795

# Database Connection
DATABASE_NAME=rankalpha
DB_USERNAME=rankalpha
HOST=database
PORT=5432

# CORS for Frontend (adjust host/container ports if FRONTEND_PORT changes)
CORS_ORIGINS=["http://localhost:3000", "http://frontend:3000"]
```

### Frontend Settings

```env
# API Connection
NEXT_PUBLIC_API_URL=http://api:6080  # Internal Docker network
```

### Observability Settings

Customize telemetry ports by editing `compose/.env` (when running from `compose/`), exporting env vars, or passing `docker compose --env-file ...`:

```env
PROMETHEUS_PORT=19090
GRAFANA_PORT=13101
OTEL_COLLECTOR_GRPC_PORT=14317
OTEL_COLLECTOR_HTTP_PORT=14318
OTEL_COLLECTOR_PROM_PORT=19464
LOKI_PORT=13100
CADVISOR_PORT=18085
INGESTION_METRICS_PORT=19100
SCORER_METRICS_PORT=19101
```

Inside containers you can also override OTLP targets if you host the collector elsewhere:

```env
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_EXPORTER_OTLP_INSECURE=true
OTEL_SERVICE_NAME=rankalpha-api
```

## 🏃‍♂️ Development Workflow

### Starting Services

```bash
# Full stack
docker compose up --build

# Specific services
docker compose up database cache api frontend

# View logs
docker compose logs -f api
docker compose logs -f frontend
```

### Making Changes

```bash
# Rebuild after code changes
docker compose up --build api frontend

# Restart single service
docker compose restart api
```

### Database Operations

```bash
# Run migrations
docker compose up flyway

# Connect to database
docker compose exec database psql -U rankalpha -d rankalpha

# View database logs
docker compose logs database
```

## 🔍 Troubleshooting

### Common Issues

**"Apps not found" errors on Windows:**
- Use PowerShell or CMD, NOT Git Bash
- Ensure paths use backslashes: `compose\docker-compose.yml`

**API not starting:**
```bash
# Check API logs
docker compose logs api

# Common issues:
# - Database not ready (wait 30-60 seconds)
# - Environment file missing
# - Python dependencies not installed
```

**Frontend not connecting to API:**
```bash
# Check network connectivity
docker compose exec frontend curl http://api:6080/

# Verify CORS settings in api.env
# Check frontend environment variables
```

**Database connection failed:**
```bash
# Verify database is running
docker compose ps database

# Check database logs
docker compose logs database

# Test connection
docker compose exec database pg_isready -U rankalpha
```

### Service Health Checks

All services include health checks:

```bash
# View service status
docker compose ps

# Services should show "healthy" status
# If "unhealthy", check logs for that service
```

### Reset Everything

```bash
# Stop and remove all containers, networks, volumes
docker compose down -v

# Rebuild from scratch
docker compose up --build
```

## 📊 Monitoring

### Viewing Logs

```bash
# All services
docker compose logs

# Specific service
docker compose logs api
docker compose logs frontend

# Follow logs in real-time
docker compose logs -f api
```

### Health Status

```bash
# Check service health
docker compose ps

# API health endpoint
curl http://localhost:${API_PORT:-6080}/api/v1/pipeline/health

# Frontend health
curl http://localhost:${FRONTEND_PORT:-3000}
```

## Security / Production

- For public server deployments: read `DEPLOYMENT.md` (especially the **Security Hardening** section) before exposing anything.
- For Cloudflared: see `docs/PROD_RUN.md` and use `compose/docker-compose.prod.yml` to avoid publishing internal ports.
- Do not publish Postgres/Redis/Airflow/RabbitMQ/SFTP/metrics endpoints to the public Internet; keep them private and access via SSH port-forwarding or a private network.

## 🆘 Getting Help

- Check service logs: `docker compose logs [service]`
- View container status: `docker compose ps`
- Run health checks: `../scripts/test-docker.sh`
- Restart services: `docker compose restart [service]`
- Reset everything: `docker compose down -v && docker compose up --build`
