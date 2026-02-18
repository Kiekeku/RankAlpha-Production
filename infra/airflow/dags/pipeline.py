import os
import time
from typing import Iterable
import docker
from docker.errors import APIError
from docker.types import Mount
from airflow import DAG
from airflow.utils.dates import days_ago
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.models import Variable
from datetime import timedelta, datetime, timezone, date, time as dt_time
import pendulum
from airflow.timetables.interval import CronDataIntervalTimetable
import requests
import psycopg2
from psycopg2.extras import execute_values

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
    'retry_exponential_backoff': True,
    'max_retry_delay': timedelta(minutes=30),
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

# Scheduling: default to 5:00 AM Mountain Time, configurable via Airflow Variable or env
# - PIPELINE_SCHEDULE: cron string (e.g., "0 5 * * *")
# - PIPELINE_TIMEZONE: IANA tz name (e.g., "America/Denver")
PIPELINE_TZ_NAME = Variable.get(
    "PIPELINE_TIMEZONE", default_var=os.environ.get("PIPELINE_TIMEZONE", "America/Denver")
)
LOCAL_TZ = pendulum.timezone(PIPELINE_TZ_NAME)
PIPELINE_SCHEDULE = Variable.get(
    "PIPELINE_SCHEDULE", default_var=os.environ.get("PIPELINE_SCHEDULE", "0 5 * * *")
)

dag = DAG(
    'rankalpha_pipeline',
    default_args=default_args,
    description='Daily RankAlpha data pipeline with ingestion, scoring, AI analysis, and frontend update',
    timetable=CronDataIntervalTimetable(cron=PIPELINE_SCHEDULE, timezone=LOCAL_TZ),
    start_date=days_ago(1),
    catchup=False,
    # Avoid overlapping runs to prevent concurrent ingestion on shared volumes.
    max_active_runs=1,
)

# Environment profile selection: prefer Airflow Variable, fall back to container env, then 'local'
ENV_PROFILE = Variable.get("ENV_PROFILE", default_var=os.environ.get("RANKALPHA_ENV", "local"))
SHARED_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/shared.env"
INGESTION_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/ingestion.env"
NEWSWIRE_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/newswire.env"
SCORER_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/scorer.env"
SENTIMENT_ENV_PATH = f"/opt/rankalpha/env/{ENV_PROFILE}/sentiment.env"
PRICES_DATA_VOLUME = Variable.get(
    "PRICES_DATA_VOLUME",
    default_var=os.environ.get("PRICES_DATA_VOLUME", "prices_data"),
)
# Allow overriding the Docker network used by DockerOperator. Must match docker-compose network (project-prefixed).
DOCKER_NETWORK = Variable.get(
    "DOCKER_NETWORK",
    default_var=os.environ.get("DOCKER_NETWORK", "rankalpha_backend_network"),
)
AI_ENABLED = str(Variable.get("AI_ENABLED", default_var=os.environ.get("AI_ENABLED", "false"))).lower() == "true"
NEWS_ENABLED = str(Variable.get("NEWS_ENABLED", default_var=os.environ.get("NEWS_ENABLED", "true"))).lower() == "true"
NEWS_LLM_TASK_ENABLED = str(Variable.get("NEWS_LLM_TASK_ENABLED", default_var=os.environ.get("NEWS_LLM_TASK_ENABLED", "false"))).lower() == "true"

SERVICE_RESTART_STOP_TIMEOUT = _get_int_config("SERVICE_RESTART_STOP_TIMEOUT", 15)
SERVICE_RESTART_HEALTH_TIMEOUT = _get_int_config("SERVICE_RESTART_HEALTH_TIMEOUT", 180)
SERVICE_RESTART_POLL_SECONDS = _get_float_config("SERVICE_RESTART_POLL_SECONDS", 5.0)

def load_env_vars(env_file):
    try:
        out = {}
        with open(env_file) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                out[key] = val
        return out
    except FileNotFoundError:
        print(f"[WARNING] Missing env file: {env_file}")
        return {}

def merge_env(base: dict, names: list[str]) -> dict:
    """Return a copy of base with values overridden by Airflow Variables when present.

    For each env var name in names, take Variable.get(name) if defined, otherwise keep base[name].
    """
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


def _wait_for_container_health(container, timeout_seconds: int, poll_seconds: float) -> None:
    deadline = time.monotonic() + max(timeout_seconds, 0)
    poll_seconds = max(poll_seconds, 0.5)
    while True:
        container.reload()
        state = container.attrs.get("State", {})
        status = state.get("Status")
        health = state.get("Health")
        if status == "running":
            if not health:
                return
            health_status = health.get("Status")
            if health_status == "healthy":
                return
            if health_status == "unhealthy":
                raise RuntimeError(f"container reported unhealthy status: {container.name}")
            # health present but still starting; continue waiting
        elif status in {"exited", "dead"}:
            exit_code = state.get("ExitCode")
            raise RuntimeError(f"container {container.name} exited during restart (status={status}, exit_code={exit_code})")

        if time.monotonic() >= deadline:
            raise RuntimeError(f"timed out waiting for container {container.name} to become healthy")

        time.sleep(poll_seconds)


def recycle_services(
    services: list[str],
    stop_timeout: int = SERVICE_RESTART_STOP_TIMEOUT,
    health_timeout: int = SERVICE_RESTART_HEALTH_TIMEOUT,
    poll_seconds: float = SERVICE_RESTART_POLL_SECONDS,
) -> None:
    """Restart the specified Docker Compose services via Docker SDK."""

    if not services:
        print("[service_recycle] No services provided; skipping restart.")
        return

    compose_project = None
    try:
        compose_project = Variable.get("COMPOSE_PROJECT_NAME", default_var=os.environ.get("COMPOSE_PROJECT_NAME"))
    except Exception:
        compose_project = os.environ.get("COMPOSE_PROJECT_NAME")

    try:
        target_network = Variable.get("DOCKER_NETWORK", default_var=os.environ.get("DOCKER_NETWORK"))
    except Exception:
        target_network = os.environ.get("DOCKER_NETWORK")

    client = docker.from_env()
    project_filter = []
    if compose_project:
        project_filter.append(f"com.docker.compose.project={compose_project}")

    try:
        for service in services:
            label_filters = [f"com.docker.compose.service={service}", *project_filter]
            containers = client.containers.list(all=True, filters={"label": label_filters})
            if not containers:
                print(
                    f"[service_recycle] No containers found for service '{service}'"
                    f" (project={compose_project or 'any'}); skipping."
                )
                continue

            matched_containers = []
            for container in containers:
                if compose_project:
                    label_project = container.labels.get("com.docker.compose.project")
                    if label_project != compose_project:
                        print(
                            f"[service_recycle] Skipping container {container.name} (service={service}) "
                            f"not in project '{compose_project}' (found '{label_project or 'unknown'}')."
                        )
                        continue
                elif target_network:
                    networks = (container.attrs.get("NetworkSettings", {}).get("Networks") or {})
                    if target_network not in networks:
                        print(
                            f"[service_recycle] Skipping container {container.name} (service={service}) "
                            f"not attached to network '{target_network}'. Networks={list(networks.keys())}"
                        )
                        continue
                matched_containers.append(container)

            if not matched_containers:
                print(
                    f"[service_recycle] No containers matched stack filters for service '{service}'. "
                    "Skipping restart."
                )
                continue

            for container in matched_containers:
                print(f"[service_recycle] Restarting container {container.name} (service={service})")
                try:
                    container.restart(timeout=max(stop_timeout, 0))
                    if health_timeout > 0:
                        _wait_for_container_health(container, health_timeout, poll_seconds)
                except APIError as exc:
                    print(
                        f"[service_recycle] Failed to restart container {container.name} (service={service}): "
                        f"{exc.explanation}. Continuing without failing task."
                    )
                    continue
                except RuntimeError as exc:
                    print(
                        f"[service_recycle] Container {container.name} (service={service}) failed post-restart health "
                        f"check: {exc}. Continuing without failing task."
                    )
                    continue
                except Exception as exc:
                    print(
                        f"[service_recycle] Error restarting container {container.name} (service={service}): "
                        f"{exc}. Continuing without failing task."
                    )
                    continue

                print(f"[service_recycle] Container {container.name} (service={service}) is ready")
    finally:
        client.close()


def trigger_price_cache_refresh_task(**context) -> None:
    """Load active symbols and notify the API admin endpoint to warm price caches."""
    shared_env = load_env_vars(SHARED_ENV_PATH)
    ingestion_env = load_env_vars(INGESTION_ENV_PATH)
    api_env = load_env_vars(f"/opt/rankalpha/env/{ENV_PROFILE}/api.env")
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
        payload = {"symbols": batch, "reason": "airflow", "force": True}
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
        f"in {batches} batches (reason=airflow, as_of={as_of_iso})"
    )


def warm_default_page_caches_task(**context) -> None:
    """Warm key frontend/API cache entries for default pages.

    This is best-effort and should not fail the pipeline; it reduces the cold-start
    penalty after cache invalidation when the nightly publish completes.
    """
    def _normalize_symbol(raw: object) -> str | None:
        try:
            sym = str(raw or "").strip().upper()
        except Exception:
            return None
        if not sym:
            return None
        # Basic ticker hygiene (supports common cases like BRK.B, RDS.A).
        # Reject anything that would generate weird URLs.
        import re

        if not re.match(r"^[A-Z0-9][A-Z0-9.\-]{0,15}$", sym):
            return None
        return sym

    frontend_port = str(
        Variable.get(
            "FRONTEND_SERVICE_PORT",
            default_var=os.environ.get("FRONTEND_SERVICE_PORT", "3000"),
        )
    ).strip() or "3000"
    frontend_base = (
        Variable.get(
            "FRONTEND_INTERNAL_URL",
            default_var=os.environ.get("FRONTEND_INTERNAL_URL", f"http://frontend:{frontend_port}"),
        )
        .strip()
        .rstrip("/")
    )

    timeout = float(
        Variable.get(
            "CACHE_WARM_TIMEOUT_SECONDS",
            default_var=os.environ.get("CACHE_WARM_TIMEOUT_SECONDS", "15"),
        )
    )
    headers = {"User-Agent": "rankalpha-airflow-cache-warm/1.0"}
    stock_detail_enabled = _get_bool_config("STOCK_DETAIL_CACHE_WARM_ENABLED", True)
    stock_detail_all_active = _get_bool_config("STOCK_DETAIL_CACHE_WARM_ALL_ACTIVE", False)
    stock_detail_limit = max(0, _get_int_config("STOCK_DETAIL_CACHE_WARM_LIMIT", 25))
    stock_detail_timeout = _get_float_config("STOCK_DETAIL_CACHE_WARM_TIMEOUT_SECONDS", timeout)
    technical_days = max(1, _get_int_config("STOCK_DETAIL_TECHNICAL_SERIES_DAYS", 400))
    rankings_limit = 25
    if stock_detail_enabled and not stock_detail_all_active and stock_detail_limit > 0:
        # /api/v1/grading/grades enforces limit<=200; keep within bounds.
        rankings_limit = max(rankings_limit, min(stock_detail_limit, 200))

    # Default pages: rankings, screener, AI analysis, and overview dashboard APIs.
    paths = [
        # Rankings (default query: page 1, best grades first)
        f"/api/grading/grades?limit={rankings_limit}&skip=0&sort_by=grade&sort_order=desc",
        "/api/grading/grades?limit=25&skip=0&sort_by=grade&sort_order=desc",
        "/api/grading/grades?limit=10&skip=0&sort_by=grade&sort_order=desc",
        "/api/grading/sectors",
        "/api/grading/weights",
        # Screener (default view: consensus + changes + breadth + regime)
        "/api/screener/consensus?style_logic=all&source_logic=all&skip=0&limit=25&sort_by=consensus_score&sort_order=desc",
        "/api/screener/consensus?skip=0&limit=10&sort_by=consensus_score&sort_order=desc",
        "/api/screener/changes?change_types=entered&change_types=reentered&change_types=dropped&latest_only=true&limit=200&sort_by=change_date&sort_order=desc",
        "/api/screener/breadth/flow?limit=180&sort_order=desc",
        "/api/screener/breadth?limit=180&sort_order=desc",
        "/api/screener/regime/latest",
        "/api/screener/regime-rules/latest",
        "/api/screener/styles/meta",
        "/api/screener/styles/meta?bias=all",
        "/api/screener/sources/meta?prefix=RA-",
        # AI analysis (default page: latest list with proximity)
        "/api/ai-analysis/latest?skip=0&limit=20&sort_by=date&sort_order=desc&include_proximity=true",
        # Overview bundles used by tab prefetch.
        "/api/overview/nowcast",
        "/api/overview/macro",
        "/api/overview/regime",
        # Home/overview latest snapshots.
        "/api/nowcast/latest",
        "/api/earnings/upcoming?days=3&min_market_cap=2000000000",
        "/api/macro/liquidity/latest",
        "/api/macro/liquidity/net-liquidity/latest?lookback_weeks=520",
        "/api/breadth/latest",
        "/api/benchmarks/latest",
        "/api/hy-stress/latest",
        "/api/fra-ois/latest?fra_source=SR3",
        "/api/vol-regime/latest",
        "/api/money-flow/sectors",
        "/api/rates/treasury/latest",
        "/api/fx/latest",
        # Macro Dashboard (direct per-card API calls in MacroDashboard).
        "/api/macro/liquidity/series?series=on_rrp&sort_order=desc&limit=180&skip=0",
        "/api/macro/liquidity/series?series=tga&sort_order=desc&limit=180&skip=0",
        "/api/macro/liquidity/net-liquidity/series?sort_order=desc&limit=260&skip=0",
        "/api/hy-stress/series?sort_order=desc&limit=252&skip=0",
        "/api/fra-ois/series?fra_source=SR3&start_months=3&end_months=6&sort_order=desc&limit=252&skip=0",
        "/api/macro/put-call/series?series=equity&sort_order=desc&limit=252&skip=0",
        "/api/macro/put-call/series?series=spx&sort_order=desc&limit=252&skip=0",
        "/api/benchmarks/series?benchmark_name=%24USDX&sort_order=desc&limit=260&skip=0",
        "/api/benchmarks/series?benchmark_name=XAUUSD&sort_order=desc&limit=260&skip=0",
        "/api/benchmarks/series?benchmark_name=%40WTI&sort_order=desc&limit=260&skip=0",
        "/api/rates/treasury/series?tenor=2Y&sort_order=desc&limit=260&skip=0",
        "/api/rates/treasury/series?tenor=10Y&sort_order=desc&limit=260&skip=0",
        "/api/rates/treasury/series?tenor=O%2FN&sort_order=desc&limit=260&skip=0",
        "/api/macro/real-rates/tips10y/series?sort_order=desc&limit=260&skip=0",
        "/api/prices/history?symbol=TLT&limit=260&skip=0",
        "/api/prices/history?symbol=EMB&limit=260&skip=0",
        "/api/fx/series?pair=USDJPY&sort_order=desc&limit=260&skip=0",
        "/api/fx/series?pair=CNYUSD&sort_order=desc&limit=260&skip=0",
        "/api/breadth/series?universe=SPX&indicator=target_exposure&sort_order=desc&limit=252&skip=0",
        "/api/breadth/series?universe=NDX&indicator=target_exposure&sort_order=desc&limit=252&skip=0",
        "/api/breadth/series?universe=NYSE&indicator=ad_ratio&sort_order=desc&limit=252&skip=0",
        "/api/money-flow/sectors/series?days=180",
    ]

    ok = 0
    failed = 0
    warmed_grade_symbols: list[str] = []
    warmed_consensus_symbols: list[str] = []
    symbol_parse_errors = 0
    invalid_symbols = 0
    for path in paths:
        url = f"{frontend_base}{path}"
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code >= 400:
                failed += 1
                body = (resp.text or "")[:200].replace("\n", " ")
                print(f"[cache_warm] FAIL {resp.status_code} {url} body={body!r}")
            else:
                ok += 1
                print(f"[cache_warm] OK {resp.status_code} {url}")
                if not warmed_grade_symbols and path.startswith("/api/grading/grades"):
                    try:
                        payload = resp.json()
                        stocks = payload.get("stocks") if isinstance(payload, dict) else None
                        if isinstance(stocks, list):
                            discovered: list[str] = []
                            for row in stocks:
                                if not isinstance(row, dict):
                                    continue
                                sym = _normalize_symbol(row.get("symbol"))
                                if not sym:
                                    invalid_symbols += 1
                                    continue
                                discovered.append(sym)
                            warmed_grade_symbols = discovered
                    except Exception:
                        symbol_parse_errors += 1
                        body_preview = (resp.text or "")[:200].replace("\n", " ")
                        print(
                            f"[cache_warm] WARN Failed to parse symbols from {url} body={body_preview!r}"
                        )
                if not warmed_consensus_symbols and path.startswith("/api/screener/consensus"):
                    try:
                        payload = resp.json()
                        items = payload.get("items") if isinstance(payload, dict) else None
                        if isinstance(items, list):
                            discovered: list[str] = []
                            for row in items:
                                if not isinstance(row, dict):
                                    continue
                                sym = _normalize_symbol(row.get("symbol"))
                                if not sym:
                                    invalid_symbols += 1
                                    continue
                                discovered.append(sym)
                            warmed_consensus_symbols = discovered
                    except Exception:
                        symbol_parse_errors += 1
                        body_preview = (resp.text or "")[:200].replace("\n", " ")
                        print(
                            f"[cache_warm] WARN Failed to parse screener symbols from {url} body={body_preview!r}"
                        )
        except Exception as exc:
            failed += 1
            print(f"[cache_warm] ERROR {url}: {exc}")

    # Optional: warm the "stock detail modal" endpoints for top-ranked symbols
    # or the entire active universe (dim_stock.is_active = true).
    if stock_detail_enabled:
        if stock_detail_all_active:
            shared_env = load_env_vars(SHARED_ENV_PATH)
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
                    raise RuntimeError(f"[cache_warm:stock] Missing required DB credential: {key}")

            try:
                with psycopg2.connect(
                    database=db_name,
                    user=db_user,
                    password=db_pass,
                    host=db_host,
                    port=int(db_port),
                ) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT symbol FROM dim_stock WHERE is_active IS TRUE ORDER BY symbol")
                        warmed_grade_symbols = [row[0] for row in cur.fetchall()]
                warmed_grade_symbols = [s for s in warmed_grade_symbols if _normalize_symbol(s)]
                print(f"[cache_warm:stock] Loaded active symbols count={len(warmed_grade_symbols)}")
            except Exception as exc:
                symbol_parse_errors += 1
                print(f"[cache_warm:stock] ERROR loading active symbols: {exc}")
                warmed_grade_symbols = []

        if not warmed_grade_symbols:
            grades_url = f"{frontend_base}/api/grading/grades?limit={stock_detail_limit}&skip=0&sort_by=grade&sort_order=desc"
            try:
                resp = requests.get(grades_url, headers=headers, timeout=stock_detail_timeout)
                if resp.status_code < 400:
                    payload = resp.json()
                    stocks = payload.get("stocks") if isinstance(payload, dict) else None
                    if isinstance(stocks, list):
                        discovered: list[str] = []
                        for row in stocks:
                            if not isinstance(row, dict):
                                continue
                            sym = _normalize_symbol(row.get("symbol"))
                            if not sym:
                                invalid_symbols += 1
                                continue
                            discovered.append(sym)
                        warmed_grade_symbols = discovered
                else:
                    body = (resp.text or "")[:200].replace("\n", " ")
                    print(f"[cache_warm:stock] FAIL {resp.status_code} {grades_url} body={body!r}")
            except Exception as exc:
                symbol_parse_errors += 1
                print(f"[cache_warm:stock] ERROR {grades_url}: {exc}")

        warmed_grade_symbols = [s for s in warmed_grade_symbols if s]
        if not stock_detail_all_active and stock_detail_limit > 0:
            warmed_grade_symbols = warmed_grade_symbols[:stock_detail_limit]
        if warmed_grade_symbols:
            indicators = "RSI14,MACD_HIST,ATR14"
            for sym in warmed_grade_symbols:
                stock_paths = [
                    f"/api/grading/asset/{sym}",
                    f"/api/technicals/latest?symbol={sym}",
                    f"/api/technicals/series?symbol={sym}&indicators={indicators}&days={technical_days}",
                ]
                for path in stock_paths:
                    url = f"{frontend_base}{path}"
                    try:
                        resp = requests.get(url, headers=headers, timeout=stock_detail_timeout)
                        if resp.status_code >= 400:
                            failed += 1
                            body = (resp.text or "")[:200].replace("\n", " ")
                            print(f"[cache_warm:stock] FAIL {resp.status_code} {url} body={body!r}")
                        else:
                            ok += 1
                            print(f"[cache_warm:stock] OK {resp.status_code} {url}")
                    except Exception as exc:
                        failed += 1
                        print(f"[cache_warm:stock] ERROR {url}: {exc}")
        else:
            print("[cache_warm:stock] No symbols found to warm; skipping.")

    # Rankings landing page: warm setup summaries for visible default symbols.
    setup_symbols = list(dict.fromkeys([s for s in warmed_grade_symbols if s]))[:25]
    if setup_symbols:
        setup_url = f"{frontend_base}/api/screener/setups/summary"
        setup_params = [("symbols", s) for s in setup_symbols] + [("window_days", "3")]
        try:
            resp = requests.get(setup_url, params=setup_params, headers=headers, timeout=timeout)
            if resp.status_code >= 400:
                failed += 1
                body = (resp.text or "")[:200].replace("\n", " ")
                print(f"[cache_warm:rankings] FAIL {resp.status_code} {resp.url} body={body!r}")
            else:
                ok += 1
                print(f"[cache_warm:rankings] OK {resp.status_code} {resp.url}")
        except Exception as exc:
            failed += 1
            print(f"[cache_warm:rankings] ERROR {setup_url}: {exc}")
    else:
        print("[cache_warm:rankings] No symbols found for setup summary warm.")

    # Screener landing page: warm AI preview badges for default consensus symbols.
    preview_symbols = list(dict.fromkeys([s for s in warmed_consensus_symbols if s]))[:25]
    if preview_symbols:
        preview_url = f"{frontend_base}/api/ai-analysis/preview"
        preview_params = [("symbols", s) for s in preview_symbols]
        try:
            resp = requests.get(preview_url, params=preview_params, headers=headers, timeout=timeout)
            if resp.status_code >= 400:
                failed += 1
                body = (resp.text or "")[:200].replace("\n", " ")
                print(f"[cache_warm:screener] FAIL {resp.status_code} {resp.url} body={body!r}")
            else:
                ok += 1
                print(f"[cache_warm:screener] OK {resp.status_code} {resp.url}")
        except Exception as exc:
            failed += 1
            print(f"[cache_warm:screener] ERROR {preview_url}: {exc}")
    else:
        print("[cache_warm:screener] No symbols found for AI preview warm.")

    print(
        f"[cache_warm] Completed ok={ok} failed={failed} base={frontend_base} "
        f"stock_detail_enabled={stock_detail_enabled} stock_detail_limit={stock_detail_limit} "
        f"symbol_parse_errors={symbol_parse_errors} invalid_symbols={invalid_symbols}"
    )


def compute_nowcast_snapshot_task(**context) -> None:
    """Compute and upsert Nowcast snapshots in Postgres (nightly)."""
    shared_env = load_env_vars(SHARED_ENV_PATH)
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
            raise RuntimeError(f"[nowcast_snapshot] Missing required DB credential: {key}")

    model_version = (
        Variable.get(
            "NOWCAST_MODEL_VERSION",
            default_var=os.environ.get("NOWCAST_MODEL_VERSION", "nowcast_v2"),
        )
        .strip()
        or "nowcast_v2"
    )
    backfill_days = max(0, _get_int_config("NOWCAST_BACKFILL_DAYS", 0))

    with psycopg2.connect(
        database=db_name,
        user=db_user,
        password=db_pass,
        host=db_host,
        port=int(db_port),
    ) as conn:
        with conn.cursor() as cur:
            if backfill_days > 0:
                print(
                    f"[nowcast_snapshot] Backfilling last {backfill_days} trading days "
                    f"(model_version={model_version})"
                )
                # Avoid calling the DB backfill function directly: it runs in a single
                # transaction and can take a long time with no visible progress.
                # Instead, loop day-by-day so each upsert is committed and observable.
                cur.execute(
                    """
                    SELECT full_date
                    FROM rankalpha.dim_date
                    WHERE is_trading_day IS TRUE
                      AND full_date <= CURRENT_DATE
                    ORDER BY date_key DESC
                    LIMIT %s;
                    """,
                    (backfill_days,),
                )
                days = [row[0] for row in cur.fetchall() if row and row[0] is not None]
                days = list(reversed(days))
                total = len(days)
                for idx, day in enumerate(days, start=1):
                    print(f"[nowcast_snapshot] Upserting {day} ({idx}/{total})")
                    cur.execute(
                        "SELECT rankalpha.fn_nowcast_snapshot_upsert_for_date(%s, %s);",
                        (day, model_version),
                    )
                    conn.commit()
            else:
                print(f"[nowcast_snapshot] Upserting latest snapshot (model_version={model_version})")
                cur.execute(
                    "SELECT rankalpha.fn_nowcast_snapshot_upsert_latest(%s);",
                    (model_version,),
                )
        conn.commit()


def enqueue_post_earnings_sentiment(**context) -> None:
    """Enqueue post-earnings sentiment jobs for qualified symbols."""
    if not _get_bool_config("SENTIMENT_EARNINGS_QUEUE_ENABLED", True):
        print("[earnings_sentiment] Disabled via config; skipping.")
        return

    shared_env = load_env_vars(SHARED_ENV_PATH)
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
            raise RuntimeError(f"[earnings_sentiment] Missing required DB credential: {key}")

    run_hour = max(0, min(23, _get_int_config("SENTIMENT_EARNINGS_RUN_HOUR_UTC", 13)))
    run_minute = max(0, min(59, _get_int_config("SENTIMENT_EARNINGS_RUN_MINUTE_UTC", 0)))
    priority = _get_int_config("SENTIMENT_EARNINGS_PRIORITY", 90)
    source_label = Variable.get(
        "SENTIMENT_EARNINGS_SOURCE_LABEL",
        default_var=os.environ.get("SENTIMENT_EARNINGS_SOURCE_LABEL", "airflow-earnings"),
    )

    select_sql = """
        WITH latest_screener AS (
            SELECT symbol
            FROM rankalpha.mv_screener_scores_latest
            WHERE as_of_date = (
                SELECT MAX(as_of_date) FROM rankalpha.mv_screener_scores_latest
            )
        )
        SELECT e.stock_key,
               ds.symbol,
               e.earnings_date
        FROM rankalpha.fact_stock_next_earnings e
        JOIN rankalpha.dim_stock ds ON ds.stock_key = e.stock_key
        LEFT JOIN rankalpha.mv_latest_grades g ON g.symbol = ds.symbol
        LEFT JOIN latest_screener ls ON ls.symbol = ds.symbol
        WHERE e.earnings_date = CURRENT_DATE
          AND ds.is_active IS TRUE
          AND (g.grade IN ('A','B') OR ls.symbol IS NOT NULL)
    """

    earnings_rows: list[tuple[int, str, date]] = []
    with psycopg2.connect(
        database=db_name,
        user=db_user,
        password=db_pass,
        host=db_host,
        port=int(db_port),
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(select_sql)
            fetched = cur.fetchall()
            if not fetched:
                print("[earnings_sentiment] No qualifying earnings today; skipping.")
                return
            for stock_key, symbol, earnings_date in fetched:
                earnings_rows.append((int(stock_key), str(symbol).upper(), earnings_date))

        inserted = 0
        updated = 0
        with conn.cursor() as cur:
            for stock_key, symbol, earnings_date in earnings_rows:
                run_day = earnings_date + timedelta(days=1)
                run_after_ts = datetime.combine(
                    run_day,
                    dt_time(hour=run_hour, minute=run_minute),
                    tzinfo=timezone.utc,
                )
                target_date = run_after_ts.astimezone(timezone.utc).date()
                cur.execute(
                    """
                    SELECT queue_id
                    FROM rankalpha.sentiment_analysis_queue
                    WHERE stock_key = %s
                      AND event_id IS NULL
                      AND status IN ('pending','in_progress')
                      AND run_after_date = %s
                    """,
                    (stock_key, target_date),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        """
                        UPDATE rankalpha.sentiment_analysis_queue
                        SET run_after_ts = %s,
                            priority = %s,
                            source = %s,
                            force_run = TRUE,
                            status = 'pending'
                        WHERE queue_id = %s
                        """,
                        (run_after_ts, int(priority), source_label, existing[0]),
                    )
                    updated += cur.rowcount or 0
                else:
                    cur.execute(
                        """
                        INSERT INTO rankalpha.sentiment_analysis_queue
                            (stock_key, symbol, priority, status, run_after_ts, source, force_run)
                        VALUES (%s, %s, %s, 'pending', %s, %s, TRUE)
                        """,
                        (stock_key, symbol, int(priority), run_after_ts, source_label),
                    )
                    inserted += cur.rowcount or 0
        conn.commit()
    print(
        "[earnings_sentiment] Upserted post-earnings sentiment jobs: "
        f"inserted={inserted} updated={updated} attempted={len(earnings_rows)}"
    )


def enqueue_top_grade_sentiment(**context) -> None:
    """Push Grade A/B symbols into the sentiment queue for same-day processing."""
    shared_env = load_env_vars(SHARED_ENV_PATH)
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
            raise RuntimeError(f"[sentiment_grade_queue] Missing required DB credential: {key}")

    try:
        limit_raw = Variable.get(
            "SENTIMENT_TOP_GRADE_QUEUE_LIMIT",
            default_var=os.environ.get("SENTIMENT_TOP_GRADE_QUEUE_LIMIT", "120"),
        )
        queue_limit = int(limit_raw)
    except Exception:
        queue_limit = 120
    try:
        priority_a = int(
            Variable.get(
                "SENTIMENT_QUEUE_PRIORITY_A",
                default_var=os.environ.get("SENTIMENT_QUEUE_PRIORITY_A", "80"),
            )
        )
    except Exception:
        priority_a = 80
    try:
        priority_b = int(
            Variable.get(
                "SENTIMENT_QUEUE_PRIORITY_B",
                default_var=os.environ.get("SENTIMENT_QUEUE_PRIORITY_B", "60"),
            )
        )
    except Exception:
        priority_b = 60

    source_label = Variable.get(
        "SENTIMENT_QUEUE_SOURCE_LABEL",
        default_var=os.environ.get("SENTIMENT_QUEUE_SOURCE_LABEL", "airflow-top-grades"),
    )

    sql = """
        SELECT s.stock_key,
               g.symbol,
               g.grade,
               g.avg_score
        FROM rankalpha.mv_latest_grades g
        JOIN rankalpha.dim_stock s ON s.symbol = g.symbol
        WHERE g.grade IN ('A','B')
          AND s.is_active IS TRUE
        ORDER BY CASE WHEN g.grade = 'A' THEN 0 ELSE 1 END,
                 g.avg_score DESC
    """
    params = []
    if queue_limit > 0:
        sql += " LIMIT %s"
        params.append(queue_limit)

    run_after_ts = datetime.now(timezone.utc)

    with psycopg2.connect(
        database=db_name,
        user=db_user,
        password=db_pass,
        host=db_host,
        port=int(db_port),
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            if not rows:
                print("[sentiment_grade_queue] No Grade A/B symbols found; skipping.")
                return

            values = []
            for stock_key, symbol, grade, _avg_score in rows:
                priority = priority_a if grade == "A" else priority_b
                values.append(
                    (
                        int(stock_key),
                        str(symbol),
                        None,
                        None,
                        None,
                        priority,
                        "pending",
                        run_after_ts,
                        source_label,
                        False,
                    )
                )

            execute_values(
                cur,
                """
                INSERT INTO rankalpha.sentiment_analysis_queue
                    (stock_key, symbol, event_id, title, url, priority, status, run_after_ts, source, force_run)
                SELECT v.stock_key,
                       v.symbol,
                       v.event_id,
                       v.title,
                       v.url,
                       v.priority,
                       v.status,
                       v.run_after_ts,
                       v.source,
                       v.force_run
                FROM (VALUES %s) AS v(
                    stock_key,
                    symbol,
                    event_id,
                    title,
                    url,
                    priority,
                    status,
                    run_after_ts,
                    source,
                    force_run
                )
                WHERE NOT EXISTS (
                  SELECT 1 FROM rankalpha.sentiment_analysis_queue s
                  WHERE s.stock_key = v.stock_key
                    AND s.event_id IS NULL
                    AND s.status IN ('pending','in_progress')
                    AND s.run_after_date <= (v.run_after_ts AT TIME ZONE 'UTC')::date
                )
                ON CONFLICT DO NOTHING
                """,
                values,
                template="(%s::int, %s::text, %s::uuid, %s::text, %s::text, %s::int, %s::text, %s::timestamptz, %s::text, %s::boolean)",
            )
            inserted = max(cur.rowcount or 0, 0)
        conn.commit()

    total = len(values)
    print(
        f"[sentiment_grade_queue] Enqueued {inserted} of {total} Grade A/B symbols "
        f"(limit={queue_limit}, run_after_ts={run_after_ts.isoformat()}, source={source_label})"
    )


def enqueue_new_consensus_sentiment(**context) -> None:
    """Enqueue new consensus entrants vs the previous consensus date."""
    if not _get_bool_config("SENTIMENT_CONSENSUS_QUEUE_ENABLED", True):
        print("[consensus_queue] Disabled via config; skipping.")
        return

    shared_env = load_env_vars(SHARED_ENV_PATH)
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
            raise RuntimeError(f"[consensus_queue] Missing required DB credential: {key}")

    min_app = _get_float_config("SENTIMENT_CONSENSUS_QUEUE_MIN_APPEARANCES", 1.0)
    min_styles = _get_float_config("SENTIMENT_CONSENSUS_QUEUE_MIN_STYLES", 1.0)
    limit = _get_int_config("SENTIMENT_CONSENSUS_QUEUE_LIMIT", 200)
    priority = _get_int_config("SENTIMENT_CONSENSUS_QUEUE_PRIORITY", 70)
    source_label = Variable.get(
        "SENTIMENT_CONSENSUS_QUEUE_SOURCE_LABEL",
        default_var=os.environ.get(
            "SENTIMENT_CONSENSUS_QUEUE_SOURCE_LABEL", "airflow-consensus-new"
        ),
    )

    run_after_ts = datetime.now(timezone.utc)
    with psycopg2.connect(
        database=db_name,
        user=db_user,
        password=db_pass,
        host=db_host,
        port=int(db_port),
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(full_date) FROM rankalpha.v_latest_screener_consensus")
            latest = cur.fetchone()[0]
            if not latest:
                print("[consensus_queue] No consensus dates found; skipping.")
                return
            cur.execute(
                """
                SELECT MAX(full_date)
                FROM rankalpha.v_latest_screener_consensus
                WHERE full_date < %s
                """,
                (latest,),
            )
            prev = cur.fetchone()[0]
            if not prev:
                print(f"[consensus_queue] Only one consensus date found ({latest}); skipping.")
                return

            sql = """
                SELECT ds.stock_key,
                       c.symbol,
                       c.company_name,
                       c.consensus_score,
                       c.appearances,
                       c.styles_distinct,
                       c.sources_distinct
                FROM rankalpha.v_latest_screener_consensus c
                JOIN rankalpha.dim_stock ds ON ds.symbol = c.symbol
                JOIN rankalpha.mv_universe_eligible ue
                  ON ue.symbol = ds.symbol AND ue.eligible IS TRUE
                WHERE c.full_date = %s
                  AND ds.is_active IS TRUE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM rankalpha.v_latest_screener_consensus p
                    WHERE p.full_date = %s
                      AND p.symbol = c.symbol
                      AND p.position_side = c.position_side
                  )
            """
            params: list[object] = [latest, prev]
            if min_app > 0:
                sql += " AND c.appearances >= %s"
                params.append(min_app)
            if min_styles > 0:
                sql += " AND c.styles_distinct >= %s"
                params.append(min_styles)
            sql += " ORDER BY c.consensus_score DESC NULLS LAST"
            if limit > 0:
                sql += " LIMIT %s"
                params.append(limit)
            cur.execute(sql, params)
            rows = cur.fetchall()
            if not rows:
                print(
                    f"[consensus_queue] No new consensus entrants for {latest} vs {prev}; skipping."
                )
                return

            values = []
            for stock_key, symbol, _company_name, *_rest in rows:
                values.append(
                    (
                        int(stock_key),
                        str(symbol),
                        None,
                        None,
                        None,
                        int(priority),
                        "pending",
                        run_after_ts,
                        source_label,
                        False,
                    )
                )

            execute_values(
                cur,
                """
                INSERT INTO rankalpha.sentiment_analysis_queue
                    (stock_key, symbol, event_id, title, url, priority, status, run_after_ts, source, force_run)
                SELECT v.stock_key,
                       v.symbol,
                       v.event_id,
                       v.title,
                       v.url,
                       v.priority,
                       v.status,
                       v.run_after_ts,
                       v.source,
                       v.force_run
                FROM (VALUES %s) AS v(
                    stock_key,
                    symbol,
                    event_id,
                    title,
                    url,
                    priority,
                    status,
                    run_after_ts,
                    source,
                    force_run
                )
                WHERE NOT EXISTS (
                  SELECT 1 FROM rankalpha.sentiment_analysis_queue s
                  WHERE s.stock_key = v.stock_key
                    AND s.event_id IS NULL
                    AND s.status IN ('pending','in_progress')
                    AND s.run_after_date <= (v.run_after_ts AT TIME ZONE 'UTC')::date
                )
                ON CONFLICT DO NOTHING
                """,
                values,
                template="(%s::int, %s::text, %s::uuid, %s::text, %s::text, %s::int, %s::text, %s::timestamptz, %s::text, %s::boolean)",
            )
            inserted = max(cur.rowcount or 0, 0)
        conn.commit()

    total = len(values)
    print(
        f"[consensus_queue] Enqueued {inserted} of {total} new consensus entrants "
        f"(date={latest} vs {prev}, limit={limit}, source={source_label})"
    )

recycle_target_services = ["broker", "sentiment"] if AI_ENABLED else []

recycle_broker_sentiment = PythonOperator(
    task_id="recycle_broker_sentiment",
    python_callable=recycle_services,
    op_kwargs={"services": recycle_target_services},
    dag=dag,
)

ingestion = DockerOperator(
    task_id='run_ingestion',
    image='rankalpha_ingestion',
    api_version='auto',
    auto_remove='force',
    command='python apps/ingestion/main.py',
    docker_url='unix://var/run/docker.sock',
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    cpus=float(Variable.get('INGESTION_CPUS', default_var='1.0')),
    mem_limit=Variable.get('INGESTION_MEM', default_var='1g'),
    environment=(lambda base: {
        **merge_env(
            base,
            [
                # optional DB overrides
                'DB_USERNAME','PASSWORD','DB_HOST','DB_PORT','DATABASE_NAME',
                # optional cache and secret overrides
                'REDIS_URL','OPENAI_API_KEY',
            ]
        ),
        "RANKALPHA_ENV": ENV_PROFILE,
        # Keep runtime metrics endpoint aligned with Prometheus scrape target.
        "OBSERVABILITY_METRICS_PORT": "9100",
        "OBSERVABILITY_METRICS_FLUSH_SECONDS": os.environ.get("BATCH_METRICS_FLUSH_SECONDS", "20"),
    })({**load_env_vars(INGESTION_ENV_PATH), **load_env_vars(SHARED_ENV_PATH)}),
    mounts=[Mount(source=PRICES_DATA_VOLUME, target="/data/prices", type="volume")],
    mount_tmp_dir=False,
    working_dir='/app',
    # Prometheus discovers batch containers via docker_sd + these labels.
    labels={
        'rankalpha.prometheus.scrape': 'true',
        'rankalpha.prometheus.job': 'ingestion',
        'rankalpha.prometheus.port': '9100',
        'rankalpha.prometheus.path': '/metrics',
    },
    dag=dag,
)

scorer = DockerOperator(
    task_id='run_scorer',
    image='rankalpha_scorer',
    api_version='auto',
    auto_remove='force',
    command='python apps/scorer/main.py',
    docker_url='unix://var/run/docker.sock',
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    cpus=float(Variable.get('SCORER_CPUS', default_var='1.0')),
    mem_limit=Variable.get('SCORER_MEM', default_var='1g'),
    environment=(lambda base: {
        **merge_env(
            base,
            [
                'DB_USERNAME','PASSWORD','DB_HOST','DB_PORT','DATABASE_NAME',
                'REDIS_URL'
            ]
        ),
        "RANKALPHA_ENV": ENV_PROFILE,
        # Keep runtime metrics endpoint aligned with Prometheus scrape target.
        "OBSERVABILITY_METRICS_PORT": "9101",
        "OBSERVABILITY_METRICS_FLUSH_SECONDS": os.environ.get("BATCH_METRICS_FLUSH_SECONDS", "20"),
    })({**load_env_vars(SCORER_ENV_PATH), **load_env_vars(SHARED_ENV_PATH)}),
    mounts=[Mount(source=PRICES_DATA_VOLUME, target="/data/prices", type="volume")],
    mount_tmp_dir=False,
    working_dir='/app',
    # Prometheus discovers batch containers via docker_sd + these labels.
    labels={
        'rankalpha.prometheus.scrape': 'true',
        'rankalpha.prometheus.job': 'scorer',
        'rankalpha.prometheus.port': '9101',
        'rankalpha.prometheus.path': '/metrics',
    },
    dag=dag,
)

# Refresh universe eligibility MV after ingestion so downstream (scorer/sentiment)
# use the current price/liquidity filters for symbol selection.
refresh_universe_mv = DockerOperator(
    task_id='refresh_universe_mv',
    image='postgres:16',
    api_version='auto',
    auto_remove='success',
    command="""
bash -lc "set -euo pipefail;
psql -h ${DB_HOST} -p ${DB_PORT:-5432} -U ${DB_USERNAME} -d ${DATABASE_NAME} -v ON_ERROR_STOP=1 <<'SQL'
DO $do$
BEGIN
  BEGIN
    EXECUTE 'REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_universe_eligible';
  EXCEPTION WHEN others THEN
    EXECUTE 'REFRESH MATERIALIZED VIEW rankalpha.mv_universe_eligible';
  END;
END
$do$;
SQL
"
    """,
    docker_url='unix://var/run/docker.sock',
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    cpus=float(Variable.get('PSQL_CPUS', default_var='0.5')),
    mem_limit=Variable.get('PSQL_MEM', default_var='256m'),
    environment=(lambda base: {
        **merge_env(
            base,
            ['DB_USERNAME','PASSWORD','DB_HOST','DB_PORT','DATABASE_NAME']
        ),
        'PGPASSWORD': base.get('PASSWORD', ''),
    })({**load_env_vars(INGESTION_ENV_PATH), **load_env_vars(SHARED_ENV_PATH)}),
    mount_tmp_dir=False,
    working_dir='/',
    dag=dag,
)

price_cache_refresh = PythonOperator(
    task_id="price_cache_refresh",
    python_callable=trigger_price_cache_refresh_task,
    dag=dag,
)

compute_nowcast_snapshot = PythonOperator(
    task_id="compute_nowcast_snapshot",
    python_callable=compute_nowcast_snapshot_task,
    dag=dag,
)

enqueue_post_earnings_queue = PythonOperator(
    task_id="enqueue_post_earnings_sentiment",
    python_callable=enqueue_post_earnings_sentiment,
    dag=dag,
)

enqueue_grade_ab_queue = PythonOperator(
    task_id="enqueue_grade_a_b_sentiment",
    python_callable=enqueue_top_grade_sentiment,
    dag=dag,
)

enqueue_consensus_new_queue = PythonOperator(
    task_id="enqueue_consensus_new_sentiment",
    python_callable=enqueue_new_consensus_sentiment,
    dag=dag,
)

# Optional pre-market newswire blitz run (bounded runtime)
if NEWS_ENABLED:
    newswire_blitz = DockerOperator(
        task_id='newswire_blitz',
        image='rankalpha_newswire',
        api_version='auto',
        auto_remove='success',
        command='python -m newswire.main',
        docker_url='unix://var/run/docker.sock',
        network_mode=DOCKER_NETWORK,
        do_xcom_push=False,
        environment=(lambda base: {
            **merge_env(
                base,
                [
                    'DB_USERNAME','PASSWORD','DB_HOST','DB_PORT','DATABASE_NAME',
                ]
            ),
            'RANKALPHA_ENV': ENV_PROFILE,
            'NEWS_RUN_MINUTES': Variable.get('NEWS_RUN_MINUTES', default_var=os.environ.get('NEWS_RUN_MINUTES', '20')),
            'NEWS_POLL_INTERVAL_PRE': Variable.get('NEWS_POLL_INTERVAL_PRE', default_var='45'),
            'NEWS_POLL_INTERVAL': Variable.get('NEWS_POLL_INTERVAL', default_var='120'),
            'NEWS_MATERIALITY_THRESHOLD': Variable.get('NEWS_MATERIALITY_THRESHOLD', default_var='0.70'),
        })({**load_env_vars(NEWSWIRE_ENV_PATH), **load_env_vars(INGESTION_ENV_PATH), **load_env_vars(SHARED_ENV_PATH)}),
        mount_tmp_dir=False,
        working_dir='/app',
        dag=dag,
    )

if NEWS_LLM_TASK_ENABLED:
    newswire_analyze = DockerOperator(
        task_id='newswire_analyze',
        image='rankalpha_newswire',
        api_version='auto',
        auto_remove='success',
        command='python -m newswire.cli analyze',
        docker_url='unix://var/run/docker.sock',
        network_mode=DOCKER_NETWORK,
        do_xcom_push=False,
        environment=(lambda base: {
            **merge_env(
                base,
                [
                    'DB_USERNAME','PASSWORD','DB_HOST','DB_PORT','DATABASE_NAME',
                    'OPENAI_API_KEY'
                ]
            ),
            'RANKALPHA_ENV': ENV_PROFILE,
            'NEWS_LLM_ANALYZE_HOURS': Variable.get('NEWS_LLM_ANALYZE_HOURS', default_var=os.environ.get('NEWS_LLM_ANALYZE_HOURS', '6')),
            'NEWS_LLM_ANALYZE_LIMIT': Variable.get('NEWS_LLM_ANALYZE_LIMIT', default_var=os.environ.get('NEWS_LLM_ANALYZE_LIMIT', '20')),
        })({**load_env_vars(NEWSWIRE_ENV_PATH), **load_env_vars(INGESTION_ENV_PATH), **load_env_vars(SHARED_ENV_PATH)}),
        mount_tmp_dir=False,
        working_dir='/app',
        dag=dag,
    )

# AI Analysis container step removed (run_ai_analysis no longer used)

# Update grading after scoring and AI analysis complete
update_grading = BashOperator(
    task_id='update_grading',
    bash_command="""
set -euo pipefail
auth=()
if [ -n "${AUTH_SERVICE_TOKEN:-}" ]; then
  auth=(-H "X-RA-Service-Token: ${AUTH_SERVICE_TOKEN}")
elif [ -n "${ADMIN_BEARER_TOKEN:-}" ]; then
  auth=(-H "Authorization: Bearer ${ADMIN_BEARER_TOKEN}")
fi
curl --fail --silent --show-error \
  --connect-timeout "${API_CONNECT_TIMEOUT:-10}" \
  --max-time "${API_MAX_TIME:-60}" \
  --retry "${API_RETRY_COUNT:-2}" \
  --retry-all-errors \
  "${auth[@]}" \
  -X POST "$API_URL/api/v1/grading/refresh" || exit 1
""",
    env={
        **load_env_vars(SHARED_ENV_PATH),
        **load_env_vars(f"/opt/rankalpha/env/{ENV_PROFILE}/api.env"),
        "RANKALPHA_ENV": ENV_PROFILE,
        # Prefer API_URL from container environment if set; else Airflow Variable; else default
        "API_URL": Variable.get("API_URL", default_var=os.environ.get("API_URL", "http://api:6080")),
        "API_CONNECT_TIMEOUT": Variable.get("API_CONNECT_TIMEOUT", default_var=os.environ.get("API_CONNECT_TIMEOUT", "10")),
        "API_MAX_TIME": Variable.get("API_MAX_TIME", default_var=os.environ.get("API_MAX_TIME", "60")),
        "API_RETRY_COUNT": Variable.get("API_RETRY_COUNT", default_var=os.environ.get("API_RETRY_COUNT", "2")),
    },
    dag=dag,
)

# Refresh AI Analysis proximity MV + invalidate API caches
update_ai_analysis = BashOperator(
    task_id='update_ai_analysis',
    bash_command="""
set -euo pipefail
auth=()
if [ -n "${AUTH_SERVICE_TOKEN:-}" ]; then
  auth=(-H "X-RA-Service-Token: ${AUTH_SERVICE_TOKEN}")
elif [ -n "${ADMIN_BEARER_TOKEN:-}" ]; then
  auth=(-H "Authorization: Bearer ${ADMIN_BEARER_TOKEN}")
fi
curl --fail --silent --show-error \
  --connect-timeout "${API_CONNECT_TIMEOUT:-10}" \
  --max-time "${API_MAX_TIME:-60}" \
  --retry "${API_RETRY_COUNT:-2}" \
  --retry-all-errors \
  "${auth[@]}" \
  -X POST "$API_URL/api/v1/admin/ai-analysis/refresh" || exit 1
""",
    env={
        **load_env_vars(SHARED_ENV_PATH),
        **load_env_vars(f"/opt/rankalpha/env/{ENV_PROFILE}/api.env"),
        "RANKALPHA_ENV": ENV_PROFILE,
        "API_URL": Variable.get("API_URL", default_var=os.environ.get("API_URL", "http://api:6080")),
        "API_CONNECT_TIMEOUT": Variable.get("API_CONNECT_TIMEOUT", default_var=os.environ.get("API_CONNECT_TIMEOUT", "10")),
        "API_MAX_TIME": Variable.get("API_MAX_TIME", default_var=os.environ.get("API_MAX_TIME", "60")),
        "API_RETRY_COUNT": Variable.get("API_RETRY_COUNT", default_var=os.environ.get("API_RETRY_COUNT", "2")),
    },
    dag=dag,
)

# Publish gate: only notify the frontend when grading has been updated (either via API refresh
# or the direct MV fallback) AND the AI analysis refresh succeeded. This preserves "serve
# yesterday" behavior on partial failures by avoiding cache busting/signals unless the
# full publish set completes.
grading_published = EmptyOperator(
    task_id='grading_published',
    dag=dag,
    trigger_rule='one_success',
)

# Fallback: refresh MV directly via psql if API is down
refresh_mv_direct = DockerOperator(
    task_id='refresh_mv_direct',
    image='postgres:16',
    api_version='auto',
    auto_remove='success',
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
    docker_url='unix://var/run/docker.sock',
    network_mode=DOCKER_NETWORK,
    do_xcom_push=False,
    cpus=float(Variable.get('PSQL_CPUS', default_var='0.5')),
    mem_limit=Variable.get('PSQL_MEM', default_var='256m'),
    environment=(lambda base: {
        **merge_env(
            base,
            ['DB_USERNAME','PASSWORD','DB_HOST','DB_PORT','DATABASE_NAME']
        ),
        'PGPASSWORD': base.get('PASSWORD', ''),
    })({**load_env_vars(INGESTION_ENV_PATH), **load_env_vars(SHARED_ENV_PATH)}),
    mount_tmp_dir=False,
    working_dir='/',
    dag=dag,
    trigger_rule='one_failed',  # run only if update_grading fails
)

# Notify frontend to refresh data via API call
notify_frontend = BashOperator(
    task_id='notify_frontend',
    bash_command="""
    # Send a signal to the frontend that new data is available
    # The frontend should have a polling mechanism or websocket to detect this
    # Best-effort: purge API Redis HTTP cache so reads don't wait for TTL expiry.
    auth=()
    if [ -n "${AUTH_SERVICE_TOKEN:-}" ]; then
      auth=(-H "X-RA-Service-Token: ${AUTH_SERVICE_TOKEN}")
    elif [ -n "${ADMIN_BEARER_TOKEN:-}" ]; then
      auth=(-H "Authorization: Bearer ${ADMIN_BEARER_TOKEN}")
    fi
    curl --silent --show-error "${auth[@]}" -X POST "$API_URL/api/v1/admin/cache/purge" -H "Content-Type: application/json" -d '{"prefixes":["httpcache:"]}' || true
    if [ -z "${FRONTEND_REFRESH_TOKEN:-}" ]; then \
      echo "FRONTEND_REFRESH_TOKEN not set; skipping frontend refresh" >&2; \
    else \
      curl --fail --silent --show-error -X POST -H "Authorization: Bearer ${FRONTEND_REFRESH_TOKEN}" "http://frontend:${FRONTEND_SERVICE_PORT:-3000}/api/refresh-data" || true; \
    fi
    echo "Frontend notification sent"
    """,
    dag=dag,
    trigger_rule='all_success',
    env={
        **load_env_vars(SHARED_ENV_PATH),
        **load_env_vars(f"/opt/rankalpha/env/{ENV_PROFILE}/api.env"),
        "RANKALPHA_ENV": ENV_PROFILE,
        "API_URL": Variable.get("API_URL", default_var=os.environ.get("API_URL", "http://api:6080")),
        "FRONTEND_REFRESH_TOKEN": Variable.get(
            "FRONTEND_REFRESH_TOKEN",
            default_var=os.environ.get("FRONTEND_REFRESH_TOKEN", ""),
        ),
        "FRONTEND_SERVICE_PORT": Variable.get(
            "FRONTEND_SERVICE_PORT",
            default_var=os.environ.get("FRONTEND_SERVICE_PORT", "3000"),
        ),
    },
)

warm_default_page_caches = PythonOperator(
    task_id="warm_default_page_caches",
    python_callable=warm_default_page_caches_task,
    dag=dag,
)

"""Task dependencies
Build the dependency graph dynamically so we never attempt to pipe list -> list,
which Airflow 2.9+ disallows. Every downstream processing task must finish before
we trigger grading or AI refreshes.
"""

downstream_tasks = [scorer]

if NEWS_ENABLED:
    downstream_tasks.append(newswire_blitz)

recycle_broker_sentiment >> ingestion

enqueue_post_earnings_queue >> refresh_universe_mv

for task in downstream_tasks:
    refresh_universe_mv >> task
    task >> update_grading
    task >> update_ai_analysis

scorer >> enqueue_grade_ab_queue
enqueue_grade_ab_queue >> update_grading

scorer >> compute_nowcast_snapshot
scorer >> enqueue_consensus_new_queue

ingestion >> enqueue_post_earnings_queue
ingestion >> price_cache_refresh
price_cache_refresh >> update_grading
price_cache_refresh >> update_ai_analysis

update_grading >> refresh_mv_direct
update_grading >> grading_published
refresh_mv_direct >> grading_published
grading_published >> notify_frontend
update_ai_analysis >> notify_frontend
compute_nowcast_snapshot >> notify_frontend
notify_frontend >> warm_default_page_caches
