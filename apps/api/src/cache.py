from __future__ import annotations

import hashlib
import json
import socket
import time
from collections.abc import Callable
from typing import Any, Optional, TypeVar, cast

import redis

from .settings import Settings

_redis_client: Optional[redis.Redis] = None
_cache_disabled: bool = False
_cache_disabled_until: Optional[float] = None
_CACHE_ERROR_DISABLE_SECONDS = 30.0


def _get_client() -> redis.Redis:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    settings = Settings()
    # Configure small timeouts so missing Redis doesn’t stall local dev
    common_kwargs = dict(
        decode_responses=True,
        socket_connect_timeout=0.1,
        socket_timeout=0.2,
        retry_on_timeout=False,
        health_check_interval=0,
    )
    if settings.redis_url:
        _redis_client = redis.from_url(settings.redis_url, **common_kwargs)
    else:
        host = settings.redis_host or "localhost"
        port = int(settings.redis_port or 6379)
        # Optional best-effort DNS probe to avoid long getaddrinfo delays
        try:
            socket.getaddrinfo(host, port)
        except Exception:
            raise ConnectionError(f"Redis host not resolvable: {host}")
        _redis_client = redis.Redis(
            host=host,
            port=port,
            db=int(settings.redis_db or 0),
            password=settings.redis_password or None,
            **common_kwargs,
        )
    return _redis_client


def make_key(prefix: str, params: dict[str, Any]) -> str:
    """Create a stable cache key based on a prefix and params dict."""
    # Sort keys for stability and hash long payloads
    items = sorted((k, params[k]) for k in params)
    raw = json.dumps(items, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _is_cache_disabled_now() -> bool:
    global _cache_disabled_until
    if _cache_disabled:
        return True
    if _cache_disabled_until is None:
        return False
    now = time.time()
    if now < _cache_disabled_until:
        return True
    _cache_disabled_until = None
    return False


def _disable_cache_temporarily() -> None:
    global _cache_disabled_until
    cooldown = max(float(_CACHE_ERROR_DISABLE_SECONDS), 0.0)
    _cache_disabled_until = time.time() + cooldown


def get_json(key: str) -> Optional[Any]:
    if _is_cache_disabled_now():
        return None
    try:
        val = _get_client().get(key)
        return json.loads(val) if val else None
    except Exception:
        # Trip a short cooldown window so transient Redis issues do not disable cache forever.
        _disable_cache_temporarily()
        return None


def set_json(key: str, value: Any, ttl_secs: Optional[int] = None) -> None:
    if _is_cache_disabled_now():
        return
    try:
        payload = json.dumps(value, default=str)
        if ttl_secs and ttl_secs > 0:
            _get_client().setex(key, ttl_secs, payload)
        else:
            _get_client().set(key, payload)
    except Exception:
        _disable_cache_temporarily()
        # best-effort cache; ignore failures
        pass


T = TypeVar("T")


def get_or_set_json(
    key: str,
    *,
    ttl_secs: Optional[int],
    factory: Callable[[], T],
) -> T:
    """Return cached JSON value or compute+store it.

    Unlike many ad-hoc call sites, this treats any non-None cached value as a hit
    (including empty lists/dicts and 0), which avoids recomputing empty results.
    """
    cached = get_json(key)
    if cached is not None:
        return cast(T, cached)
    value = factory()
    set_json(key, value, ttl_secs=ttl_secs)
    return value


def invalidate_prefix(prefix: str) -> int:
    """Delete keys starting with a given prefix. Returns number of keys deleted."""
    if _is_cache_disabled_now():
        return 0
    try:
        client = _get_client()
        # Use SCAN to avoid blocking
        total = 0
        cursor = 0
        pattern = f"{prefix}*"
        while True:
            cursor, keys = client.scan(cursor=cursor, match=pattern, count=500)
            if keys:
                total += client.delete(*keys)
            if cursor == 0:
                break
        return total
    except Exception:
        return 0


def ping_redis() -> bool:
    """Best-effort ping to Redis with small timeouts.

    Returns True if a ping succeeds; otherwise sets a process-wide
    disable flag to avoid future stalls and returns False.
    """
    if _is_cache_disabled_now():
        return False
    try:
        client = _get_client()
        # 'ping' will attempt a connect if not already connected
        ok = client.ping()
        if not ok:
            _disable_cache_temporarily()
        return bool(ok)
    except Exception:
        _disable_cache_temporarily()
        return False


def disable_cache_globally() -> None:
    """Disable cache for the lifetime of this process."""
    global _cache_disabled
    _cache_disabled = True


def is_cache_disabled() -> bool:
    return _is_cache_disabled_now()
