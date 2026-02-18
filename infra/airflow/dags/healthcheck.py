import os
from datetime import timedelta

from airflow import DAG
from airflow.utils.dates import days_ago
from airflow.models import Variable
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount


def _load_env_vars(env_file: str) -> dict:
    try:
        out: dict[str, str] = {}
        with open(env_file) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
        return out
    except FileNotFoundError:
        return {}


default_args = {
    "owner": "airflow",
    "retries": 0,
}

dag = DAG(
    dag_id="healthcheck",
    description="Nightly health checks for RankAlpha stack",
    default_args=default_args,
    schedule="15 3 * * *",  # 03:15 daily
    start_date=days_ago(0),
    catchup=False,
    max_active_runs=1,
)

ENV_PROFILE = Variable.get("ENV_PROFILE", default_var=os.environ.get("RANKALPHA_ENV", "local"))
DOCKER_NETWORK = Variable.get(
    "DOCKER_NETWORK", default_var=os.environ.get("DOCKER_NETWORK", "rankalpha_backend_network")
)
INGESTION_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/ingestion.env"
CACHE_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/cache.env"
API_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/api.env"

ENV_DB = _load_env_vars(INGESTION_ENV_PATH)
ENV_CACHE = _load_env_vars(CACHE_ENV_PATH)
ENV_API = _load_env_vars(API_ENV_PATH)


check_db = DockerOperator(
    task_id="check_db",
    image="postgres:16",
    api_version="auto",
    auto_remove="success",
    command=(
        "bash -lc \"pg_isready -h ${HOST:-database} -p ${PORT:-5432} -U ${DB_USERNAME:-rankalpha} -t 5\""
    ),
    docker_url="unix://var/run/docker.sock",
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    mount_tmp_dir=False,
    environment={
        **{k: v for k, v in ENV_DB.items() if k in {"HOST", "PORT", "DB_USERNAME"}},
    },
    dag=dag,
)

check_cache = DockerOperator(
    task_id="check_cache",
    image="redis:7-alpine",
    api_version="auto",
    auto_remove="success",
    command=(
        "sh -lc 'redis-cli -h ${REDIS_HOST:-cache} -p ${REDIS_PORT:-6379} PING'"
    ),
    docker_url="unix://var/run/docker.sock",
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    mount_tmp_dir=False,
    environment={
        "REDIS_HOST": ENV_CACHE.get("REDIS_HOST", "cache"),
        "REDIS_PORT": ENV_CACHE.get("REDIS_PORT", "6379"),
    },
    dag=dag,
)

check_api = DockerOperator(
    task_id="check_api",
    image="busybox:1.36",
    api_version="auto",
    auto_remove="success",
    command=(
        "sh -lc 'wget -qO- ${API_URL:-http://api:6080/} | head -n1 > /dev/stdout'"
    ),
    docker_url="unix://var/run/docker.sock",
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    mount_tmp_dir=False,
    environment={
        "API_URL": Variable.get("API_URL", default_var=ENV_API.get("API_URL", "http://api:6080/")),
    },
    dag=dag,
)

check_volume_prices = DockerOperator(
    task_id="check_volume_prices",
    image="busybox:1.36",
    api_version="auto",
    auto_remove="success",
    command=(
        "sh -lc 'test -d /data/prices && touch /data/prices/.health && echo OK'"
    ),
    docker_url="unix://var/run/docker.sock",
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    mount_tmp_dir=False,
    mounts=[
        Mount(source="prices_data", target="/data/prices", type="volume"),
    ],
    dag=dag,
)

check_dockeroperator = DockerOperator(
    task_id="check_dockeroperator",
    image="hello-world",
    api_version="auto",
    auto_remove="success",
    docker_url="unix://var/run/docker.sock",
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    mount_tmp_dir=False,
    dag=dag,
)

check_dockeroperator >> [check_db, check_cache, check_api, check_volume_prices]
