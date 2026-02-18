# RankAlpha Sentiment Analysis Service

## Purpose
The Sentiment service performs multi-agent AI analysis on financial news and reports to generate comprehensive investment insights. It uses a sophisticated pipeline of specialized AI agents to analyze news sentiment, extract themes and entities, and provide detailed explanations of investment scores.

## What's New
- yfinance MCP for fast, structured market data (prices, OHLCV, basic ratios).
- SEC EDGAR MCP for authoritative filings and XBRL facts (10‑K/10‑Q/8‑K).
- Agents now include `yfinance` and `edgar` tool servers alongside `serper` (preferred in prod), `g-search`, `fetch`, and `filesystem`.
- New env var `SEC_EDGAR_USER_AGENT` is supported via the sentiment Settings and exported for MCP subprocesses.
- JSON schema standardized to `pct` keys (e.g., `probability_pct`, `price_drop_risk_pct`).
- Filesystem MCP roots are configured before server start; reports save reliably under `/data/company_reports`.
- Logs are written to `/data/logs/sentiment_oai_*.log`; Compose mounts a `sentiment_logs` volume for persistence.
- Tool-usage summary is appended to the log after each run showing counts by tool and by agent.
- Optional “Consensus Screener” batch mode: run a one‑off (or daily) batch of top consensus symbols from `v_latest_screener_consensus` before the regular catalyst schedule.
- Re‑run guard: skip analysis if the latest run is within `SENTIMENT_SKIP_IF_WITHIN_DAYS` (default 1 day). Consensus and scheduled paths both honor this.
- Testing safeguard: cap scheduled analyses per pass with `SENTIMENT_MAX_ANALYSES` to limit OpenAI calls during local/dev runs.
- Sentiment queue entries now carry the originating news `raw_id`; the queue worker fetches the stored article body and logs a stub preview via `signals/pipeline.py` before any AI work runs.

## Technologies & Tools

### Core Framework
- **Python 3.12**: Async-capable runtime for agent orchestration
- **MCP Agent Framework**: Multi-agent coordination platform
- **OpenAI GPT-4**: Large language model for analysis
- **PostgreSQL**: Database for storing analysis results

### AI & NLP Technologies
- **OpenAI API**: GPT-4 for text analysis and reasoning
- **Multi-Agent System**: Specialized agents for different analysis tasks
- **Workflow Orchestration**: Coordinated agent execution
- **Quality Evaluation**: Built-in evaluation and optimization

### Data Processing
- **JSON Schema Validation**: Structured output validation
- **Text Processing**: News article cleaning and preprocessing
- **Entity Extraction**: Company, person, and financial concept identification
- **Sentiment Scoring**: Multi-dimensional sentiment analysis

## Design Principles

### 1. **Multi-Agent Architecture**
- Specialized agents for specific analysis tasks
- Chain-of-thought reasoning for transparency
- Quality evaluation and feedback loops
- Iterative refinement of analysis

### 2. **Explainable AI**
- Detailed explanations for all scores
- Reasoning transparency
- Audit trail of analysis decisions
- Human-readable output format

### 3. **Scalability**
- Asynchronous processing
- Batch analysis capabilities
- Rate limiting for API calls
- Efficient resource utilization

### 4. **Quality Assurance**
- Built-in evaluation metrics
- Output validation
- Confidence scoring
- Error handling and recovery

## Project Structure

### Core Files

#### `main.py`
- **Purpose**: Main orchestration and pipeline execution
- **Key Functions**:
  - `run_sentiment_analysis()`: Main entry point
  - `process_scheduled_stocks()`: Process stocks based on catalyst schedule
  - `analyze_company()`: Complete company analysis pipeline
  - `save_analysis_results()`: Store results in database
  - `update_schedule()`: Manage catalyst-based scheduling

#### Agent Configuration Files

#### `mcp_agent.config.yaml`
- **Purpose**: Configuration for AI agents and workflow
- **Key Sections**:
  - Agent definitions and prompts
  - LLM parameters and settings
  - Evaluation criteria
  - Output schemas

#### Schema Files (`schema/`)
- JSON schema definitions for structured outputs
- Validation rules for analysis results
- Type definitions for data consistency

## Multi-Agent Pipeline

### Agent Workflow
1. **TL;DR Agent**: Creates concise news summaries
2. **Sentiment Agent**: Analyzes sentiment dimensions
3. **Themes & Entities Agent**: Extracts key themes and entities
4. **Score Explanation Agent**: Provides detailed score rationale

### Agent Specializations

#### TL;DR Agent
```python
# Summarizes news articles into key points
- Extracts most important information
- Identifies key developments
- Maintains factual accuracy
- Provides concise overview
```

#### Sentiment Agent
```python
# Multi-dimensional sentiment analysis
- Overall sentiment (positive/negative/neutral)
- Confidence levels
- Sector-specific sentiment
- Time-horizon sentiment (short vs long term)
- Risk assessment
```

#### Themes & Entities Agent
```python
# Thematic and entity extraction
- Key investment themes
- Named entity recognition
- Financial concepts
- Market relationships
- Competitive landscape
```

#### Score Explanation Agent
```python
# Detailed score breakdown
- Factor contribution analysis
- Risk-reward assessment
- Catalyst identification
- Investment thesis summary
- Recommendation rationale
```

## Scheduling System

### Catalyst-Based Scheduling
- Analyzes stocks based on expected catalyst dates
- Schedules re-analysis around important events
- Maintains analysis schedule in JSON file
- Automatic rescheduling after completion

### Schedule Configuration
```json
{
  "AAPL": {
    "next_analysis_date": "2025-01-15",
    "catalyst_date": "2025-01-20",
    "catalyst_type": "earnings",
    "last_analysis": "2025-01-10"
  }
}
```

### Analysis Triggers
- **Initial Analysis**: First-time stock analysis
- **Pre-Catalyst**: 7 days before expected catalyst
- **Post-Catalyst**: 1 day after catalyst event
- **Follow-up**: 7 days after catalyst for impact assessment

## How Symbols Are Selected

The Sentiment app can run in three complementary modes. Symbol discovery uses the database as source of truth and considers only listings that are both active and eligible by price/liquidity policy:

- Active: `dim_stock.is_active = TRUE`
- Eligible: `mv_universe_eligible.eligible = TRUE` (policy from `rankalpha.universe_policy`, ETFs included)

Implementation lives primarily in `apps/sentiment/src/main.py`.

1) On‑Demand Single Symbol
- Triggered via CLI (`--symbol TICKER`) or `SENTIMENT_SYMBOL`.
- Optional `--force` (or `SENTIMENT_FORCE=1`) bypasses recency checks.
- Looks up the `stock_key` from `dim_stock`; skips if it ran for this stock within the configured recency window.

2) Consensus Batch (optional)
- When `SENTIMENT_USE_CONSENSUS=1`, a one‑off batch selects symbols from `v_latest_screener_consensus` joined to `dim_stock`:
  - Filters: `SENTIMENT_CONSENSUS_MIN_APPEARANCES`, `SENTIMENT_CONSENSUS_MIN_STYLES`.
  - Ordering: `consensus_score DESC`.
  - Limit: `SENTIMENT_CONSENSUS_LIMIT`.
- Each candidate is skipped if analyzed recently (see Recency Guard below) or already completed in the current process today.
- `SENTIMENT_CONSENSUS_BATCH_ONLY=1` runs the batch and exits.

3) Catalyst‑Driven Schedule Loop
- Schedule file: JSON at `/data/analysis_schedule/analysis_schedule.json` (override with `SENTIMENT_SCHEDULE_FILE`).
- Universe load: all active stocks from `dim_stock`, prioritized so tickers with no prior analysis run first.
- First‑time stocks run immediately; after a successful run, the schedule is seeded from detected catalysts.
- For covered stocks, an analysis runs on dates present in their schedule, subject to the Recency Guard.
- After each successful run, the schedule is updated from catalysts: `expected_date −7d`, `+1d`, `+7d`, deduped and future‑only.

Guards & Caps
- Recency Guard: skip if last analysis was within `SENTIMENT_SKIP_IF_WITHIN_DAYS` (default 1 day; same‑day re‑runs are skipped).
- Per‑Process Guard: in‑memory map prevents re‑running the same `stock_key` twice in one process/day.
- Pass Cap: limit scheduled work per pass via `SENTIMENT_MAX_ANALYSES` (useful in dev/test).

Key Environment Variables
- Selection toggles:
  - `SENTIMENT_SYMBOL` / `--symbol`, `SENTIMENT_FORCE`, `SENTIMENT_SINGLE_SYMBOL_ONLY`
  - `SENTIMENT_USE_CONSENSUS`, `SENTIMENT_CONSENSUS_MIN_APPEARANCES`, `SENTIMENT_CONSENSUS_MIN_STYLES`, `SENTIMENT_CONSENSUS_LIMIT`, `SENTIMENT_CONSENSUS_BATCH_ONLY`
  - `SENTIMENT_SKIP_IF_WITHIN_DAYS`, `SENTIMENT_MAX_ANALYSES`
- Paths: `SENTIMENT_DATA_DIR`, `SENTIMENT_OUTPUT_DIR`, `SENTIMENT_SCHEDULE_FILE`

Quick Examples
- On‑demand AAPL: `uv run python src/main.py --symbol AAPL`
- Consensus batch‑only (top 10): set `SENTIMENT_USE_CONSENSUS=1`, `SENTIMENT_CONSENSUS_LIMIT=10`, `SENTIMENT_CONSENSUS_BATCH_ONLY=1`, then run `uv run python src/main.py`
- Scheduled with cap 3/day: set `SENTIMENT_MAX_ANALYSES=3` and run `uv run python src/main.py`

## Data Flow

### Input Sources
- News articles and financial reports
- Market data for context
- Previous analysis history
- Catalyst schedules and dates

### Processing Pipeline
1. **Article Collection**: Gather relevant news
2. **Preprocessing**: Clean and structure text
3. **Agent Orchestration**: Run multi-agent analysis
4. **Quality Validation**: Check output quality
5. **Database Storage**: Save structured results
6. **Schedule Update**: Update next analysis dates

### Output Format
```json
{
  "symbol": "AAPL",
  "analysis_date": "2025-01-15",
  "tldr": "Brief summary of key developments",
  "sentiment": {
    "overall_score": 0.75,
    "confidence": 0.9,
    "dimensions": {...}
  },
  "themes": [...],
  "entities": [...],
  "score_explanation": "Detailed reasoning",
  "next_catalyst": "2025-01-20"
}
```

## Configuration Management

### Environment Variables
```env
# OpenAI configuration
OPENAI_API_KEY=<change_me>
OPENAI_MODEL=gpt-5-mini

# Database connection
DATABASE_URL=postgresql://...

# Analysis settings
MAX_ITERATIONS=3
ANALYSIS_BATCH_SIZE=10

# SEC EDGAR MCP
# Required for the EDGAR server; include your name and contact per SEC guidelines.
# Prefer setting this in env/<ENV>/sentiment.env (so it's scoped to the sentiment app).
SEC_EDGAR_USER_AGENT="Your Name your-email@example.com"
```

Optional sentiment-specific overrides:
- `SENTIMENT_TOOL_CACHE_TTL_SECONDS` — default cache TTL in seconds (falls back to
  86,400 if unset).
- `SENTIMENT_TOOL_CACHE_TTL_OVERRIDES` — JSON mapping of `tool_name` → TTL to let
  high-churn tools (e.g., `{ "yfinance.quote": 900 }`) refresh more frequently.
- `SENTIMENT_ANCHOR_API_TIMEOUT_SECONDS` — read timeout in seconds for anchor price
  fetches against `/api/v1/prices/latest` (defaults to 12).

### Model Selection
- Default model comes from `apps/sentiment/src/mcp_agent.config.yaml` under `openai.default_model`.
- You can override it per environment by setting `OPENAI_MODEL` (e.g., `OPENAI_MODEL=gpt-4o`).
- Precedence: `OPENAI_MODEL` env var → `openai.default_model` in config. No hardcoded fallback.

#### Token limits per model family
- GPT‑5 family (e.g., `gpt-5`, `gpt-5-mini`) uses `max_completion_tokens`.
  - Configure via `OPENAI_MAX_COMPLETION_TOKENS`.
- Other models use `max_tokens`.
  - Configure via `OPENAI_MAX_TOKENS`.
If unset, the app does not pass a token limit.

#### Reasoning controls
- The MCP framework sets a default reasoning effort (`medium`) which may cause a fallback to `o3` in some libraries when a non‑reasoning model is selected.
- To avoid this, either:
  - Set `OPENAI_DISABLE_REASONING=true` to remove the reasoning effort entirely; or
  - Set `OPENAI_REASONING_EFFORT=low|medium|high` explicitly.
The app logs the effective reasoning settings at startup.

### LLM & Search Guardrails (shared with Newswire)

Both the sentiment orchestrator and the newswire service now use the shared guardrail layer in `apps/common/src/ai` for outbound LLM and search usage. Highlights:

- **Budgets & rate limits** — Every call reserves a budget estimate before execution and reconciles actual usage afterward. Budgets enforce:
  - `AI_RPM`: per-minute request cap
  - `AI_MAX_DAILY_TOKENS`: total input + output tokens per UTC day
  - `AI_MAX_DAILY_COST_USD`: daily cost ceiling (USD)
- **Dry-run & disable toggles** — `AI_DISABLE=1` blocks calls entirely; `AI_DRY_RUN=1` short-circuits before reservation so dry runs never burn budget.
- **Daily reset** — Counters roll to a fresh bucket automatically at the UTC day boundary. If a call crosses midnight UTC, the reservation sticks to the prior day but the actual usage lands in the new day without double-charging.
- **Shared counters via Redis** — When `REDIS_URL` (or `REDIS_HOST`/`REDIS_PORT`) is configured, counters live in Redis so limits apply across processes and across services (sentiment + newswire). Without Redis, each worker falls back to an in-process counter.
- **Admin visibility & reset** — The API exposes `GET /api/v1/admin/budget` to inspect usage (tokens, cost, RPM) per service and `POST /api/v1/admin/budget/reset` to clear today’s counters/RPM. Protect these routes with `ADMIN_BEARER_TOKEN`.
- **Search throttling** — Newswire’s Serper polling goes through the same gateway with caching, per-query cap, and optional per-query cost (`SEARCH_COST_USD`, `SEARCH_SERPER_COST_USD`, etc.).

Environment knobs (documented in `sentiment.env.example`) apply to both services:

| Variable | Purpose |
| --- | --- |
| `AI_DISABLE` | Hard off switch for all guarded LLM/search calls |
| `AI_DRY_RUN` | Return stubbed results without reserving budget |
| `AI_RPM` | Requests per minute (RPM) limit |
| `AI_MAX_DAILY_TOKENS` | Total tokens (in + out) allowed per UTC day |
| `AI_MAX_DAILY_COST_USD` | Total estimated spend per UTC day |
| `AI_MAX_CONCURRENCY` | Async semaphore controlling concurrent outbound calls |
| `COST_SAFETY_MARGIN` | Multiplier applied to preflight cost/token estimates (default 1.25) |
| `AI_PRICING_JSON` / `AI_PRICING_YAML` | Pricing catalog used to translate tokens → USD |
| `SEARCH_DISABLE`, `SEARCH_COST_USD`, `SEARCH_SERPER_COST_USD`, … | Optional search throttles/cost per provider |
| `REDIS_URL` (or host/port/db/password) | Enables cross-process/shared counters and cache |

Because the guardrails live under `apps/common`, this section covers both apps. Link to it from the newswire docs if you need a reminder that the knobs are shared.

Budget alert emails reuse the shared Gmail/SMTP settings defined in `env/<env>/api.env` (`GMAIL_SENDER`, `GMAIL_RECIPIENT`, optional `BUDGET_ALERT_RECIPIENTS`, and `GMAIL_APP_PASSWORD` or `SMTP_*`). Configure those once and both services will emit warnings at 80% and 100% of their daily budgets.

### Agent Configuration
```yaml
# mcp_agent.config.yaml
agents:
  tldr_agent:
    prompt: "Summarize the key points..."
    max_tokens: 500
    temperature: 0.1
  
  sentiment_agent:
    prompt: "Analyze sentiment dimensions..."
    max_tokens: 800
    temperature: 0.2
```

### Prompt Files (Markdown)
- Agent and workflow prompts are externalized under `apps/sentiment/src/prompts/` as `.md` files:
  - `search_finder.md`, `research_evaluator.md`, `financial_analyst.md`, `report_writer.md`, `orchestrator_task.md`
- Dynamic values use double-brace tokens and are substituted at runtime:
  - `{{COMPANY_NAME}}`, `{{OUTPUT_PATH}}`
- To adjust behavior, edit these `.md` files without touching Python code.

## Quality Assurance

### Evaluation Metrics
- **Accuracy**: Factual correctness of analysis
- **Completeness**: Coverage of important aspects
- **Consistency**: Alignment between agents
- **Relevance**: Focus on investment-relevant information

### Validation Checks
```python
def validate_analysis(result):
    checks = [
        'sentiment' in result,
        'themes' in result and len(result['themes']) > 0,
        'score_explanation' in result,
        result['sentiment']['overall_score'] between -1 and 1
    ]
    return all(checks)
```

## Performance Monitoring

### Key Metrics
- **Analysis Completion Rate**: Successful vs failed analyses
- **Processing Time**: Time per analysis
- **API Usage**: OpenAI token consumption
- **Quality Scores**: Evaluation ratings
- **Coverage**: Stocks analyzed vs scheduled
- **OTLP traces / Prometheus metrics**: Emitted automatically when running under Docker Compose. Compose sets `OBSERVABILITY_METRICS_PORT` (default `9102`) so Prometheus can scrape the sentiment service directly.
  - `rankalpha_sentiment_reports_total{status="success|error"}` – report outcomes
  - `rankalpha_sentiment_tool_calls_total{tool="<name>", outcome="ok|error"}` – MCP tool call outcomes (counts “error” when the tool raises or returns `isError=true`)
  - Metrics surface in Grafana dashboards described in `docs/observability.md`.

### Health Monitoring
```python
def health_check():
    return {
        "status": "healthy",
        "last_analysis": last_run_time,
        "pending_analyses": len(get_scheduled_stocks()),
        "api_quota_remaining": check_openai_quota(),
        "quality_score_avg": calculate_avg_quality()
    }
```

## Running the Service

### Local Development
```bash
cd apps/sentiment
uv venv
uv sync --locked
# Optional for local (avoid /data permission issues):
# export SENTIMENT_DATA_DIR=$(pwd)/.localdata
uv run python src/main.py
```

### Consensus Screener (optional)
- The consensus snapshot aggregates the latest screener hits to one row per symbol with a `consensus_score`.
- Enable a batch of top names via environment:

```env
SENTIMENT_USE_CONSENSUS=true
SENTIMENT_CONSENSUS_MIN_APPEARANCES=2
SENTIMENT_CONSENSUS_MIN_STYLES=1
SENTIMENT_CONSENSUS_LIMIT=10
# If true, run only once and exit (useful for Airflow one‑off task)
SENTIMENT_CONSENSUS_BATCH_ONLY=false

# Skip re‑analysis if last analysis is within N days (default 1 = same day)
SENTIMENT_SKIP_IF_WITHIN_DAYS=1
```

Logs will include a summary like:

```
Consensus batch done: processed=7, skipped_recent=3, requested=10
Scheduled check summary: processed=12, skipped_recent=5, total_stocks=120
```

### Cost‑Safety Cap (Testing)
- Use `SENTIMENT_MAX_ANALYSES` to limit how many successful analyses the scheduled loop performs in a single pass.
- Purpose: keep OpenAI usage/costs under control while iterating locally.
- Scope: applies to the scheduled loop only; consensus batches are controlled by `SENTIMENT_CONSENSUS_LIMIT`, and on‑demand `--symbol` runs are unaffected.

```env
# Cap total successful analyses per scheduled pass
SENTIMENT_MAX_ANALYSES=2   # set 0 or unset to disable
```

When active, logs will include lines like:

```
Analyses cap active: SENTIMENT_MAX_ANALYSES=2
Reached analyses cap (2/2); stopping scheduled run
```

### MCP Server Setup (Ubuntu)
The sentiment pipeline uses Model Context Protocol (MCP) tools for search, HTTP fetch, and filesystem access. If you see warnings like:

- "Filesystem server not configured - report saving may fail"
- "No search MCP found. Configure 'serper' (preferred) or 'g-search'"

then the MCP servers are not set up or the config file wasn’t discovered. Follow these steps.

1) Install Node.js (provides `npx` for MCP servers)

Option A — NodeSource (system-wide):
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```
Option B — nvm (per-user):
```bash
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.nvm/nvm.sh
nvm install --lts
```
Verify:
```bash
node -v && npm -v && npx -v
```

2) Ensure `uv` is installed for the Python MCP fetch server
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
exec $SHELL -l  # reload PATH so `uv`/`uvx` are available
uv --version
```

3) (If using g-search) Install Playwright dependencies for g-search-mcp (Ubuntu/Debian)
The Google Search MCP uses a headless browser. Install the system libraries and Chromium via Playwright:
```bash
sudo apt-get update && sudo apt-get install -y \
  wget \
  ca-certificates \
  fonts-liberation \
  libasound2 \
  libatk-bridge2.0-0 \
  libatk1.0-0 \
  libatspi2.0-0 \
  libcairo2 \
  libcups2 \
  libdbus-1-3 \
  libdrm2 \
  libgbm1 \
  libglib2.0-0 \
  libgtk-3-0 \
  libnspr4 \
  libnss3 \
  libpango-1.0-0 \
  libx11-6 \
  libx11-xcb1 \
  libxcb1 \
  libxcomposite1 \
  libxcursor1 \
  libxdamage1 \
  libxext6 \
  libxfixes3 \
  libxi6 \
  libxrandr2 \
  libxrender1 \
  libxss1 \
  libxtst6 \
  xdg-utils

# Install Playwright and Chromium (Python route, mirrors Dockerfile)
pip install --user playwright
python -m playwright install chromium
```
Note: You can alternatively use the Node.js Playwright installer:
```bash
npm -g install playwright  # optional
npx playwright install chromium
```

4) Verify MCP server commands
- Serper MCP (Python, preferred in production):
```bash
# Requires SERPER_API_KEY in environment; no global install needed when using uvx
export SERPER_API_KEY=<change_me>
uvx serper-mcp-server --help
```
- Google Search MCP (Node, fallback):
```bash
npx -y g-search-mcp --help
```
- Filesystem MCP (Node):
```bash
npx -y @modelcontextprotocol/server-filesystem --help
```
- Fetch MCP (Python via uvx):
```bash
uvx mcp-server-fetch --help
```

5) Make sure the MCP config is discovered

The app expects `mcp_agent.config.yaml` in the current working directory. The file lives at `apps/sentiment/src/mcp_agent.config.yaml` in this repo. Choose one of:

- Run the app from `apps/sentiment` and create a symlink (recommended):
```bash
cd apps/sentiment
# Remove any stale file/symlink first (safe if it doesn't exist)
rm -f mcp_agent.config.yaml
# Create symlink so the app can auto-discover the MCP config from CWD
ln -s src/mcp_agent.config.yaml mcp_agent.config.yaml
# Verify
ls -l mcp_agent.config.yaml
```
- If symlinks are restricted in your environment, copy instead (remember to keep it updated):
```bash
cd apps/sentiment
cp -f src/mcp_agent.config.yaml mcp_agent.config.yaml
```
- Or run from the `src` folder (path-aware imports are handled in code):
```bash
cd apps/sentiment/src
uv run python main.py
```

Tip: If you switch between running from `apps/sentiment` and `apps/sentiment/src`, ensure the symlink exists in the directory you run from or run with the working directory set where `mcp_agent.config.yaml` resides.

6) Optional: Enable Yahoo Finance (yfinance) MCP for raw market data

This app can use a dedicated MCP server that wraps yfinance for fast, structured market data. We ship Docker images with this server pre-cloned; for local runs clone it once:

```bash
cd apps/sentiment
mkdir -p ext
git clone https://github.com/rankalpha/yahoo-finance-mcp.git ext/yahoo-finance-mcp
# Verify
ls ext/yahoo-finance-mcp/server.py
```

The MCP config already includes a `yfinance` entry:

```yaml
mcp:
  servers:
    yfinance:
      command: "uv"
      args: ["--directory", "ext/yahoo-finance-mcp", "run", "server.py"]
```

No separate install is required; `uv` will resolve dependencies on first use. In Docker, the server is cloned to `/app/apps/sentiment/ext/yahoo-finance-mcp` during the image build.

Quickstart: run the yfinance MCP locally

```bash
cd apps/sentiment
uv --directory ext/yahoo-finance-mcp run server.py --help
# or start the server
uv --directory ext/yahoo-finance-mcp run server.py
```

7) Optional: Enable SEC EDGAR MCP for filings and XBRL facts

Clone the EDGAR server locally (Docker images ship with it pre‑cloned) and install deps once:

```bash
cd apps/sentiment
mkdir -p ext
git clone https://github.com/rankalpha/sec-edgar-mcp.git ext/sec-edgar-mcp
uv --directory ext/sec-edgar-mcp sync --locked || uv --directory ext/sec-edgar-mcp sync
```

Set your SEC EDGAR user agent (required by the server) — recommended to place in your env file (e.g., `env/local/sentiment.env`):

```bash
export SEC_EDGAR_USER_AGENT="your-name your-email@example.com"
```

The MCP config includes an `edgar` server:

```yaml
mcp:
  servers:
    edgar:
      command: "uv"
      args: ["--directory", "ext/sec-edgar-mcp", "run", "-m", "sec_edgar_mcp.server"]
```

On first use, `uv` resolves dependencies. If `SEC_EDGAR_USER_AGENT` is missing, the server will refuse requests.

Quickstart: run the EDGAR MCP locally

```bash
cd apps/sentiment
export SEC_EDGAR_USER_AGENT="Your Name your-email@example.com"
uv --directory ext/sec-edgar-mcp run -m sec_edgar_mcp.server --help
# or start the server
uv --directory ext/sec-edgar-mcp run -m sec_edgar_mcp.server
```

8) Run with GPT‑5 and debug (optional)
```bash
export OPENAI_API_KEY=<change_me>
export OPENAI_MODEL=gpt-5-mini
export SENTIMENT_OPENAI_DEBUG=true   # capture OpenAI/httpx + step traces
# Prefer Serper for search in production:
# export SERPER_API_KEY=<change_me>
cd apps/sentiment
uv run python src/main.py --symbol AAPL --force
```

If debug is enabled, you will see per-step OpenAI Responses API calls, raw outputs (truncated), tool calls and results, and report save confirmation.

### Troubleshooting MCP Servers
- "Google Search server not found": `npx` missing or config not discovered. Install Node.js and ensure `mcp_agent.config.yaml` is in CWD (see step 4).
- "Filesystem server not configured": same as above; verify `npx -y @modelcontextprotocol/server-filesystem --help` works.
- `npx: command not found`: Install Node.js (step 1).
- `uvx: command not found`: Install `uv` (step 2) or replace `uvx mcp-server-fetch` with a globally installed alternative (e.g., `pipx install mcp-server-fetch` and adjust the config command accordingly).

#### If `npx -y g-search-mcp --help` hangs
This usually means either `npx` cannot reach the npm registry, or the `g-search-mcp` package is waiting on dependencies/credentials. Try:

1) Verify `npx` works for other packages:
```bash
npx -y @modelcontextprotocol/server-filesystem --help
npx -y cowsay hello   # any trivial package also works to test
```

2) Increase verbosity to see where it stalls:
```bash
NPM_CONFIG_LOGLEVEL=verbose npx -y g-search-mcp --help
# or
npm -ddd exec -y g-search-mcp -- --help
```

3) Clear npx cache and retry:
```bash
rm -rf ~/.npm/_npx
npm cache verify
npx -y g-search-mcp --help
```

4) Install globally to avoid on-the-fly npx installation:
```bash
sudo npm install -g g-search-mcp
g-search-mcp --help
```

4.1) Ensure Playwright browser and system deps are installed (common cause):
```bash
# System dependencies (see section above for the full list)
sudo apt-get update && sudo apt-get install -y libnss3 libxss1 libasound2 libatk-bridge2.0-0 libgbm1 libgtk-3-0 xdg-utils
# Install Chromium for Playwright
pip install --user playwright && python -m playwright install chromium
# Or Node variant: npm i -g playwright && npx playwright install chromium
```

5) Check network/proxy settings (common in corporate environments):
```bash
npm config get registry
# If needed
npm config set proxy http://YOUR_PROXY:PORT
npm config set https-proxy http://YOUR_PROXY:PORT
```

6) Credentials: many Google search MCP servers require API keys. Set the appropriate env vars before running (consult the server’s README). Common options:
- `GOOGLE_API_KEY` and `GOOGLE_CSE_ID` (Google Programmable Search Engine)
- or `SERPER_API_KEY` (Serper.dev)
- or `TAVILY_API_KEY` (if using a Tavily-backed server)

7) Workaround: use an alternative search MCP under the same server alias. Edit `apps/sentiment/src/mcp_agent.config.yaml` to point `g-search` to another MCP, e.g. Tavily:
```yaml
mcp:
  servers:
    g-search:
      command: "npx"
      args: ["-y", "mcp-server-tavily"]
```
Set `TAVILY_API_KEY` and re-run.


### Docker Deployment
```bash
# Part of docker-compose stack
docker compose -f compose/docker-compose.yml up sentiment
```

In Compose, the sentiment service mounts three volumes:
- `/data/company_reports` (report outputs)
- `/data/analysis_schedule` (schedule JSON)
- `/data/logs` (persistent logs)

### Paths and local development
- By default, the app writes to `/data/company_reports` and `/data/analysis_schedule` (suited for Docker volumes).
- For local runs without Docker, set writable paths via env:
  - `SENTIMENT_DATA_DIR=$(pwd)/.localdata` (used to derive both output and schedule paths), or
  - `SENTIMENT_OUTPUT_DIR` and `SENTIMENT_SCHEDULE_FILE` explicitly.

### Manual Analysis
```python
# Analyze specific symbol
python src/main.py --symbol AAPL

# Batch analysis
python src/main.py --batch --limit 10

# Force reanalysis
python src/main.py --symbol AAPL --force
```

- `--symbol`: runs an on-demand analysis for the symbol immediately (bypasses schedule).
- `--force`: if provided with `--symbol`, runs even if an analysis was already completed today.

### Docker Compose usage
- One-off run with arguments:
  - `docker compose -f compose/docker-compose.yml run --rm sentiment uv run main.py --symbol AAPL --force`

- Or set environment variables in your env file `env/<profile>/sentiment.env` and use regular `up`:
  - `SENTIMENT_SYMBOL=AAPL`
  - `SENTIMENT_FORCE=true`
  - Then: `docker compose -f compose/docker-compose.yml up sentiment`

- Temporary override via an extra compose file:
  - Create `compose/docker-compose.override.yml` with:
    ```yaml
    services:
      sentiment:
        command: ["uv", "run", "main.py", "--symbol", "AAPL", "--force"]
    ```
  - Run: `docker compose -f compose/docker-compose.yml -f compose/docker-compose.override.yml up --build sentiment`

### Debugging OpenAI requests
- To log the actual request details sent by the OpenAI SDK, enable debug mode:
  - Set `SENTIMENT_OPENAI_DEBUG=true` in your env file (or export it).
  - This sets `OPENAI_LOG=debug` and enables additional `httpx` logging.
  - Caution: This can be verbose. Do not enable in production.
  
Environment loading
- The app loads variables from env/<ENV>/*.env via the central Settings class.
- Default ENV is `local` (i.e., `env/local/*.env`). You can override with `RANKALPHA_ENV`.
- Recommended: Put `SENTIMENT_OPENAI_DEBUG` and `SENTIMENT_LOG_PROMPTS` in `env/local/sentiment.env`.

#### File logging for traces
- When debug is enabled, the app writes detailed traces (OpenAI requests/responses, tool calls, planner iterations) to a timestamped file:
  - `${SENTIMENT_DATA_DIR:-/data}/logs/sentiment_oai_YYYYMMDD_HHMMSS.log`
- Logs are also emitted to the console. Each log file rotates at ~10MB with up to 5 backups.
- Example:
  ```bash
  export SENTIMENT_DATA_DIR=$(pwd)/.localdata
  export SENTIMENT_OPENAI_DEBUG=true
  uv run python src/main.py --symbol AAPL --force
  # Inspect latest log:
  LATEST_LOG=$(ls -t .localdata/logs/sentiment_oai_*.log | head -1)
  tail -n 200 -f "$LATEST_LOG"
  ```

#### Capture full prompts and responses
- To log the full prompt messages sent to OpenAI (developer + user messages list) and the full Responses API result JSON, set:
  ```bash
  export SENTIMENT_LOG_PROMPTS=true
  ```
- This writes the complete structures into the same log file (`sentiment_oai.log`). Use with care; content can be large and may include sensitive data.
  
Note
- Even though internal components read `SENTIMENT_LOG_PROMPTS` from the process environment, the app bridges that flag from Settings. If you set it in `env/local/sentiment.env`, it will be picked up automatically at startup (no need to `export`).

#### Tuning fetch tool output length
- The `fetch` MCP server can truncate long pages. The app forces a minimum `max_length` per call so the model receives more content.
- Configure via environment variable (default: 5000 characters):
  ```bash
  export SENTIMENT_FETCH_MAX_LENGTH=5000
  ```
  Any tool call to `fetch` (or tools with "fetch" in their name) that does not set `max_length`, or sets a smaller value, will be upgraded to this minimum.

## Output Storage

### Database Schema
- **fact_news_sentiment**: Sentiment scores and metadata
- **fact_analysis_reports**: Full analysis results
- **dim_analysis_schedule**: Catalyst scheduling data

### File System
- **Company Reports**: `/data/company_reports/`
- **Schedule Files**: `/data/analysis_schedule/`
- **Logs**: Application and analysis logs

## Testing Strategy

### Unit Tests
```bash
pytest tests/sentiment/
```

### Integration Tests
- Mock OpenAI API responses
- Test agent coordination
- Validate output schemas
- Check database operations

## Advanced Features

### Iterative Refinement
- Quality evaluation after each analysis
- Automatic retry with feedback
- Prompt optimization based on results
- Continuous improvement loop

### Batch Processing
- Efficient processing of multiple stocks
- Resource optimization
- Parallel analysis execution
- Progress tracking and recovery

## Future Enhancements

### Planned Features
- Real-time news monitoring
- Custom agent specializations
- Alternative LLM providers
- Enhanced entity linking
- Multilingual analysis support
- Market regime awareness
- Sector-specific analysis
- Integration with external data sources

## Dependencies

### Internal
- `common`: Database models and utilities

### External
- openai>=1.0.0
- mcp-agent (custom framework)
- psycopg2-binary>=2.9.0
- pydantic>=2.0.0
- Node.js (for `npx`-based MCP servers)
- Playwright + Chromium (required by g-search MCP)
- MCP servers (local clones run via `uv`):
  - rankalpha/yahoo-finance-mcp (yfinance)
  - rankalpha/sec-edgar-mcp (EDGAR; requires `SEC_EDGAR_USER_AGENT`)

## Troubleshooting

### Common Issues

1. **OpenAI API Errors**
   - Check API key validity
   - Verify quota limits
   - Monitor rate limiting
   - Handle temporary outages

2. **Analysis Quality Issues**
   - Review agent prompts
   - Adjust temperature settings
   - Check input data quality
   - Validate output schemas

3. **Scheduling Problems**
   - Verify schedule file permissions
   - Check date calculations
   - Review catalyst data accuracy
   - Monitor schedule updates

4. **Performance Issues**
   - Optimize batch sizes
   - Adjust concurrent requests
   - Monitor memory usage
   - Review database queries

## Contributing

### Adding New Agents
1. Define agent in config file
2. Create specialized prompts
3. Add output validation
4. Write unit tests
5. Document agent purpose
6. Test integration with pipeline
