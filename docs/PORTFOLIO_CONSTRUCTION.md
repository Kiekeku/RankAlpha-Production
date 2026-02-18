# Portfolio Construction & Deployment (Model → Broker) — Spec + Runbook

This document is the canonical reference for RankAlpha’s **portfolio construction / tracking system** introduced in:
- `docker/database/sql/migrations/V111__portfolio_construction_multiccy.sql` (initial data model + approvals + export gating)
- `docker/database/sql/migrations/V112__portfolio_instrument_type_expansion.sql` (enum expansion for future instruments)

Last verified against the repo as of **2026-01-08**.

It covers:
- **Spec**: the data model, entities, and invariants (including approvals + versioning).
- **Runbook**: how to operate it via API + the admin UI (`/portfolio`).

## 1) Mental model (end-to-end)

RankAlpha separates **idea generation** from **portfolio construction** and **broker execution**:

1) **Ideas** land as **trade recommendations** (one row per idea).
2) Portfolio construction creates:
   - versioned **policies** (risk tolerance),
   - daily **runs** (drafts → approvals),
   - **target holdings / weights / orders** (per-line approval).
3) Broker accounts can follow multiple **model portfolios** at once using **deployments**.
4) Because broker accounts can have **manual executions** outside the system, the model introduces:
   - baseline vs target snapshots,
   - sleeve shadow books,
   - explicit **internal crosses** between sleeves,
   - a future-proof link/alloc mechanism to attribute fills to intent.

## 2) Core concepts and tables (spec)

All tables below are in the Postgres schema `rankalpha`.

### 2.1 Trade recommendations (idea feed)

**Table:** `fact_trade_recommendation` (and view `vw_trade_recommendation`)

- One row per *recommended* trade idea (not the executed transaction).
- Actions are `BUY | SELL | SHORT | COVER` (enum `trade_action`).
- Used by external systems and (today) the broker execution pipeline.

See: `docs/TRADING_SIGNAL_INGESTION.md`.

### 2.2 Portfolio master (what a “portfolio” means here)

**Table:** `portfolio`

This is the top-level object for:
- Real brokerage accounts
- Model portfolios
- Sleeve “shadow” portfolios (per model deployment into an account)

**Key fields**
- `portfolio_kind`:
  - `BROKER`: real brokerage account (e.g., an IBKR account)
  - `MODEL`: model portfolio definition / target book
  - `SLEEVE`: per-model shadow portfolio inside a broker account
- `currency_code`: portfolio base currency (not the listing currency of securities)
- `broker_name`, `broker_account_id`: metadata for `BROKER` portfolios

Existing tables remain in place:
- `portfolio_position`: current equity positions by `stock_key`
- `portfolio_cash_position`: current cash by currency (multi-CCY; new in V111)
- view `vw_portfolio_position`: readable position view

### 2.3 Multi-currency conventions

**Listing currency (per security)**
- `dim_stock.currency_code` is the **listing/local currency** for the security.
- `fact_security_price.close_px` is treated as **local/listing currency**.
- `dim_stock.exchange` is **informational** (sourced externally) and is not a reliable way to infer currency; `dim_stock.currency_code` is the authoritative field for pricing/FX.

**Portfolio base currency (per portfolio)**
- `portfolio.currency_code` is the portfolio’s **base currency**.

**Cash**
- `portfolio_cash_position` stores cash balances **by currency**.
- Negative cash is allowed and represents margin borrowing (“short cash”).

**FX**
- The schema includes `fact_fx_rate` for conversion, and `portfolio_run_position.market_value_base` is intended to hold base-currency values.
- FX ingestion/conversion is not fully automated yet; treat base conversions as “best-effort” until the FX pipeline is wired.

### 2.4 Portfolio policies (risk tolerance over time)

**Table:** `portfolio_policy_version`

Stores time-versioned policy parameters (SCD2-ish):
- `effective_from`, `effective_to`
- `target_vol` (primary for now)
- `target_gross_exposure`, `target_net_exposure` (present now; useful immediately for long/short + leverage)
- `constraints` (JSON for forward-compatible risk constraints: sector caps, liquidity, drawdown, etc.)

**Invariant**
- Policies for the same portfolio cannot overlap in time (enforced by a daterange exclusion constraint).

### 2.5 Deployments (broker accounts follow multiple model portfolios)

**Table:** `portfolio_deployment`

A deployment ties:
- `broker_portfolio_id` (BROKER)
- `model_portfolio_id` (MODEL)
- `sleeve_portfolio_id` (SLEEVE shadow book)

Plus:
- `allocation_pct` (capital allocation of the broker account to this model)
  - `allocation_pct` is non-negative and may exceed `100` only when broker policy enables margin.
  - Broker rebalance generation enforces policy-level caps:
    - `constraints.exposure.allow_margin=false` => total active deployments must be `<=100`.
    - `allow_margin=true` => total active deployments may exceed `100`, but can be capped by `max_gross_exposure_pct` (or aliases).
- effective dates + an exclusion constraint so `(broker, model)` deployments do not overlap.

**Sleeve naming**
Sleeves are created automatically (idempotent) using:
- `apps/common/src/portfolio/construction.py::_slug_sleeve_name`
- pattern: `sleeve::<BROKER_NAME>::<MODEL_NAME>` (hashed/truncated to <= 50 chars)

### 2.6 Runs (daily snapshots + approvals)

**Table:** `portfolio_run`

Represents a daily run for a portfolio:
- `run_kind`:
  - `MODEL_CONSTRUCTION`: build a model portfolio target
  - `BROKER_REBALANCE`: build a broker account rebalance plan
  - `SLEEVE_BUILD`: build sleeve-level targets/attribution snapshots
- `as_of_date`
- `run_seq`: multiple drafts per day
- `status`: `DRAFT | IN_REVIEW | APPROVED | REJECTED | SUPERSEDED`

**Invariant**
- Only one run per `(portfolio_id, run_kind, as_of_date)` may be `APPROVED` at a time (partial unique index).

**Implementation note (today)**
- The current admin UI/API primarily uses `DRAFT` → `APPROVED` (+ automatic `SUPERSEDED` of prior approved runs). `IN_REVIEW` / `REJECTED` are present in the schema for future workflow expansion.

**Run inputs (broker runs referencing multiple model runs)**

**Table:** `portfolio_run_input`

Captures, for a given broker run:
- which `portfolio_deployment` rows were used, and
- which model runs were used as inputs,
- and a snapshot of `allocation_pct` at the time.

### 2.7 Positions (baseline vs target; equity + cash)

**Table:** `portfolio_run_position`

Stores run snapshots of:
- `position_role`:
  - `BASELINE` (what you *have* as-of date; can include manual broker activity)
  - `TARGET` (what you *want* post-rebalance)
- `instrument_type`:
  - **Currently supported (enforced by a check constraint in V111):**
    - `EQUITY` (via `stock_key`)
    - `CASH` (via `currency_code`)
  - **Enum values reserved for future (added in V112):** `ETF`, `FX`, `FUTURE`, `OPTION`, `BOND`, `CRYPTO` (not yet supported by `portfolio_run_position` without a schema change)

**Key design point:** cash is a first-class line item (supports multi-currency cash + margin).

**Important column semantics (to prevent implementation drift)**
- `quantity`
  - `instrument_type=EQUITY`: shares
  - `instrument_type=CASH`: currency units (can be negative)
- `weight_pct`
  - Used to store **target weights** (canonical for `MODEL_CONSTRUCTION` runs and also useful on `BROKER_REBALANCE` targets for explainability).
  - For `MODEL_CONSTRUCTION` runs, `quantity` may be treated as a placeholder (e.g., `0`) and must not be interpreted as “shares to trade”.
- `price_close_local`, `market_value_local`, `market_value_base`
  - Intended for valuation snapshots (especially on broker runs) using close-based pricing and FX conversion.

### 2.8 Order intents (the approved trade list)

**Table:** `portfolio_order_intent`

This is the per-line “trade list” that gets approved:
- keyed by `(run_id, line_no)` (unique)
- fields include:
  - `stock_key`, `action`, `qty_shares`
  - execution hints (`order_type`, `time_in_force`, `limit_price`, `stop_trigger_price`)
  - optional `target_weight_after` (recorded target weight *after* this line)
  - `approval_status` + `approved_at/by`

**Invariant (approval)**
- A run becomes `APPROVED` only when **all order lines** are `APPROVED`.
- Any edit to an order line resets its approval back to `PENDING`.

Implementation: `apps/common/src/portfolio/construction.py:upsert_order_intents` and `apps/common/src/portfolio/construction.py:approve_run`.

**Idea lineage + sleeve allocation hooks**
- `portfolio_order_intent_source`: ties an order to one or more `fact_trade_recommendation` rows (idea lineage).
- `portfolio_order_intent_alloc`: splits an order across deployments/sleeves (quantity and weight components).

### 2.9 Execution ledger and attribution (actual fills vs intent)

**Actual executions**
- `fact_portfolio_trade` is the executed trade ledger (broker fills ingested here).
- Broker accounts can have manual fills that do not map to recommendations or order intents.

**Attribution hooks (future-proofing)**
- `portfolio_trade_link`: links a `fact_portfolio_trade` to a `portfolio_order_intent` (if it originated from the run).
- `portfolio_trade_alloc`: allocates actual fills across deployments/sleeves for attribution.

### 2.10 Internal crosses (explicit sleeve-to-sleeve transfers)

**Table:** `fact_internal_cross`

When two sleeves offset within the same broker account (one wants to buy what another wants to sell), record an explicit **internal cross**:
- `buy_sleeve_portfolio_id`, `sell_sleeve_portfolio_id`
- `cross_qty` (> 0)
- `price_close_local`, `currency_code`
- optional linkage to the actual buy/sell `fact_portfolio_trade` rows

Pricing convention:
- “internal-cross pricing” is recorded **as-of close** (use `fact_security_price.close_px` in local currency).

## 3) Operational flows (runbook)

### 3.1 Prereqs

1) Apply migrations (Flyway runs in Compose via `flyway` service):

```bash
docker compose -f compose/docker-compose.yml up --build
```

2) Ensure these are configured for admin UI server actions:
- `AUTH_SERVICE_TOKEN` (frontend server → API admin auth via `X-RA-Service-Token`)
- optionally `INTERNAL_API_URL` (or `NEXT_PUBLIC_API_URL`)

### 3.2 Ingest trade recommendations (ideas)

Use the trading ingestion API:
- `POST /api/v1/trading/signals`
- `Authorization: Bearer <TRADING_BEARER_TOKEN>`

Include `currency_code` for non-USD equities so `dim_stock.currency_code` is correct.

Example:

```json
{
  "symbol": "7203",
  "action": "BUY",
  "as_of_date": "2025-12-28",
  "recommended_price": 2500,
  "currency_code": "JPY",
  "source_name": "External-Trader",
  "strategy_name": "Global-Value"
}
```

### 3.3 Configure portfolios + deployments (UI)

Go to the admin-only page:
- Frontend: `/portfolio`

1) Create:
   - a `MODEL` portfolio (e.g., `Model-Core`)
   - a `BROKER` portfolio for your IBKR account (e.g., `DU1234567`)
2) Create a deployment (broker → model) with `allocation_pct`.
   - This auto-creates a `SLEEVE` portfolio for that (broker, model) pair.
   - For margin-enabled brokers, total active deployment allocation can exceed `100%` only when policy sets `constraints.exposure.allow_margin=true` (and optional exposure caps).

### 3.4 Create runs (daily)

From `/portfolio` (or API):
- Create a `MODEL_CONSTRUCTION` run per model portfolio/day (drafts allowed).
- Create a `BROKER_REBALANCE` run per broker account/day if you’re producing an account-level trade list.

`run_seq` increments for multiple drafts; only one can be `APPROVED`.

### 3.5 Populate order lines (trade list) and approve

Today the UI supports manual upsert of order lines (JSON array). Example:

```json
[
  {"line_no": 1, "symbol": "AAPL", "action": "BUY", "qty_shares": 10, "order_type": "MARKET", "time_in_force": "DAY"},
  {"line_no": 2, "symbol": "TSLA", "action": "SHORT", "qty_shares": 5, "order_type": "LIMIT", "limit_price": 225.0}
]
```

API note: `POST /api/v1/portfolio/runs/{run_id}/orders` expects the array wrapped as:

```json
{
  "orders": [
    {"line_no": 1, "symbol": "AAPL", "action": "BUY", "qty_shares": 10, "order_type": "MARKET", "time_in_force": "DAY"}
  ]
}
```

Notes:
- To “omit” an idea for a given portfolio while still recording review intent, you can include the line with `target_weight_after=0` and approve it (if that’s your convention).
- Any edit to a line resets its approval to `PENDING`.

Approvals:
1) Approve/reject each order line.
2) Approve the run (only enabled when **all lines** are approved).
3) Approving a run supersedes the previous approved run for the same portfolio/kind/day (`SUPERSEDED`).

### 3.6 Execution status (important)

Broker execution remains based on `fact_trade_recommendation` (see `docs/TRADING_SIGNAL_INGESTION.md`), but **broker execution is gated by portfolio approvals**:

- External systems submit **ideas** under non-broker sources (not `broker::...`).
- When you approve a `BROKER_REBALANCE` run for a `BROKER` portfolio, RankAlpha **exports** its approved `portfolio_order_intent` lines into **executable** trade recommendations with `source_name = broker::<ACCOUNT_NUMBER>`.
- The broker runner then picks those up, claims them (`is_live=true`), places orders, and ingests fills into `fact_portfolio_trade`.

Export behavior (current implementation):
- Export happens automatically inside run approval (`apps/common/src/portfolio/construction.py:approve_run`).
- Export sets `expiry_ts` to end-of-day **America/New_York** (converted to UTC) for that `as_of_date`.
- Export will **refuse** to proceed if there are already claimed/live broker recommendations for the same `(account, date, symbol, action)` (safety against double-submit).
- Export will **expire** any still-pending broker recommendations for the same `(account, date)` before writing the new ones (so superseded drafts don’t execute).

Current export constraints (by design):
- Broker export expects **integer share quantities** (because `fact_trade_recommendation.size_shares` is an `INT` today).
- Broker export expects at most **one net order per (symbol, action)** per run.

### 3.7 Admin API endpoints (portfolio)

All portfolio construction endpoints are admin-gated (the frontend uses `X-RA-Service-Token`; see `apps/frontend/src/app/portfolio/page.tsx`).

- Create/list portfolios: `POST /api/v1/portfolio/portfolios`, `GET /api/v1/portfolio/portfolios`
- Create/list deployments: `POST /api/v1/portfolio/deployments`, `GET /api/v1/portfolio/deployments`
- Create/list runs: `POST /api/v1/portfolio/runs`, `GET /api/v1/portfolio/runs`
- Upsert/list order intents: `POST /api/v1/portfolio/runs/{run_id}/orders`, `GET /api/v1/portfolio/runs/{run_id}/orders`
- Approve/reject order line: `POST /api/v1/portfolio/orders/{order_id}/approve`, `POST /api/v1/portfolio/orders/{order_id}/reject`
- Approve run (triggers broker export when `BROKER_REBALANCE`): `POST /api/v1/portfolio/runs/{run_id}/approve`
- Inspect trade recommendations (admin convenience): `GET /api/v1/portfolio/trade-recommendations`

### 3.8 What’s not automated yet (read before integrating)

The schema is intentionally ahead of the current implementation. As of **2026-01-08**, these are present but not end-to-end automated:
- Building `portfolio_run_position` baseline/target snapshots from broker data and model targets.
- Auto-generating `portfolio_order_intent` from `fact_trade_recommendation` or from model weights.
- Using `portfolio_run_input`, `portfolio_order_intent_source`, and `portfolio_order_intent_alloc` for traceable idea lineage / sleeve allocation in production.
- Auto-detecting and recording `fact_internal_cross` events.
- Managing `portfolio_policy_version` via UI/API (runs can optionally reference `policy_id`, but policy authoring is not yet exposed).

## 4) Code map (where logic lives)

- Migration (source of truth): `docker/database/sql/migrations/V111__portfolio_construction_multiccy.sql`
- ORM models: `apps/common/src/models.py`
- Portfolio construction helpers (runs, deployments, approvals): `apps/common/src/portfolio/construction.py`
- API router: `apps/api/src/routers/portfolio.py`
- Frontend admin page: `apps/frontend/src/app/portfolio/page.tsx`

## 5) Required build-out (today): long-only equities, multiple models, supervised execution

This section describes what you still need to implement to make RankAlpha “real” for **equity-only, long-only** trading across **multiple model portfolios** with account-level balancing and risk controls.

### 5.1 Three input sources (and how they should flow)

RankAlpha has three distinct “shapes” of inputs. Keeping them distinct avoids conflating *ideas*, *targets*, and *executable orders*:

1) **External delta trades** (from other repos / strategies)
   - Where they land: `rankalpha.fact_trade_recommendation` under a **non-broker** source (`source_name` must NOT start with `broker::`).
   - Ingestion path: `POST /api/v1/trading/signals` (token-gated).
   - What they represent: **delta trades** (“do this trade”), usually with their own proposed sizing.
   - How to consume them for trading:
     - Treat them as one term in the daily netting problem and convert into `BROKER_REBALANCE` order intents.
     - Portfolio/risk engines may **resize, defer, veto, or skip** a delta based on account policy.
   - Long-only safety rules (day-1 / MVP):
     - Ignore/reject `SHORT` and `COVER`.
     - Treat `SELL` as **reduce-only** (drop if no position exists; cap to baseline shares to avoid sell-to-open).

2) **Self-generated RankAlpha models** (grades/screener → model targets)
   - Where they should land: `rankalpha.portfolio_run` + `rankalpha.portfolio_run_position` for `MODEL_CONSTRUCTION` runs (TARGET positions).
   - What they represent: deterministic **model targets as weights** for a specific `as_of_date` (see as-of semantics below).

3) **Real broker account import** (positions/cash; manual trading exists)
   - Source of truth: **direct broker snapshots (daily)** are authoritative for “what is actually held”.
   - Where they land (current-state tables):
     - Positions: `rankalpha.portfolio_position` (equities)
     - Cash: `rankalpha.portfolio_cash_position` (multi-CCY)
   - Where they should land (per-run audit snapshots):
     - For each broker rebalance run, store `portfolio_run_position (BASELINE)` so audits don’t depend on mutable “current position” tables.

### 5.2 What to build: model engine, balance engine, risk engine

To trade long-only equities across multiple models you need three cooperating components (often easiest as a separate “portfolio app” scheduled daily):

1) **Model engine** (per model portfolio)
   - Inputs: RankAlpha grades/screener outputs (and optionally external idea feeds).
   - Output: a `MODEL_CONSTRUCTION` run containing TARGET positions expressed as **weights**.
   - Responsibilities:
     - Select universe and compute target weights per model.
     - Persist metadata needed to reproduce outputs (model version, universe rules, exclusions, inputs used).

2) **Balance engine** (account-level netting across models and deltas)
   - Inputs:
     - Broker baseline snapshot (positions + cash)
     - Deployments (`portfolio_deployment`) mapping broker account → model portfolios with allocation %
     - Latest relevant model targets (MODEL_CONSTRUCTION TARGETs)
     - External deltas (fact_trade_recommendation non-broker sources)
   - Output:
     - A `BROKER_REBALANCE` run with:
       - `portfolio_run_position (BASELINE)` and `portfolio_run_position (TARGET)` snapshots, and
       - a deterministic set of `portfolio_order_intent` lines.
   - Responsibilities:
     - Scale each model’s targets by its `allocation_pct`.
     - Combine model targets and external deltas, then **strictly net** to one final target position per symbol.
     - Convert **target weights → target shares** in **USD base currency** using:
       - security close prices in local currency (`fact_security_price.close_px`),
       - FX rates (`fact_fx_rate`) to translate local → USD for valuation and sizing,
       - and broker snapshot’s USD-equivalent NAV/cash as the sizing anchor.
         - Practical recommendation: use broker-provided NetLiquidation/NLV (if available) as the primary NAV anchor, and log an internal “reconstructed NAV” (positions × close × FX + cash) as a cross-check for discrepancies.
     - FX fallback policy:
       - If the FX rate for the required pair/date is missing, use the **most recent available** rate on or before `as_of_date`.
       - If the required FX pair has **no history at all**, treat it as a data error and **skip that symbol** for the day.
     - Cash buffer (day-1): target **99% deployment** (hold **1% USD cash buffer**) to reduce reject risk from price/FX drift.
     - Convert baseline vs target into one net order per symbol/action (idempotent, low-chaos trade list).

3) **Risk engine** (pre-trade constraints + explainability)
   - Inputs: broker baseline, proposed targets, proposed orders, and portfolio policy constraints.
   - Output:
     - pass/fail and a machine-readable **constraint evaluation artifact** per run (for audit/UI), e.g.:
       - constraint name → pass/fail → offending symbols → computed value → threshold → reason code.
   - Day-1 constraints (equities-only, long-only):
     - Long-only: no negative target positions; no sell-to-open.
     - Concentration: max single-name weight **20%** at the broker-account level (post-deployment, post-netting).
     - Liquidity: require **$ADV (USD) ≥ $10,000,000** over **20 trading days**.
       - Practical definition: trailing 20-trading-day average of `(close_px_local * volume)` converted to USD via `fact_fx_rate`.
     - Spread: include a spread guard hook, but keep it **disabled** until broker bid/ask retrieval is wired into portfolio runs.
       - Source-of-truth when enabled: broker bid/ask quotes (IBKR).

### 5.3 As-of date semantics (to avoid look-ahead)

RankAlpha is currently **daily close-based**. To keep point-in-time discipline:

- Define **D-1** as the last completed trading day (latest close you can rely on overnight).
- Define **D** as the execution day (the next trading day you want to work orders).

Convention:
- `MODEL_CONSTRUCTION.run.as_of_date = D-1` (signals computed from D-1 close + PIT inputs).
- `BROKER_REBALANCE.run.as_of_date = D-1` (sized off D-1 close + FX).
- Execution timing is expressed via `valid_from_ts` / `expiry_ts` (execution day D).

**Snapshot timestamp (recommended enhancement)**
- The broker baseline import occurs on day **D** (e.g., ~06:30 ET) and should record a durable `baseline_snapshot_ts` (UTC) so “broker truth at snapshot time” is explicit and audit-friendly.
- Implementation choices:
  - add `baseline_snapshot_ts TIMESTAMPTZ` on `portfolio_run` for `BROKER_REBALANCE` runs, or
  - store it in a per-run snapshot artifact (see below).

This avoids:
- misleading audit trails (“sized on yesterday’s close but labeled today”), and
- accidental “latest view” leakage that can become look-ahead.

### 5.4 Daily schedule + order eligibility (ET; RTH-only)

Time zone: **America/New_York (ET)**; store timestamps in UTC in Postgres.

Daily schedule (simple default):
- **06:00 ET (D)**: signals are generated/available using data as-of **D-1**.
- **06:30 ET (D)**: portfolio construction runs (model targets + broker rebalance drafts).
- **09:00 ET (D)**: final trade list is approved/exported/placed (pre-open).

Order eligibility convention:
- Export broker recommendations with:
  - `valid_from_ts = D 09:00 ET`
  - `expiry_ts = D EOD ET`
- All orders are intended to be **RTH-only** (no premarket execution). Practically:
  - submit/queue orders pre-open with “outside RTH” disabled so they become active at the 09:30 ET open.

Order-type semantics (current desired behavior):
- `MOO`, `MKT`, `LMT`, `MOC` can be queued at/after 09:00 ET and worked during RTH on day D.
- `STP`, `STP LMT`, `TRAIL` are **protective only**:
  - if no position exists at the broker, skip/ignore.
  - Same-day protection: for new positions opened on day D, place protective stops **after entry fills are observed** (intraday) so protection is active the same day.
  - Practical simplification (recommended): use **bracket orders** for new entries (parent entry + child stop), so protection becomes active automatically when the entry fills.

EOD handling:
- LIMIT: if not filled by EOD, cancel (do not carry).
- MOC: intended to execute at the close on day D.
  - If a MOC order fails to submit / is rejected / is not live for the close, re-issue on the next trading day.
- Protective stops: expected to be live intraday; persistence beyond EOD is policy-driven (DAY vs GTC), but day-1 can keep this simple.

### 5.5 Execution gate (approval → export → broker queue)

RankAlpha’s safety hinge remains:
- the broker executes only `fact_trade_recommendation` rows with `source_name = broker::<ACCOUNT>` and eligible timestamps.

Recommended flow:
1) Portfolio app drafts a `BROKER_REBALANCE` run + `portfolio_order_intent` lines.
2) Human reviews and approves order lines + run.
3) Run approval exports executable broker recommendations.
4) Broker runner claims rows and places orders; fills are ingested to `fact_portfolio_trade`.

---

## 6) Future expansion / enhancements: shorts, options, FX, futures

The current portfolio construction schema is intentionally equity-first. Adding other instruments will require:
- a first-class instrument master (not only `dim_stock`),
- order intents and run positions that reference instruments (not only stock_key/cash),
- risk and sizing that are instrument-aware (margin, multipliers, Greeks, borrow, etc.).

See `docs/PORTFOLIO_CONSTRUCTION.md` section 2.7 notes on current instrument support and `V112__portfolio_instrument_type_expansion.sql` for enum expansion.

---

## 7) Open questions (remaining)

- Spread threshold: what max spread (bps) should be used once broker bid/ask integration exists?
- Protective stops persistence: once a protective stop is placed intraday, should the default be `DAY` or `GTC`?
