# Functional Requirements

## Scope & Purpose
- Provide a headless trading executor for Interactive Brokers Client‑Portal Web API (IBKR CP), driven by database trade instructions and real‑time signals.
- Offer a multi‑account service with a simple HTTP API, safety controls, and daily reporting.

## Core Capabilities
- IBKR Connectivity
  - Authenticate via OAuth 1.0a (ibind) using RSA key files.
  - Keep session alive (`/tickle`), perform contract search, market snapshots, historical fetch, order placement/modification/cancel, open orders, account summary, and positions.
- Database‑Driven Execution
  - Read trade instructions (QuantDB) and size/place orders per account.
  - Multi‑account safety: idempotence and per‑account scoping use `rankalpha.fact_trade_recommendation` with `source_name = broker::<ACCOUNT_NUMBER>`; fills are recorded in `rankalpha.fact_portfolio_trade`.
- Real‑Time Signals
  - Accept ad‑hoc trade signals over HTTP and route them to a per‑account queue for immediate execution.
- Position Reconciliation
  - Compare IB positions with system state; generate exit transactions for unaccounted positions when enabled.
- Risk & Hedging (lightweight)
  - Track net liquidity and issue reminders or hedging suggestions based on thresholds.
- Daily Reporting
  - Produce an HTML email with holdings, account summary, open orders, and basic indicators (requires `GMAIL_SENDER`, `GMAIL_RECIPIENT`, `GMAIL_APP_PASSWORD`); optional Telegram mirroring.

## Service & APIs
- FastAPI Service (one executor per configured account)
  - `GET /health`: per‑account status (executing flag).
  - `GET /accounts`: discovered accounts.
  - `POST /signal`: enqueue a `RealTimeSignal {account,symbol,action,quantity,order_type,...}`.
  - `POST /report/{account}`: trigger daily report for the account.
- In‑process SignalBus ensures FIFO delivery per account.

## Scheduling & Market Calendar
- Execution loop runs only within configured market hours and skips non‑trading days.
- Calendar
  - `is_trading_day(date)`: Mon–Fri minus US equity holidays.
  - Early close support (e.g., Black Friday, Christmas Eve, July 3) with close time adjusted relative to open.
- Daily Report can be scheduled (cron/Task Scheduler) and additionally gated by `is_trading_day`.

## Safety & Controls
- Dry‑run: disable actual placement via per‑account flags.
- Human‑in‑the‑loop: optional Telegram confirmations for order sizing/submit.
- Price hygiene: optional limit‑price optimization (never cross the market).
- Logging: centralized configuration; error handling avoids crashes in schedulers or service loops.

## Data & Persistence
- PostgreSQL via SQLAlchemy models: `TradeTransaction`, `SystemTransaction`, `Portfolio`, `SystemRunStatus`.
- Tools
  - `tradeexec.tools.init_db`: optional sanity checks (no audit table required).
  - `tradeexec.tools.place_once`: one‑shot placement.
  - `tradeexec.tools.debug_env`: validate configuration.

## Configuration
- Pydantic settings with `.env` support; multi‑account via `ACCOUNT{N}_*` blocks (separate OAuth for broker and market data supported).
- Sensitive values supplied via environment variables and local key files; do not commit secrets.

## Non‑Functional
- Multi‑account orchestration (supervised executors) with minute‑level work loop.
- Tests: unit tests (no external deps) and optional integration tests (IBKR/Telegram/DB).
- Linting and typing enforced (ruff, mypy, pyright); CI workflow provided.

## Out of Scope
- Strategy generation, portfolio construction, and advanced broker routing are not implemented; the system executes instructions and performs light reconciliation/hedging only.

## Acceptance Criteria

### IBKR Connectivity
- Given valid OAuth credentials and key files, when the client initializes, then it can:
  - Return market snapshots with bid/ask/last/close for a resolved `conid`.
  - Fetch contract details for a `conid` and map to a symbol when available.
  - Place, modify, and cancel orders without unhandled exceptions; errors are logged.
- Given an idle session, when requests are made, then a keep‑alive (`/tickle`) is performed as needed.

### Database‑Driven Execution
- Given pending `TradeTransaction` rows, when `PlaceTransaction.execute()` runs during market hours, then eligible transactions are sized and orders are submitted or skipped with a reason in `ExecutionNote`.
- Given per‑account execution, when an order is placed, a row is upserted in `fact_trade_recommendation` with `is_live=true` and broker metadata (order id, trade_tx_id) in `preconditions`. This prevents duplicate submissions per account.

### Real‑Time Signals
- Given `POST /signal` with a known account and valid payload, when the service receives the request, then the signal is enqueued (FIFO) and processed by that account’s executor.

### Position Reconciliation
- Given IB positions and system state, when reconciliation runs with `close_unaccounted_positions=True`, then exit transactions are generated for IB holdings not present in system positions; otherwise no exits are generated.
- Given recent fills at IB, when `FilledPrice` is empty, then `FilledPrice` is updated from IB average cost where available.

### Risk & Hedging
- Given a configured hedge threshold, when portfolio drawdown exceeds the threshold, then a reminder/hedge suggestion is logged or emitted without crashing the loop.

### Daily Reporting
- Given valid Gmail config, when the report runs on a trading day, then an HTML email is sent with: holdings, account summary, and open orders (and optional Telegram mirror). If Gmail config is missing, the report logs the failure and continues without raising.

### Service API
- `GET /health` returns a JSON map of accounts to `{account, executing}`.
- `GET /accounts` returns the discovered account list from settings.
- `POST /report/{account}` triggers report generation for the account and returns `{status: "sent"}` (or 404 for unknown account).

### Scheduling & Calendar
- Given local open/close times, when `_within_market_hours` evaluates, then it returns true only on `is_trading_day(date)` and before early close when applicable.
- Given a daily scheduler, when `is_trading_day(today)` is false (weekend/holiday), then the report and executor skip without errors.

### Safety & Controls
- Given `ACCOUNTN_EXECUTE_ORDER=False`, when the executor runs, then it logs intended actions but does not place orders.
- Given Telegram is configured and confirmations are enabled, when a trade requires confirmation, then the bot presents inline options and applies the user’s choice or times out safely.

### Configuration & Secrets
- Given a well‑formed `.env`, when the app starts, then settings resolve without validation errors and key files are verified (or a clear error is raised).
- No sensitive tokens or key contents are checked into version control.

### Data & Tooling
- `tradeexec.tools.init_db --apply` currently no‑ops (reserved for future broker-local migrations).
- `tradeexec.tools.debug_env` prints effective settings including account discovery and key paths.
- `tradeexec.tools.place_once <ACCOUNT>` processes a single placement cycle and exits with a clear log of outcomes.
