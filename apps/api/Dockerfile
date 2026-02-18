FROM ghcr.io/astral-sh/uv:python3.12-alpine AS builder
WORKDIR /app

# Copy the entire apps directory structure to maintain relative paths
COPY apps/api ./apps/api
COPY apps/common ./apps/common

# Create venv and install dependencies from api directory
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv venv --python 3.12 /opt/venv

# Change to api directory and sync dependencies
WORKDIR /app/apps/api
RUN uv sync --locked

# Runtime stage
FROM python:3.12-alpine

RUN addgroup -S app && adduser -S -G app -D app

# Copy virtual environment and source
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
# Optional: uv binary not needed at runtime when using prebuilt venv
# COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# Install curl for health checks
RUN apk add --no-cache curl

# Set environment variables
ENV VENV_PATH=/opt/venv
ENV PATH="/opt/venv/bin:/usr/local/bin:$PATH"
ENV PYTHONPATH="/app"

WORKDIR /app/apps/api

RUN chown -R app:app /opt/venv /app

USER app

# Default listen port (can be overridden by environment)
ENV PORT=6080

EXPOSE 6080

# Health check (respects PORT env)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD sh -lc 'curl -f http://localhost:${PORT:-6080}/ || exit 1'

# Start the FastAPI app (bind to ${PORT}) using the prebuilt venv
CMD ["sh", "-lc", "/opt/venv/bin/python -m uvicorn apps.api.src.main:app --host 0.0.0.0 --port ${PORT:-6080}"]
