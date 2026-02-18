"""Cache refresh helpers for ingestion."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

import requests

from apps.ingestion.src.settings import Settings


class PriceCacheRefresher:
    """Notifies downstream cache when prices change."""

    def __init__(self, settings: Settings, logger) -> None:
        self._settings = settings
        self._logger = logger

    def refresh(self, symbol_dates: Dict[str, date]) -> None:
        if not symbol_dates:
            return
        refresh_url = getattr(self._settings, "price_cache_refresh_url", None)
        if not refresh_url:
            return
        timeout = float(
            getattr(self._settings, "price_cache_refresh_timeout_seconds", None) or 15.0
        )
        chunk_size = int(
            getattr(self._settings, "price_history_cache_refresh_chunk_size", None) or 50
        )
        service_token = getattr(self._settings, "auth_service_token", None)
        headers = {"Content-Type": "application/json"}
        token_value = (service_token or "").strip()
        if token_value.lower().startswith("bearer "):
            token_value = token_value[7:].strip()
        if not token_value:
            self._logger.warning(
                "Skipping price cache refresh; AUTH_SERVICE_TOKEN not configured (set in env/<ENV>/shared.env)"
            )
            return
        headers["X-RA-Service-Token"] = token_value
        if not refresh_url.lower().startswith("http"):
            self._logger.warning("Skipping price cache refresh; invalid URL: %s", refresh_url)
            return
        all_symbols = sorted(symbol_dates.keys())
        try:
            as_of = max(symbol_dates.values()).isoformat()
        except Exception:
            as_of = None
        batches = self._chunked(all_symbols, chunk_size)
        success = 0
        for batch in batches:
            payload: dict[str, Any] = {"symbols": batch, "reason": "ingestion", "force": True}
            if as_of:
                payload["as_of"] = as_of
            try:
                resp = requests.post(refresh_url, json=payload, headers=headers, timeout=timeout)
                if resp.status_code >= 400:
                    self._logger.warning(
                        "Price cache refresh call failed: status=%s body=%s symbols=%s",
                        resp.status_code,
                        resp.text[:300],
                        batch,
                    )
                else:
                    success += len(batch)
            except Exception as exc:
                self._logger.warning(
                    "Price cache refresh request failed for symbols=%s: %s", batch, exc
                )
        self._logger.info(
            "Ingestion issued price cache refresh: requested=%d succeeded=%d batches=%d",
            len(all_symbols),
            success,
            len(batches),
        )

    @staticmethod
    def _chunked(items: list[str], size: int) -> list[list[str]]:
        if size <= 0:
            size = 1
        return [items[i : i + size] for i in range(0, len(items), size)]
