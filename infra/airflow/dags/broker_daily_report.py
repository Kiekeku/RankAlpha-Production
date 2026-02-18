from __future__ import annotations

import os
import re
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.exceptions import AirflowSkipException
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.timetables.interval import CronDataIntervalTimetable
from airflow.utils.dates import days_ago

from apps.broker.tradeexec.utils.market_calendar import is_trading_day


def _load_env_vars(env_file: str) -> dict[str, str]:
    try:
        out: dict[str, str] = {}
        with open(env_file) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                out[key.strip()] = val.strip().strip('"').strip("'")
        return out
    except FileNotFoundError:
        return {}


def _get_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _parse_accounts(env_map: dict[str, str]) -> list[str]:
    accounts: list[tuple[int, str]] = []
    for key, val in env_map.items():
        match = re.match(r"ACCOUNT(\d+)_ACCOUNT_NUMBER$", key)
        if not match:
            continue
        account = val.strip()
        if not account:
            continue
        accounts.append((int(match.group(1)), account))
    return [acct for _, acct in sorted(accounts, key=lambda item: item[0])]


def _resolve_accounts(env_map: dict[str, str]) -> list[str]:
    raw = Variable.get(
        "BROKER_REPORT_ACCOUNTS",
        default_var=os.environ.get("BROKER_REPORT_ACCOUNTS", ""),
    )
    raw = str(raw).strip()
    if raw:
        parts = [p.strip() for p in re.split(r"[,\s]+", raw) if p.strip()]
        return parts
    return _parse_accounts(env_map)


def _task_suffix(account: str) -> str:
    suffix = re.sub(r"[^a-zA-Z0-9]+", "_", account).strip("_").lower()
    return suffix or "account"


def _send_report(
    account: str,
    base_url: str,
    connect_timeout: int,
    read_timeout: int,
    service_token: str | None,
) -> None:
    import requests

    url = f"{base_url.rstrip('/')}/report/{account}"
    headers = {"X-RA-Service-Token": service_token} if service_token else None
    response = requests.post(url, headers=headers, timeout=(connect_timeout, read_timeout))
    if response.status_code == 404:
        raise RuntimeError(f"Broker report failed: account {account} not configured (404).")
    response.raise_for_status()


def _skip_no_accounts() -> None:
    raise AirflowSkipException("No broker accounts configured for daily report.")


def _guard_trading_day(tz_name: str) -> None:
    now = pendulum.now(tz_name)
    if not is_trading_day(now.date()):
        raise AirflowSkipException(
            f"Skipping broker daily report; {now.date()} is not a trading day."
        )


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

ENV_PROFILE = Variable.get("ENV_PROFILE", default_var=os.environ.get("RANKALPHA_ENV", "local"))
BROKER_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/broker.env"

REPORT_TZ_NAME = Variable.get(
    "BROKER_REPORT_TIMEZONE",
    default_var=os.environ.get("BROKER_REPORT_TIMEZONE", "America/Denver"),
)
REPORT_SCHEDULE = Variable.get(
    "BROKER_REPORT_SCHEDULE",
    default_var=os.environ.get("BROKER_REPORT_SCHEDULE", "30 6 * * *"),
)
LOCAL_TZ = pendulum.timezone(REPORT_TZ_NAME)

BROKER_API_URL = Variable.get(
    "BROKER_API_URL",
    default_var=os.environ.get("BROKER_API_URL", "http://broker:8000"),
)
BROKER_SERVICE_TOKEN = Variable.get(
    "BROKER_SERVICE_TOKEN",
    default_var=os.environ.get("BROKER_SERVICE_TOKEN", ""),
).strip()
CONNECT_TIMEOUT = _get_int(
    Variable.get("BROKER_REPORT_CONNECT_TIMEOUT", default_var=os.environ.get("BROKER_REPORT_CONNECT_TIMEOUT", "10")),
    10,
)
READ_TIMEOUT = _get_int(
    Variable.get("BROKER_REPORT_READ_TIMEOUT", default_var=os.environ.get("BROKER_REPORT_READ_TIMEOUT", "300")),
    300,
)

ENV_BROKER = _load_env_vars(BROKER_ENV_PATH)
ACCOUNTS = _resolve_accounts(ENV_BROKER)

dag = DAG(
    dag_id="broker_daily_report",
    description="Daily broker report email for configured IBKR accounts",
    default_args=default_args,
    timetable=CronDataIntervalTimetable(cron=REPORT_SCHEDULE, timezone=LOCAL_TZ),
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["broker", "reports"],
)

if not ACCOUNTS:
    PythonOperator(
        task_id="skip_no_accounts",
        python_callable=_skip_no_accounts,
        dag=dag,
    )
else:
    guard = PythonOperator(
        task_id="guard_trading_day",
        python_callable=_guard_trading_day,
        op_kwargs={"tz_name": REPORT_TZ_NAME},
        dag=dag,
    )
    previous = None
    for account in ACCOUNTS:
        task = PythonOperator(
            task_id=f"send_report_{_task_suffix(account)}",
            python_callable=_send_report,
            op_kwargs={
                "account": account,
                "base_url": BROKER_API_URL,
                "connect_timeout": CONNECT_TIMEOUT,
                "read_timeout": READ_TIMEOUT,
                "service_token": BROKER_SERVICE_TOKEN,
            },
            dag=dag,
        )
        if previous is None:
            guard >> task
        else:
            previous >> task
        previous = task
