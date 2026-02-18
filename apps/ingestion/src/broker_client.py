"""Broker client helpers for ingestion."""

from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd
import requests

from apps.ingestion.src.settings import Settings


class BrokerClient:
    """Thin wrapper around the broker prev-close endpoint."""

    def __init__(self, settings: Settings, logger) -> None:
        self._logger = logger
        self._base_url = getattr(settings, "broker_service_url", None)
        self._service_token = getattr(settings, "broker_service_token", None)

    def fetch_prev_close(self, symbol: str) -> Tuple[Optional[pd.Timestamp], Optional[float]]:
        if not self._base_url:
            return None, None
        url = f"{self._base_url.rstrip('/')}/price/prev-close/{symbol.upper()}"
        headers = {}
        token = (self._service_token or "").strip()
        if token:
            headers["X-RA-Service-Token"] = token
        try:
            resp = requests.get(url, timeout=4, headers=headers or None)
        except Exception as exc:
            self._logger.debug("Broker prev-close request failed for %s: %s", symbol, exc)
            return None, None
        if resp.status_code != 200:
            return None, None
        data = resp.json() or {}
        px = data.get("previous_close")
        as_of = data.get("as_of")
        if px is None or as_of is None:
            return None, None
        try:
            ts = pd.Timestamp(as_of)
            if getattr(ts, "tz", None) is not None:
                ts = ts.tz_localize(None)
            return ts.normalize(), float(px)
        except Exception:
            return None, None
