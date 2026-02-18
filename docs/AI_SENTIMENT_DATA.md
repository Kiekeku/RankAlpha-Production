# RankAlpha AI Sentiment and AI Analysis Data (Functional)

Last updated: 2026-01-19

This document describes **what data is collected and persisted** by RankAlpha’s AI analysis / sentiment agent (`apps/sentiment`) and how that data maps into the **Sentiment score** used by scoring and grades.

This is a functional/audit view (what the data represents and how it is used), not a full schema reference. For table/view inventories, see `docs/schemas.md`.

## 1) Definitions (important for audits)

RankAlpha uses the term “sentiment” in two related but distinct ways:

1) **AI analysis outputs (qualitative + structured)**  
   Stored as a historical set of AI “memos” per symbol (plus structured tables for scenarios, catalysts, risks, etc.).

2) **Sentiment score (0–100) used in the grade composite**  
   This is a numeric pillar used by `rankalpha.mv_latest_grades`. It is **not** just a text sentiment label.

This doc covers both:
- What the agent stores (the AI memo + structured fields).
- How those stored fields become a numeric Sentiment score.

## 2) What triggers an AI sentiment/analysis run

The sentiment service (`apps/sentiment`) can run in multiple modes (on-demand, scheduled, and queue-driven). It uses the database as the source of truth for:

- Symbol eligibility (`dim_stock.is_active`, `mv_universe_eligible.eligible`)
- Prior AI analysis history (`fact_ai_stock_analysis`) to avoid re-running too frequently
- News/event-driven work queue (`sentiment_analysis_queue`) when enabled

Operational artifacts:
- Schedule file (JSON): `/data/analysis_schedule/analysis_schedule.json`
- Saved report files: `/data/company_reports/…`
- Logs: `/data/logs/sentiment_oai_*.log`

## 3) Input sources (what the agent reads)

The AI analysis pipeline may incorporate inputs from:

- **Newswire / stored news** (preferred for reproducibility):
  - News/event queue rows: `rankalpha.sentiment_analysis_queue` (can reference `fact_news_raw.raw_id` and `fact_news_event.event_id`)
  - Underlying news content typically lives in RankAlpha’s news tables (see `docs/DATA_CATALOG.md` Newswire section).
- **Market data context** (for anchor price and basic context):
  - Broker snapshots and/or RankAlpha API price endpoints (for an anchor/close price)
  - Optional yfinance and other structured market data tools
- **Fundamentals and filings** (when enabled):
  - SEC EDGAR filings and XBRL facts (tool-driven)
- **Web research** (when enabled):
  - Search results used to gather public “what changed” context (e.g., analyst target distributions)

Audit note: many inputs are **public** sources, but the memo and its structured outputs are **model-generated** artifacts and should be treated as decision support, not authoritative facts.

## 4) What the sentiment agent stores (Postgres)

The sentiment agent persists one **analysis header** row per run plus structured “child” tables keyed by `analysis_id`.

### 4.1 Core analysis header: `fact_ai_stock_analysis`

**Grain**
- One row per `(symbol, as_of_date, run)` with a unique `analysis_id`.
- Historical: the table retains prior runs; “latest” is defined by a stable ordering (see Views below).

**What it stores (high-level)**
- **Identity and lineage**
  - `analysis_id`, `date_key` / `as_of_date`, `stock_key`, `source_key`, `load_ts`
- **Fundamental / business snapshot fields**
  - Market cap and growth context (e.g., `market_cap_usd`, `revenue_cagr_3y_pct`)
  - Trend labels for core fundamentals (gross/net margin, FCF, insider activity) via dimension keys
- **Macro sensitivity context**
  - `beta_sp500`, `rate_sensitivity_bps`, plus coarse exposure labels (FX / commodity)
- **Sentiment/positioning context**
  - `news_sentiment_30d`, `social_sentiment_7d`, `options_skew_30d`, `short_interest_pct_float`
  - A few additional “alt sentiment” signals when available (employee/glassdoor, buzz)
  - `commentary` (often used to store the narrative summary; some shapes pack JSON for structured commentary)
- **Overall stance + meta**
  - `overall_rating` (dimension-mapped label), `confidence`, `recommendation_timeframe`

### 4.2 Structured tables (per-analysis attachments)

These tables are populated by `apps/sentiment/src/persistence.py` when the corresponding section exists in the generated report payload.

- **Valuation snapshot:** `rankalpha.fact_ai_valuation_metrics`
  - Example fields: forward P/E, forward EV/EBITDA, sector percentile.
- **Peer comparison panel:** `rankalpha.fact_ai_peer_comparison`
  - Peers + basic comparable metrics + a short narrative summary.
- **Factor scores (AI factors):** `rankalpha.fact_ai_factor_score`
  - Per-style scores keyed by `style_key` (style dictionary: `rankalpha.dim_style`).
  - These are exposed as `value_score`, `quality_score`, `momentum_score`, `low_vol_score` in `vw_ai_analysis_*`.
- **Catalysts:** `rankalpha.fact_ai_catalyst`
  - Records catalysts with `catalyst_type` (short/long/event), title/description, probability, expected move, expected date, “priced-in” estimate, and downside risk if it fails.
- **Bull/Base/Bear price scenarios:** `rankalpha.fact_ai_price_scenario`
  - Price targets and probabilities for scenario types `bull`, `base`, `bear`.
- **Macro risks:** `rankalpha.fact_ai_macro_risk` (list-like)
- **Headline risks:** `rankalpha.fact_ai_headline_risk` (list-like)
- **Data gaps / missing information:** `rankalpha.fact_ai_data_gap` (list-like)

Optional/extended tables (exist in the DB; may or may not be joined into the main views depending on migrations/features enabled):

- `rankalpha.fact_ai_event` (structured events)
- `rankalpha.fact_ai_risk` (structured risks with probability/severity)
- `rankalpha.fact_ai_news` (news items referenced by the analysis: headline, URL, timestamp, per-item sentiment score)
- `rankalpha.fact_ai_scenario_proximity` (scenario similarity outputs when enabled)
- `rankalpha.fact_ai_alternative_data` (alt data scores: credit card spend, app ranking, job postings trend)
- `rankalpha.fact_ai_benchmarking` (relative ranks: growth/margins/valuation/sentiment)
- `rankalpha.fact_ai_summary_metrics` (upside/downside/base-case and risk-reward summary)
- `rankalpha.fact_ai_overall_summary` (lean structured summary payload)
- `rankalpha.fact_ai_human_analyst_target` (scraped “human analyst target” distribution snapshot)

### 4.3 Operational queue (news-driven scheduling): `sentiment_analysis_queue`

The sentiment agent can read/process a DB-backed queue for event/news-driven runs.

- **DB object:** `rankalpha.sentiment_analysis_queue`
- **What it stores:**
  - `stock_key`, `symbol`
  - optional linkage to a news event (`event_id`) and raw news payload (`raw_id`)
  - title/url metadata, priority, status, timestamps, attempts, and “run after” controls

## 5) Canonical “latest” views and how the UI/API consumes AI analysis

### 5.1 Denormalized views

- **Full history view:** `rankalpha.vw_ai_analysis_full`  
  A denormalized join over `fact_ai_stock_analysis` and several child tables, aggregating catalysts/risks/peers into JSON/arrays.

- **Latest-per-symbol view:** `rankalpha.vw_ai_analysis_latest`  
  Defines “latest” deterministically using:
  - `date_key DESC`, then `load_ts DESC`, then `analysis_id DESC`

Primary API consumers:
- `GET /api/v1/ai-analysis` (history/list)
- `GET /api/v1/ai-analysis/latest` (latest lists)
- `GET /api/v1/ai-analysis/{symbol}` and `/id/{analysis_id}` (detail)

### 5.2 List and proximity materializations

- **Latest list MV:** `rankalpha.mv_ai_analysis_latest_list` (for fast list queries)
- **Scenario proximity MV:** `rankalpha.mv_ai_scenario_proximity` and view `rankalpha.vw_ai_scenario_proximity` (when enabled)

## 6) How the “AI Sentiment score” (0–100) is produced today

RankAlpha’s grading layer sources “Sentiment” from a **scenario-based sentiment proxy** when available.

### 6.1 Scenario-based proxy (preferred): `mv_sentiment_proxy`

- **DB object:** `rankalpha.mv_sentiment_proxy`
- **Inputs:**
  - latest AI analysis per symbol (from `fact_ai_stock_analysis`)
  - bull/base/bear targets + probabilities (from `fact_ai_price_scenario`)
  - latest close price (from `fact_security_price`)
- **Computation:**
  - Expected return is computed as a probability-weighted expected return vs the latest close:
    - `ER = Σ p_i * ((target_i / close) - 1)`
  - Probabilities are normalized to sum to 1 when provided; if missing, defaults are used (0.2/0.6/0.2).
  - ER is then mapped to a **0–100 cross-sectional score** using a robust 5th–95th percentile scaling:
    - `score = clamp( (ER - p05) / (p95 - p05) * 100, 0, 100 )`

This `sentiment_proxy_score` is the value used by `rankalpha.mv_latest_grades.sentiment_score` when present.

### 6.2 Fallback proxy (when scenario proxy is missing)

The scorer also computes a fallback sentiment score from `vw_ai_analysis_latest` using:
- `news_sentiment_30d` and `social_sentiment_7d` (averaged), then normalized to 0–100.

Operationally:
- `apps/scorer/src/services/alpha_inputs.py` prefers `mv_sentiment_proxy.sentiment_proxy_score` if available, else uses the normalized `news/social` proxy.
- `apps/scorer/src/main.py` writes the resulting value into `fact_score_history` under score type `sentiment score`.

## 7) Data sensitivity notes (privacy / compliance)

- The AI analysis tables store **public-market context** and **model-generated text** (summaries, risks, catalysts).
- Some fields may include **names of people/companies** mentioned in public news or filings, but the system is not designed to ingest user PII.
- URLs and headlines may be stored (public sources). Secrets/credentials should never be stored in these tables.

## 8) Audit/verification queries (examples)

- Latest analysis per symbol:
  - `SELECT * FROM rankalpha.vw_ai_analysis_latest WHERE symbol='AAPL';`
- Confirm scenario proxy availability:
  - `SELECT symbol, px_date_key, sentiment_proxy_score FROM rankalpha.mv_sentiment_proxy ORDER BY sentiment_proxy_score DESC NULLS LAST;`
- Confirm sentiment score is being written into score history:
  - `SELECT max(date_key) FROM rankalpha.fact_score_history f JOIN rankalpha.dim_score_type t ON t.score_type_key=f.score_type_key WHERE t.score_type_name='sentiment score';`
- Queue health (if using news/event-driven runs):
  - `SELECT status, count(*) FROM rankalpha.sentiment_analysis_queue GROUP BY status ORDER BY 2 DESC;`

## 9) Where to look in code

- Workflow/orchestration: `apps/sentiment/src/analysis_workflow.py`
- Persistence (DB writes): `apps/sentiment/src/persistence.py`
- Queue worker: `apps/sentiment/src/queue_worker.py`
- “AI inputs → scorer scores” bridge: `apps/scorer/src/services/alpha_inputs.py`
- Grade composite source of sentiment: `docker/database/sql/migrations/V57__ai_latest_and_sentiment_proxy.sql`
