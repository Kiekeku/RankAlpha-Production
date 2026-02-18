# Deployment Guide: Single Host, Test + Prod (Docker Compose)

This document explains how to run two isolated RankAlpha environments (test and prod) on a single Ubuntu host using Docker Compose, without a reverse proxy.

## Overview

- Two Compose projects on one host: `rankalpha-test` and `rankalpha-prod`.
- Each project uses a different env profile (`ENV=test` vs `ENV=prod`) and distinct host ports.
- Containers, networks, and volumes are isolated by Compose project name; no global container names are used.

## Prerequisites

- Ubuntu host with Docker Engine and Compose plugin installed
- Open network ports as needed (see Port Map)

## Directory Layout

```
/opt/rankalpha/
  ├─ test/
  │   ├─ compose/                  # repo compose folder
  │   ├─ apps/                     # repo apps
  │   ├─ env/
  │   │   └─ test/
  │   │       ├─ api.env
  │   │       ├─ database.env
  │   │       ├─ cache.env
  │   │       ├─ ingestion.env
  │   │       ├─ flyway.env
  │   │       ├─ airflow.env
  │   │       └─ sentiment.env
  │   └─ .compose.env              # test-only port overrides
  └─ prod/
      ├─ compose/
      ├─ apps/
      ├─ env/
      │   └─ prod/
      │       └─ *.env             # prod values
      └─ .compose.env              # optional prod overrides
```

Tip: Prepare each environment by copying `env/example/*.env.example` → `env/<env>/*.env` and filling values.

## Environment Profiles

- The Compose file passes `RANKALPHA_ENV=${ENV:-local}` to API/ingestion/scorer/sentiment and mounts `../env` into `/app/env` in each container.
- The shared Settings load `/app/env/<ENV>/*.env` inside containers.
- Select profiles by exporting `ENV` before `docker compose`:
  - Bash: `export ENV=test` or `export ENV=prod`
  - PowerShell: `$env:ENV='test'`
- For a deeper explanation of env profiles and discovery, see [README: Env Profiles](README.md#env-profiles).

## Port Map (no reverse proxy)

Use different host ports per environment to avoid collisions.

Suggested mapping:

| Service                    | Prod (default)          | Test (example)          |
|----------------------------|--------------------------|-------------------------|
| API                        | 6080                     | 6081                    |
| Broker (FastAPI)           | 8000                     | 8001                    |
| Frontend                   | 3000                     | 3001                    |
| Postgres                   | 6543→5432                | 6544→5433               |
| Redis                      | 6379→6379                | 6380→6379               |
| Airflow Web                | 8080                     | 8180                    |
| Airflow Scheduler Health   | 8974 (internal default)  | 8794 (host example)     |
| RabbitMQ (AMQP)            | 5672                     | 5673                    |
| RabbitMQ (Mgmt)            | 15672                    | 15673                   |
| SFTP                       | 2222→22                  | 2223→22                 |
| Prometheus                 | 9090                     | 9091                    |
| Grafana                    | 3101                     | 3102                    |
| OpenTelemetry Collector gRPC | 4317                  | 4417                    |
| OpenTelemetry Collector HTTP | 4318                  | 4418                    |
| OpenTelemetry Collector Prom | 9464                  | 9564                    |
| Loki                       | 3100                     | 3110                    |
| Tempo (HTTP)               | 3200 (internal only)     | shared internal         |
| cAdvisor                   | 8085                     | 8185                    |
| Ingestion Metrics          | 9100 (internal, exposed) | 9110                    |
| Scorer Metrics             | 9101 (internal, exposed) | 9111                    |

The test stack also reconfigures internal container ports to match the host mappings (e.g., API listens on 6081 inside the test stack). This matches the approach already used for Airflow Web, Redis, RabbitMQ, SFTP, etc., and reduces confusion when inspecting containers.

Set these via a `.compose.env` file per environment (see next section).

## .compose.env Examples

Create `/opt/rankalpha/test/.compose.env` with:

```
COMPOSE_PROJECT_NAME=rankalpha-test
ENV=test
API_PORT=6081
FRONTEND_PORT=3001
BROKER_PORT=8001
BROKER_RUNNER_HEALTH_PORT=8796
BROKER_RUNNER_HEALTH_PORT_HOST=8796
DB_PORT_HOST=6544
DB_PORT_CONTAINER=5433
REDIS_PORT_HOST=6380
AIRFLOW_WEB_PORT=8180
AIRFLOW_SCHEDULER_HEALTH_PORT=8794
# Set internal port if you need to avoid conflicts between stacks sharing the same host network
AIRFLOW_SCHEDULER_HEALTH_PORT_INTERNAL=8975
RABBITMQ_PORT_HOST=5673
RABBITMQ_MGMT_PORT_HOST=15673
SFTP_PORT_HOST=2223
SFTP_USER=foo
SFTP_PASS=secret
PROMETHEUS_PORT=9091
GRAFANA_PORT=3102
OTEL_COLLECTOR_GRPC_PORT=4417
OTEL_COLLECTOR_HTTP_PORT=4418
OTEL_COLLECTOR_PROM_PORT=9564
LOKI_PORT=3110
CADVISOR_PORT=8185
INGESTION_METRICS_PORT=9110
SCORER_METRICS_PORT=9111
```

`AIRFLOW_WEB_PORT` now controls both the published host port and the internal
Airflow webserver port, so each environment can bind to its own value without
containers fighting over `8080`.

`FRONTEND_PORT` likewise sets the port exposed inside the frontend container,
so the UI, health checks, and Airflow webhook all stay aligned even when prod
and test stacks use different values.

`REDIS_PORT_HOST` now applies to both sides of the Redis binding, so each stack
can run its cache on a distinct port without containers competing for `6379`.

`RABBITMQ_PORT_HOST`/`RABBITMQ_MGMT_PORT_HOST` similarly drive the internal
RabbitMQ ports; update them per environment to prevent clashes on `5672/15672`.

`SFTP_PORT_HOST` sets the port used by the SFTP container inside the network as
well as on the host, keeping parallel stacks from colliding on `22`.

The frontend now proxies browser requests through its own `/api/*` routes, so
all calls stay on the same host/port that served the UI (no more baked-in
references to `3000`).

Optionally create `/opt/rankalpha/prod/.compose.env` (prod can keep defaults):

```
COMPOSE_PROJECT_NAME=rankalpha-prod
ENV=prod
# API_PORT=6080
# FRONTEND_PORT=3000
# DB_PORT_HOST=6543
# REDIS_PORT_HOST=6379
# AIRFLOW_WEB_PORT=8080
# AIRFLOW_SCHEDULER_HEALTH_PORT=8974
# RABBITMQ_PORT_HOST=5672
# RABBITMQ_MGMT_PORT_HOST=15672
# RABBITMQ_CONSUMER_TIMEOUT_MS=21600000
# SFTP_PORT_HOST=2222
# PROMETHEUS_PORT=9090
# GRAFANA_PORT=3101
# OTEL_COLLECTOR_GRPC_PORT=4317
# OTEL_COLLECTOR_HTTP_PORT=4318
# OTEL_COLLECTOR_PROM_PORT=9464
# LOKI_PORT=3100
# CADVISOR_PORT=8085
# INGESTION_METRICS_PORT=9100
# SCORER_METRICS_PORT=9101

# Turnstile (optional, frontend captcha)
# NEXT_PUBLIC_TURNSTILE_SITE_KEY=<change_me>
# TURNSTILE_SECRET_KEY=<change_me>
```

## Start Stacks

From each env directory:

```
cd /opt/rankalpha/test
docker compose -p rankalpha-test --env-file .compose.env -f compose/docker-compose.yml up -d --build

cd /opt/rankalpha/prod
docker compose -p rankalpha-prod --env-file .compose.env -f compose/docker-compose.yml up -d --build
```

### Using the Makefile (multi-stack)

The root Makefile supports multiple stacks via `PROJECT` and `ENVFILE` overrides:

```
# Start test stack
make PROJECT=rankalpha-test ENVFILE=/opt/rankalpha/test/.compose.env airflow-up

# Recreate worker with correct docker.sock permissions (auto-detects DOCKER_GID)
make PROJECT=rankalpha-test ENVFILE=/opt/rankalpha/test/.compose.env airflow-worker-recreate

# Tail logs / list DAGs for test
make PROJECT=rankalpha-test ENVFILE=/opt/rankalpha/test/.compose.env airflow-logs
make PROJECT=rankalpha-test ENVFILE=/opt/rankalpha/test/.compose.env airflow-list-dags

# Start prod stack
make PROJECT=rankalpha-prod ENVFILE=/opt/rankalpha/prod/.compose.env airflow-up

Other handy targets (all accept PROJECT/ENVFILE):

```
# Restart entire stack
make PROJECT=rankalpha-test ENVFILE=/opt/rankalpha/test/.compose.env stack-restart

# List containers in the stack
make PROJECT=rankalpha-test ENVFILE=/opt/rankalpha/test/.compose.env stack-ps

# Tail logs across the stack (optionally filter one service)
make PROJECT=rankalpha-test ENVFILE=/opt/rankalpha/test/.compose.env stack-logs
make PROJECT=rankalpha-test ENVFILE=/opt/rankalpha/test/.compose.env SERVICE=api stack-logs

# Stop stack and keep volumes (data persists)
make PROJECT=rankalpha-test ENVFILE=/opt/rankalpha/test/.compose.env stack-down

# Danger: stop stack and remove volumes
make PROJECT=rankalpha-test ENVFILE=/opt/rankalpha/test/.compose.env stack-down-v
```
```

Notes
- We removed fixed `container_name` entries and global network name to support multiple stacks on one host. Compose now prefixes resources per project automatically.
- API now binds to the same port inside the container as on the host (PORT=${API_PORT}). Frontend and Airflow refer to `http://api:${API_PORT}` inside the project network.
- API/ingestion/scorer/sentiment containers read `/app/env/<ENV>/*.env` via `RANKALPHA_ENV` set by Compose.
- Frontend is configured via its `environment:` (e.g., `NEXT_PUBLIC_API_URL`) and does not read `/app/env`.

## Verify

Test endpoints (using the sample test ports):

- API (test): http://localhost:6081/
- Frontend (test): http://localhost:3001/
- Airflow Web (test): http://localhost:8180/

Prod endpoints (defaults):

- API (prod): http://localhost:6080/
- Frontend (prod): http://localhost:3000/
- Airflow Web (prod): http://localhost:8080/

## Upgrade

To update an environment from new sources:

```
git pull   # or replace with a tagged release
docker compose -p rankalpha-test --env-file .compose.env -f compose/docker-compose.yml up -d --build
```

Repeat for prod.

## SFTP Notes

- The SFTP service uses the `atmoz/sftp` image with a default user `foo` and home `/home/foo` chroot.
- The upload directory inside the container is `/home/foo/upload`, mapped to the named volume `prices_data`.
- When connecting via SFTP as user `foo`, your remote root `/` is the chrooted home. Use `/upload` as the remote path (not `/home/foo/upload`).
- Default credentials (for local/test): `SFTP_USER=foo`, `SFTP_PASS=secret` (override in `.compose.env` or `--env-file` for production).
- The init script at `infra/sftp/sftp-init.sh` ensures `/home/foo/upload` is owned by the SFTP user and group. Make sure it is executable on the host:
  - `chmod +x infra/sftp/sftp-init.sh`
  - Then restart the SFTP service: `docker compose -f compose/docker-compose.yml up -d sftp`

## Local Environment (Compose)

Run a single development stack locally with the `local` profile.

### Prepare env files

1) Copy templates and fill values under `env/local/`:

```
cp env/example/*.env.example env/local/
# rename *.env.example -> *.env and set required values (DB creds, OPENAI_API_KEY, etc.)
```

### Start the local stack

```
cd compose
export ENV=local
docker compose -p rankalpha-local -f docker-compose.yml up -d --build
```

Endpoints (defaults):
- API: http://localhost:6080/
- Frontend: http://localhost:3000/
- Airflow Web: http://localhost:8080/

### Port already in use?

Create a local `.compose.env` with overrides, then run with `--env-file`:

```
ENV=local
API_PORT=7080
FRONTEND_PORT=3100
DB_PORT_HOST=7543
REDIS_PORT_HOST=6381
AIRFLOW_WEB_PORT=8180
AIRFLOW_SCHEDULER_HEALTH_PORT=8794
RABBITMQ_PORT_HOST=5673
RABBITMQ_MGMT_PORT_HOST=15673
SFTP_PORT_HOST=2223
```

```
docker compose -p rankalpha-local --env-file .compose.env -f compose/docker-compose.yml up -d --build
```

### Notes

- Compose passes `RANKALPHA_ENV=${ENV:-local}` to API/Ingestion/Scorer/Sentiment and mounts `../env` at `/app/env` inside containers; the Settings classes load `/app/env/<ENV>/*.env`.
- We avoid fixed `container_name` values to support multiple stacks; use a project name for clarity (e.g., `rankalpha-local`). Containers will be named like `rankalpha-local_api_1`.
- Frontend does not read `/app/env`; configure it via its Compose `environment:` (e.g., `NEXT_PUBLIC_API_URL`).
- For day‑to‑day commands (build/logs/ps/down), see DOCKER_DEPLOYMENT.md → Development Workflow and Troubleshooting.

## Security Tips

- Keep env files (with secrets) readable only by the deploying user: `chmod 600 env/<env>/*.env`.
- Avoid exposing Postgres/Redis to the public Internet; if you don’t need host access to them, you can comment out their port mappings.
- Consider using firewall rules (ufw) to restrict access to published ports.

## Security Hardening (Self‑Hosting on a Public Server)

This repository was built to run well on a single host, but it is **not a security product** and it should be treated as **internet‑unsafe by default**.

### Disclaimer (read before you deploy)

- This stack is **not security audited**. If you expose it to the public Internet, you are accepting real risk.
- RankAlpha handles sensitive inputs (DB credentials, API keys, broker credentials/tokens, email credentials). Assume compromise of the host or containers can lead to **data loss and account loss**.
- **Do not publish internal services** (Postgres, Redis, Airflow, RabbitMQ, SFTP, metrics endpoints) to the Internet.
- The broker components can place trades. If you enable the broker, treat it as **high risk** and keep it **strictly private**.

### Recommended default stance (infrastructure‑level)

If you want to run this on a server, start with:

1) **Expose only the frontend** (`127.0.0.1:${FRONTEND_PORT}`) and put it behind an access layer (Cloudflare Tunnel + Access policy, or a reverse proxy with strong auth).
2) Keep the API on the Docker network only (no published host port) and lock down admin endpoints with `ADMIN_BEARER_TOKEN`.
3) Disable mutation surfaces in production (`API_READ_ONLY=true`) unless you explicitly need them.
4) Lock down the host firewall to SSH only (or SSH + your reverse proxy ports), and keep all other ports closed.

The project includes a hardened override compose file: `compose/docker-compose.prod.yml`. For a Cloudflared example, see `docs/PROD_RUN.md` and `docs/UFW_EXAMPLE.md`.

### High‑Level Hardening Plan (checklist)

Use this as a phased plan. You can stop after Phase 1 for “private hobby deployment”, but for public exposure you should aim for Phase 3+.

#### Phase 0 — Decide what will be public

- **Public:** ideally *only* the UI.
- **Private (never public):** Postgres, Redis, Airflow, RabbitMQ, SFTP, ingestion/scorer/sentiment containers, Prometheus/Grafana/Loki/Tempo/cAdvisor, broker service, broker runners.
- If you need remote access to Postgres/Grafana/Airflow for admin/debugging, prefer **SSH port‑forwarding** or a private VPN over opening ports.

#### Phase 1 — Perimeter and exposure control

- Use `compose/docker-compose.prod.yml` (or your own override) to remove host `ports:` for internal services.
- Bind the frontend to loopback (`127.0.0.1`) and place it behind one of:
  - **Cloudflare Tunnel + Access** (recommended, easiest path), or
  - **Reverse proxy** (Caddy/Nginx/Traefik) with TLS + authentication.
- Firewall (UFW) to default‑deny inbound; allow only:
  - SSH from trusted IPs
  - If using a reverse proxy on the host: 80/443 (and nothing else)
- Add rate limiting / request size limits at the edge (Cloudflare or reverse proxy).

#### Phase 2 — Secrets and identity boundaries

- Ensure env files are **not world readable** (`chmod 600 env/<env>/*.env`); keep `/opt/rankalpha/*` owned by a dedicated deploy user.
- Prefer secret injection mechanisms over plaintext env files when possible:
  - Docker secrets (Swarm) or external secret stores, or at minimum encrypted storage at rest.
- Rotate and separate credentials:
  - `ADMIN_BEARER_TOKEN` for admin endpoints
  - `AUTH_SERVICE_TOKEN` for trusted service‑to‑service automation
  - `BROKER_SERVICE_TOKEN` for broker control plane (do not reuse admin tokens)
- Set strict CORS in production:
  - `CORS_ORIGINS='["https://your-domain"]'`
- If you don’t use AI/news features, remove the keys and disable those services to reduce blast radius.

#### Phase 3 — Host and container hardening

Host OS:
- Keep the OS patched (unattended upgrades where appropriate).
- SSH hardening: disable password auth, use keys, restrict to admin IPs, consider 2FA; add `fail2ban`.
- Separate deploy user from admin/root; restrict Docker access to trusted operators only (Docker socket == root‑equivalent).

Docker/Compose:
- Run only the services you need; fewer containers = smaller attack surface.
- Prefer images pinned by digest and keep dependencies updated.
- Consider container hardening options (evaluate compatibility first):
  - Run services as non‑root users
  - Drop Linux capabilities
  - Read‑only root filesystem
  - Resource limits (CPU/mem) to reduce DoS impact
- Avoid mounting sensitive host paths into containers; keep volumes minimal and scoped.

#### Phase 4 — Data protection, backups, and recovery

- Back up Postgres regularly (logical dumps + WAL if needed) and test restores.
- Protect `/data` volumes (prices, analysis artifacts) with least privilege; avoid sharing them broadly on the host.
- Store backups off‑host and encrypted.
- Define an incident/rotation playbook:
  - How to rotate API keys/tokens quickly
  - How to revoke Cloudflare Access credentials
  - How to rebuild from clean images and restore DB

#### Phase 5 — Monitoring and alerting (security‑relevant)

- Keep observability components private; if you need Grafana remotely, put it behind Access/VPN.
- Alert on:
  - spikes in 4xx/5xx and auth failures
  - unexpected admin endpoint usage
  - broker order placement activity (if enabled)
  - container restarts / unhealthy services
- Centralize logs (Loki) and retain enough to investigate incidents.

### Quick “minimum safe-ish” setup (practical)

- Use `compose/docker-compose.prod.yml` + Cloudflared + UFW default‑deny inbound.
- Expose only `127.0.0.1:${FRONTEND_PORT:-3000}` on the host.
- Set:
  - `API_READ_ONLY=true`
  - `ADMIN_BEARER_TOKEN=<change_me>`
  - `CORS_ORIGINS='["https://your-domain"]'`
- Keep broker disabled unless you have a clear operational need and a private access path.
