from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.timetables.interval import CronDataIntervalTimetable
from airflow.utils.dates import days_ago


def _get_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _get_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    v = str(value).strip().lower()
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    return default


def _build_headers() -> dict[str, str]:
    shared_env: dict[str, str] = {}
    api_env: dict[str, str] = {}
    # Best-effort load env files if they exist (mirrors other DAGs).
    env_profile = Variable.get("ENV_PROFILE", default_var=os.environ.get("RANKALPHA_ENV", "local"))
    shared_path = f"/opt/rankalpha/env/{env_profile}/shared.env"
    api_path = f"/opt/rankalpha/env/{env_profile}/ingestion.env"
    for path, target in ((shared_path, shared_env), (api_path, api_env)):
        try:
            with open(path) as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    target[k.strip()] = v.strip().strip('"').strip("'")
        except FileNotFoundError:
            pass

    service_token = Variable.get(
        "AUTH_SERVICE_TOKEN",
        default_var=os.environ.get(
            "AUTH_SERVICE_TOKEN",
            shared_env.get("AUTH_SERVICE_TOKEN", api_env.get("AUTH_SERVICE_TOKEN", "")),
        ),
    ).strip()
    admin_token = Variable.get(
        "ADMIN_BEARER_TOKEN",
        default_var=os.environ.get(
            "ADMIN_BEARER_TOKEN",
            api_env.get("ADMIN_BEARER_TOKEN", ""),
        ),
    ).strip()

    headers = {"Content-Type": "application/json"}
    if service_token:
        token_value = service_token
        token_value = token_value[7:].strip() if token_value.lower().startswith("bearer ") else token_value
        headers["X-RA-Service-Token"] = token_value
        return headers
    if admin_token:
        headers["Authorization"] = admin_token if admin_token.startswith("Bearer ") else f"Bearer {admin_token}"
        return headers
    raise RuntimeError("No AUTH_SERVICE_TOKEN or ADMIN_BEARER_TOKEN configured for broker holdings sync.")


def _sync_broker_holdings(base_url: str, timeout_seconds: int) -> None:
    import requests

    url = f"{base_url.rstrip('/')}/api/v1/portfolio/broker-holdings/sync"
    headers = _build_headers()
    resp = requests.post(url, json={}, headers=headers, timeout=timeout_seconds)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"broker_holdings_sync failed ({resp.status_code}): {resp.text[:500]}"
        )


def _ingest_broker_fills(base_url: str, timeout_seconds: int) -> None:
    import requests

    url = f"{base_url.rstrip('/')}/api/v1/portfolio/broker-fills/ingest"
    headers = _build_headers()
    resp = requests.post(url, json={}, headers=headers, timeout=timeout_seconds)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"broker_fills_ingest failed ({resp.status_code}): {resp.text[:500]}"
        )


def _rollup_broker_attribution(base_url: str, timeout_seconds: int) -> None:
    import requests

    url = f"{base_url.rstrip('/')}/api/v1/portfolio/broker-attribution/rollup"
    headers = _build_headers()
    resp = requests.post(url, json={}, headers=headers, timeout=timeout_seconds)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"broker_attribution_rollup failed ({resp.status_code}): {resp.text[:500]}"
        )


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

TZ_NAME = Variable.get(
    "BROKER_HOLDINGS_SYNC_TIMEZONE",
    default_var=os.environ.get("BROKER_HOLDINGS_SYNC_TIMEZONE", "America/Denver"),
)
ENABLED = _get_bool(
    Variable.get(
        "BROKER_HOLDINGS_SYNC_ENABLED",
        default_var=os.environ.get("BROKER_HOLDINGS_SYNC_ENABLED", "true"),
    ),
    True,
)
SCHEDULE = Variable.get(
    "BROKER_HOLDINGS_SYNC_SCHEDULE",
    default_var=os.environ.get("BROKER_HOLDINGS_SYNC_SCHEDULE", "0 1 * * *"),
)
LOCAL_TZ = pendulum.timezone(TZ_NAME)

API_URL = Variable.get("API_URL", default_var=os.environ.get("API_URL", "http://api:6080"))
TIMEOUT = _get_int(
    Variable.get(
        "BROKER_HOLDINGS_SYNC_TIMEOUT_SECONDS",
        default_var=os.environ.get("BROKER_HOLDINGS_SYNC_TIMEOUT_SECONDS", "30"),
    ),
    30,
)

timetable = CronDataIntervalTimetable(cron=SCHEDULE, timezone=LOCAL_TZ) if ENABLED else None

dag = DAG(
    dag_id="broker_holdings_sync",
    description="Nightly broker holdings snapshot into portfolio_position and history"
    if ENABLED
    else "Broker holdings snapshot (disabled; manual trigger only)",
    default_args=default_args,
    timetable=timetable,
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["broker", "portfolio"],
)

PythonOperator(
    task_id="ingest_broker_fills",
    python_callable=_ingest_broker_fills,
    op_kwargs={"base_url": API_URL, "timeout_seconds": TIMEOUT},
    dag=dag,
)

PythonOperator(
    task_id="sync_broker_holdings",
    python_callable=_sync_broker_holdings,
    op_kwargs={"base_url": API_URL, "timeout_seconds": TIMEOUT},
    dag=dag,
)

PythonOperator(
    task_id="rollup_broker_attribution",
    python_callable=_rollup_broker_attribution,
    op_kwargs={"base_url": API_URL, "timeout_seconds": TIMEOUT},
    dag=dag,
)

dag.get_task("ingest_broker_fills") >> dag.get_task("sync_broker_holdings") >> dag.get_task(
    "rollup_broker_attribution"
)
