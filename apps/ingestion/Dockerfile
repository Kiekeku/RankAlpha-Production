FROM python:3.12-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore
RUN apt-get update \
    && apt-get -y install libpq-dev gcc \
    && apt-get clean

RUN pip install uv
WORKDIR /app

COPY apps/common ./apps/common

ENV VENV_PATH="/app/.venv"
ENV PATH="$VENV_PATH/bin:$PATH"
ENV PYTHONPATH="/app"

COPY apps/ingestion/pyproject.toml apps/ingestion/uv.lock ./

RUN uv sync --locked

COPY apps/ingestion/__init__.py ./apps/ingestion/__init__.py
COPY apps/ingestion/main.py ./apps/ingestion/main.py
COPY apps/ingestion/src/ ./apps/ingestion/src/
