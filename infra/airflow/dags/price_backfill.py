import os
from datetime import timedelta
from typing import Iterable

import pendulum
import psycopg2
import requests
from airflow import DAG
from airflow.models import Variable
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.timetables.interval import CronDataIntervalTimetable
from airflow.utils.dates import days_ago
from docker.types import Mount


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=60),
}


def _get_int_config(var_name: str, default: int) -> int:
    raw = Variable.get(var_name, default_var=os.environ.get(var_name, str(default)))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _get_float_config(var_name: str, default: float) -> float:
    raw = Variable.get(var_name, default_var=os.environ.get(var_name, str(default)))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _get_bool_config(var_name: str, default: bool) -> bool:
    raw = Variable.get(var_name, default_var=os.environ.get(var_name, str(default).lower()))
    return str(raw).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def load_env_vars(env_file: str) -> dict:
    try:
        out = {}
        with open(env_file) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                out[key] = val
        return out
    except FileNotFoundError:
        print(f"[WARNING] Missing env file: {env_file}")
        return {}


def merge_env(base: dict, names: list[str]) -> dict:
    """Return a copy of base with values overridden by Airflow Variables when present."""
    merged = dict(base)
    for n in names:
        try:
            v = Variable.get(n, default_var=base.get(n))
        except Exception:
            v = base.get(n)
        if v is not None:
            merged[n] = v
    return merged


def _chunked(items: list[str], size: int) -> Iterable[list[str]]:
    if size <= 0:
        size = 1
    return (items[i : i + size] for i in range(0, len(items), size))


PIPELINE_TZ_NAME = Variable.get(
    "PIPELINE_TIMEZONE", default_var=os.environ.get("PIPELINE_TIMEZONE", "America/Denver")
)
PRICE_BACKFILL_TZ_NAME = Variable.get(
    "PRICE_BACKFILL_TIMEZONE",
    default_var=os.environ.get("PRICE_BACKFILL_TIMEZONE", PIPELINE_TZ_NAME),
)
PRICE_BACKFILL_SCHEDULE = Variable.get(
    "PRICE_BACKFILL_SCHEDULE",
    default_var=os.environ.get("PRICE_BACKFILL_SCHEDULE", "0 4 * * 0"),
)
PRICE_BACKFILL_ENABLED = _get_bool_config("PRICE_BACKFILL_ENABLED", False)

dag_kwargs = dict(
    dag_id="rankalpha_price_backfill",
    default_args=default_args,
    description="Full price history resync from Parquet into Postgres",
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
)
if PRICE_BACKFILL_ENABLED:
    dag_kwargs["timetable"] = CronDataIntervalTimetable(
        cron=PRICE_BACKFILL_SCHEDULE,
        timezone=pendulum.timezone(PRICE_BACKFILL_TZ_NAME),
    )
else:
    dag_kwargs["schedule_interval"] = None

dag = DAG(**dag_kwargs)

ENV_PROFILE = Variable.get("ENV_PROFILE", default_var=os.environ.get("RANKALPHA_ENV", "local"))
SHARED_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/shared.env"
INGESTION_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/ingestion.env"
API_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/api.env"
PRICES_DATA_VOLUME = Variable.get(
    "PRICES_DATA_VOLUME",
    default_var=os.environ.get("PRICES_DATA_VOLUME", "prices_data"),
)
DOCKER_NETWORK = Variable.get(
    "DOCKER_NETWORK",
    default_var=os.environ.get("DOCKER_NETWORK", "rankalpha_backend_network"),
)


def trigger_price_cache_refresh_task(**context) -> None:
    """Load active symbols and notify the API admin endpoint to warm price caches."""
    shared_env = load_env_vars(SHARED_ENV_PATH)
    ingestion_env = load_env_vars(INGESTION_ENV_PATH)
    api_env = load_env_vars(API_ENV_PATH)
    api_base_url = Variable.get(
        "API_URL",
        default_var=os.environ.get("API_URL", api_env.get("API_URL", "http://api:6080")),
    ).rstrip("/")
    refresh_url = Variable.get(
        "PRICE_CACHE_REFRESH_URL",
        default_var=os.environ.get(
            "PRICE_CACHE_REFRESH_URL",
            ingestion_env.get("PRICE_CACHE_REFRESH_URL") or api_env.get("PRICE_CACHE_REFRESH_URL"),
        ),
    )
    if not refresh_url:
        refresh_url = f"{api_base_url}/api/v1/admin/prices/cache-refresh"
        print(f"[price_cache_refresh] PRICE_CACHE_REFRESH_URL not set; using default {refresh_url}")

    db_name = shared_env.get("DATABASE_NAME")
    db_user = shared_env.get("DB_USERNAME")
    db_pass = shared_env.get("PASSWORD")
    db_host = shared_env.get("DB_HOST") or shared_env.get("HOST")
    db_port = shared_env.get("DB_PORT") or shared_env.get("DB_PORT_CONTAINER")
    for key, value in {
        "DATABASE_NAME": db_name,
        "DB_USERNAME": db_user,
        "PASSWORD": db_pass,
        "DB_HOST": db_host,
        "DB_PORT": db_port,
    }.items():
        if not value:
            raise RuntimeError(f"[price_cache_refresh] Missing required DB credential: {key}")

    with psycopg2.connect(
        database=db_name,
        user=db_user,
        password=db_pass,
        host=db_host,
        port=int(db_port),
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol FROM dim_stock WHERE is_active IS TRUE ORDER BY symbol")
            symbols = [row[0] for row in cur.fetchall()]
            cur.execute("SELECT MAX(price_date) FROM rankalpha.vw_stock_price_history")
            as_of_row = cur.fetchone()

    if not symbols:
        print("[price_cache_refresh] No active symbols returned; skipping.")
        return

    as_of_iso = as_of_row[0].isoformat() if as_of_row and as_of_row[0] else None
    chunk_size = int(
        Variable.get(
            "PRICE_HISTORY_CACHE_REFRESH_CHUNK_SIZE",
            default_var=os.environ.get(
                "PRICE_HISTORY_CACHE_REFRESH_CHUNK_SIZE",
                ingestion_env.get("PRICE_HISTORY_CACHE_REFRESH_CHUNK_SIZE", "50"),
            ),
        )
    )
    timeout = float(
        Variable.get(
            "PRICE_CACHE_REFRESH_TIMEOUT_SECONDS",
            default_var=os.environ.get(
                "PRICE_CACHE_REFRESH_TIMEOUT_SECONDS",
                ingestion_env.get("PRICE_CACHE_REFRESH_TIMEOUT_SECONDS", "15"),
            ),
        )
    )

    service_token = Variable.get(
        "AUTH_SERVICE_TOKEN",
        default_var=os.environ.get(
            "AUTH_SERVICE_TOKEN",
            shared_env.get("AUTH_SERVICE_TOKEN", api_env.get("AUTH_SERVICE_TOKEN", "")),
        ),
    )
    admin_token = Variable.get(
        "ADMIN_BEARER_TOKEN",
        default_var=os.environ.get("ADMIN_BEARER_TOKEN", api_env.get("ADMIN_BEARER_TOKEN", "")),
    )
    headers = {"Content-Type": "application/json"}
    if service_token:
        token_value = service_token.strip()
        token_value = token_value[7:].strip() if token_value.lower().startswith("bearer ") else token_value
        headers["X-RA-Service-Token"] = token_value
    elif admin_token:
        token_value = admin_token if admin_token.startswith("Bearer ") else f"Bearer {admin_token}"
        headers["Authorization"] = token_value

    total = len(symbols)
    succeeded = 0
    batches = 0
    for batch in _chunked(symbols, chunk_size):
        payload = {"symbols": batch, "reason": "airflow_backfill", "force": True}
        if as_of_iso:
            payload["as_of"] = as_of_iso
        resp = requests.post(refresh_url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"[price_cache_refresh] API call failed ({resp.status_code}): {resp.text[:200]}"
            )
        succeeded += len(batch)
        batches += 1

    print(
        f"[price_cache_refresh] Warmed cache for {succeeded}/{total} symbols "
        f"in {batches} batches (reason=airflow_backfill, as_of={as_of_iso})"
    )


repair_outliers = _get_bool_config("PRICE_BACKFILL_REPAIR_OUTLIERS", True)
max_ratio = _get_float_config("PRICE_BACKFILL_MAX_RATIO", 100.0)
max_abs = _get_float_config("PRICE_BACKFILL_MAX_ABS", 1.0e7)
limit_symbols = _get_int_config("PRICE_BACKFILL_LIMIT", 0)
symbols_override = Variable.get(
    "PRICE_BACKFILL_SYMBOLS", default_var=os.environ.get("PRICE_BACKFILL_SYMBOLS", "")
).strip()
dry_run = _get_bool_config("PRICE_BACKFILL_DRY_RUN", False)

backfill_cmd = ["python", "apps/ingestion/src/price_backfill.py"]
if dry_run:
    backfill_cmd.append("--dry-run")
if symbols_override:
    backfill_cmd.extend(["--symbols", symbols_override])
if limit_symbols > 0:
    backfill_cmd.extend(["--limit", str(limit_symbols)])
if repair_outliers:
    backfill_cmd.extend(
        ["--repair-outliers", "--max-ratio", str(max_ratio), "--max-abs", str(max_abs)]
    )

price_backfill = DockerOperator(
    task_id="price_backfill",
    image="rankalpha_ingestion",
    api_version="auto",
    auto_remove="success",
    command=" ".join(backfill_cmd),
    docker_url="unix://var/run/docker.sock",
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    cpus=float(Variable.get("INGESTION_CPUS", default_var="1.0")),
    mem_limit=Variable.get("INGESTION_MEM", default_var="2g"),
    environment=(lambda base: {
        **merge_env(
            base,
            [
                "DB_USERNAME",
                "PASSWORD",
                "DB_HOST",
                "DB_PORT",
                "DATABASE_NAME",
                "REDIS_URL",
            ],
        ),
        "RANKALPHA_ENV": ENV_PROFILE,
    })({**load_env_vars(INGESTION_ENV_PATH), **load_env_vars(SHARED_ENV_PATH)}),
    mounts=[Mount(source=PRICES_DATA_VOLUME, target="/data/prices", type="volume")],
    mount_tmp_dir=False,
    working_dir="/app",
    dag=dag,
)

refresh_mv_direct = DockerOperator(
    task_id="refresh_mv_direct",
    image="postgres:16",
    api_version="auto",
    auto_remove="success",
    command="""
bash -lc "set -euo pipefail;
psql -h ${DB_HOST} -p ${DB_PORT:-5432} -U ${DB_USERNAME} -d ${DATABASE_NAME} -v ON_ERROR_STOP=1 <<'SQL'
DO $do$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT matviewname
    FROM pg_matviews
    WHERE schemaname = 'rankalpha' AND matviewname LIKE 'mv_%'
  LOOP
    BEGIN
      EXECUTE format('REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.%I', r.matviewname);
    EXCEPTION WHEN others THEN
      EXECUTE format('REFRESH MATERIALIZED VIEW rankalpha.%I', r.matviewname);
    END;
  END LOOP;
END
$do$;
SQL
"
    """,
    docker_url="unix://var/run/docker.sock",
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    cpus=float(Variable.get("PSQL_CPUS", default_var="0.5")),
    mem_limit=Variable.get("PSQL_MEM", default_var="256m"),
    environment=(lambda base: {
        **merge_env(base, ["DB_USERNAME", "PASSWORD", "DB_HOST", "DB_PORT", "DATABASE_NAME"]),
        "PGPASSWORD": base.get("PASSWORD", ""),
    })({**load_env_vars(INGESTION_ENV_PATH), **load_env_vars(SHARED_ENV_PATH)}),
    mount_tmp_dir=False,
    working_dir="/",
    dag=dag,
)

purge_api_cache = BashOperator(
    task_id="purge_api_cache",
    bash_command="""
    auth=()
    if [ -n "${AUTH_SERVICE_TOKEN:-}" ]; then
      auth=(-H "X-RA-Service-Token: ${AUTH_SERVICE_TOKEN}")
    elif [ -n "${ADMIN_BEARER_TOKEN:-}" ]; then
      auth=(-H "Authorization: Bearer ${ADMIN_BEARER_TOKEN}")
    fi
    curl --silent --show-error "${auth[@]}" -X POST "$API_URL/api/v1/admin/cache/purge" \
      -H "Content-Type: application/json" \
      -d '{"prefixes":["httpcache:","prices:history:","prices:history:head:","prices:history:meta:","grade:","asset:","grades:","grades_v2:","grades_v3:","grades_v4:","grades_v7:","grades_v8:","grades_count_v1:","screener_changes:","screener_breadth:","ai_list:","ai_latest:","ai_id:","news_latest:","news_symbol:","px_latest_live_v1:"]}' \
      || true
    """,
    dag=dag,
    env={
        **load_env_vars(SHARED_ENV_PATH),
        **load_env_vars(API_ENV_PATH),
        "API_URL": Variable.get("API_URL", default_var=os.environ.get("API_URL", "http://api:6080")),
    },
)

price_cache_refresh = PythonOperator(
    task_id="price_cache_refresh",
    python_callable=trigger_price_cache_refresh_task,
    dag=dag,
)

price_backfill >> refresh_mv_direct >> purge_api_cache >> price_cache_refresh
