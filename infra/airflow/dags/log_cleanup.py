"""Daily cleanup of old Airflow task and sentiment logs to keep disk usage bounded."""

from __future__ import annotations

import os

from airflow import DAG
from airflow.configuration import conf
from airflow.models import Variable
from airflow.operators.bash import BashOperator
from airflow.utils import timezone
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount


def _parse_int(value: str | None, fallback: int) -> int:
    try:
        return int(value) if value is not None else fallback
    except ValueError:
        return fallback


ENV_DEFAULT_RETENTION_DAYS = _parse_int(os.getenv("AIRFLOW_LOG_RETENTION_DAYS"), 30)
SENTIMENT_DEFAULT_RETENTION_DAYS = _parse_int(
    os.getenv("SENTIMENT_LOG_RETENTION_DAYS"), ENV_DEFAULT_RETENTION_DAYS
)
SENTIMENT_LOG_VOLUME = os.getenv(
    "SENTIMENT_LOGS_VOLUME",
    Variable.get("SENTIMENT_LOGS_VOLUME", default_var="rankalpha-local_sentiment_logs"),
)
COMPANY_REPORTS_DEFAULT_RETENTION_DAYS = _parse_int(
    os.getenv("COMPANY_REPORT_RETENTION_DAYS"), 90
)
COMPANY_REPORTS_MAX_AGE_DAYS = _parse_int(
    os.getenv("COMPANY_REPORT_MAX_AGE_DAYS"), 365
)
COMPANY_REPORTS_VOLUME = os.getenv(
    "COMPANY_REPORTS_VOLUME",
    Variable.get("COMPANY_REPORTS_VOLUME", default_var="rankalpha-local_company_reports"),
)

dag = DAG(
    dag_id="log_cleanup",
    description="Prune local task logs older than the retention window",
    start_date=timezone.utcnow(),
    schedule="30 4 * * *",
    catchup=False,
    max_active_runs=1,
    tags=["maintenance"],
)

# The log directory is shared across web/scheduler/worker via the airflow_logs volume.
LOG_DIR = conf.get("logging", "base_log_folder")

cleanup_logs = BashOperator(
    task_id="delete_old_logs",
    bash_command=(
        "set -euo pipefail\n"
        "RETENTION_DAYS={{ var.value.get('LOG_RETENTION_DAYS', params.default_retention_days) }}\n"
        'if ! [[ ${RETENTION_DAYS} =~ ^[0-9]+$ ]]; then\n'
        "  RETENTION_DAYS={{ params.default_retention_days }}\n"
        "fi\n"
        "find {{ params.log_dir }} -type f -mtime +${RETENTION_DAYS} -print -delete\n"
        "find {{ params.log_dir }} -type d -empty -delete\n"
    ),
    params={
        "default_retention_days": ENV_DEFAULT_RETENTION_DAYS,
        "log_dir": LOG_DIR,
    },
    dag=dag,
)

cleanup_sentiment_logs = DockerOperator(
    task_id="delete_old_sentiment_logs",
    image="busybox:1.36",
    api_version="auto",
    auto_remove="success",
    command=(
        "sh -c \"set -e;"
        "RETENTION_DAYS={{ var.value.get('SENTIMENT_LOG_RETENTION_DAYS', "
        "var.value.get('LOG_RETENTION_DAYS', params.default_retention_days)) }};"
        "case $RETENTION_DAYS in ''|*[!0-9]*) RETENTION_DAYS={{ params.default_retention_days }};; esac;"
        "find /data/logs -type f -mtime +$RETENTION_DAYS -print -delete;"
        "find /data/logs -type d -empty -delete\""
    ),
    mounts=[Mount(target="/data/logs", source=SENTIMENT_LOG_VOLUME, type="volume")],
    docker_url="unix://var/run/docker.sock",
    network_mode=None,
    do_xcom_push=False,
    params={
        "default_retention_days": SENTIMENT_DEFAULT_RETENTION_DAYS,
    },
    dag=dag,
)

cleanup_logs >> cleanup_sentiment_logs

cleanup_company_reports = DockerOperator(
    task_id="delete_old_company_reports",
    image="busybox:1.36",
    api_version="auto",
    auto_remove="success",
    command=(
        "sh -c \"set -e;"
        "RETENTION_DAYS={{ var.value.get('COMPANY_REPORT_RETENTION_DAYS', params.default_retention_days) }};"
        "MAX_AGE_DAYS={{ var.value.get('COMPANY_REPORT_MAX_AGE_DAYS', params.default_max_age_days) }};"
        "case $RETENTION_DAYS in ''|*[!0-9]*) RETENTION_DAYS={{ params.default_retention_days }};; esac;"
        "case $MAX_AGE_DAYS in ''|*[!0-9]*) MAX_AGE_DAYS={{ params.default_max_age_days }};; esac;"
        "NOW=$(date +%s);"
        "RETENTION_CUTOFF=$((NOW - RETENTION_DAYS*86400));"
        "MAX_AGE_CUTOFF=$((NOW - MAX_AGE_DAYS*86400));"
        "find /data/company_reports -type f -print0 | while IFS= read -r -d '' f; do "
        "dir=$(dirname \"$f\"); "
        "mtime=$(stat -c %Y \"$f\" 2>/dev/null || busybox stat -c %Y \"$f\"); "
        "printf '%s\\t%s\\t%s\\n' \"$dir\" \"$mtime\" \"$f\"; "
        "done | sort -k1,1 -k2,2nr | awk -v rc=$RETENTION_CUTOFF -v mc=$MAX_AGE_CUTOFF '"
        "BEGIN{prev=\"\";} "
        "{dir=$1; mtime=$2; path=$3; "
        "  if (dir!=prev){is_latest=1; prev=dir;} else {is_latest=0;} "
        "  if ((!is_latest && mtime < rc) || (is_latest && mtime < mc)) {print path;} "
        "}' | while read -r victim; do "
        "  echo \"Deleting $victim\"; rm -f \"$victim\" || true; "
        "done;"
        "find /data/company_reports -type d -empty -delete\""
    ),
    mounts=[Mount(target="/data/company_reports", source=COMPANY_REPORTS_VOLUME, type="volume")],
    docker_url="unix://var/run/docker.sock",
    network_mode=None,
    do_xcom_push=False,
    params={
        "default_retention_days": COMPANY_REPORTS_DEFAULT_RETENTION_DAYS,
        "default_max_age_days": COMPANY_REPORTS_MAX_AGE_DAYS,
    },
    dag=dag,
)

cleanup_sentiment_logs >> cleanup_company_reports
