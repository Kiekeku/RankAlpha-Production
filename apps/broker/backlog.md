# Backlog

Top 3 priorities first, followed by the full backlog. Numbers are unique across all items.

1) Order state machine + idempotent audit
- Category: State & Orders
- Outcome: Persistent order ledger (new/ack/partfill/fill/cx/replace) with broker exec IDs; robust delta reconciliation; idempotency keys across retries/restores.
- Notes: Extend `TradeExecutionAudit` or add an `OrderLedger` table; add idempotent keys and atomic writes.
 - Estimate: L
 - Dependencies: DB migrations (Alembic), stable order schema, broker exec‑ID mapping

2) Pre-trade risk/compliance checks
- Category: Risk & Compliance
- Outcome: Hard stops before placement: price bands vs NBBO/microprice, stale-quote guard, LULD/halts checks, SSR awareness, locate/borrow gates.
- Notes: Centrally enforced validator called by all placements.
 - Estimate: M
 - Dependencies: Reliable snapshot feed; SSR/halts sources (broker or reference)

3) Algo wrappers (VWAP/TWAP/POV/Adaptive Mid) + TCA metrics
- Category: Execution
- Outcome: Parent/child time-sliced orders, bracket/OCO, iceberg; collect slippage vs arrival/mid for TCA.
- Notes: Start with TWAP/VWAP; add rate-limit aware pacing.
 - Estimate: L
 - Dependencies: Basic pacing (#9), metrics/TCA store (#13)

4) Max loss circuits (day/strategy/account)
- Category: Risk & Compliance
- Outcome: Halt new orders and cancel risky leaves when drawdown breaches limits.
 - Estimate: M
 - Dependencies: PnL calc source (positions + prices); alerting (#14)

5) Exposure limits & ADV caps
- Category: Risk & Compliance
- Outcome: Per-symbol/sector/factor/cap exposures, concentration and leverage caps, stricter ADV ceilings.
 - Estimate: M
 - Dependencies: Symbol master (#10), factor/sector map (#12)

6) Short-sale rule handling (SSR/HTB)
- Category: Risk & Compliance
- Outcome: Auto-detect SSR, enforce non-marketable shorts, integrate locate/borrow checks.
 - Estimate: M
 - Dependencies: Broker SSR/locate endpoints or data vendor

7) Dynamic limit offsets & queue heuristics
- Category: Execution
- Outcome: Volatility-aware offsets, microstructure cues, NBBO alignment.
 - Estimate: M
 - Dependencies: Consistent NBBO snapshot; microprice estimator

8) Auction handling (open/close)
- Category: Execution
- Outcome: Opening/closing auction routes; safe MOC sizing with rails.
 - Estimate: M
 - Dependencies: Broker auction routes; market status (#11)

9) Rate limiting & pacing
- Category: Execution
- Outcome: Broker throttle handling, jittered retries, backoff; idempotent cancel/replace.
 - Estimate: M
 - Dependencies: Broker throttle specs; resilient job loop

10) Symbol master & corp-actions
- Category: Data & Models
- Outcome: Normalize tick/lot/multipliers; splits/dividends; venue metadata.
 - Estimate: M
 - Dependencies: Reference data source; migration

11) Market status & calendars (multi-region)
- Category: Data & Models
- Outcome: Poll market-status endpoints; add non‑US calendars; unify open/close logic.
 - Estimate: M
 - Dependencies: Vendor APIs; timezone handling

12) Factor/sector mapping
- Category: Data & Models
- Outcome: Exposure controls and attribution in reports.
 - Estimate: M
 - Dependencies: Mapping table or vendor feed; symbol master (#10)

13) Metrics (Prometheus) & dashboards (Grafana)
- Category: Monitoring
- Outcome: Orders, fills, rejects, slippage, retries; service health.
 - Estimate: S
 - Dependencies: Prometheus client & scrape target; Grafana instance

14) Alerts & kill-switch
- Category: Monitoring
- Outcome: Slack/Telegram/PagerDuty for circuits/reject spikes; liveness; manual and API kill.
 - Estimate: S
 - Dependencies: Metrics (#13); secrets for webhooks

15) Durable queues & resume
- Category: Reliability
- Outcome: Redis/Kafka SignalBus; resume from offsets on restart.
 - Estimate: M/L
 - Dependencies: Redis/Kafka infra; message schemas

16) Intraday PnL & exposure panes
- Category: Reporting
- Outcome: Real-time PnL/greeks (if applicable), exposure by sector/factor; risk budgets vs realized.
 - Estimate: M
 - Dependencies: Positions + prices; factor mapping (#12)

17) Post-trade TCA & rollups
- Category: Reporting
- Outcome: Slippage vs arrival/mid, venue analysis, cancel/replace efficiency; per-strategy/account daily summaries.
 - Estimate: M
 - Dependencies: Metrics store (#13); order ledger (#1)

18) Universe management & event filters
- Category: Strategy Ops
- Outcome: Reconstitutions, earnings/IPO/halts filters; skip rules around events.
 - Estimate: M
 - Dependencies: Corporate/actions calendar; symbol master (#10)

19) Cash/FX hedging
- Category: Strategy Ops
- Outcome: Multi-currency handling; automatic residual FX hedges.
 - Estimate: M/L
 - Dependencies: FX pricing; multi-currency accounting

20) Replay harness & scenario tests
- Category: Testing & Tooling
- Outcome: Record/replay broker responses; deterministic clock; outage/throttle/partial-fill/gap/split scenarios.
 - Estimate: M/L
 - Dependencies: Logging of raw I/O; deterministic clock injection

21) DB migrations & secrets management
- Category: Tooling
- Outcome: Alembic migrations; move secrets to Vault/SM; rotate credentials safely.
 - Estimate: M
 - Dependencies: Alembic baseline; secret store

## Suggested Sprint Plan (first 3 items)

Sprint 1 (2 weeks)
- 1) Order state machine (minimal): schema + CRUD; idempotency keys; integrate into placement path; unit tests.
- Add basic Prometheus metrics (#13) and alert hooks (#14) for order errors.

Sprint 2 (2 weeks)
- 2) Pre-trade checks (phase 1): price bands vs mid, stale quote guard, basic halts/SSR flags; central validator used by all placements.
- 9) Pacing primitives: retry/backoff scaffolding used by wrappers.

Sprint 3 (2–3 weeks)
- 3) Algo wrappers (phase 1): TWAP/VWAP parents + child slicing; collect arrival‑vs‑fill slippage for TCA.
- Close gaps: add missing tests and dashboards for order/fill rates and rejects.

## Sprint Tickets (timeboxed)

### Sprint 1 — Order state + metrics (2 weeks)

- S1-1: OrderLedger schema & migration
  - Owner: Data/DB
  - Timebox: 2 days
  - Tasks: Alembic migration; table with order_id (broker), idempotency_key, parent/child, state, ts, reason, account, symbol, qty, prices; indexes on (account, idempotency_key), (broker_order_id), (state, ts).
  - Acceptance Tests:
    - `alembic upgrade head` creates schema; downgrade restores.
    - CRUD unit tests pass; unique(idempotency_key, account) enforced.

- S1-2: Idempotency keys + atomic audit
  - Owner: Execution
  - Timebox: 3 days
  - Tasks: Generate idempotency key per logical order; atomic write to Ledger + Audit; handle retries/concurrency.
  - Acceptance Tests:
    - Duplicate placement calls (retries) create exactly one broker order; ledger shows single new→ack transition.
    - Concurrent simulation shows no duplicate rows; errors are logged.

- S1-3: Placement integration + state transitions
  - Owner: Execution
  - Timebox: 3 days
  - Tasks: Emit state changes (new/ack/partfill/fill/cx/replace) to ledger; reconcile open orders into transitions.
  - Acceptance Tests:
    - Mock fills drive partfill→fill transitions; ledger sequence matches events.
    - Cancel/replace flows record cx→new correctly.

- S1-4: Prometheus metrics
  - Owner: Infra
  - Timebox: 1 day
  - Tasks: Expose `/metrics`; counters for orders/fills/rejects/cancels; histograms for placement latency.
  - Acceptance Tests:
    - `/metrics` contains counters after a dry-run; scrape test parses without errors.

- S1-5: Alert hooks (Slack/Telegram) for order errors
  - Owner: Infra
  - Timebox: 1 day
  - Tasks: Integrate webhook notifier on reject/error; rate-limit alerts to avoid floods.
  - Acceptance Tests:
    - Forced error triggers a single alert; message includes account, symbol, reason.

### Sprint 2 — Pre-trade checks + pacing (2 weeks)

- S2-1: Pre-trade validator (phase 1)
  - Owner: Risk
  - Timebox: 3 days
  - Tasks: Price bands vs mid (tick-aware), stale-quote guard, notional/qty sanity; central call in placement path.
  - Acceptance Tests:
    - Invalid inputs rejected with explicit reason; unit tests with mocked quotes.

- S2-2: SSR flags + short-sale rules
  - Owner: Risk
  - Timebox: 2 days
  - Tasks: Detect SSR (10% down) via broker or ref feed; prevent marketable shorts; allow limits above offer.
  - Acceptance Tests:
    - SSR day: marketable short rejected; non‑marketable short accepted; logs contain SSR reason.

- S2-3: Halts/LULD check
  - Owner: Risk
  - Timebox: 2 days
  - Tasks: Basic halt/LULD detection via reference; skip placement.
  - Acceptance Tests:
    - Halted symbol: skip with reason; unit test with mocked status feed.

- S2-4: Pacing primitives (retry/backoff)
  - Owner: Execution
  - Timebox: 3 days
  - Tasks: Retry policy with jitter/backoff; idempotent cancel/replace; throttle error handling.
  - Acceptance Tests:
    - Simulated throttle returns lead to successful retry within budget; no duplicate orders.

### Sprint 3 — TWAP/VWAP + TCA (2–3 weeks)

- S3-1: TWAP parent/child wrapper
  - Owner: Execution
  - Timebox: 4 days
  - Tasks: Schedule slices; child idempotency; end‑of‑window completion rules; cancel residuals.
  - Acceptance Tests:
    - Simulation: child schedule respects window and size; ledger shows parent/children with correct totals.

- S3-2: VWAP wrapper (baseline curve)
  - Owner: Execution
  - Timebox: 4 days
  - Tasks: Use static intraday volume curve; fallback to TWAP when curve missing; simple POV constraint.
  - Acceptance Tests:
    - Simulation: schedule correlates with curve; fallback verified when no curve.

- S3-3: TCA baseline (arrival/mid slippage)
  - Owner: Analytics
  - Timebox: 2 days
  - Tasks: Record arrival price, child fill prices, mid quotes; compute slippage; daily rollup.
  - Acceptance Tests:
    - TCA table populated after runs; daily job/email shows slippage by symbol and strategy.

- S3-4: Dashboards for fill rate/slippage/rejects
  - Owner: Infra
  - Timebox: 2 days
  - Tasks: Grafana panels; SLOs for rejects and fill rates; alert thresholds wired.
  - Acceptance Tests:
    - Panels render with test data; alerts fire when reject rate exceeds threshold in simulation.
