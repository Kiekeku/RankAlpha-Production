# Newswire (Collector + Dedup + Prefilter)

Purpose: collect breaking news (GDELT, Serper), deduplicate/cluster near-duplicates, and run a local, cheap first-pass materiality classifier (TF‑IDF + Logistic Regression) before any LLM escalation.

Key features
- Async pollers for sources (stubs included; wire keys and rate limits via env).
- URL canonicalization + SimHash-like fingerprint for robust dedup.
- TF‑IDF Logistic first-pass classifier with optional rules boost.
- Pre‑market “blitz” window configurable; default 07:00–09:15 America/New_York.

Trigger configuration (env)
- You can override the first‑pass trigger and rumor patterns without changing code:
  - `NEWS_TRIGGER_REGEXES` — list of regex patterns. Supply either:
    - JSON array: `["\\b(earnings|guidance)\\b","\\b(acquisition|merger)\\b"]`, or
    - A single string with patterns separated by `;;`:
      `\b(earnings|guidance)\b;;\b(acquisition|merger)\b`.
    - If unset, defaults cover M&A, earnings/guidance, bankruptcy, regulators, recalls/halts, exec moves, contracts, and ratings/price targets.
  - `NEWS_RUMOR_REGEX` — full regex to flag rumor/soft verbs (takes precedence if set).
  - `NEWS_RUMOR_WORDS` — comma/space‑separated tokens compiled to `\b(?:… )\b`.
  - Examples are included in `env/example/newswire.env.example`.
  - Amount and % tiers (scoring heuristics):
    - `NEWS_AMOUNT_SCORE_TIERS` — comma `threshold=score` pairs, units allowed (K/M/B/bn). Default `500M=1.0,100M=0.8,25M=0.6,5M=0.4`.
    - `NEWS_PCT_SCORE_TIERS` — comma `threshold=score` pairs using absolute percentage points. Default `20=0.8,10=0.6,5=0.4`.
    - JSON arrays of pairs are also accepted, e.g., `[[500000000,1.0],[100000000,0.8]]`.

Run (dev)
1) `cd apps/newswire && uv venv && uv sync --locked`
2) `export PYTHONPATH=../..`
3) Collector loop (pollers): `uv run python src/newswire/main.py`
4) Queue worker (process partner suggestions): `uv run python src/newswire/queue_worker.py`

Config (env)
- Core
  - `NEWS_SOURCES` (gdelt,serper,rss)
  - `NEWS_PREMARKET_START` (07:00), `NEWS_PREMARKET_END` (09:15), `NEWS_TIMEZONE` (America/New_York)
  - `NEWS_MATERIALITY_THRESHOLD` (0.80)
  - `NEWS_EVENT_DUP_WINDOW_HOURS` (72) — suppress creating a new event if a recent event exists with the same canonical URL or identical text fingerprint.
  - `NEWS_TRIGGER_REGEXES`, `NEWS_RUMOR_REGEX` / `NEWS_RUMOR_WORDS` (optional overrides)
  - `NEWS_TFIDF_MODEL_PATH` (optional joblib path)
  - Entity mapping cache: `NEWS_ENTITY_UNIVERSE_CACHE_SEC` (600), `NEWS_ENTITY_UNIVERSE_CACHE_MAX_STALE_SEC` (3600)
  - Service-specific configuration now lives in `env/<env>/newswire.env`; shared DB credentials remain in `env/<env>/ingestion.env`.
- Cadence / Cursors
  - `NEWS_CURSOR_OVERLAP_MIN` (2) – overlap minutes to avoid gaps
  - `NEWS_MAX_BACKFILL_HOURS` (72) – cap catch-up window after downtime (set `0` to disable)
  - `NEWS_GDELT_PERIOD_SEC` (900); `NEWS_GDELT_PERIOD_PRE_SEC` (optional pre‑market override)
  - `NEWS_SERPER_PERIOD_SEC` (300); `NEWS_SERPER_PERIOD_PRE_SEC` (optional pre‑market override)
  - `NEWS_RSS_PERIOD_SEC` (300); `NEWS_RSS_PERIOD_PRE_SEC` (optional pre‑market override)
  - `NEWS_POLL_INTERVAL` (180), `NEWS_POLL_INTERVAL_PRE` (60) – main loop sleep
- Serper
  - `SERPER_API_KEY`, `SERPER_NEWS_URL` (https://google.serper.dev/news)
  - `SERPER_GL` (us), `SERPER_HL` (en)
  - `SERPER_NEWS_QUERIES` (bar‑separated), `SERPER_TBS` (optional qdr:h/d/w)
  
 - RSS
  - `NEWS_RSS_FEEDS` — bar‑separated list or JSON array of feed URLs. Examples:
    - Federal Reserve: https://www.federalreserve.gov/feeds/press_all.xml
    - SEC press releases: https://www.sec.gov/news/pressreleases.rss
    - Treasury press releases: https://home.treasury.gov/news/press-releases/feed
    - USTR press releases: https://ustr.gov/press-releases/rss.xml
    - USITC press releases: https://www.usitc.gov/press_room/news_release/rss.xml
    - CFTC press releases: https://www.cftc.gov/PressRoom/PressReleases/rss
  - Windows are de‑duplicated downstream by canonical URL and fingerprint.
    - Defaults prioritize company-impactful events (earnings/guidance, M&A, bankruptcy, layoffs, buybacks/dividends, regulatory enforcement) to reduce macro noise.
- GDELT
  - `GDELT_DOC_URL` (https://api.gdeltproject.org/api/v2/doc/doc)
  - `GDELT_MODE` (ArtList), `GDELT_SORT` (DateDesc)
  - `GDELT_TIMESPAN` (15m fallback), `GDELT_STEP_MIN` (15)
  - `GDELT_QUERY` (default: US/CA event-focused filter on earnings/guidance/M&A/bankruptcy/regulatory actions)
- LLM (OpenAI)
  - `OPENAI_API_KEY` (required), `OPENAI_MODEL` (optional global), `NEWS_LLM_MODEL` (optional override)
  - Auto-run: `NEWS_LLM_AUTO` (false), caps `NEWS_LLM_MAX_EVENTS` (5), `NEWS_LLM_MAX_EVENTS_PRE` (10)
  - Queue worker cap: `NEWS_LLM_QUEUE_MAX_EVENTS` (10 per `NEWS_LLM_QUEUE_WINDOW_SEC=300` seconds)
  - Idempotency: `NEWS_LLM_FORCE_REANALYZE` (false) forces re-analysis when an event already has a successful LLM response.
  - Enable/disable: `NEWS_LLM_ENABLED` (true) gates all LLM calls (CLI + auto-run)
  - Filter: `NEWS_LLM_MIN_SCORE` (0.50), `NEWS_LLM_PRE_ONLY` (false)
  - Fuzzy mapping for LLM‑added impacts: `NEWS_LLM_FUZZY_SCORE` (88), `NEWS_LLM_ALLOWED_EXCHANGES` (NASDAQ,NYSE,NYSEARCA,NYSE AMERICAN,OTC,TSX,TSXV,CS E,NEO)
  - Sentiment enqueue (re-run analysis when highly material):
    - `NEWS_SENTIMENT_ENQUEUE_ENABLED` (true) disables the queue hand-off entirely when false
    - `NEWS_SENTIMENT_ENQUEUE_MIN_EVENT_SCORE` (0.85)
    - `NEWS_SENTIMENT_ENQUEUE_MIN_IMPACT_MAG` (70)
    - `NEWS_SENTIMENT_SCHEDULE_FILE` (optional path; default `/data/analysis_schedule/analysis_schedule.json`)
  - Guardrails (shared with sentiment): Budgets, dry-run toggles, Redis-backed counters, and admin endpoints are documented in [apps/sentiment/README.md](../sentiment/README.md#llm--search-guardrails-shared-with-newswire). Budget alert emails use the centralized SMTP/Gmail config under `env/<env>/api.env`.
- Queue worker
  - `NEWS_QUEUE_WORKER_SLEEP_SEC` (5) – idle sleep time when no jobs are pending.
  - `NEWS_QUEUE_WORKER_ID` – optional override for the worker identifier stored on queue rows; defaults to `<hostname>:<pid>`.
  - `NEWS_QUEUE_WORKER_MAX_ATTEMPTS` (5) – retry transient failures before marking the job failed.
  - `NEWS_QUEUE_WORKER_RETRY_BACKOFF_BASE_SEC` (30), `NEWS_QUEUE_WORKER_RETRY_BACKOFF_MAX_SEC` (3600) – exponential backoff.
  - `NEWS_QUEUE_WORKER_STALE_LOCK_SEC` (0) – reclaim jobs stuck `in_progress` (disabled by default; set >0 carefully to avoid double-processing).

- Body fetch guardrails
  - `NEWS_BODY_MAX_FETCH_BYTES` (800000) caps raw HTML bytes downloaded per article before extraction.
  - Existing controls still apply: allowlist (`NEWS_BODY_ALLOWLIST`), timeout (`NEWS_BODY_FETCH_TIMEOUT_SEC`), and stored text cap (`NEWS_BODY_MAX_CHARS`).

Data contract
- Writes raw/articles, clusters, events, and impacts to Postgres tables defined under `docker/database/sql/migrations` (see V63 migration).
- Processes partner submissions from `rankalpha.news_suggestion`/`news_ingest_queue` (see API `/api/v1/news/suggestions` endpoints). Suggestions are idempotent per `source_name` + `idempotency_key`.
- Trace viewer is available at `/admin/newswire` in the frontend admin console (requires admin role).
