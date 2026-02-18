# TradeExec (IBKR Web API)

Python 3.12 trading executor that talks to **Interactive Brokers Client‑Portal Web API** (OAuth 1.0a via `ibind`), pulls trades from the shared **PostgreSQL** database, supports **multiple accounts**, optional **Telegram** confirmations, a **FastAPI** service with real‑time signals, and a **daily HTML report** via Gmail.

> Use a **paper** account first. You are responsible for your orders. Configure confirmations before live trading.

---

## Table of Contents
- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Configuration (.env)](#configuration-env)
  - [Multiple Accounts](#multiple-accounts)
  - [Database](#database)
  - [Telegram (optional)](#telegram-optional)
  - [Email (optional)](#email-optional)
- [Install](#install)
- [Run Modes](#run-modes)
  - [A) Single Pass (per account)](#a-single-pass-per-account)
  - [B) Continuous Runner (per account)](#b-continuous-runner-per-account)
  - [C) Service Mode (multi‑account, FastAPI + async bus)](#c-service-mode-multiaccount-fastapi--async-bus)
  - [D) Docker](#d-docker)
  - [E) Daily Report](#e-daily-report)
- [API Endpoints](#api-endpoints)
  - [Rates: SOFR Futures](#rates-sofr-futures)
- [Command Cheatsheet](#command-cheatsheet)
- [Testing](#testing)
- [Operational Safety](#operational-safety)
- [Troubleshooting](#troubleshooting)
- [Project Layout](#project-layout-selected)

---

## Quick Start

```bash
# 1) Copy env and edit
cp .env.example .env
# Fill IB OAuth, DB, and (optional) Telegram/Gmail

# 2) Install deps (Python 3.12+)
uv pip install -e .

# 3) (Optional) DB sanity checks
uv run -m tradeexec.tools.init_db --apply

# 4) Smoke checks
uv run -m tradeexec.tools.debug_env
python test_db_connection.py

# 5) One-shot placement (DB -> IB) for a specific account
uv run -m tradeexec.tools.place_once DU-changeme

# 6) Or run continuously for that account (market hours)
uv run -m tradeexec.trade_execution DU-changeme

# 7) Or run the multi-account service API (restarts executors forever)
uvicorn tradeexec.service:app --host 0.0.0.0 --port 8000
```

---

## Prerequisites

- **Python**: 3.12+
- **IBKR Client‑Portal Web API** access via **OAuth 1.0a** (no TWS/Gateway):
  - `consumer_key`, `access_token`, `access_token_secret`
  - Key files: `private_encryption.pem`, `private_signature.pem`
  - Optional: `IB_OAUTH_DH_PRIME` (Diffie‑Hellman prime)
- **PostgreSQL** reachable from this host (uses a shared DB with other apps)
- (Optional) **Telegram** bot + chat ID (interactive confirmations/alerts)
- (Optional) **Gmail** app password (daily HTML report)

> If your CA bundle is non‑standard, set `IBIND_CACERT` to a custom PEM.

---

## Configuration

IBKR‑specific secrets are read from `env/{RANKALPHA_ENV}/broker.env` (preferred) or `apps/broker/.env` (local fallback). Key files (`private_encryption.pem`, `private_signature.pem`) should be stored outside of source control (e.g., `env/{ENV}/broker/`). The loader resolves key paths in this order:

1) exact path as provided
2) relative to `apps/broker/`
3) `env/{ENV}/broker/<filename>`
4) `env/{ENV}/<filename>`

Tip: either set absolute/relative paths in env, or just provide the filename and place the PEMs in `env/{ENV}/broker/`.

### Ports & Environment Overrides (multi‑stack safe)

- Service API (FastAPI) port
  - `BROKER_PORT` (default `8000`): container listen port and host publish in Compose.
  - Choose a unique value per stack to avoid conflicts with the API service (`API_PORT`, default `6080`).

- Runner health port (per‑account executor, no HTTP API)
  - `BROKER_RUNNER_HEALTH_PORT` (default `8795`): container listen port for `/health`.
  - `BROKER_RUNNER_HEALTH_PORT_HOST` (default `8795`): host port published for the runner health endpoint.

Example `.compose.env` overrides for a secondary stack (e.g., test):

```
COMPOSE_PROJECT_NAME=rankalpha-test
ENV=test
# Avoid collisions with prod/default
API_PORT=6081
FRONTEND_PORT=3001
BROKER_PORT=8001
BROKER_RUNNER_HEALTH_PORT=8796
BROKER_RUNNER_HEALTH_PORT_HOST=8796
```
Shared settings (DB, Gmail, Telegram) now live in `env/{ENV}/shared.env` and are loaded via `apps.common.src.settings_base.BaseAppSettings`.

Example broker.env (per-account config): see `env/example/broker.env.example`.

## Observability
- The FastAPI service auto-exposes Prometheus metrics at `/metrics` (request throughput, latency percentiles, in-flight gauges) and emits OpenTelemetry spans. Configure the OTLP endpoint or service name via `OTEL_EXPORTER_OTLP_*` in `broker.env`.
- When running under Docker Compose, metrics are scraped by Prometheus and traces are collected by Grafana Tempo (see `docs/observability.md`). Override host ports through `.compose.env` (`PROMETHEUS_PORT`, `GRAFANA_PORT`, etc.) if multiple stacks share a host.

### IBKR rate limits & caching

Interactive Brokers enforces per-endpoint throttles on the Client-Portal Web API. The broker app now ships with token buckets and semaphores that keep traffic within IBKR’s published limits. Tune them via environment variables if your account has different allowances (e.g., on-prem bridge vs. hosted CP Gateway):

- `IBKR_GLOBAL_RPS` / `IBKR_GLOBAL_BURST` (defaults: 40 rps / burst=rate) – global cap per IB username across all endpoints.
- `IBKR_SNAPSHOT_RPS` (default `8`) – `/iserver/marketdata/snapshot` quota.
- `IBKR_HISTORY_RPS` and `IBKR_HISTORY_MAX_CONCURRENCY` (defaults: `4` rps / `5` concurrent) – `/iserver/marketdata/history` pacing plus in-flight limit.
- `IBKR_ORDERS_RPS` (default `0.2`, i.e., one order/cancel every 5 seconds) – `/iserver/orders` (place/modify/cancel/live) calls.
- `BROKER_ORDER_PACE_SECONDS` (default `5`) – app-level spacing between order submissions (DB placements, hedges, real-time signals).

FastAPI `/price` and `/price/prev-close` endpoints also cache results briefly to avoid hammering the upstream API:

- `BROKER_PRICE_CACHE_TTL_SECONDS` (default `5`) – in-memory TTL for snapshot quotes per symbol/account/exchange.
- `BROKER_PREV_CLOSE_CACHE_TTL_SECONDS` (default `30`) – TTL for previous-close lookups (history or snapshot fallback).

Set the TTLs to `0` to disable caching entirely.

### Multiple Accounts

Define one or more `ACCOUNT{N}_*` sections. Each corresponds to an executor, with distinct OAuth keys. The service will discover them automatically. An explicit system whitelist is REQUIRED: if an account has no `SYSTEM_NAME{M}` entries, the runner will skip DB‑driven placements and ignore real‑time signals for that account.

```dotenv
# ----------------- Account 1 -----------------
ACCOUNT1_ACCOUNT_NUMBER=DU-changeme
ACCOUNT1_EXECUTE_ORDER=True
ACCOUNT1_WAIT_FOR_CONFIRMATION=False
ACCOUNT1_OPTIMIZE_PRICE=False
ACCOUNT1_CLOSE_UNACCOUNTED_POSITIONS=True
ACCOUNT1_HEDGE_THRESHOLD=0.95

# OAuth for placing orders (required)
ACCOUNT1_BROKER_OAUTH_CONSUMER_KEY=...
ACCOUNT1_BROKER_OAUTH_ACCESS_TOKEN=...
ACCOUNT1_BROKER_OAUTH_ACCESS_TOKEN_SECRET=...
ACCOUNT1_BROKER_OAUTH_ENCRYPTION_KEY_FP=private_encryption.pem
ACCOUNT1_BROKER_OAUTH_SIGNATURE_KEY_FP=private_signature.pem
# ACCOUNT1_BROKER_OAUTH_DH_PRIME=...

# Optional: separate OAuth for market data (else broker OAuth is reused)
# ACCOUNT1_MARKET_OAUTH_CONSUMER_KEY=...
# ACCOUNT1_MARKET_OAUTH_ACCESS_TOKEN=...
# ACCOUNT1_MARKET_OAUTH_ACCESS_TOKEN_SECRET=...

# Whitelisted systems + allocation per system (examples)
ACCOUNT1_SYSTEM_NAME1=FixedSizeMomentum0-Hyper
ACCOUNT1_TRADING_FUND1=BuyingPower
ACCOUNT1_POSITION_ALLOCATION_PERCENT1=0.25

ACCOUNT1_SYSTEM_NAME2=FixedSizeMomentum1
ACCOUNT1_TRADING_FUND2=BuyingPower
ACCOUNT1_POSITION_ALLOCATION_PERCENT2=0.25

# ----------------- Account 2 -----------------
ACCOUNT2_ACCOUNT_NUMBER=U1234567
ACCOUNT2_EXECUTE_ORDER=True
ACCOUNT2_WAIT_FOR_CONFIRMATION=True
ACCOUNT2_OPTIMIZE_PRICE=True

ACCOUNT2_BROKER_OAUTH_CONSUMER_KEY=...
ACCOUNT2_BROKER_OAUTH_ACCESS_TOKEN=...
ACCOUNT2_BROKER_OAUTH_ACCESS_TOKEN_SECRET=...
ACCOUNT2_BROKER_OAUTH_ENCRYPTION_KEY_FP=private_encryption.pem
ACCOUNT2_BROKER_OAUTH_SIGNATURE_KEY_FP=private_signature.pem
```

### Market-Data Only Account

To run a dedicated account for market data (e.g., paper account for quotes, live account for orders):

- Set `ACCOUNTN_EXECUTE_ORDER=false` so the runner never places trades.
- Leave the broker OAuth fields blank (or dummy) and fill only `ACCOUNTN_MARKET_OAUTH_*` with that account’s Client-Portal keys.
- Example:

```dotenv
# Account 3 – market data only
ACCOUNT3_ACCOUNT_NUMBER=DU0000000
ACCOUNT3_EXECUTE_ORDER=false
ACCOUNT3_WAIT_FOR_CONFIRMATION=false
# Broker OAuth omitted so this account never places orders
ACCOUNT3_BROKER_OAUTH_CONSUMER_KEY=
ACCOUNT3_BROKER_OAUTH_ACCESS_TOKEN=
ACCOUNT3_BROKER_OAUTH_ACCESS_TOKEN_SECRET=
ACCOUNT3_BROKER_OAUTH_ENCRYPTION_KEY_FP=
ACCOUNT3_BROKER_OAUTH_SIGNATURE_KEY_FP=
# Market data OAuth for this account
ACCOUNT3_MARKET_OAUTH_CONSUMER_KEY=md-key
ACCOUNT3_MARKET_OAUTH_ACCESS_TOKEN=md-token
ACCOUNT3_MARKET_OAUTH_ACCESS_TOKEN_SECRET=md-secret
ACCOUNT3_MARKET_OAUTH_ENCRYPTION_KEY_FP=paper_encryption.pem
ACCOUNT3_MARKET_OAUTH_SIGNATURE_KEY_FP=paper_signature.pem
```

When the service starts, each `ExecutionProgram` maintains separate `broker_ib` (orders) and `market_ib` (quotes) sessions. Endpoints such as `/price` or `/rates/sofr-futures` use whichever program has a live `market_ib` session; orders still route through accounts with `EXECUTE_ORDER=true`.

System settings pattern
- Name format: `ACCOUNT{N}_SYSTEM_NAME{M}`, `ACCOUNT{N}_TRADING_FUND{M}`, `ACCOUNT{N}_POSITION_ALLOCATION_PERCENT{M}`.
- Indexing: {M} starts at 1 per account and must be contiguous (1,2,3,…). The loader stops when `SYSTEM_NAME{M}` is missing.
- Allocation: `POSITION_ALLOCATION_PERCENT{M}` is a 0..1 fraction. The sum across systems per account should be ≤ 1.0. Currently used for visibility and future sizing controls; order placement uses explicit `Size`/`SizePercent` from `TradeTransaction` today.
- Trading fund: a label (e.g., `BuyingPower`), reserved for future cash‑bucket routing.

Real‑time signals and whitelist
- By default, the runner enforces the per‑account whitelist for both DB‑driven placements and real‑time signals.
- You can relax real‑time enforcement in two ways:
  1) Add a catch‑all tag (default `real-time`) to the whitelist and tag your signals with it (see `BROKER_REALTIME_SYSTEM_NAME`).
  2) Set `BROKER_ALLOW_REALTIME_WITHOUT_SYSTEM=true` to accept signals even when they lack a system tag or the tag isn’t in the whitelist.
- Env keys (broker.env):
  - `BROKER_REALTIME_SYSTEM_NAME=real-time`
  - `BROKER_ALLOW_REALTIME_WITHOUT_SYSTEM=false`

> Validate accounts & key paths:
> ```bash
> uv run -m tradeexec.tools.debug_env
> ```

### Database

The broker uses the shared PostgreSQL configuration from `env/{ENV}/api.env` (same as API/other apps). No separate DB settings are needed in `broker.env`.

### Market Hours (with Timezone)

- Set `MARKET_TIMEZONE` (IANA, default `America/New_York`). The runner evaluates `MARKET_OPEN_TIME` and `MARKET_CLOSE_TIME` in this timezone.
- Daylight Saving Time is handled automatically by `zoneinfo`; keep open/close as local market times (e.g., 09:30–16:00) and they will track DST correctly.

Run a quick DB sanity check or apply broker-local migrations (no-op by default):
  ```bash
  uv run -m tradeexec.tools.init_db --apply
  ```

### Telegram (optional)

- Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- If `ACCOUNTN_WAIT_FOR_CONFIRMATION=True`, Telegram will prompt with inline choices: **100%**, **50%**, **MOC**, **Delay**, **Cancel**.

### Email (optional)

- Set `GMAIL_SENDER`, `GMAIL_RECIPIENT`, and `GMAIL_APP_PASSWORD` in the environment.
- GmailSMTP now requires these values; if any are missing, email delivery raises an error.
- See `reports/daily.py` for HTML email details.

---

## Install

```bash
# Using uv (recommended)
uv pip install -e .

# Or plain pip
pip install -e .
```

---

## Run Modes

### A) Single Pass (per account)

Runs one DB placement cycle and exits. Good for smoke tests and migration checks.

```bash
uv run -m tradeexec.tools.place_once DU-changeme
# add --allow-legacy to bypass optional safety checks
```

### B) Continuous Runner (per account)

Connects to IBKR via OAuth, keeps the session warm (`/tickle`), and loops during market hours: reconcile positions, size & place orders, and do lightweight hedging/reminders.

```bash
uv run -m tradeexec.trade_execution DU-changeme
```

Honors **per-account** flags:
- `ACCOUNTN_EXECUTE_ORDER` — if `False`, logs actions without placing
- `ACCOUNTN_WAIT_FOR_CONFIRMATION` — Telegram confirmation gate
- `ACCOUNTN_OPTIMIZE_PRICE` — nudge limit price toward inside/mid (never cross)
- `ACCOUNTN_CLOSE_UNACCOUNTED_POSITIONS` — create exit txns for IB positions not in system

### C) Service Mode (multi‑account, FastAPI + async bus)

Boots a manager that starts one **supervised** `ExecutionProgram` per configured account, keeps them running **forever**, and exposes an API for **real‑time signals** per account.

```bash
uvicorn tradeexec.service:app --host 0.0.0.0 --port 8000
```

See [API Endpoints](#api-endpoints) for the full HTTP surface (health, accounts, signal, report, price).

**Example**

```bash
curl -X POST http://localhost:8000/signal   -H "content-type: application/json"   -H "X-RA-Service-Token: $BROKER_SERVICE_TOKEN"   -d '{
        "account":"DU-changeme",
        "symbol":"AAPL",
        "action":"buy",
        "quantity":100,
        "order_type":"LMT",
        "limit_price":222.50,
        "system":"FixedSizeMomentum0",
        "tag":"API",
        "custom_string":"Ticket-42"
      }'
```

The service uses an in‑process async **SignalBus**; swap for Redis/Kafka later if you need multi‑process distribution.

### D) Docker

A minimal image is provided.

```bash
# Build
docker build -t tradeexec:latest .

# Run service (mount .env and OAuth key files)
docker run --rm -p 8000:8000   -v $PWD/.env:/app/.env   -v $PWD/private_encryption.pem:/app/private_encryption.pem   -v $PWD/private_signature.pem:/app/private_signature.pem   tradeexec:latest

# Run a dedicated per-account executor container
docker run --rm   -v $PWD/.env:/app/.env   -v $PWD/private_encryption.pem:/app/private_encryption.pem   -v $PWD/private_signature.pem:/app/private_signature.pem   tradeexec:latest   uv run -m tradeexec.trade_execution DU-changeme
```

### E) Daily Report

Send an HTML daily account report via Gmail (optionally mirror to Telegram). The report includes holdings, account summary, and open orders.

Run ad‑hoc:

```bash
uv run -m tradeexec.reports.daily
# Or via the service API (per account):
curl -X POST http://localhost:8000/report/DU-changeme -H "X-RA-Service-Token: $BROKER_SERVICE_TOKEN"
```

Scheduling (skip weekends automatically):

- Option 1 — OS scheduler Mon–Fri
  - Linux/macOS (cron): `30 7 * * 1-5 cd /path/to/ibkrwebapi && uv run -m tradeexec.reports.daily`
  - Windows Task Scheduler: weekly trigger Mon–Fri → `uv run -m tradeexec.reports.daily`

- Option 2 — daily trigger + calendar guard (holidays & weekends)
  ```python
  from datetime import date
  from tradeexec.utils.market_calendar import is_trading_day
  from tradeexec.core.ib import IBInterfacing
  from tradeexec.reports.daily import DailyReport

  if is_trading_day(date.today()):
      DailyReport(IBInterfacing(use_global_settings=True)).email_report()
  ```

Notes: The market calendar (utils/market_calendar.py) covers US holidays and common early‑close days (e.g., Black Friday). Adjust scheduler time to your local timezone.

See `docs/scheduling` for ready‑to‑use cron and Windows Task Scheduler templates.

---

## API Endpoints

All routes live in `tradeexec/service.py`. The service listens on `http://localhost:8000` by default (override with `BROKER_PORT`). Errors use FastAPI’s JSON problem details payload with a `detail` field.

All endpoints except `GET /health` require a service token (set `BROKER_SERVICE_TOKEN` or `AUTH_SERVICE_TOKEN`) and accept either `X-RA-Service-Token: <token>` or `Authorization: Bearer <token>`.

- **`GET /health`** – Returns executor status keyed by account (`executing` indicates the supervised loop is active).

  ```json
  {
    "DU-changeme": {"account": "DU-changeme", "executing": true},
    "DU7654321": {"account": "DU7654321", "executing": false}
  }
  ```

- **`GET /accounts`** – Lists all configured IB account numbers.

  ```json
  ["DU-changeme", "DU7654321"]
  ```

- **`POST /signal`** – Publishes a real-time trading signal for the specified account. Returns 404 if the account is unknown.

  Request body:

  ```json
  {
    "account": "DU-changeme",
    "symbol": "AAPL",
    "action": "buy",
    "quantity": 100,
    "order_type": "MKT",
    "limit_price": null,
    "stop_price": null,
    "system": "FixedSizeMomentum0-Hyper",
    "tag": "intraday",
    "custom_string": "ticket-123"
  }
  ```

  Order types:
  - Supported: `MKT`, `LMT`, `STP`, `STP LMT`, `MOC`, `MOO` (friendly names like `Market`, `Limit`, `StopLimit` are normalized).
  - `STP` requires `stop_price`.
  - `STP LMT` requires both `stop_price` (trigger) and `limit_price` (limit).
  - Unrecognized strings are upper-cased and passed through to IBKR; invalid values will be rejected by the API.

  Success response:

  ```json
  {"status": "queued", "account": "DU-changeme", "symbol": "AAPL"}
  ```

### Rates: SOFR Futures

- **`GET /rates/sofr-futures`** – Returns a compact SOFR futures chain for SR3 (3M) or SR1 (1M) with last and settle.

  Query params:
  - `root` (string, default `SR3`): `SR3` for 3M SOFR futures, `SR1` for 1M SOFR futures.
  - `limit` (int, default `8`): how many contracts to return from the front.
  - `account` (string, optional): IB account to use; defaults to the first configured.

  Example:

  ```bash
  curl -H "X-RA-Service-Token: $BROKER_SERVICE_TOKEN" 'http://localhost:8000/rates/sofr-futures?root=SR3&limit=6'
  ```

  Response:

  ```json
  {
    "account": "DU-changeme",
    "root": "SR3",
    "exchange": "GLOBEX",
    "items": [
      {
        "root": "SR3",
        "local_symbol": "SR3Z25",
        "conid": 123456789,
        "year": 2025,
        "month": 12,
        "expiry": "202512",
        "last": 95.32,
        "settle": 95.28
      }
      // ...
    ]
  }
  ```

  Notes:
  - Requires IBKR market data entitlements for CME SOFR futures.
  - Uses IBKR `trsrv/futures` for directory + `marketdata/snapshot` for last/close.
  - The ingestion pricer (`apps/ingestion/src/fra_ois_pricer.py`) consumes this endpoint to build a SOFR‑based discount curve and to derive FRA rates from futures.

- **`GET /rates/sofr-futures/history`** – Returns daily EOD bars (1‑day bar size) for the front SOFR futures (SR3 or SR1) over the last N years (IBKR limit ≈2y).

  Query params:
  - `root` (string, default `SR3`): `SR3` (3M) or `SR1` (1M).
  - `years` (int, default `2`): lookback window; clamped to [1, 2].
  - `limit` (int, default `16`): how many front contracts to include.
  - `account` (string, optional): IB account override.

  Example:

  ```bash
  curl -H "X-RA-Service-Token: $BROKER_SERVICE_TOKEN" 'http://localhost:8000/rates/sofr-futures/history?root=SR3&years=2&limit=12'
  ```

  Response (abridged):

  ```json
  {
    "account": "DU-changeme",
    "root": "SR3",
    "exchange": "GLOBEX",
    "period": "2 y",
    "items": [
      {
        "root": "SR3",
        "local_symbol": "SR3H25",
        "conid": 123456789,
        "year": 2025,
        "month": 3,
        "expiry": "202503",
        "bars": [
          {"as_of_date": "2024-12-02", "close": 95.38, "open": 95.35, "high": 95.40, "low": 95.32, "volume": 12345},
          {"as_of_date": "2024-12-03", "close": 95.40, ...}
        ]
      }
    ]
  }
  ```

  Notes:
  - Designed for ingestion backfills of FRA/OIS history; returns only daily bars (no intraday).
  - Bars are best-effort; contracts missing conid or data are skipped.

- **`POST /report/{account}`** – Triggers the daily report email for the account. Returns 404 when the account is not configured.

  ```json
  {"status": "sent"}
  ```

- **`GET /price/{symbol}`** – Retrieves an Interactive Brokers snapshot quote. Optional query parameters:
  - `account`: override the default (first configured) account.
  - `exchange`: pass-through to contract search (defaults: `STK→SMART`, `FUT→GLOBEX`, `FX/CASH→IDEALPRO`).

  Returns 503 if no accounts are active and 502 for upstream IBKR failures.

  ```json
  {
    "account": "DU-changeme",
    "symbol": "AAPL",
    "bid": 208.77,
    "ask": 208.79,
    "last": 208.78,
    "close": 207.99,
    "raw": {
      "31": "208.78",
      "55": "208.77",
      "84": "208.79",
      "86": "207.99",
      "bid": 208.77,
      "ask": 208.79,
      "last": 208.78,
      "close": 207.99
    }
  }
  ```

- **`GET /price/prev-close/{symbol}`** – Returns the previous trading day’s close from IBKR.
  - Uses daily historical bars for an authoritative “yesterday close”. If unavailable, falls back to the snapshot’s prior close field (never last price).
  - Optional query parameters (hard defaults: `STK→SMART`, `FUT→GLOBEX`, `FX/CASH→IDEALPRO`):
    - `account` – override default account
    - `exchange` – contract search hint / override
    - `sec_type` – `STK` (default) | `FUT` | `CASH` (alias: `FX`)
    - `currency` – for FX pairs when symbol is only the base (e.g., `EUR` + `currency=USD`)

  Examples
  - US stock: `/price/prev-close/AAPL`
  - E-mini S&P future: `/price/prev-close/ESZ5?sec_type=FUT&exchange=GLOBEX`
  - FX: `/price/prev-close/EURUSD?sec_type=FX` or `/price/prev-close/EUR?sec_type=CASH&currency=USD`

  ```json
  {
    "account": "DU-changeme",
    "symbol": "AAPL",
    "previous_close": 207.99,
    "as_of": "2024-10-11",
    "source": "history",
    "raw": { "open": 208.5, "high": 210.2, "low": 206.9, "close": 207.99, "volume": 41234567, "date": "2024-10-11" }
  }
  ```

---

## Command Cheatsheet

```bash
# Inspect resolved settings (accounts, key paths, DB URL)
uv run -m tradeexec.tools.debug_env

# Optional DB checks (no audit table required)
uv run -m tradeexec.tools.init_db --apply

# One-shot placement
uv run -m tradeexec.tools.place_once <ACCOUNT_NUMBER>

# Continuous runner
uv run -m tradeexec.trade_execution <ACCOUNT_NUMBER>

# Multi-account service API
uvicorn tradeexec.service:app --host 0.0.0.0 --port 8000
```

---

## Placing Orders Into `rankalpha.fact_trade_recommendation`

This table holds trade intent (recommendations) and execution metadata shared across the stack. The broker executor uses it to:

- Deduplicate per account (source_name = `broker::<ACCOUNT_NUMBER>`), and
- Mark fills (filled_price / filled_date) when executions are observed.

Two supported ways to upsert recommendations:

- A) REST API (recommended for external tools)
- B) Python (direct via the shared CRUD helper)

Notes
- Uniqueness: a recommendation is unique per `(date_key, stock_key, source_key, action)`. Use a consistent `source_name` to avoid accidental duplicates.
- Per‑account scoping: to scope a recommendation to an IB account, set `source_name = broker::<ACCOUNT_NUMBER>` (e.g., `broker::DU-changeme`). The broker uses this to dedupe per account and to update fills.
- `is_live` is set by the broker on placement; you typically don’t set it yourself.
- Optional `portfolio_id` routes an idea to a specific logical book; if omitted, the broker auto‑creates/uses a portfolio with `portfolio_name=<ACCOUNT_NUMBER>` on fill.

### A) REST: POST /api/v1/trading/signals

Pre‑req: set `TRADING_BEARER_TOKEN` in the API service and use it as a Bearer token.

Example:

```bash
curl -X POST "$NEXT_PUBLIC_API_URL/api/v1/trading/signals" \
  -H "Authorization: Bearer $TRADING_BEARER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "symbol": "AAPL",
        "action": "BUY",
        "as_of_date": "2025-10-08",
        "recommended_price": 182.45,
        "order_type": "LIMIT",
        "limit_price": 182.50,
        "time_in_force": "DAY",
        "size_percent": 2.5,
        "source_name": "broker::DU-changeme",
        "strategy_name": "Breakout-Oct"
      }'
```

Verify via the view:

```sql
SELECT *
FROM rankalpha.vw_trade_recommendation
WHERE source_name = 'broker::DU-changeme' AND symbol = 'AAPL'
ORDER BY recommendation_date DESC;
```

### B) Python: apps.common.src.crud.upsert_trade_recommendation

```python
from datetime import date
from sqlalchemy.orm import Session
from apps.common.src.crud import get_engine, upsert_trade_recommendation

with Session(get_engine()) as sess:
    rec_id = upsert_trade_recommendation(sess, {
        "symbol": "AAPL",
        "action": "BUY",
        "as_of_date": date.today().isoformat(),
        "recommended_price": 182.45,
        "order_type": "LIMIT",
        "limit_price": 182.50,
        "time_in_force": "DAY",
        "size_percent": 2.5,
        "source_name": "broker::DU-changeme",
        "strategy_name": "Breakout-Oct",
        # optional: portfolio_id (UUID), routing_hint, risk_budget_bps, preconditions, etc.
    })
    print("recommendation_id=", rec_id)
```

### How the Broker Uses These Rows

- The executor reads pending trades from `rankalpha.fact_trade_recommendation` for each account (scoped by `source_name=broker::<ACCOUNT>`), filtered by `is_live=false`, `valid_from_ts` (≤ now) and `expiry_ts` (not expired).
- The per‑account system whitelist is applied via `strategy_name` ∈ {whitelisted systems}.
- On placement, the broker marks the recommendation live (`is_live=true`) and sets IB metadata in `preconditions`.
- When a fill is observed from IBKR, the broker writes a trade into `rankalpha.fact_portfolio_trade` (idempotent) and updates the matching recommendation with `filled_price` and `filled_date`.

---

## Testing

Run the fast unit tests by default; run integration tests only when credentials are available.

Unit tests (no external services):

```bash
# Core utilities & mocks (quick)
uv run pytest -q \
  tests/test_market_calendar.py \
  tests/test_events_signal_bus.py \
  tests/test_logging_setup.py \
  tests/test_order_place_transaction_mocks.py \
  tests/test_reconcile_helpers.py
```

All tests (includes integration; requires creds):

```bash
uv run pytest -v
```

- IBKR integration: needs OAuth in `.env` (use a paper account)
- Telegram integration: set `TEST_TELEGRAM_BOT_TOKEN` and `TEST_TELEGRAM_CHAT_ID`
- Database: `python test_db_connection.py` verifies engine/session

Lint & types:

```bash
uv run ruff check .
uv run mypy tradeexec
uv run pyright
```

---

## Operational Safety

- To **dry‑run**: set `ACCOUNTN_EXECUTE_ORDER=False`.
- Enable **human‑in‑the‑loop**: `ACCOUNTN_WAIT_FOR_CONFIRMATION=True` (Telegram required).
- The **reconciler** can emit **MOC** exits for positions that exist at IB but not in your system (`ACCOUNTN_CLOSE_UNACCOUNTED_POSITIONS=True`).
- Logging: `LOG_LEVEL` (`DEBUG` | `INFO` | `WARNING` | `ERROR`).

---

## Troubleshooting

- **Key files not found**: ensure `private_encryption.pem` and `private_signature.pem` exist at paths declared in `.env`; the loader checks relative to repo root as well.
- **DB connection errors**: verify `database_name`, `db_username`, `password`, `host`, `port` in `env/{ENV}/api.env`, or set a full `DATABASE_URL` (e.g., `postgresql+psycopg2://user:pass@host:5432/db`). Run `python test_db_connection.py` to see the effective URL.
- **Session drops**: the wrapper hits `/tickle`; if your infra kills idle sockets, add a reverse proxy with aggressive keep‑alive or shorten tickle intervals.
- **Timezones**: scheduler defaults target US/Eastern (market) and US/Mountain (report). Adjust to your deployment.

---

## Project Layout (selected)

```
tradeexec/
  core/ib.py                   # IBKR Web API wrapper (OAuth, tickle, quotes, hist, orders)
  events.py                    # Async SignalBus + RealTimeSignal dataclass
  trade_execution.py           # Per-account runner + supervised forever loop
  order/place_transaction.py   # DB -> IB placement, sizing, confirmations, price nudge
  order/order_placement.py     # Open-order adjustments & chunking helpers
  order/reconcile_positions.py # Reconcile IB vs System/DB; create exit txns
  risk/portfolio_management.py # Simple hedging / reminders
  reports/daily.py             # HTML daily report via Gmail (optional Telegram copy)
  comms/telegram.py            # Telegram bot integration
  service.py                   # FastAPI multi-account manager + endpoints
  settings.py                  # Pydantic settings (.env, multi-account)
  tools/init_db.py             # Optional DB checks (no audit table required)
  tools/place_once.py          # Single cycle DB placement tool
  tools/debug_env.py           # Prints resolved settings + sanity checks
  test_db_connection.py        # Simple DB connectivity test
```
