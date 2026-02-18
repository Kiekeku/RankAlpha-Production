# RankAlpha — Current State (Quant + System Overview)

This is a high-level snapshot of what RankAlpha (RA) is **today** and what parts are **scaffolding vs. production-grade**. It’s intended for a senior quant who hasn’t read the repo yet.

As-of: **2026-01-08** (repo state).

For deeper dives:
- Architecture diagram: `docs/architecture.md`
- Functional data catalog (data products + lineage): `docs/DATA_CATALOG.md`
- Scoring definitions (Value/Momentum/Grades): `docs/SCORING.md`
- Risk Nowcast mechanics (DB snapshot logic + deltas): `docs/NOWCAST_QUANT_CHECKLIST.md`
- Portfolio construction schema + ops + build plan: `docs/PORTFOLIO_CONSTRUCTION.md`
- External signal ingestion contract: `docs/TRADING_SIGNAL_INGESTION.md`

---

## 1) What RankAlpha is (today)

RankAlpha is a daily (batch-first) equities platform with:
- **Data ingestion** (prices + macro series) into canonical Parquet + Postgres.
- **Cross-sectional scoring + grades** (Momentum + Value are core; Sentiment is optional).
- **Screener + market regime/breadth** analytics (rules-driven; multiple views/MVs).
- A **FastAPI + Next.js UI** that reads from DB views/materialized views.
- A **broker execution subsystem** (IBKR Client Portal Web API) that can place orders from a DB-backed queue.
- A **portfolio construction schema + admin workflow** (runs, approvals, deployments), with partial automation today.

---

## 2) Daily data flow (batch pipeline mental model)

1) **Ingestion**
   - Pulls OHLCV (yfinance) and writes canonical Parquet files to `/data/prices`.
   - Syncs price history into Postgres (`fact_security_price`) and maintains activity/eligibility artifacts.
   - Runs “tail jobs” for non-price data (breadth, stress, macro series depending on settings).

2) **Scorer**
   - Reads Parquet and computes factor scores (Momentum, Value, Money Flow, plus additional market state metrics).
   - Writes scores to `fact_score_history`.
   - Computes model weights periodically (hybrid IC + risk parity + shrinkage) and persists them to weight tables (including time-versioned weights).
   - Refreshes DB materialized views used by the API/UI.

3) **(Optional) Sentiment / AI / Newswire**
   - Can populate AI analysis outputs and/or news-derived sentiment used as an optional pillar in grades.

4) **API / Frontend**
   - API reads DB views/MVs and serves them; Redis caches many GET responses.
   - Frontend is a pure consumer of the API (no local scoring logic).

---

## 3) The “truth layer”: Postgres schema + views

RankAlpha’s design bias is to keep the **database as the single source of truth** for “latest grades”, “latest screener state”, etc., via materialized views and deterministic tie-breakers.

Key objects (non-exhaustive):
- Prices: `fact_security_price` (+ views for “latest”, “history”)
- Scores: `fact_score_history` (normalized score store)
- Grades: `mv_latest_grades` and an as-of function (`fn_grades_as_of(date)`) for point-in-time queries
- Weights: `dim_model_weight` (legacy) and `dim_model_weight_version` + `dim_model_weight_item` (time-versioned)
- Technicals: `fact_technical_indicator` + `vw_latest_technicals`
- Screener: consensus/changes/breadth materialized views + event facts
- Trading: `fact_trade_recommendation` (idea feed and/or executable queue depending on source)
- Portfolio construction: portfolios, deployments, runs, run positions, order intents, attribution hooks

---

## 4) Signals & grades (what the numbers mean)

### 4.1 Score conventions
- Scores are generally stored on a **0–100** scale.
- Grades are **cross-sectional percentiles**, mapped into `avg_score ∈ [1, 100]` and a letter band.
- RankAlpha is primarily a **ranking system** today; grades are relative within the universe, not calibrated expected returns.

### 4.2 Momentum (equities)
Current intent: an auditable daily “trend” factor stored as a 0–100 score and used as a core pillar in grades.

### 4.3 Value (equities)
Current intent: fundamentals-based relative cheapness:
- Stored as a 0–100 `value score` and used as a core pillar in grades.

### 4.4 Sentiment (optional)
Current intent: include a sentiment pillar when available without penalizing missing coverage:
- If present, mapped into a 0–100 scale and included; otherwise excluded and weights renormalize.

### 4.5 Composite grades
Current intent: stable, interpretable ranking for screening:
- Composite is a weighted blend of available pillars.
- Weights are either defaults (fallback) or learned weights produced by the scorer and persisted in weight tables.
- Final output is percentile-based (relative ranking), not an absolute return forecast.

Canonical references (consolidated)
- Audit + lineage (what is stored, where it comes from): `docs/DATA_CATALOG.md`
- Exact methodology (Momentum/Value/Grades, bands, and fallbacks): `docs/SCORING.md`

---

## 5) Screener, breadth, and regimes (state today)

RankAlpha has a “market state” layer that complements single-name grades:
- **Screener consensus**: per-symbol aggregation across screener styles/sources.
- **Screener changes + breadth**: entrants/exits/continuers, churn, and breadth time series.
- **Vol regimes**: VIX term structure and SPX/VIX variance risk premium (VRP) derived features + regime labels.
- **Macro series**: rates, FX, stress metrics, liquidity plumbing series, etc. (varies by enabled ingestion jobs).

The Nowcast summary logic (risk-off score composition) is documented in `docs/NOWCAST_QUANT_CHECKLIST.md`.

---

## 6) Trading & execution (what’s real vs. scaffolding)

### 6.1 Trade recommendation table: dual use (ideas vs executable queue)
`rankalpha.fact_trade_recommendation` is used in two ways:
- **External ideas**: submitted under a non-broker `source_name` via API ingestion.
- **Executable broker queue**: rows with `source_name = broker::<ACCOUNT_NUMBER>` are reserved for broker execution.

The API rejects external writes to `source_name` starting with `broker::` to prevent bypassing approvals.

### 6.2 Portfolio approval gate (how orders become executable)
Broker execution is designed to be gated by portfolio approvals:
- A human (admin) approves a `BROKER_REBALANCE` run.
- Approval exports the run’s `portfolio_order_intent` lines into `fact_trade_recommendation` under `broker::<ACCOUNT>`.
- The broker runner then claims and places those orders.

Safety invariant: **the broker should only execute `broker::<ACCOUNT>` rows that came from an approved portfolio run.**

### 6.3 Broker execution (IBKR Client Portal Web API)

Status: **real order placement exists**, designed to be driven by the DB queue and gated by approvals (not “click-to-trade off ranks”).

What exists today:
- `apps/broker` (“TradeExec”) supports:
  - per-account executor loop,
  - a FastAPI control plane (health, signal ingest, prices),
  - fills ingestion into the shared Postgres schema (`fact_portfolio_trade`).
- Contract search + market data are broker-backed (IBKR); rate limits and pacing exist.
- Execution reads pending account recommendations and claims them before placing orders (idempotence + safety).
- Fills are ingested with best-effort linkage back to recommendations.

Notable limitations (important for quant review):
- Backtest tooling does not validate execution realism (see 6.5).
- Some order semantics (TIF, protective stops, exit sizing) are simplified today.
  - Protective stops are currently best treated as “protective-only”; same-day protection for new positions requires placing stops after entry fills are observed (an explicit desired behavior in the portfolio build-out plan).

### 6.4 Portfolio construction (schema + manual workflow exist; automation is partial)

Status: **data model and approval workflow exist**; automated “model → account rebalance” engines are not fully built yet.

What exists today (usable):
- Portfolio kinds: `BROKER`, `MODEL`, and `SLEEVE` portfolios.
- Deployments: broker account follows multiple models with `allocation_pct`.
- Runs + approvals:
  - `MODEL_CONSTRUCTION` runs (intended model targets)
  - `BROKER_REBALANCE` runs (intended account trade list)
  - per-line approvals on `portfolio_order_intent`
  - broker-run approval exports executable broker::<ACCOUNT> recommendations.
- Admin UI + API endpoints exist to create runs and manually upsert/approve order lines.

What is not automated end-to-end yet:
- Systematic generation of model targets (weights) from RankAlpha grades/screener into MODEL runs.
- Daily broker baseline import into run snapshots (BASELINE) in a “boringly reliable” way.
- Deterministic balance engine (multiple model targets + deltas → one net trade list).
- Risk engine enforcement with explainable constraint reports.
- Full attribution linking (intent lineage, sleeve allocation, fill-to-intent).

### 6.5 Backtesting (present in API, not research-grade yet)

Status: **placeholder/demo**, not suitable for performance claims.

- Backtest endpoints exist, but current logic is not a true replay simulator (no point-in-time discipline, no costs, no real fills).
- Treat it as UI scaffolding until a deterministic simulator is built (daily signals → next day execution with costs and constraints).

---

## 7) Operational posture (today)

Relatively mature:
- Docker Compose stack (Postgres + Redis + services).
- Observability: OpenTelemetry + Prometheus metrics; Grafana/Tempo/Loki stack in default compose.
- Caching: Redis-backed caching on many API reads; refresh endpoints clear keys + refresh MVs.
- Security knobs: admin/service tokens; production hardening guidance exists (read-only mode, restricted CORS, etc.).

Operator-driven by design (today):
- Portfolio approvals (manual review) are a feature, not a bug.
- Execution should start in paper / tiny-notional and be monitored.

---

## 8) Quant caveats / model-risk notes (important for review)

- Grades are relative ranks, not calibrated expected returns.
- Data PIT risk exists unless explicitly guaranteed (e.g., corporate action adjustments, fundamentals revision timing, news availability).
- Universe definition matters (eligibility, delistings, stale symbols, sector mapping).
- Learned weights are heuristic by design (hybrid IC + RP + shrinkage), not a full institutional factor risk model.
- Execution realism is not yet validated by backtest tooling.

---

## 9) Suggested senior-quant review agenda (quick checklist)

### 9.1 “Do the signals make sense?”
- Momentum: windowing, strength weighting, and neutrality assumptions.
- Value: metric set, sector-vs-market blend, missingness behavior.
- Composite: required vs optional pillars, renormalization behavior, percentile band cutoffs.

### 9.2 “Is it research-safe?”
- Look-ahead: confirm all inputs are available at the chosen “data as-of date”.
- Corporate actions/adjustments: confirm `Adj Close` usage is acceptable for your intent.
- Universe: eligibility policy, delisting handling, ETFs inclusion/exclusion where intended.

### 9.3 “Can we safely trade it (today)?”
- Approvals + audit: are baseline/target snapshots and approvals sufficient for supervised trading?
- Risk constraints: what day-1 constraints must be enforced (ADV, max name weight, cash buffer)?
- Execution: identify minimum OMS features needed before scaling beyond supervised trading (idempotent client IDs, order state tracking, cancel/replace).
