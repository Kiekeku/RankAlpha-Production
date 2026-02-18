import os
from airflow import DAG
from airflow.utils import timezone
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.models import Variable


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
}

dag = DAG(
    dag_id="test_docker_operator",
    description="Sanity checks for DockerOperator and networking",
    default_args=default_args,
    start_date=timezone.utcnow(),
    schedule=None,
    catchup=False,
    max_active_runs=1,
)

ENV_PROFILE = Variable.get("ENV_PROFILE", default_var=os.environ.get("RANKALPHA_ENV", "local"))
DOCKER_NETWORK = Variable.get(
    "DOCKER_NETWORK", default_var=os.environ.get("DOCKER_NETWORK", "rankalpha_backend_network")
)
INGESTION_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/ingestion.env"
ENV = _load_env_vars(INGESTION_ENV_PATH)


docker_hello = DockerOperator(
    task_id="docker_hello",
    image="hello-world",
    api_version="auto",
    auto_remove="success",
    docker_url="unix://var/run/docker.sock",
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    dag=dag,
)

pg_isready_db = DockerOperator(
    task_id="pg_isready_db",
    image="postgres:16",
    api_version="auto",
    auto_remove="success",
    command=(
        "bash -lc \"pg_isready -h ${HOST:-database} -p ${PORT:-5432} -U ${DB_USERNAME:-rankalpha} -t 5\""
    ),
    docker_url="unix://var/run/docker.sock",
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    environment={
        **{k: v for k, v in ENV.items() if k in {"HOST", "PORT", "DB_USERNAME"}},
    },
    dag=dag,
)

curl_api = DockerOperator(
    task_id="curl_api",
    image="busybox:1.36",
    api_version="auto",
    auto_remove="success",
    command=(
        "sh -lc 'wget -qO- ${API_URL:-http://api:6080/} | head -n1 > /dev/stdout'"
    ),
    docker_url="unix://var/run/docker.sock",
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    environment={
        "API_URL": Variable.get("API_URL", default_var="http://api:6080/"),
    },
    dag=dag,
)

docker_hello >> [pg_isready_db, curl_api]
