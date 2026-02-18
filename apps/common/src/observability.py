from __future__ import annotations

import logging
import os
import socket
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, Optional
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

try:  # Optional; used for centralized exception tracking (Sentry SaaS/self-hosted).
    import sentry_sdk  # type: ignore

    try:
        from sentry_sdk.integrations.logging import LoggingIntegration  # type: ignore
        from sentry_sdk.integrations.logging import ignore_logger as _ignore_logger  # type: ignore
    except Exception:  # pragma: no cover - optional integration
        LoggingIntegration = None  # type: ignore
        _ignore_logger = None  # type: ignore

    try:
        from sentry_sdk.integrations.starlette import StarletteIntegration  # type: ignore
    except Exception:  # pragma: no cover - optional integration
        StarletteIntegration = None  # type: ignore

    try:
        from sentry_sdk.integrations.fastapi import FastApiIntegration  # type: ignore
    except Exception:  # pragma: no cover - optional integration
        FastApiIntegration = None  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    sentry_sdk = None  # type: ignore
    LoggingIntegration = None  # type: ignore
    StarletteIntegration = None  # type: ignore
    FastApiIntegration = None  # type: ignore

try:  # Prefer gRPC exporter; fall back to HTTP if requested explicitly.
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter as _GRPCExporter,
    )
except Exception:  # pragma: no cover - importer guard
    _GRPCExporter = None

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter as _HTTPExporter,
    )
except Exception:  # pragma: no cover - importer guard
    _HTTPExporter = None

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
except Exception:  # pragma: no cover - optional dependency
    FastAPIInstrumentor = None  # type: ignore

try:
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
except Exception:  # pragma: no cover - optional dependency
    LoggingInstrumentor = None  # type: ignore

try:
    from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
except Exception:  # pragma: no cover - optional dependency
    Psycopg2Instrumentor = None  # type: ignore

try:
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
except Exception:  # pragma: no cover - optional dependency
    RequestsInstrumentor = None  # type: ignore

try:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
except Exception:  # pragma: no cover - optional dependency
    SQLAlchemyInstrumentor = None  # type: ignore

try:
    from prometheus_client import (  # type: ignore
        REGISTRY,
        Counter,
        Gauge,
        Histogram,
        start_http_server,
    )
except Exception:  # pragma: no cover - fallback when dependency missing
    Counter = Gauge = Histogram = None  # type: ignore
    REGISTRY = None  # type: ignore
    start_http_server = None  # type: ignore

logger = logging.getLogger("apps.common.observability")

_TRACING_INITIALIZED = False
_SENTRY_INITIALIZED = False
_METRICS_SERVER_STARTED: set[tuple[str, int]] = set()
_FASTAPI_INSTRUMENTED: set[int] = set()
_UNAVAILABLE_ENDPOINTS: set[str] = set()


def _lookup_registered_collector(name: str) -> Optional[Any]:
    if REGISTRY is None:
        return None
    mapping = getattr(REGISTRY, "_names_to_collectors", None)
    if mapping is not None:
        existing = mapping.get(name)
        if existing is not None:
            return existing
    inverse = getattr(REGISTRY, "_collector_to_names", None)
    if inverse:
        for collector, names in inverse.items():
            if name in names:
                return collector
    return None


def get_or_create_counter(name: str, documentation: str, **kwargs: Any) -> Counter:
    if Counter is None:  # pragma: no cover - defensive guard when prometheus missing
        raise RuntimeError("prometheus_client Counter unavailable")
    try:
        return Counter(name, documentation, **kwargs)
    except ValueError:
        existing = _lookup_registered_collector(name)
        if isinstance(existing, Counter):
            return existing
        raise


def get_or_create_histogram(name: str, documentation: str, **kwargs: Any) -> Histogram:
    if Histogram is None:  # pragma: no cover - defensive guard when prometheus missing
        raise RuntimeError("prometheus_client Histogram unavailable")
    try:
        return Histogram(name, documentation, **kwargs)
    except ValueError:
        existing = _lookup_registered_collector(name)
        if isinstance(existing, Histogram):
            return existing
        raise


def get_or_create_gauge(name: str, documentation: str, **kwargs: Any) -> Gauge:
    if Gauge is None:  # pragma: no cover - defensive guard when prometheus missing
        raise RuntimeError("prometheus_client Gauge unavailable")
    try:
        return Gauge(name, documentation, **kwargs)
    except ValueError:
        existing = _lookup_registered_collector(name)
        if isinstance(existing, Gauge):
            return existing
        raise


def _build_resource(service_name: str, service_version: str | None = None) -> Resource:
    attrs: Dict[str, Any] = {"service.name": service_name}
    if service_version:
        attrs["service.version"] = service_version
    deployment_env = (
        os.getenv("OTEL_RESOURCE_ATTRIBUTES_DEPLOYMENT_ENV")
        or os.getenv("DEPLOYMENT_ENV")
        or os.getenv("ENV")
        or os.getenv("RANKALPHA_ENV")
    )
    if deployment_env:
        attrs["deployment.environment"] = deployment_env
    # Allow callers to append additional attributes via OTEL_RESOURCE_ATTRIBUTES
    extra = os.getenv("OTEL_RESOURCE_ATTRIBUTES")
    if extra:
        for item in extra.split(","):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key:
                attrs[key] = value
    return Resource.create(attrs)


def init_error_reporting(service_name: str, service_version: str | None = None) -> None:
    """Initialise exception reporting (Sentry) once per process.

    Controlled via:
      - SENTRY_DSN (required to enable)
      - SENTRY_ENABLED (optional; defaults true)
      - SENTRY_ENVIRONMENT (optional; defaults to ENV/RANKALPHA_ENV)
      - SENTRY_RELEASE (optional; defaults to service_version when provided)
      - SENTRY_ERROR_SAMPLE_RATE (optional; defaults 1.0)
      - SENTRY_TRACES_SAMPLE_RATE (optional; defaults 0.0)
      - SENTRY_IGNORE_LOGGERS (optional; comma-separated logger names to ignore)
    """

    global _SENTRY_INITIALIZED
    if _SENTRY_INITIALIZED:
        return
    if sentry_sdk is None:
        # Keep services runnable without sentry-sdk installed (e.g., lightweight dev envs).
        return
    dsn = (os.getenv("SENTRY_DSN") or "").strip()
    if not dsn:
        return
    enabled = (os.getenv("SENTRY_ENABLED") or "true").strip().lower() in {"1", "true", "yes"}
    if not enabled:
        return

    # Filter noisy third-party loggers (Sentry captures ERROR+ log records via LoggingIntegration).
    # This is especially important for background "tickler"/keepalive threads in broker integrations
    # that can intermittently fail due to upstream connectivity without representing an actionable
    # app error.
    default_ignored_loggers = {
        "ibind.ibkr_utils",
        "opentelemetry.exporter.otlp.proto.grpc.exporter",
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.sdk.trace.export",
    }
    extra_ignored_raw = (os.getenv("SENTRY_IGNORE_LOGGERS") or "").strip()
    extra_ignored = {s.strip() for s in extra_ignored_raw.split(",") if s.strip()}
    if _ignore_logger is not None:
        for logger_name in sorted(default_ignored_loggers | extra_ignored):
            try:
                _ignore_logger(logger_name)
            except Exception:
                continue

    deployment_env = (
        os.getenv("SENTRY_ENVIRONMENT")
        or os.getenv("DEPLOYMENT_ENV")
        or os.getenv("ENV")
        or os.getenv("RANKALPHA_ENV")
        or "unknown"
    )
    release = (os.getenv("SENTRY_RELEASE") or "").strip() or (service_version or None)

    integrations = []
    if LoggingIntegration is not None:
        # Capture breadcrumbs from INFO+; emit events only for ERROR+ log records.
        integrations.append(
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)  # type: ignore[arg-type]
        )
    # Capture FastAPI / Starlette request exceptions when available.
    if FastApiIntegration is not None:
        integrations.append(FastApiIntegration())  # type: ignore[misc]
    elif StarletteIntegration is not None:
        integrations.append(StarletteIntegration())  # type: ignore[misc]

    try:
        error_sample_rate = float(os.getenv("SENTRY_ERROR_SAMPLE_RATE", "1.0"))
    except Exception:
        error_sample_rate = 1.0
    try:
        traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0"))
    except Exception:
        traces_sample_rate = 0.0

    try:
        sentry_sdk.init(  # type: ignore[misc]
            dsn=dsn,
            environment=deployment_env,
            release=release,
            server_name=os.getenv("SENTRY_SERVER_NAME") or socket.gethostname(),
            sample_rate=error_sample_rate,
            traces_sample_rate=traces_sample_rate,
            send_default_pii=False,
            integrations=integrations or None,
        )
        try:
            sentry_sdk.set_tag("service", service_name)  # type: ignore[misc]
            sentry_sdk.set_tag("deployment.environment", deployment_env)  # type: ignore[misc]
        except Exception:
            pass
        _SENTRY_INITIALIZED = True
        logger.info("Sentry error reporting enabled for %s (env=%s)", service_name, deployment_env)
    except Exception:  # pragma: no cover - defensive
        logger.warning("Failed to initialise Sentry; continuing without error reporting.")


def capture_message(
    message: str,
    *,
    level: str = "info",
    tags: Optional[Dict[str, str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    if sentry_sdk is None or not _SENTRY_INITIALIZED:
        return
    try:
        with sentry_sdk.push_scope() as scope:  # type: ignore[misc]
            if tags:
                for k, v in tags.items():
                    scope.set_tag(k, v)
            if extra:
                for k, v in extra.items():
                    scope.set_extra(k, v)
            sentry_sdk.capture_message(message, level=level)  # type: ignore[misc]
    except Exception:
        return


def capture_exception(
    exc: BaseException,
    *,
    tags: Optional[Dict[str, str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    if sentry_sdk is None or not _SENTRY_INITIALIZED:
        return
    try:
        with sentry_sdk.push_scope() as scope:  # type: ignore[misc]
            if tags:
                for k, v in tags.items():
                    scope.set_tag(k, v)
            if extra:
                for k, v in extra.items():
                    scope.set_extra(k, v)
            sentry_sdk.capture_exception(exc)  # type: ignore[misc]
    except Exception:
        return


def report_ratio_threshold(
    *,
    service: str,
    check: str,
    ratio: float,
    threshold: float,
    total: int,
    affected: int,
    sample: Optional[list[str]] = None,
    level: str = "error",
) -> None:
    """Send a single Sentry event when a ratio breaches a threshold."""
    if ratio < threshold:
        return
    msg = f"{service}: {check} breached threshold ({affected}/{total} = {ratio:.2%}, threshold={threshold:.2%})"
    tags = {"service": service, "check": check}
    extra: Dict[str, Any] = {
        "ratio": ratio,
        "threshold": threshold,
        "total": total,
        "affected": affected,
    }
    if sample:
        extra["sample"] = sample[:25]
    capture_message(msg, level=level, tags=tags, extra=extra)


def _build_otlp_exporter() -> Optional[Any]:
    protocol = (os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL") or "grpc").lower()
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "http://otel-collector:4317"
    headers = _parse_headers(os.getenv("OTEL_EXPORTER_OTLP_HEADERS"))

    if not _is_endpoint_available(endpoint):
        if endpoint not in _UNAVAILABLE_ENDPOINTS:
            logger.warning(
                "OpenTelemetry endpoint %s unreachable; continuing without remote tracing.",
                endpoint,
            )
            _UNAVAILABLE_ENDPOINTS.add(endpoint)
        return None

    if protocol in {"http", "http/protobuf"}:
        if _HTTPExporter is None:
            logger.warning(
                "Requested OTLP HTTP exporter but dependency is unavailable; traces will log only."
            )
            return None
        try:
            return _HTTPExporter(endpoint=endpoint, headers=headers)  # type: ignore[arg-type]
        except Exception:  # pragma: no cover - defensive
            logger.warning(
                "Failed to initialise OTLP HTTP exporter for endpoint %s; traces will log only.",
                endpoint,
            )
            return None
    if _GRPCExporter is None:
        logger.warning(
            "OTLP gRPC exporter unavailable; traces will log only. Install opentelemetry-exporter-otlp-proto-grpc."
        )
        return None
    insecure = (os.getenv("OTEL_EXPORTER_OTLP_INSECURE") or "true").lower() in {
        "1",
        "true",
        "yes",
    }
    try:
        return _GRPCExporter(endpoint=endpoint, headers=headers, insecure=insecure)  # type: ignore[arg-type]
    except Exception:  # pragma: no cover - defensive
        logger.warning(
            "Failed to initialise OTLP gRPC exporter for endpoint %s; traces will log only.",
            endpoint,
        )
        return None


def _parse_headers(raw: Optional[str]) -> Optional[Dict[str, str]]:
    if not raw:
        return None
    headers: Dict[str, str] = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        headers[key.strip()] = value.strip()
    return headers or None


def init_tracing(service_name: str, service_version: str | None = None) -> Optional[TracerProvider]:
    """Initialise OpenTelemetry tracing once per process."""
    global _TRACING_INITIALIZED
    if _TRACING_INITIALIZED:
        return trace.get_tracer_provider()  # type: ignore[return-value]

    # Initialise error reporting early so unhandled import/startup errors are captured.
    init_error_reporting(service_name, service_version)

    exporter = _build_otlp_exporter()
    resource = _build_resource(service_name, service_version)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(exporter) if exporter else BatchSpanProcessor(_NoopExporter())
    )
    trace.set_tracer_provider(provider)
    _TRACING_INITIALIZED = True

    if LoggingInstrumentor:
        try:
            LoggingInstrumentor().instrument(set_logging_format=True)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to instrument logging with OpenTelemetry context.")
    if RequestsInstrumentor:
        try:
            RequestsInstrumentor().instrument()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to instrument requests library.")
    if Psycopg2Instrumentor:
        try:
            Psycopg2Instrumentor().instrument()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to instrument psycopg2.")
    if SQLAlchemyInstrumentor:
        try:
            SQLAlchemyInstrumentor().instrument(enable_commenter=True, commenter_options={})
        except Exception:  # pragma: no cover - defensive
            logger.warning("SQLAlchemy instrumentation failed; continuing without DB spans.")
    return provider


def ensure_metrics_server(service_name: str, port: int, host: str = "0.0.0.0") -> None:
    """Start a Prometheus metrics endpoint on the requested port if available."""
    if start_http_server is None:
        logger.warning(
            "prometheus_client not installed; metrics server unavailable for %s", service_name
        )
        return
    key = (service_name, port)
    if key in _METRICS_SERVER_STARTED:
        return
    start_http_server(port, addr=host)  # type: ignore[arg-type]
    logger.info("Started Prometheus metrics server for %s on %s:%s", service_name, host, port)
    _METRICS_SERVER_STARTED.add(key)


def init_service_observability(
    service_name: str,
    *,
    service_version: str | None = None,
    metrics_port_env: str = "OBSERVABILITY_METRICS_PORT",
    metrics_host_env: str = "OBSERVABILITY_METRICS_HOST",
) -> None:
    """Helper to initialise tracing and metrics for long-running Python services."""
    init_tracing(service_name, service_version)
    port_value = os.getenv(metrics_port_env)
    if port_value:
        try:
            port = int(port_value)
        except ValueError:
            logger.warning(
                "Invalid metrics port '%s' for %s; skipping metrics server.",
                port_value,
                service_name,
            )
        else:
            host = os.getenv(metrics_host_env, "0.0.0.0")
            ensure_metrics_server(service_name, port, host)


def sleep_for_metrics_flush(
    service_name: str,
    *,
    seconds_env: str = "OBSERVABILITY_METRICS_FLUSH_SECONDS",
) -> None:
    """Optionally sleep before exit so Prometheus can scrape final metric values.

    This is primarily useful for short-lived/batch services that update counters/histograms
    at the end of their run and then exit before the next scrape interval.
    """
    raw = (os.getenv(seconds_env) or "").strip()
    if not raw:
        return
    try:
        seconds = float(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r for %s; skipping metrics flush sleep.",
            seconds_env,
            raw,
            service_name,
        )
        return
    if seconds <= 0:
        return
    logger.info("Sleeping %.1fs to allow Prometheus scrape (%s).", seconds, service_name)
    time.sleep(seconds)


def instrument_fastapi_app(
    app: Any,
    *,
    service_name: str,
    service_version: str | None = None,
    enable_metrics: bool = True,
    metrics_app_name: str | None = None,
) -> None:
    """Attach Prometheus + OpenTelemetry instrumentation to a FastAPI app."""
    init_tracing(service_name, service_version)
    app_id = id(app)
    if app_id in _FASTAPI_INSTRUMENTED:
        return

    if enable_metrics and Counter is not None:
        try:
            from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore

            instrumentator = Instrumentator(
                should_group_status_codes=True,
                should_instrument_requests_inprogress=True,
                excluded_handlers={"/metrics"},
            )
            instrumentator.instrument(app).expose(app, include_in_schema=False)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to initialise Prometheus instrumentation for FastAPI app.")

    if FastAPIInstrumentor:
        try:
            FastAPIInstrumentor.instrument_app(
                app,
                tracer_provider=trace.get_tracer_provider(),
                excluded_urls=".*,\\/metrics",
                server_request_hook=_server_request_hook(metrics_app_name or service_name),
                client_request_hook=None,
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to instrument FastAPI app for tracing.")

    _FASTAPI_INSTRUMENTED.add(app_id)


def _server_request_hook(app_name: str):
    def hook(span, scope):
        try:
            span.set_attribute("service.request_app", app_name)
            if scope:
                span.set_attribute("http.route", scope.get("path"))
                span.set_attribute("http.method", scope.get("method"))
        except Exception:
            pass

    return hook


@contextmanager
def start_span(name: str, **attributes: Any) -> Iterator[Any]:
    tracer = trace.get_tracer("rankalpha")
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            try:
                span.set_attribute(key, value)
            except Exception:
                continue
        yield span


def _resolve_endpoint(endpoint: str) -> Optional[tuple[str, int]]:
    """Return host/port tuple for the configured OTLP endpoint, if determinable."""
    if "://" in endpoint:
        parsed = urlparse(endpoint)
    else:
        parsed = urlparse(f"grpc://{endpoint}")
    host = parsed.hostname or parsed.path
    if not host:
        return None
    port = parsed.port
    if port is None:
        if parsed.scheme in {"http", "http/protobuf", "https"}:
            port = 4318
        else:
            port = 4317
    return host, port


def _is_endpoint_available(endpoint: str) -> bool:
    host_port = _resolve_endpoint(endpoint)
    if not host_port:
        return True
    host, port = host_port
    try:
        timeout = float(os.getenv("OTEL_EXPORTER_CONNECT_TIMEOUT", "0.5"))
    except ValueError:
        timeout = 0.5
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class _NoopExporter:  # pragma: no cover - fallback exporter when OTLP unavailable
    def export(self, span_data: Iterable[Any]) -> str:
        if not span_data:
            return "SUCCESS"
        first = next(iter(span_data), None)
        if first:
            logger.debug("Trace(export noop): %s", first)
        return "SUCCESS"

    def shutdown(self) -> None:
        return
