FROM apache/airflow:2.11.0-python3.12


COPY infra/airflow/dags /opt/airflow/dags
COPY infra/airflow/scripts /opt/airflow/scripts
COPY apps /app/apps

USER root

RUN chmod +x /opt/airflow/scripts/*.sh \
 && true

RUN apt-get update \
 && apt-get install -y docker.io gosu \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY infra/airflow/wait-for-it.sh /opt/wait-for-it.sh
RUN chmod +x /opt/wait-for-it.sh

USER airflow

COPY infra/airflow/pyproject.toml infra/airflow/uv.lock ./

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

ENV VENV_PATH="/app/.venv"
ENV PATH="$VENV_PATH/bin:$PATH"
ENV PYTHONPATH=/app

RUN pip install uv \
 && uv pip install --no-deps -r <(uv pip compile --output -)

WORKDIR /opt/airflow
COPY infra/airflow/dags/ ./dags
