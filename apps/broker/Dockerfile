FROM ghcr.io/astral-sh/uv:python3.12-alpine AS builder

# SECURITY: Do NOT bake env/ into the image; runtime env_file/volume provides it.
# COPY env /app/env
WORKDIR /app

# Copy the broker app and shared common code
COPY apps/broker ./apps/broker
COPY apps/common ./apps/common

# Create venv and install dependencies from broker directory
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv venv --python 3.12 /opt/venv

WORKDIR /app/apps/broker
RUN uv sync --locked

# Runtime stage
FROM python:3.12-alpine

RUN addgroup -S app && adduser -S -G app -D app && apk add --no-cache curl tzdata

# Copy virtual environment and source
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# Environment/path setup
ENV VENV_PATH=/opt/venv
ENV UV_PROJECT_ENVIRONMENT=${VENV_PATH}
ENV PATH="/opt/venv/bin:/usr/local/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PORT=8000

WORKDIR /app/apps/broker

RUN chown -R app:app /opt/venv /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD sh -lc 'curl -sf http://localhost:${PORT:-8000}/health || curl -sf http://localhost:${PORT:-8000}/ || exit 1'

CMD ["sh", "-lc", "uv run uvicorn tradeexec.service:app --host 0.0.0.0 --port ${PORT:-8000}"]
