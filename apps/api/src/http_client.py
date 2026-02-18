from __future__ import annotations

import threading
from typing import Optional

import httpx

_sync_client: Optional[httpx.Client] = None
_sync_lock = threading.Lock()
_async_client: Optional[httpx.AsyncClient] = None
_async_lock = threading.Lock()

_DEFAULT_LIMITS = httpx.Limits(max_keepalive_connections=20, max_connections=100)


def get_sync_client() -> httpx.Client:
    global _sync_client
    if _sync_client is not None:
        return _sync_client
    with _sync_lock:
        if _sync_client is None:
            _sync_client = httpx.Client(limits=_DEFAULT_LIMITS)
    return _sync_client


def get_async_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is not None:
        return _async_client
    with _async_lock:
        if _async_client is None:
            _async_client = httpx.AsyncClient(limits=_DEFAULT_LIMITS)
    return _async_client


async def aclose_clients() -> None:
    """Best-effort cleanup for shared HTTP clients."""
    global _async_client, _sync_client
    if _sync_client is not None:
        _sync_client.close()
        _sync_client = None
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None
