FROM python:3.12-slim AS builder

WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

# Copy project files needed for dependency resolution
COPY apps/newswire/pyproject.toml apps/newswire/uv.lock ./apps/newswire/
COPY apps/common ./apps/common

# Create venv and install deps relative to the newswire project directory
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app/apps/newswire
RUN uv venv --python 3.12 /opt/venv && uv sync --locked

# Copy source after deps to leverage Docker layer caching
COPY apps/newswire/src ./src
COPY apps/newswire/main.py /app/apps/newswire/main.py

FROM python:3.12-slim
RUN addgroup --system app && adduser --system --ingroup app app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:/app/apps/newswire/src"
# Run as root to ensure we can write shared volumes (schedule)
USER root
WORKDIR /app

ENV NEWS_SOURCES="rss" \
    NEWS_PREMARKET_START="07:00" \
    NEWS_PREMARKET_END="09:15" \
    NEWS_TIMEZONE="America/New_York" \
    NEWS_MATERIALITY_THRESHOLD="0.80" \
    NEWS_POLL_INTERVAL="180" \
    NEWS_POLL_INTERVAL_PRE="60" \
    NEWS_CURSOR_OVERLAP_MIN="2" \
    GDELT_QUERY="(sourcecountry:US OR sourcecountry:CA) AND (earnings OR guidance OR merger OR acquisition OR bankruptcy OR \"SEC\" OR \"FDA\" OR \"DOJ\" OR \"CFTC\" OR recall OR dividend OR layoffs)" \
    NEWS_GDELT_PERIOD_SEC="900" \
    NEWS_SERPER_PERIOD_SEC="300" \
    NEWS_GDELT_PERIOD_PRE_SEC="900" \
    NEWS_SERPER_PERIOD_PRE_SEC="60"
ENV NEWS_LLM_AUTO="false" \
    NEWS_LLM_MAX_EVENTS="5" \
    NEWS_LLM_MAX_EVENTS_PRE="10" \
    NEWS_LLM_QUEUE_MAX_EVENTS="10" \
    NEWS_LLM_QUEUE_WINDOW_SEC="300" \
    NEWS_LLM_PRE_ONLY="false" \
    NEWS_LLM_MIN_SCORE="0.50" \
    NEWS_EVENT_DUP_WINDOW_HOURS="72" \
    NEWS_LLM_FUZZY_SCORE="88" \
    NEWS_LLM_ALLOWED_EXCHANGES="NASDAQ,NYSE,NYSEARCA,NYSE AMERICAN,OTC,TSX,TSXV,CSE,NEO"

# Run with the venv’s Python; no need for uv at runtime
CMD ["/opt/venv/bin/python", "apps/newswire/main.py"]
