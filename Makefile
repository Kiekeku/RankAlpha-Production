PROJECT ?=
ENVFILE ?=
SERVICE ?=

# Compose command with optional project and env-file flags (supports multi-stack deploys)
## RankAlpha Makefile (multi-stack aware)
##
## Variables (override as needed; lowercase preferred, uppercase aliases still work):
##  - project / PROJECT   : Compose project name, e.g. rankalpha-test (maps to `docker compose -p`)
##  - envfile / ENVFILE   : Path to .compose.env for the stack (maps to `--env-file`)
##  - service / SERVICE   : Used by `stack-logs` to filter a single service
##  - docker_socket / DOCKER_SOCKET : Path to docker.sock (default: /var/run/docker.sock)
##  - docker_gid / DOCKER_GID      : Auto-detected group id for docker.sock (used to grant airflow-worker access)
##  - compose_bin / COMPOSE_BIN    : Compose command. Auto-detects `docker compose`, then `docker-compose`.
##
## Examples:
##  make project=rankalpha-test envfile=/opt/rankalpha/test/.compose.env stack-up
##  make project=rankalpha-test envfile=/opt/rankalpha/test/.compose.env airflow-worker-recreate
##  make project=rankalpha-test envfile=/opt/rankalpha/test/.compose.env service=api stack-logs
##  make project=rankalpha-prod  envfile=/opt/rankalpha/prod/.compose.env stack-down

# Detect base compose binary (prefer Docker Compose plugin, then docker-compose)
COMPOSE_BIN ?= $(shell if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then echo docker compose; \
                         elif command -v docker-compose >/dev/null 2>&1; then echo docker-compose; \
                         else echo docker compose; fi)

ifneq ($(strip $(project)),)
PROJECT := $(strip $(project))
endif
ifneq ($(strip $(envfile)),)
ENVFILE := $(strip $(envfile))
endif
ifneq ($(strip $(service)),)
SERVICE := $(strip $(service))
endif
ifneq ($(strip $(compose_bin)),)
COMPOSE_BIN := $(strip $(compose_bin))
endif

COMPOSE_BASE := $(COMPOSE_BIN) $(if $(PROJECT),-p $(PROJECT),) $(if $(ENVFILE),--env-file $(ENVFILE),)
COMPOSE := $(COMPOSE_BASE) -f compose/docker-compose.yml
COMPOSE_PROD := $(COMPOSE) -f compose/docker-compose.prod.yml
COMPOSE_LOCAL := $(COMPOSE) -f compose/docker-compose.local.yml
# Attempt to auto-detect the Docker socket group id for granting the Airflow worker
# access to /var/run/docker.sock. Works on Linux (stat -c), BSD/macOS (stat -f),
# or falls back to the 'docker' group id if present, else 0.
ifneq ($(strip $(docker_socket)),)
DOCKER_SOCKET := $(strip $(docker_socket))
endif
DOCKER_SOCKET ?= /var/run/docker.sock
DOCKER_GID ?= $(shell sh -lc 'stat -c "%g" $(DOCKER_SOCKET) 2>/dev/null || stat -f "%g" $(DOCKER_SOCKET) 2>/dev/null || getent group docker | awk -F: "{print $$3}" || echo 0')
ifneq ($(strip $(docker_gid)),)
DOCKER_GID := $(strip $(docker_gid))
endif
# Export for all recipes so docker compose sees it (compose uses ${DOCKER_GID:-0}).
export DOCKER_GID
COMPOSE_ENV := DOCKER_GID=$(DOCKER_GID)

.PHONY: help
help:
	@echo "Common targets:"
	@echo "  stack-up                 Build and start full stack (PROJECT/ENVFILE aware)"
	@echo "  observability-up         Start only observability services (Prometheus/Grafana/etc.)"
	@echo "  obs-up                   Alias for observability-up"
	@echo "  up-prod                  Start hardened stack with prod override (loopback-only frontend)"
	@echo "  up-local                 Start dev/test stack bound to loopback only"
	@echo "  stack-down               Stop stack (keep volumes)"
	@echo "  down-prod                Stop hardened stack (uses prod override)"
	@echo "  down-local               Stop dev/test loopback stack"
	@echo "  stack-down-v             Stop stack and remove volumes (DANGEROUS)"
	@echo "  stack-restart            Restart all services"
	@echo "  stack-ps                 List containers in the stack"
	@echo "  stack-logs               Tail logs for entire stack (use SERVICE=<name> to filter)"
	@echo "  stack-status             Print endpoints and current Compose ps"
	@echo "  svc-up                   Start one service (SERVICE=...)"
	@echo "  svc-restart              Restart one service (SERVICE=...)"
	@echo "  svc-down                 Stop one service (SERVICE=...)"
	@echo "  svc-logs                 Tail logs for one service (SERVICE=...)"
	@echo "  svc-ps                   Show state for one service (SERVICE=...)"
	@echo "  svc-build                Build one service (SERVICE=...)"
	@echo "  svc-exec                 Exec into a service (SERVICE=..., CMD=...)"
	@echo "  svc-wait                 Wait for one service to be healthy (SERVICE=..., WAIT_TIMEOUT=seconds)"
	@echo "  stack-wait               Wait for all services to be healthy (WAIT_TIMEOUT=seconds)"
	@echo "  airflow-build            Build ingestion/scorer/sentiment/news/airflow images"
	@echo "  airflow-up               Start Airflow services"
	@echo "  airflow-restart          Restart Airflow services"
	@echo "  airflow-logs             Tail Airflow worker logs"
	@echo "  airflow-list-dags        List Airflow DAGs"
	@echo "  airflow-trigger-pipeline Trigger main pipeline DAG"
	@echo "  airflow-trigger-healthcheck Trigger nightly healthcheck DAG now"
	@echo "  airflow-test-docker      Trigger DockerOperator test DAG"
	@echo "  airflow-vars-network     Set DOCKER_NETWORK Airflow Variable"
	@echo ""
	@echo "Vars (optional): project=<name> envfile=/path/.compose.env service=<name>"
	@echo "Aliases: uppercase names still supported (e.g. PROJECT, ENVFILE, SERVICE)"
	@echo "Auto-detected: DOCKER_GID=$(DOCKER_GID) from $(DOCKER_SOCKET)"
	@echo "Compose bin  : $(COMPOSE_BIN)"
	@echo ""
	@echo "Broker shortcuts:"
	@echo "  broker-build                   Build the broker image"
	@echo "  broker-up                      Start the broker service"
	@echo "  broker-restart                 Restart the broker service"
	@echo "  broker-logs                    Tail broker logs"
	@echo "  broker-runner-up               Start per-account runner (BROKER_ACCOUNT=DUxxxxxxx)"
	@echo "  broker-runner-restart          Restart the per-account runner"
	@echo "  broker-runner-logs             Tail per-account runner logs"
	@echo "  broker-signal                  Send a test signal to broker service (ACC/SYMBOL/ACTION/...)"
	@echo ""
	@echo "Quality targets:"
	@echo "  format-py                 Ruff-format Python code (repo-wide)"
	@echo "  lint-py                   Ruff-lint Python code (repo-wide)"
	@echo "  fix-lint-py               Ruff-lint-fix Python code (repo-wide)"
	@echo "  typecheck-py              Mypy type-check Python code (repo-wide)"

.PHONY: help-vars
help-vars:
	@echo "project=$(PROJECT)  [alias PROJECT]"
	@echo "envfile=$(ENVFILE)  [alias ENVFILE]"
	@echo "service=$(SERVICE)  [alias SERVICE]"
	@echo "docker_socket=$(DOCKER_SOCKET)  [alias DOCKER_SOCKET]"
	@echo "docker_gid=$(DOCKER_GID)  [alias DOCKER_GID]"
	@echo "compose_bin=$(COMPOSE_BIN)  [alias COMPOSE_BIN]"
	@echo "cmd=$(CMD)  [alias CMD]"
	@echo "wait_timeout=$(WAIT_TIMEOUT)  [alias WAIT_TIMEOUT]"

PY_RUFF_VERSION ?= 0.14.10
PY_MYPY_VERSION ?= 1.19.1

.PHONY: format-py
format-py:
	@set -e; \
	for app in api common ingestion scorer sentiment newswire portfolio; do \
	  cfg="apps/$$app/pyproject.toml"; \
	  dir="apps/$$app/src"; \
	  uv tool run ruff==$(PY_RUFF_VERSION) format --config "$$cfg" "$$dir"; \
	done; \
	uv tool run ruff==$(PY_RUFF_VERSION) format --config "apps/broker/pyproject.toml" apps/broker/tradeexec apps/broker/tests apps/broker/utils

.PHONY: lint-py
lint-py:
	@set -e; \
	for app in api common ingestion scorer sentiment newswire portfolio; do \
	  cfg="apps/$$app/pyproject.toml"; \
	  dir="apps/$$app/src"; \
	  uv tool run ruff==$(PY_RUFF_VERSION) check --config "$$cfg" "$$dir"; \
	done; \
	uv tool run ruff==$(PY_RUFF_VERSION) check --config "apps/broker/pyproject.toml" apps/broker/tradeexec apps/broker/tests apps/broker/utils

.PHONY: fix-lint-py
fix-lint-py:
	@set -e; \
	for app in api common ingestion scorer sentiment newswire portfolio; do \
	  cfg="apps/$$app/pyproject.toml"; \
	  dir="apps/$$app/src"; \
	  uv tool run ruff==$(PY_RUFF_VERSION) check --fix --config "$$cfg" "$$dir"; \
	done; \
	uv tool run ruff==$(PY_RUFF_VERSION) check --fix --config "apps/broker/pyproject.toml" apps/broker/tradeexec apps/broker/tests apps/broker/utils

.PHONY: compileall-py
compileall-py:
	python -m compileall -q apps tests infra scripts
.PHONY: typecheck-py
typecheck-py:
	@set -e; \
	(cd apps/api && uv tool run mypy==$(PY_MYPY_VERSION) --config-file pyproject.toml src); \
	(cd apps/common && uv tool run mypy==$(PY_MYPY_VERSION) --config-file pyproject.toml src); \
	(cd apps/ingestion && uv tool run mypy==$(PY_MYPY_VERSION) --config-file pyproject.toml src); \
	(cd apps/scorer && uv tool run mypy==$(PY_MYPY_VERSION) --config-file pyproject.toml src); \
	(cd apps/sentiment && uv tool run mypy==$(PY_MYPY_VERSION) --config-file pyproject.toml src); \
	(cd apps/newswire && uv tool run mypy==$(PY_MYPY_VERSION) --config-file pyproject.toml src); \
	(cd apps/portfolio && uv tool run mypy==$(PY_MYPY_VERSION) --config-file pyproject.toml src); \
	(cd apps/broker && uv tool run mypy==$(PY_MYPY_VERSION) --config-file pyproject.toml tradeexec)

.PHONY: stack-up
stack-up:
	$(COMPOSE_ENV) $(COMPOSE) up --build -d

.PHONY: observability-up
observability-up:
	$(COMPOSE_ENV) $(COMPOSE) up --build -d otel-collector tempo prometheus grafana loki promtail cadvisor postgres-exporter airflow-postgres-exporter node-exporter

.PHONY: obs-up
obs-up: observability-up

.PHONY: up-prod
up-prod:
	# Hardened run: removes external port publishes, binds frontend to 127.0.0.1:${FRONTEND_PORT:-3000}
	$(COMPOSE_ENV) $(COMPOSE_PROD) up --build -d

.PHONY: up-local
up-local:
	# Loopback-only for dev/test: binds all published services to 127.0.0.1
	$(COMPOSE_ENV) $(COMPOSE_LOCAL) up --build -d

.PHONY: stack-down
stack-down:
	$(COMPOSE) down

.PHONY: down-prod
down-prod:
	$(COMPOSE_PROD) down

.PHONY: down-local
down-local:
	$(COMPOSE_LOCAL) down

.PHONY: stack-down-v
stack-down-v:
	$(COMPOSE) down -v

.PHONY: stack-restart
stack-restart:
	$(COMPOSE_ENV) $(COMPOSE) restart

.PHONY: stack-ps
stack-ps:
	$(COMPOSE) ps

.PHONY: stack-logs
stack-logs:
	$(COMPOSE) logs -f $(SERVICE)

.PHONY: svc-up
svc-up:
	@if [ -z "$(SERVICE)" ]; then echo "service is required (use service=<name>)"; exit 2; fi
	$(COMPOSE_ENV) $(COMPOSE) up -d $(SERVICE)

.PHONY: svc-restart
svc-restart:
	@if [ -z "$(SERVICE)" ]; then echo "service is required (use service=<name>)"; exit 2; fi
	$(COMPOSE) restart $(SERVICE)

.PHONY: svc-down
svc-down:
	@if [ -z "$(SERVICE)" ]; then echo "service is required (use service=<name>)"; exit 2; fi
	$(COMPOSE) stop $(SERVICE)

.PHONY: svc-logs
svc-logs:
	@if [ -z "$(SERVICE)" ]; then echo "service is required (use service=<name>)"; exit 2; fi
	$(COMPOSE) logs -f $(SERVICE)

.PHONY: svc-ps
svc-ps:
	@if [ -z "$(SERVICE)" ]; then echo "service is required (use service=<name>)"; exit 2; fi
	$(COMPOSE) ps $(SERVICE)

CMD ?= sh -lc 'bash || sh'
ifneq ($(strip $(cmd)),)
CMD := $(strip $(cmd))
endif
.PHONY: svc-exec
svc-exec:
	@if [ -z "$(SERVICE)" ]; then echo "service is required (use service=<name>)"; exit 2; fi
	$(COMPOSE) exec $(SERVICE) $(CMD)

.PHONY: svc-build
svc-build:
	@if [ -z "$(SERVICE)" ]; then echo "service is required (use service=<name>)"; exit 2; fi
	$(COMPOSE) build $(SERVICE)

WAIT_TIMEOUT ?= 180
ifneq ($(strip $(wait_timeout)),)
WAIT_TIMEOUT := $(strip $(wait_timeout))
endif
.PHONY: svc-wait
svc-wait:
	@if [ -z "$(SERVICE)" ]; then echo "service is required (use service=<name>)"; exit 2; fi
	@bash -lc '\
	end=$$(( $$(date +%s) + $(WAIT_TIMEOUT) )); \
	while true; do \
	  cid=$$($(COMPOSE) ps -q $(SERVICE)); \
	  [ -n "$$cid" ] || { echo "$(SERVICE): no container id yet"; sleep 2; continue; }; \
	  hs=$$(docker inspect -f "{{json .State.Health.Status}}" $$cid 2>/dev/null | tr -d '"'); \
	  if [ -n "$$hs" ]; then \
	    if [ "$$hs" = healthy ]; then echo "$(SERVICE): healthy"; exit 0; fi; \
	    echo "$(SERVICE): health=$$hs"; \
	  else \
	    rs=$$(docker inspect -f "{{.State.Running}}" $$cid 2>/dev/null); \
	    if [ "$$rs" = true ]; then echo "$(SERVICE): running (no healthcheck)"; exit 0; fi; \
	    echo "$(SERVICE): running=$$rs"; \
	  fi; \
	  [ $$(date +%s) -lt $$end ] || { echo "Timeout waiting for $(SERVICE)"; exit 1; }; \
	  sleep 3; \
	done'

.PHONY: stack-wait
stack-wait:
	@bash -lc '\
	services=$$($(COMPOSE) config --services); \
	code=0; \
	for s in $$services; do \
	  echo "Waiting for $$s..."; \
	  $(MAKE) --no-print-directory SERVICE=$$s WAIT_TIMEOUT=$(WAIT_TIMEOUT) svc-wait || code=1; \
	done; \
	exit $$code'

.PHONY: stack-status
stack-status:
	@bash -lc '\
	set -a; [ -f "$(ENVFILE)" ] && source "$(ENVFILE)" || true; set +a; \
	MAKE_PROJECT="$(PROJECT)"; \
	PN="$${COMPOSE_PROJECT_NAME:-$${MAKE_PROJECT:-rankalpha-local}}"; \
	API_PORT=$${API_PORT:-6080}; FRONTEND_PORT=$${FRONTEND_PORT:-3000}; AIRFLOW_WEB_PORT=$${AIRFLOW_WEB_PORT:-8080}; \
	BROKER_PORT=$${BROKER_PORT:-8000}; PROMETHEUS_PORT=$${PROMETHEUS_PORT:-9090}; \
	GRAFANA_PORT=$${GRAFANA_PORT:-3101}; LOKI_PORT=$${LOKI_PORT:-3100}; \
	CADVISOR_PORT=$${CADVISOR_PORT:-8085}; \
	echo "Project: $$PN"; \
	echo "API:      http://localhost:$$API_PORT"; \
	echo "Broker:   http://localhost:$$BROKER_PORT"; \
	echo "Frontend: http://localhost:$$FRONTEND_PORT"; \
	echo "Airflow:  http://localhost:$$AIRFLOW_WEB_PORT"; \
	echo "Prometheus: http://localhost:$$PROMETHEUS_PORT"; \
	echo "Grafana:    http://localhost:$$GRAFANA_PORT"; \
	echo "Loki API:   http://localhost:$$LOKI_PORT"; \
	echo "cAdvisor:   http://localhost:$$CADVISOR_PORT"; \
	echo "Docker GID (auto): $(DOCKER_GID)  Socket: $(DOCKER_SOCKET)"; \
	echo; \
	$(COMPOSE) ps;'

# ---------------------
# Broker convenience targets
# ---------------------
.PHONY: broker-build
broker-build:
	$(COMPOSE) build broker

.PHONY: broker-up
broker-up:
	$(COMPOSE_ENV) $(COMPOSE) up -d broker

.PHONY: broker-restart
broker-restart:
	$(COMPOSE) restart broker

.PHONY: broker-logs
broker-logs:
	$(COMPOSE) logs -f broker

.PHONY: broker-runner-up
broker-runner-up:
	@if [ -z "$(BROKER_ACCOUNT)" ]; then echo "BROKER_ACCOUNT not set (e.g., DU-changeme). Using default in compose."; fi
	@BROKER_ACCOUNT="$(BROKER_ACCOUNT)" $(COMPOSE_ENV) $(COMPOSE) up -d broker-runner

.PHONY: broker-runner-restart
broker-runner-restart:
	$(COMPOSE) restart broker-runner

.PHONY: broker-runner-logs
broker-runner-logs:
	$(COMPOSE) logs -f broker-runner

# Send a test signal to the broker service
# Vars: ACC (required), SYMBOL (default AAPL), ACTION (default buy), QTY (default 10), ORDER (MKT|LMT|STP|MOC, default MKT), LIMIT (for LMT)
.PHONY: broker-signal
broker-signal:
	@if [ -z "$(ACC)" ]; then echo "ACC=<ACCOUNT_NUMBER> is required"; exit 2; fi
	@bash -lc '\
	set -euo pipefail; \
	set -a; [ -f "$(ENVFILE)" ] && source "$(ENVFILE)" || true; set +a; \
	PROFILE="$${ENV:-local}"; \
	SYMBOL="$${SYMBOL:-AAPL}"; ACTION="$${ACTION:-buy}"; QTY="$${QTY:-10}"; ORDER="$${ORDER:-MKT}"; LIMIT="$${LIMIT:-}"; \
	TOKEN="$${BROKER_SERVICE_TOKEN:-$${AUTH_SERVICE_TOKEN:-}}"; \
	if [ -z "$$TOKEN" ] && [ -f "env/$$PROFILE/shared.env" ]; then \
	  TOKEN="$$(grep -E \"^(BROKER_SERVICE_TOKEN|AUTH_SERVICE_TOKEN)=\" \"env/$$PROFILE/shared.env\" | head -n1 | cut -d= -f2-)"; \
	  TOKEN="$${TOKEN#\\\"}"; TOKEN="$${TOKEN%\\\"}"; \
	fi; \
	if [ -z "$$TOKEN" ]; then \
	  echo \"Set BROKER_SERVICE_TOKEN (or AUTH_SERVICE_TOKEN). If using env profiles, put it in env/$$PROFILE/shared.env.\" >&2; \
	  exit 2; \
	fi; \
	EXTRA=\"\"; \
	if [ -n \"$$LIMIT\" ]; then EXTRA=\",\\\"limit_price\\\":$$LIMIT\"; fi; \
	curl -sS -X POST \"http://localhost:$${BROKER_PORT:-8000}/signal\" \
	  -H \"Content-Type: application/json\" \
	  -H \"X-RA-Service-Token: $$TOKEN\" \
	  -d \"{\\\"account\\\":\\\"$(ACC)\\\",\\\"symbol\\\":\\\"$$SYMBOL\\\",\\\"action\\\":\\\"$$ACTION\\\",\\\"quantity\\\":$$QTY,\\\"order_type\\\":\\\"$$ORDER\\\"$$EXTRA}\" \
	  | sed \"s/.*/[broker-signal] &/\"'

.PHONY: airflow-build
airflow-build:
	$(COMPOSE) build airflow-web airflow-scheduler airflow-worker airflow-triggerer airflow-init-dag ingestion scorer sentiment newswire

.PHONY: airflow-up
airflow-up:
	$(COMPOSE_ENV) $(COMPOSE) up -d rabbitmq database cache airflow-scheduler airflow-worker airflow-web

.PHONY: airflow-restart
airflow-restart:
	$(COMPOSE_ENV) $(COMPOSE) restart airflow-scheduler airflow-worker airflow-web

.PHONY: airflow-logs
airflow-logs:
	$(COMPOSE) logs -f airflow-worker

.PHONY: airflow-list-dags
airflow-list-dags:
	$(COMPOSE) exec airflow-web airflow dags list

.PHONY: airflow-trigger-pipeline
airflow-trigger-pipeline:
	$(COMPOSE) exec airflow-web airflow dags trigger rankalpha_pipeline

.PHONY: airflow-trigger-healthcheck
airflow-trigger-healthcheck:
	$(COMPOSE) exec airflow-web airflow dags trigger healthcheck

.PHONY: airflow-test-docker
airflow-test-docker:
	$(COMPOSE) exec airflow-web airflow dags trigger test_docker_operator

.PHONY: airflow-vars-network
airflow-vars-network:
	@bash -lc '\
	set -euo pipefail; \
	set -a; [ -f "$(ENVFILE)" ] && source "$(ENVFILE)" || true; set +a; \
	MAKE_PROJECT="$(PROJECT)"; \
	PN="$${COMPOSE_PROJECT_NAME:-$${MAKE_PROJECT:-rankalpha-local}}"; \
	NET="$${PN}_rankalpha_backend_network"; \
	echo "[airflow-vars-network] Setting DOCKER_NETWORK=$$NET"; \
	$(COMPOSE) exec airflow-web airflow variables set DOCKER_NETWORK "$$NET"'

.PHONY: airflow-worker-recreate
airflow-worker-recreate:
	@echo "Recreating airflow-worker with DOCKER_GID=$(DOCKER_GID)"
	$(COMPOSE_ENV) $(COMPOSE) up -d airflow-worker

.PHONY: docker-gid
docker-gid:
	@echo $(DOCKER_GID)

# -----------------------------------------
# Docs: render architecture diagram via Kroki
# -----------------------------------------
.PHONY: diagrams
diagrams: diagram-arch

.PHONY: diagram-arch
diagram-arch:
	@mkdir -p docs/images
	@curl -sS -X POST https://kroki.io/mermaid/svg -H 'Content-Type: text/plain' --data-binary @docs/diagrams/architecture.mmd > docs/images/architecture.svg
	@curl -sS -X POST https://kroki.io/mermaid/png -H 'Content-Type: text/plain' --data-binary @docs/diagrams/architecture.mmd > docs/images/architecture.png
	@mkdir -p apps/frontend/public/images
	@cp docs/images/architecture.svg apps/frontend/public/images/architecture.svg
	@cp docs/images/architecture.png apps/frontend/public/images/architecture.png
	@echo "Rendered diagrams → docs/images and copied to frontend public/images"
