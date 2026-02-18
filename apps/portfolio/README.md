# Portfolio Engine

This service hosts the RankAlpha portfolio engine (model construction, broker rebalancing,
and performance tracking).

## Implementation status (as of 2026-01-18)

Implemented:
- Versioned policies/configs/subscriptions are persisted in DB (ORM-backed).
- Model portfolio config parsing/validation for `strategy_blend` (weights sum to 100, unique strategy keys).
- `BROKER_REBALANCE` risk evaluation enforces a first set of constraints (see “Currently enforced checks”).
- Multi-currency valuation for broker risk checks and close-based NAV reconstruction via `rankalpha.fact_fx_rate`.
- Broker NLV ingestion table + admin upsert endpoint (below).
- Daily close-based performance rollup (NAV + total P&L) via portfolio CLI.
- Public read-only performance queries for visible public portfolios via the API:
  - `GET /api/v1/portfolios/{portfolio_id}/performance`
  - `GET /api/v1/portfolios/{portfolio_id}/strategy-performance` (MODEL only)
- Nightly broker holdings + attribution pipeline (Airflow + API + broker service):
  - fills ingest → holdings snapshot → attribution rollup (see “Broker holdings sync + attribution”).

Not implemented yet (documented for forward-compat):
- Full risk-budget sizing + vol targeting end-to-end (beyond the current close-based guards).
- Sleeve-level attribution.

## Broker holdings sync + attribution

RankAlpha tracks **BROKER** portfolio holdings and close-to-close attribution via a nightly pipeline.

### Airflow DAG

- DAG: `infra/airflow/dags/broker_holdings_sync.py` (`dag_id="broker_holdings_sync"`)
- Default schedule: `0 1 * * *` (configurable via Airflow Variables; see the DAG file)
- Disable scheduling: set `BROKER_HOLDINGS_SYNC_ENABLED=false` (DAG remains available for manual trigger)
- Tasks (in order):
  1) `POST /api/v1/portfolio/broker-fills/ingest`
  2) `POST /api/v1/portfolio/broker-holdings/sync`
  3) `POST /api/v1/portfolio/broker-attribution/rollup`

### How the pipeline decides which broker accounts to sync

The DAG does **not** specify an account. Instead:

- The API endpoint `POST /api/v1/portfolio/broker-holdings/sync` queries the DB for
  `rankalpha.portfolio` rows with:
  - `portfolio_kind = 'BROKER'`
  - `broker_account_id IS NOT NULL`
- For each such portfolio, it calls the broker service endpoint:
  - `GET /snapshot/{account}` where `{account} = portfolio.broker_account_id`

Notes:
- The broker service will only return a snapshot for accounts it is configured to run
  (it must have started an `ExecutionProgram` for that `account_number`).
- If you want to target a single account/portfolio, the API request supports filters:
  - `{"portfolio_id": "<uuid>"}` or `{"broker_account_id": "DU123..."}`.

### Broker service auth

- The API calls the broker service using `X-RA-Service-Token`.
- `BROKER_SERVICE_TOKEN` may be configured as either `<token>` or `Bearer <token>`;
  the portfolio API strips the optional `Bearer ` prefix before sending it to the broker.

### Snapshot semantics (positions + cash)

`POST /api/v1/portfolio/broker-holdings/sync`:
- Overwrites current holdings in:
  - `rankalpha.portfolio_position`
  - `rankalpha.portfolio_cash_position`
- Writes a per-day snapshot (idempotent per `portfolio_id` + `effective_date`) into:
  - `rankalpha.fact_portfolio_position_hist`
- De-duplicates broker positions that map to the same `(portfolio_id, stock_key)`:
  - sums `quantity`
  - computes a weighted-average `avg_cost` when present
- Auto-creates missing `dim_stock` rows when the broker reports an unknown symbol:
  - creates `rankalpha.dim_stock` row (best-effort)
  - uses broker-provided `currency_code` when present

Safety behavior:
- If any broker symbol cannot be mapped/created, the endpoint fails with `422` and **does not**
  delete/replace holdings (the request is atomic via the API DB session; no partial commits).

### Attribution semantics (close-to-close, D-1)

`POST /api/v1/portfolio/broker-attribution/rollup` computes per-position close-to-close attribution:
- Start-of-period holdings: `fact_portfolio_position_hist` on `prev_date`
- End-of-period holdings: `fact_portfolio_position_hist` on `as_of_date` (if present)
- Prices: `rankalpha.fact_security_price.close_px` (prev + as_of)
- FX: `rankalpha.fact_fx_rate.mid_px` (prev + as_of, with inverse fallback)
- Writes to:
  - `rankalpha.fact_portfolio_position_attribution`
  - view: `rankalpha.vw_portfolio_position_attribution`

Rerun behavior:
- For a given `(portfolio_id, date_key)`, the rollup deletes any existing attribution rows first,
  then inserts the newly computed set (prevents stale symbols lingering after history corrections).

Shorts:
- `return_base` is computed as `pnl_base / abs(market_value_prev_base)` so profitable shorts report
  positive returns.

### Public read-only access

For public portfolios, attribution is exposed read-only:
- `GET /api/v1/portfolios/{portfolio_id}/attribution`

## Ticker lifecycle (DimStock “soft delete”)

`rankalpha.dim_stock` should generally **not** be hard-deleted because many fact tables join by
`stock_key` and historical data would be orphaned.

Admin endpoint:
- `POST /api/v1/admin/stocks/soft-delete`

Behavior:
- Sets `dim_stock.is_active=false`
- Renames `dim_stock.symbol` to free the ticker (format: `{SYMBOL}-{YYYYMMDD}` with collision-safe
  suffixing; always ≤ 20 chars)


## Portfolio Policies

Portfolio-level risk tolerance is stored in Postgres as **versioned policies**:

- Table: `rankalpha.portfolio_policy_version` (introduced in `docker/database/sql/migrations/V111__portfolio_construction_multiccy.sql`)
- Semantics: SCD2-ish effective dating; **policies for the same `portfolio_id` must not overlap**
  (enforced by a daterange exclusion constraint in the DB).

### Schema (DB)

Columns:
- `policy_id` (BIGSERIAL, PK)
- `portfolio_id` (UUID, FK → `rankalpha.portfolio.portfolio_id`)
- `effective_from` (DATE, required)
- `effective_to` (DATE, optional; open-ended when NULL)
- `target_vol` (NUMERIC(12,6), optional) — annualized vol target (e.g., `0.12` for 12%)
- `target_gross_exposure` (NUMERIC(12,6), optional) — e.g. `1.00` for 100% gross
- `target_net_exposure` (NUMERIC(12,6), optional) — e.g. `1.00` for fully long-only
- `constraints` (JSONB, required; default `{}`) — forward-compatible constraint bundle
- `created_at` (TIMESTAMPTZ, server default `now()`)
- `created_by` (TEXT, optional)

### How the engine should resolve a policy

For a given `portfolio_id` and `as_of_date`, pick the single row where:

`effective_from <= as_of_date < COALESCE(effective_to, 'infinity')`

If no row matches, the engine should fall back to conservative defaults (TBD).

### `constraints` JSON schema (v1 target)

`constraints` is intentionally flexible, but the portfolio app should standardize on a
schema so policies are auditable and machine-checkable. The engine will implement these
progressively; unknown keys should be ignored (but preserved).

Important: `constraints` is **persisted** (DB + ORM) and is **partially enforced** today
for `BROKER_REBALANCE` runs via the run risk report (`portfolio_run_risk_report` +
`portfolio_run_risk_check`) which is a hard approval gate for broker exports.

Example:

```json
{
  "nav": {
    "source": "BROKER_NLV",
    "min_cash_buffer_pct": 1.0
  },
  "position_limits": {
    "max_name_weight_pct": 20.0,
    "min_order_notional_usd": 100.0,
    "round_lot_size": 1
  },
  "liquidity": {
    "adv20_usd_min": 10000000,
    "max_adv_pct_per_order": 10.0
  },
  "risk_budget": {
    "enabled": true,
    "method": "RISK_BUDGET_BPS_INV_VOL",
    "total_risk_budget_bps": 1000,
    "vol_lookback_days": 20,
    "vol_floor": 0.05,
    "vol_cap": 1.00
  },
  "trading": {
    "rth_only": true,
    "valid_from_time_et": "09:00",
    "expiry_time_et": "23:59:59"
  }
}
```

Notes:
- `risk_budget.method` should match enum values in `rankalpha.signal_sizing_method`:
  `USE_SIGNAL_SIZE`, `NOTIONAL_PCT_NAV`, `RISK_BUDGET_BPS_INV_VOL`, `RISK_BUDGET_BPS_FIXED`.
- Long-only portfolios typically set `target_net_exposure=1.0` and `target_gross_exposure=1.0`.

#### Expanded schema (recommended keys)

Below is the recommended *shape* and intended meaning. Not all keys are implemented yet.

`constraints.nav` (NAV anchor + cash buffer)
- `source`: `"BROKER_NLV" | "RECONSTRUCTED_CLOSE" | "FACT_PORTFOLIO_NAV"` (engine preference order)
- `min_cash_buffer_pct`: float (e.g., `1.0` means keep 1% cash uninvested in base CCY)
- `prefer_broker_nav`: bool (when true, broker NLV wins even if reconstructed differs)
- `max_nav_mismatch_pct`: float (warn/fail when reconstructed vs broker differs too much)

Broker NLV ingestion (v1):
- Table: `rankalpha.fact_portfolio_broker_nlv` (introduced in `docker/database/sql/migrations/V125__portfolio_broker_nlv.sql`)
- Admin API: `POST /api/v1/portfolio/portfolios/{portfolio_id}/broker-nlv`

Example request body:

```json
{
  "as_of_date": "2026-01-16",
  "nlv_base_ccy": 125000.0,
  "gross_leverage": 1.15,
  "currency_code": "USD",
  "source_system": "ibkr"
}
```

`constraints.position_limits` (concentration + trade sizing clamps)
- `max_name_weight_pct`: float (post-trade target, per portfolio)
- `max_sector_weight_pct`: float (optional; requires sector mapping)
- `min_order_notional_usd`: float (skip tiny trades)
- `round_lot_size`: int (shares; 1 for US equities; can be >1 for some markets)
- `allow_fractional_shares`: bool (must be `false` for broker export; export uses integer `size_shares`)

`constraints.exposure` (portfolio-level exposure limits)
- `max_leverage`: float (max gross exposure / NAV; e.g., `1.5`)
- `max_gross_exposure`: float (alias for `max_leverage`)
- `max_gross_exposure_pct`: float percent alias for max gross exposure (e.g., `150` => 1.5x)
- `max_allocatable_exposure_pct`: float alias for `max_gross_exposure_pct`
- `allow_margin`: bool (`false` => total active deployment `allocation_pct` must be `<=100`; `true` => can exceed `100`)
- `min_net_exposure`: float (e.g., `0.0` for market-neutral lower bound)
- `max_net_exposure`: float (e.g., `1.0` for long-only upper bound)
- `long_only`: bool (when true, disallow SHORT/COVER and sell-to-open)

`constraints.liquidity` (close-based guards; needs ADV calc + FX)
- `adv20_usd_min`: float (e.g., `10000000` for $10M ADV20)
- `max_adv_pct_per_order`: float (e.g., `10.0` means order notional <= 10% of ADV)
- `max_adv_pct_position`: float (cap final position notional vs ADV)

`constraints.trading` (execution-day mechanics)
- `rth_only`: bool
- `valid_from_time_et`: `"HH:MM"` (engine uses this for broker export timing)
- `expiry_time_et`: `"HH:MM:SS"`
- `force_new_run_if_not_execution_day`: bool (implemented for broker approvals)

`constraints.fx` (multi-currency behavior; close-based)
- `fallback_to_last_available`: bool (use last FX <= as_of_date)
- `skip_symbol_if_fx_missing`: bool
- `base_currency`: string (normally redundant with `portfolio.currency_code`)

`constraints.risk_budget` (risk-based sizing; complements subscriptions)
- `enabled`: bool
- `method`: same enum as `rankalpha.signal_sizing_method`
- `total_risk_budget_bps`: int (portfolio-level budget to allocate)
- `vol_lookback_days`: int
- `vol_floor`: float
- `vol_cap`: float

### What is supported by the object models *today*

The ORM/DB supports storing the policy, and the engine enforces a first set of
broker-run constraints (see `apps/common/src/portfolio/construction.py:evaluate_run_risk`):

## Model Portfolio Config (strategy blend)

Model portfolios are the **exclusive** subscribers to external strategies. The “recipe” for a model
portfolio is stored as a versioned JSON config:

- Table: `rankalpha.portfolio_model_config_version` (introduced in `docker/database/sql/migrations/V124__portfolio_engine_extensions.sql`)
- Field: `config` (JSONB)
- Semantics: SCD2-ish effective dating; configs for the same `model_portfolio_id` must not overlap.

### `config` JSON schema (v1)

`config` is intentionally flexible (JSONB), but the portfolio engine should treat the following
structure as the v1 contract. Unknown keys should be ignored (but preserved).

Top-level keys:
- `schema_version` (int, recommended; default `1`)
- `strategy_blend` (**required**, object)
  - `require_sum_to_100` (bool, optional; default `true`)
  - `strategies` (**required**, array)
    - items:
      - `source_name` (string, required) — must exist in `rankalpha.dim_source.source_name`
      - `strategy_name` (string, required) — matches `fact_trade_recommendation.strategy_name`
      - `weight_pct` (number, required) — 0..100; enabled weights must sum to **exactly 100**
      - `enabled` (bool, optional; default `true`)
      - `notes` (string, optional)
- `notes` (string, optional) — free-form human notes

Validation rules (engine-side):
- `strategy_blend.strategies` must have unique (`source_name`, `strategy_name`) pairs
- all enabled `weight_pct` values must be within [0, 100]
- the sum of enabled `weight_pct` values must equal 100 (when `require_sum_to_100=true`)

Example:

```json
{
  "schema_version": 1,
  "strategy_blend": {
    "require_sum_to_100": true,
    "strategies": [
      {"source_name": "External-Strategy-01", "strategy_name": "A", "weight_pct": 40},
      {"source_name": "External-Strategy-01", "strategy_name": "B", "weight_pct": 30},
      {"source_name": "External-Strategy-01", "strategy_name": "D", "weight_pct": 30}
    ]
  },
  "notes": "Core model blend (risk-budgeted across strategies)"
}
```

Notes:
- These weights are intended as a **risk-budget blend** across strategies (not necessarily capital weights).
- Broker/account-level NAV, leverage limits, and allocatable-capital rules should live in the broker policy,
  not here.

Managing model configs today:
- There is **no dedicated API** for CRUD’ing `portfolio_model_config_version` yet, so for now you manage
  these rows via SQL (or via the API’s internal auto-CRUD if you enable it in the API settings).

## Signal Subscriptions (broker/account overrides)

Signal subscriptions are broker/account-level overrides for strategy routing and per-account sizing
defaults. Model portfolios define “membership” (which strategies belong to the model) via
`portfolio_model_config_version.config` (see above).

- Table: `rankalpha.portfolio_signal_subscription` (introduced in `docker/database/sql/migrations/V124__portfolio_engine_extensions.sql`)
- Scope: **BROKER** portfolios (accounts)
- Match key: (`source_name` → `dim_source.source_key`) + `strategy_name`
  - `strategy_name IS NULL` means wildcard: “all strategies for this source”
  - Exact `strategy_name` means “only this strategy”
- Overlaps: for a given (`broker_portfolio_id`, `source_key`, `strategy_key`) date ranges must not overlap
  (enforced by a daterange exclusion constraint).

Recommended semantics (engine-side resolution):
- Prefer an **exact** `strategy_name` match when present and enabled.
- Otherwise fall back to the wildcard (`strategy_name IS NULL`) subscription for that source if enabled.

### Managing subscriptions today

There is **no dedicated API** for CRUD’ing `portfolio_signal_subscription` yet, so for now you manage
these rows via SQL (or via the API’s internal auto-CRUD if you enable it in the API settings).

### Example: set per-account overrides for strategies A, B, and D

```sql
-- Example inputs:
--   broker_portfolio_id: the UUID in rankalpha.portfolio for your BROKER account
--   source_name        : the dim_source name used by the external signal ingestor
INSERT INTO rankalpha.portfolio_signal_subscription (
  broker_portfolio_id,
  source_key,
  strategy_name,
  enabled,
  effective_from,
  approval_status,
  sizing_method,
  allocation_pct
)
VALUES
  ('<BROKER_PORTFOLIO_UUID>',
   (SELECT source_key FROM rankalpha.dim_source WHERE source_name = '<SOURCE_NAME>'),
   'A',
   true,
   CURRENT_DATE,
   'APPROVED',
   'RISK_BUDGET_BPS_INV_VOL',
   NULL),
  ('<BROKER_PORTFOLIO_UUID>',
   (SELECT source_key FROM rankalpha.dim_source WHERE source_name = '<SOURCE_NAME>'),
   'B',
   true,
   CURRENT_DATE,
   'APPROVED',
   'RISK_BUDGET_BPS_INV_VOL',
   NULL),
  ('<BROKER_PORTFOLIO_UUID>',
   (SELECT source_key FROM rankalpha.dim_source WHERE source_name = '<SOURCE_NAME>'),
   'D',
   true,
   CURRENT_DATE,
   'APPROVED',
   'RISK_BUDGET_BPS_INV_VOL',
   NULL);
```

If you want a wildcard “all strategies from this source” baseline + exact overrides, insert one row
with `strategy_name = NULL`, then add additional rows for specific `strategy_name` values.

**First-class columns (typed)**
- `target_vol`, `target_gross_exposure`, `target_net_exposure` on `portfolio_policy_version`
- Per-subscription sizing defaults on `portfolio_signal_subscription`:
  - `sizing_method` (enum)
  - `default_risk_budget_bps`, `default_notional_pct_nav`, `allocation_pct`

**JSON blobs (persisted, not validated by DB)**
- `portfolio_policy_version.constraints` (this section)
- `portfolio_signal_subscription.constraints` (per source/strategy overrides)
- `fact_trade_recommendation.preconditions` (execution metadata consumed by broker runner in limited cases)

**Structured “risk report” gate (typed)**
- `portfolio_run_risk_report` + `portfolio_run_risk_check` exist and are required (fresh + non-FAIL)
  before approving/exporting `BROKER_REBALANCE` runs.

**Currently enforced checks (BROKER_REBALANCE)**
- `LONG_ONLY` (no negative post-trade shares when `constraints.exposure.long_only=true`; BUY/SELL only)
- `INTEGER_SHARES_REQUIRED` (fractional shares are not exportable today; broker export requires integer shares)
- `MAX_NAME_WEIGHT_PCT` (post-trade concentration vs `constraints.position_limits.max_name_weight_pct`)
- `MAX_LEVERAGE` (gross exposure / NAV vs `constraints.exposure.max_leverage`, `max_gross_exposure`, or pct aliases)
- `MIN_ADV20_USD` and `MAX_ORDER_PCT_ADV` (liquidity guards using close×volume ADV)
- `PRICE_AVAILABLE` (hard-fails if required closes are missing for valuation)
- Cash buffer + min-order-notional are currently warnings (report status `WARN`), not hard fails.

### Sample policy row (shape)

```json
{
  "portfolio_id": "00000000-0000-0000-0000-000000000000",
  "effective_from": "2026-01-01",
  "effective_to": null,
  "target_vol": 0.12,
  "target_gross_exposure": 1.0,
  "target_net_exposure": 1.0,
  "constraints": { "nav": { "source": "BROKER_NLV" } },
  "created_by": "admin@rankalpha"
}
```

## Environment configuration

The portfolio engine and the broker sync pipeline rely on the standard RankAlpha env profiles
under `env/<ENV>/` (selected via `RANKALPHA_ENV`, default `local`).

Key files:
- `env/<ENV>/shared.env`: DB credentials + shared tokens (notably `BROKER_SERVICE_TOKEN`, `AUTH_SERVICE_TOKEN`)
- `env/<ENV>/portfolio.env`: portfolio-engine knobs (example: `PORTFOLIO_NAV_SKIP_ZERO`)
- `env/<ENV>/api.env`: API settings including broker bridge (`BROKER_SERVICE_URL`, `BROKER_SERVICE_TIMEOUT_SECONDS`)
- `env/<ENV>/airflow.env`: Airflow DAG knobs (example: `API_URL`, `BROKER_HOLDINGS_SYNC_*`)

For now it exposes a small batch CLI:

```bash
cd apps/portfolio
uv venv && uv sync --locked
export PYTHONPATH=../..
uv run python main.py sync-nav --as-of-date 2026-01-16
uv run python main.py rollup-performance --as-of-date 2026-01-16
uv run python main.py build-model-run --model-portfolio-id <MODEL_PORTFOLIO_UUID> --as-of-date 2026-01-16
uv run python main.py build-broker-run --broker-portfolio-id <BROKER_PORTFOLIO_UUID> --as-of-date 2026-01-16
```
