import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import DeclarativeMeta

from apps.common.src.logging import get_logger, setup_logging
from apps.common.src.models import Base  # ← your huge registry
from apps.common.src.observability import instrument_fastapi_app

from .cache import disable_cache_globally, ping_redis
from .http_cache import RedisHTTPCacheMiddleware
from .http_client import aclose_clients
from .metrics import APIMetricsMiddleware
from .request_logging import RequestLoggingMiddleware
from .router_factory import build_router
from .routers import (
    admin,
    ai_analysis,
    auth,
    backtest,
    benchmarks,
    breadth,
    earnings,
    fra_ois,
    fundamentals,
    fx,
    grading,
    hy_stress,
    macro,
    market_structure,
    money_flow,
    news,
    news_ingest,
    nowcast,
    ops,
    pipeline,
    portfolio,
    portfolios,
    prices,
    rank_regime,
    rates,
    regime,
    regime_rules,
    screener,
    screener_scores,
    signals,
    technicals,
    trading,
    vol_regime,
)
from .security_headers import SecurityHeadersMiddleware
from .settings import Settings

settings = Settings()

_in_tests = "pytest" in sys.modules or bool(os.getenv("PYTEST_CURRENT_TEST"))

openapi_enabled = bool(settings.api_openapi_enabled)
docs_enabled = bool(settings.api_docs_enabled)
internal_crud_enabled = bool(settings.api_internal_crud_enabled)
if _in_tests:
    # Keep OpenAPI and /internal available in tests so we can validate
    # security headers and access controls even if prod defaults are hardened.
    openapi_enabled = True
    docs_enabled = True
    internal_crud_enabled = True
if docs_enabled and not openapi_enabled:
    # Swagger UI depends on the OpenAPI schema endpoint.
    openapi_enabled = True

app = FastAPI(
    title="RankAlpha Data‑Lake",
    version="0.2.0",
    openapi_url="/openapi.json" if openapi_enabled else None,
    docs_url="/" if docs_enabled else None,
    description="RankAlpha API for financial analysis, grading, and backtesting",
)
instrument_fastapi_app(app, service_name="rankalpha-api", service_version="0.2.0")
app.add_middleware(APIMetricsMiddleware)


@app.get("/health", include_in_schema=False)
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


if _in_tests:
    # Work around anyio threadpool hangs in this environment by forcing
    # sync endpoints/dependencies to execute via asyncio's thread helper.
    from contextlib import asynccontextmanager as _asynccontextmanager

    import fastapi.concurrency as _fastapi_concurrency
    import fastapi.dependencies.utils as _dependency_utils
    import fastapi.routing as _fastapi_routing
    import starlette.concurrency as _starlette_concurrency

    async def _run_in_threadpool(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def _run_endpoint_function(*, dependant, values, is_coroutine):
        assert dependant.call is not None
        if is_coroutine:
            return await dependant.call(**values)
        return dependant.call(**values)

    @_asynccontextmanager
    async def _contextmanager_in_threadpool(cm):
        try:
            yield cm.__enter__()
        except Exception as exc:
            ok = bool(cm.__exit__(type(exc), exc, exc.__traceback__))
            if not ok:
                raise
        else:
            cm.__exit__(None, None, None)

    _fastapi_concurrency.run_in_threadpool = _run_in_threadpool
    _dependency_utils.run_in_threadpool = _run_in_threadpool
    _dependency_utils.contextmanager_in_threadpool = _contextmanager_in_threadpool
    _fastapi_routing.run_in_threadpool = _run_in_threadpool
    _starlette_concurrency.run_in_threadpool = _run_in_threadpool
    _fastapi_routing.run_endpoint_function = _run_endpoint_function

setup_logging(
    settings.log_level,
    use_async=settings.api_async_logging_enabled,
    async_queue_maxsize=settings.api_async_logging_queue_maxsize,
)
logger = get_logger("api")
if settings.log_level:
    import logging as _logging

    try:
        logger.setLevel(getattr(_logging, settings.log_level.upper(), _logging.INFO))
    except Exception:
        logger.setLevel(_logging.INFO)

# Add CORS middleware for frontend (env-driven with sensible defaults)
default_origins = ["http://localhost:3000", "http://localhost:3001"]
cors_origins = settings.cors_origins or default_origins
if settings.cors_allow_credentials and any(o.strip() == "*" for o in cors_origins if o):
    raise ValueError(
        "CORS misconfiguration: allow_credentials=true is incompatible with '*' origins"
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods or ["*"],
    allow_headers=settings.cors_allow_headers or ["*"],
)

# Request logging and global GET cache (Redis)
app.add_middleware(RequestLoggingMiddleware)
if (
    settings.http_cache_enabled
    and "pytest" not in sys.modules
    and not os.getenv("PYTEST_CURRENT_TEST")
):
    app.add_middleware(RedisHTTPCacheMiddleware)

# Include custom routers
app.include_router(grading.router)
app.include_router(signals.router)
app.include_router(backtest.router)
app.include_router(pipeline.router)
app.include_router(ai_analysis.router)
app.include_router(screener.router)
app.include_router(screener_scores.router)
app.include_router(regime.router)
app.include_router(rank_regime.router)
app.include_router(regime_rules.router)
app.include_router(market_structure.router)
app.include_router(prices.router)
app.include_router(technicals.router)
app.include_router(fundamentals.router)
app.include_router(admin.router)
app.include_router(ops.router)
app.include_router(auth.router)
app.include_router(news.router)
app.include_router(news_ingest.router)
app.include_router(trading.router)
app.include_router(hy_stress.router)
app.include_router(fra_ois.router)
app.include_router(vol_regime.router)
app.include_router(breadth.router)
app.include_router(macro.router)
app.include_router(rates.router)
app.include_router(money_flow.router)
app.include_router(benchmarks.router)
app.include_router(fx.router)
app.include_router(portfolio.router)
app.include_router(portfolios.router)
app.include_router(nowcast.router)
app.include_router(earnings.router)


_default_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    async with _default_lifespan(_app):
        # Startup health probe for Redis cache – disables cache if unreachable
        if not _in_tests and settings.http_cache_enabled:
            try:
                if not ping_redis():
                    disable_cache_globally()
                    logger.warning("HTTP cache disabled: Redis not reachable in startup probe")
                else:
                    logger.info("HTTP cache enabled: Redis reachable")
            except Exception:
                disable_cache_globally()
                logger.warning("HTTP cache disabled: Redis probe raised exception")
        yield
        await aclose_clients()


app.router.lifespan_context = _lifespan


# -------------------------------------------------------------------------
#   Dynamically build + mount a router for **every** SQLAlchemy class
#   – views come out read‑only; ordinary tables get full CRUD.
# -------------------------------------------------------------------------
if internal_crud_enabled:
    for mapper in Base.registry.mappers:
        sa_cls: DeclarativeMeta = mapper.class_
        # skip the synthetic relationship‑only helpers (no __table__)
        if getattr(sa_cls, "__table__", None) is None:
            continue
        app.include_router(
            build_router(sa_cls, base_prefix="/internal"),
            include_in_schema=settings.api_internal_crud_include_in_schema,
        )

if settings.security_headers_enabled:
    # Keep this as the last middleware so it applies to cached responses too.
    app.add_middleware(SecurityHeadersMiddleware)
