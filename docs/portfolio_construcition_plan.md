# Portfolio Construction Implementation Plan (Agent Playbook)

This document is a detailed, execution-oriented plan for building RankAlpha’s portfolio construction system from “schema + manual approvals” into a supervised, auditable, long-only equities portfolio system with broker execution.

Audience: implementation agent(s) who will modify the repo.

As-of: **2026-01-08**

Related docs:
- Current state overview: `docs/RankAlpha_current_state.md`
- Portfolio schema + build direction: `docs/PORTFOLIO_CONSTRUCTION.md`
- External signal ingestion contract: `docs/TRADING_SIGNAL_INGESTION.md`
- Scoring: `docs/SCORING.md`
- Architecture: `docs/architecture.md`

---

## 0) Core requirements (do not deviate)

### 0.1 Inputs (three sources)

1) **External delta trades**
   - Stored in `rankalpha.fact_trade_recommendation` under **non-broker** sources (`source_name` must NOT start with `broker::`).
   - Treated as **one term in netting** (no priority overlay).
   - **Long-only safety rules (MVP)**
     - Ignore/reject `SHORT` and `COVER` actions.
     - Treat `SELL` as **reduce-only**:
       - if baseline position is 0 shares, drop the delta and record a reason code (e.g., `REDUCE_ONLY_NO_POSITION`) in the netting artifact.
       - if baseline position exists, cap sell quantity to `<= baseline_qty` (no sell-to-open).
     - `BUY` is allowed but still subject to risk constraints (liquidity + max-name cap).

2) **RankAlpha-generated model targets**
   - Expressed as **weights** (not shares).
   - Persisted as `MODEL_CONSTRUCTION` runs + TARGET snapshots.

3) **Broker baseline import (source of truth)**
   - **Daily broker snapshots** are authoritative for positions/cash.
   - Must be persisted as both:
     - “current state” tables (`portfolio_position`, `portfolio_cash_position`), and
     - per-run `portfolio_run_position(BASELINE)` snapshots for auditability.

### 0.2 Daily close-based semantics (look-ahead-safe)

RankAlpha is currently close-based. You must distinguish:
- **Data as-of date**: last completed trading day close (**D-1**)
- **Execution day**: next trading day you intend to trade (**D**)

Conventions:
- `MODEL_CONSTRUCTION.run.as_of_date = D-1`
- `BROKER_REBALANCE.run.as_of_date = D-1`
- Execution timing is represented via `valid_from_ts`/`expiry_ts` on exported broker recommendations:
  - `valid_from_ts = D 09:00 ET`
  - `expiry_ts = D EOD ET`

### 0.3 Trading schedule (ET; RTH-only)

- 06:00 ET (D): signals available (computed using D-1 data)
- 06:30 ET (D): portfolio construction job runs (draft runs created)
- 09:00 ET (D): final trade list approved/exported/queued (pre-open)
- RTH-only: do **not** allow premarket execution; queue for 09:30 ET open.

### 0.4 Base currency + FX policy

- Base currency is **USD**.
- Convert non-USD valuations using `rankalpha.fact_fx_rate`.
- FX fallback:
  - if FX missing on `as_of_date`, use most recent available ≤ `as_of_date`
  - if pair has **no history at all**: treat as data error and **skip the symbol** for the day

### 0.5 Netting + sizing policies (MVP)

- Strict netting to **one final target** and **one final order per symbol/day** (or no order).
- Cash buffer: keep **1% USD cash** (target 99% deployment).
- Risk constraints (day-1):
  - Max single-name weight **20% per broker account** (post-netting)
  - Liquidity: trailing **20 trading day $ADV ≥ $10M USD**
  - Spread: guard hook exists but **disabled by default** until broker bid/ask retrieval is integrated

### 0.6 Stop orders (protective-only + same-day protection)

- `STP`, `STP LMT`, `TRAIL` are **protective only**:
  - Skip/ignore if the position does not exist.
- Same-day protection:
  - For new positions opened on day D, place protective orders **after entry fills are observed** intraday.

### 0.7 “Institution-grade” audit artifacts (must-have)

Per broker rebalance run, persist machine-readable artifacts:
- FX rates used (pairs + rate timestamps/ids + fallback flags + skipped symbols)
- Constraint evaluation report (pass/fail per constraint, offending symbols, computed values, thresholds)
- Netting report (how targets + deltas combined into final targets)

### 0.8 Clarifications to lock in before coding (prevents agent guesswork)

These are “agent foot-guns” if left ambiguous.

1) **Where model target weights live**
   - Canonical location: `rankalpha.portfolio_run_position.weight_pct` on `position_role=TARGET` rows.
   - `portfolio_run_position.quantity` is **shares** for broker rebalance targets; for model construction targets it is allowed to be a placeholder (e.g., `0`) and must not be interpreted as “shares to trade”.
   - If you want stricter semantics, add a small migration to allow `quantity` to be nullable when `(run_kind='MODEL_CONSTRUCTION' AND position_role='TARGET' AND instrument_type='EQUITY')`.

2) **Baseline snapshot timestamp vs as_of_date**
   - `BROKER_REBALANCE.run.as_of_date` remains `D-1` (close-based inputs).
   - The broker baseline import happens on day `D` (~06:30 ET) and must record a durable `baseline_snapshot_ts` (UTC).
   - Recommendation: add a nullable `baseline_snapshot_ts TIMESTAMPTZ` column on `rankalpha.portfolio_run` (only populated for `BROKER_REBALANCE` runs). If you don’t add a column, store it in a `SNAPSHOT_REPORT` run artifact and treat that as authoritative.

3) **Run artifacts storage (strong recommendation)**
   - Add table `rankalpha.portfolio_run_artifact`:
     - `run_id UUID FK`
     - `artifact_type TEXT` (or enum: `FX_USED`, `CONSTRAINT_EVAL`, `NETTING_REPORT`, `SNAPSHOT_REPORT`, `MODEL_METADATA`, …)
     - `payload JSONB`
     - `created_at TIMESTAMPTZ`
     - `UNIQUE (run_id, artifact_type)`
   - Optional (later): `portfolio_run_metric(run_id, metric_name, metric_value, metric_jsonb)` for queryable KPIs.

4) **NAV sizing anchor**
   - Use broker-provided NetLiquidation/NLV (USD) as the **primary** sizing anchor when available (IBKR provides it via account summary).
   - Compute an internal “reconstructed NAV” (positions × D-1 close × FX + cash) as a **cross-check**, log discrepancy %, and do not silently ignore large gaps.

---

## 1) Implementation strategy (recommended shape)

### 1.1 Create a dedicated “portfolio” app (recommended)

Add a new service/app (e.g., `apps/portfolio`) that runs on schedule (or manually) and does:
- broker baseline snapshot import
- model target generation (RankAlpha-based models)
- broker rebalance draft generation (netting + sizing)
- risk evaluation + artifact persistence

This keeps the portfolio system logically separate from:
- ingestion/scorer pipelines (signal computation)
- the broker runner (order placement + fills ingestion)

### 1.2 Keep the broker runner simple

The broker runner should remain the executor of `broker::<ACCOUNT>` recommendations. Extend it only where necessary:
- stable client order IDs / idempotence across restarts
- order state tracking (minimal OMS)
- same-day protective stops after fills

---

## 2) Data contracts (what tables mean in practice)

### 2.1 Portfolio runs

`MODEL_CONSTRUCTION` run (as_of = D-1):
- TARGET snapshot expresses target weights for that model portfolio (not necessarily shares).

`BROKER_REBALANCE` run (as_of = D-1):
- BASELINE snapshot reflects broker snapshot truth as of the morning of day D.
- TARGET snapshot reflects the desired account-level targets after combining:
  - deployed model targets (scaled by allocation %)
  - external deltas (as another term)
- Order intents are derived from (TARGET - BASELINE) and are strictly netted per symbol.

### 2.2 Export to execution

Approving a `BROKER_REBALANCE` run exports to `fact_trade_recommendation` under `source_name = broker::<ACCOUNT>`.

Export must set timing for execution day D:
- `valid_from_ts = D 09:00 ET`
- `expiry_ts = D EOD ET`
- RTH-only execution (outside_rth disabled on broker order placement)

### 2.3 Order types and expected behavior (MVP)

Queued at/after 09:00 ET (D), executed during RTH:
- `MOO`, `MKT`, `LMT`, `MOC`

Protective-only:
- `STP`, `STP LMT`, `TRAIL` (skip if no position; same-day protection after fills)

EOD behavior:
- LMT: cancel if not filled by EOD
- MOC: if not live for close (failed submit/rejected), re-issue next trading day

---

## 3) Work plan with progress checklist

Use this section as the agent’s progress tracker (check boxes as you complete tasks).

### Phase 0 — Prep & invariants

- [ ] Read and align with: `docs/PORTFOLIO_CONSTRUCTION.md` and `docs/TRADING_SIGNAL_INGESTION.md`
- [ ] Confirm `dim_date` contains trading day flags needed for “next trading day D”
- [ ] Confirm broker runner supports RTH-only (outside_rth disabled) for queued pre-open orders
- [ ] Decide where to persist run artifacts (tables vs JSON blobs) and add DB migrations

### Phase 1 — “Truth imports”: broker baseline snapshot importer (must be boringly reliable)

Goal: daily snapshot of broker positions/cash becomes the canonical baseline.

- [ ] Implement broker snapshot pull per account (positions + cash + optionally open orders)
- [ ] Upsert into:
  - [ ] `portfolio_position` (equities)
  - [ ] `portfolio_cash_position` (multi-CCY)
- [ ] Create per-run BASELINE snapshots:
  - [ ] for the day’s `BROKER_REBALANCE` run, write `portfolio_run_position(BASELINE)` rows
- [ ] Handle symbol mapping edge cases:
  - [ ] IBKR symbol normalization (dots/spaces)
  - [ ] ensure `dim_stock.currency_code` consistency
- [ ] Add a “snapshot report” artifact for audit (counts, missing symbols, stale data warnings)

Acceptance criteria:
- Daily snapshots can be run repeatedly without drift or duplicate rows (idempotent).
- BASELINE snapshot is reproducible and tied to a specific run.

### Phase 2 — Model engine: generate RankAlpha-derived model targets as weights

Goal: RankAlpha grades/screener become model portfolio intent (weights), not just rankings.

- [ ] Define model catalog/config format (per model portfolio):
  - [ ] universe definition
  - [ ] ranking signal source (e.g., grades, screener consensus)
  - [ ] #names / weight scheme (equal weight, score-weighted, etc.)
  - [ ] exclusions (sectors, tickers, etc.)
  - [ ] rebalance cadence (daily for MVP)
  - [ ] Implement `MODEL_CONSTRUCTION` run writer:
  - [ ] create run for as-of D-1
  - [ ] persist TARGET weights (and metadata)
- [ ] Apply eligibility filters during model construction (first-pass risk gating):
  - [ ] $ADV20 ≥ $10M USD (computed using dates ≤ D-1 only)
  - [ ] (placeholder) spread filter hook, disabled until broker quotes exist
- [ ] Persist model metadata artifact (model version, inputs used, exclusions applied)

Acceptance criteria:
- For a fixed D-1 data snapshot, model output weights are deterministic.
- Outputs are persisted and auditable (what universe and rules produced them).

### Phase 3 — Balance engine: net models + external deltas into an account-level target

Goal: multiple model targets + delta trades collapse into a single broker account TARGET.

- [ ] Load inputs for broker account:
  - [ ] deployments (broker→model allocation %)
  - [ ] model targets (weights) as-of D-1
  - [ ] external deltas intended for the execution day D (filter rules must be deterministic)
  - [ ] broker baseline (positions/cash snapshots)
- [ ] Convert model weights into USD notional targets:
  - [ ] pull broker NLV/NetLiquidation (USD) from account summary and treat as primary NAV anchor
  - [ ] compute internal reconstructed NAV (positions × D-1 close × FX + cash) as a cross-check
  - [ ] persist NAV inputs + discrepancy in `SNAPSHOT_REPORT` artifact
  - [ ] enforce 1% USD cash buffer (99% deploy)
- [ ] Convert USD notional targets to shares using D-1 close + FX
- [ ] Incorporate external delta trades into the same netting problem:
  - [ ] deltas contribute to final target shares (no overlay priority)
  - [ ] strict net to one final per symbol
  - [ ] enforce long-only safety rules for deltas (reduce-only SELL; reject SHORT/COVER)
- [ ] Produce broker run TARGET snapshot (`portfolio_run_position(TARGET)`)
- [ ] Produce `portfolio_order_intent` lines from (TARGET - BASELINE):
  - [ ] one order per symbol/action
  - [ ] deterministic rounding rules
  - [ ] min-notional and “skip” rules (documented + logged)
- [ ] Persist a netting artifact per run (model contributions, delta contributions, final target, final order)

Acceptance criteria:
- Same inputs → same order intents.
- No duplicate (symbol, action) orders within a run.
- Explicitly logs any skipped symbol and why (FX missing, liquidity, etc.).

### Phase 4 — Risk engine: enforce constraints with explainable outputs

Goal: constraints are deterministic, machine-verifiable, and reviewable in UI.

- [ ] Implement day-1 constraints:
  - [ ] max single-name weight ≤ 20% (post-netting)
  - [ ] $ADV20 ≥ $10M USD
    - [ ] compute ADV20 from (close*volume) converted to USD with FX policy
  - [ ] spread guard hook (disabled by default)
- [ ] Re-apply eligibility/risk constraints at broker rebalance time (second-pass final gate):
  - [ ] verify $ADV20 and FX availability are still satisfied
  - [ ] ensure deltas did not reintroduce ineligible symbols
- [ ] Create constraint evaluation artifact per run:
  - [ ] constraint name
  - [ ] pass/fail
  - [ ] offending symbols
  - [ ] computed values and thresholds
  - [ ] reason codes
- [ ] Integrate risk engine decision with run lifecycle:
  - [ ] if failed, block approval/export (or require explicit override workflow)

Acceptance criteria:
- UI/ops can see *why* a run was blocked or which symbols were excluded.

### Phase 5 — Execution lifecycle hardening (minimal OMS features)

Goal: safe retries, no duplicate/ghost orders, and protective orders after fills.

- [ ] Stable client order IDs:
  - [ ] derive ID from (run_id, line_no, symbol, action, qty, order_type, limit/stop)
  - [ ] persist on recommendation preconditions and/or an execution table
- [ ] Order state tracking (minimal):
  - [ ] submitted/acknowledged/partial/filled/cancelled/rejected
  - [ ] capture broker order IDs and timestamps
- [ ] Cancel/replace:
  - [ ] support updating queued limit orders (if needed)
  - [ ] EOD cancel of unfilled LMT
- [ ] Same-day protective stops:
  - [ ] Prefer bracket orders for new entries (parent entry + child stop), with children activating only after parent fill (protective-only, same-day protection)
  - [ ] If brackets are not used, after entry fill is observed, submit protective stops (STP/TRAIL) if configured
  - [ ] ensure “protective-only”: do nothing if no position; do not place stop sell orders that open a short
- [ ] Deterministic replay harness (start early; don’t wait for Phase 6):
  - [ ] a CLI/job mode that can re-run `D-1 → D` construction for a historical date and assert reproducibility
  - [ ] outputs: diffable artifacts (inputs, netting, constraints) so regressions are obvious

Acceptance criteria:
- Restarting broker runner does not duplicate orders.
- Protective stops appear intraday after fills for newly opened positions.

### Phase 6 — Research-grade simulator (do not postpone indefinitely)

Goal: a truthful daily simulator consistent with the portfolio/risk engines.

- [ ] Implement a deterministic simulator:
  - [ ] signals as-of D-1 close
  - [ ] trade at D open (or a documented proxy)
  - [ ] transaction costs + slippage model
  - [ ] turnover + liquidity constraints consistent with the risk engine
  - [ ] strict PIT discipline (no “latest” leakage)
- [ ] Emit standard diagnostics:
  - [ ] turnover, drawdowns, capacity checks
  - [ ] constraint rejections count
  - [ ] attribution by model sleeve / delta component

Acceptance criteria:
- Simulator outputs are consistent with production constraints and data semantics.
- Results are reproducible and audit-friendly.

---

## 4) Non-goals (MVP)

Do not expand scope prematurely:
- Multi-asset (options/futures/FX) portfolio construction and execution (schema needs extension first)
- Full OMS with complex staged execution / time buckets / tax lots
- Full factor risk model / covariance-aware portfolio optimization

---

## 5) Questions an implementation agent should resolve early (and document)

- Spread guard: choose max spread bps once broker bid/ask integration exists.
- Protective stop persistence defaults: `DAY` vs `GTC`.
- What qualifies an external delta for the day D execution (date filtering rules, expiry rules).
- How to compute account USD NAV from broker snapshots (cash + positions + FX + pricing) consistently and record the inputs used.

---

## 6) Additional acceptance tests / invariants (don’t skip)

These catch “looks right” failures (look-ahead, duplicate orders, and long-only violations).

- **Idempotence (portfolio job)**: run the same `BROKER_REBALANCE` twice for the same `(account, D-1)` → same run selection semantics, identical order intents, no duplicate exports.
- **No sell-to-open (long-only)**: for every `SELL` intent, assert `sell_qty <= baseline_qty` (unless you later explicitly support same-day buy-then-sell netting rules).
- **Target weights + cash buffer**: target weights sum to ~99% (within rounding tolerance) and implied cash is ≥ 1% USD-equivalent (unless a margin/leverage policy overrides).
- **ADV20 + FX correctness**:
  - ADV20 uses only trading dates ≤ `D-1`.
  - FX fallback is deterministic and logged (pair, chosen timestamp/id, and fallback reason).
  - Symbols skipped due to no FX history are recorded and do not block the whole run.
- **No “latest leakage”**: add tests/guards that portfolio runs do not use `mv_latest_*` views when backfilling historical dates; use date-filtered facts/views only.
