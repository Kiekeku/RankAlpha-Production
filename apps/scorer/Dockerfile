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

COPY apps/scorer/pyproject.toml apps/scorer/uv.lock ./

RUN uv sync --locked

COPY apps/scorer/main.py ./apps/scorer/main.py
COPY apps/scorer/src/ ./apps/scorer/src/
