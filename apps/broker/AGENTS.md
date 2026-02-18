# Repository Guidelines

## Project Structure & Modules
- Code: `tradeexec/` — core IBKR client, order flow, FastAPI service, reports, risk, comms, database models, and tooling (`tools/*`).
- Tests: `tests/` (pytest + asyncio) and `test_db_connection.py`.
- Config & Ops: `.env`, `.env.example`, `pyproject.toml`, `pyrightconfig.json`, `Dockerfile`, `migrations/`.
- Service entry: `tradeexec.service:app`; per‑account runner: `tradeexec.trade_execution`.

## Build, Test, and Development
- Install: `uv pip install -e .` (or `pip install -e .`).
- Optional DB checks: `uv run -m tradeexec.tools.init_db --apply`.
- One‑shot placement: `uv run -m tradeexec.tools.place_once <ACCOUNT>`.
- Continuous executor: `uv run -m tradeexec.trade_execution <ACCOUNT>`.
- API service (multi‑account): `uvicorn tradeexec.service:app --host 0.0.0.0 --port 8000`.
- Tests (quick, unit-only):
  - `uv run pytest -q tests/test_market_calendar.py tests/test_events_signal_bus.py tests/test_logging_setup.py tests/test_order_place_transaction_mocks.py tests/test_reconcile_helpers.py`
- Tests (all, incl. integration): `uv run pytest -v` (requires `.env`).

## Coding Style & Naming
- Python 3.12; max line length 100.
- Lint/format: `uv run ruff check .` and `uv run ruff format .`.
- Type checks: `uv run mypy tradeexec` and `uv run pyright`.
- Naming: files/modules `snake_case.py`; classes `PascalCase`; funcs/vars `snake_case`; constants `UPPER_SNAKE_CASE`.

CI
- Lint/types workflow: `.github/workflows/lint.yml` (ruff, mypy, pyright; types job continues on error).

Scheduling
- See `docs/scheduling` for cron and Windows Task Scheduler templates to automate the daily report.

## Testing Guidelines
- Framework: `pytest` with `pytest-asyncio`.
- Location/pattern: `tests/test_*.py` and focused unit tests near logic; keep network calls mocked in unit tests.
- Integration: requires IBKR OAuth, DB, and optional Telegram in `.env`. Prefer a paper account.

## Commit & Pull Requests
- Commits: concise, imperative, optionally scoped. Examples:
  - `service: add /signal endpoint`
  - `db: fix engine creation on DSN`
- PRs: include purpose, linked issues, testing steps/outputs (e.g., `uv run -m tradeexec.tools.debug_env`, curl to `/signal`), and risk/rollback notes. Screenshot or logs for API changes help reviewers.

## Security & Configuration
- Never commit secrets or key files (`private_*.pem`, tokens). Keep them in `.env` and mounted in Docker.
- Validate configuration with `uv run -m tradeexec.tools.debug_env` before running executors.
- Use `ACCOUNTN_EXECUTE_ORDER=False` to dry‑run; enable Telegram confirmations for human‑in‑the‑loop.
