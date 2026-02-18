from __future__ import annotations

import time
from typing import Optional

import psycopg2
from psycopg2.extensions import connection

from apps.common.src.logging import get_logger
from apps.sentiment.src.settings import Settings as Settings

logger = get_logger(__name__)


def get_connection(
    settings: Settings,
    *,
    retries: int = 3,
    backoff_base: float = 2.0,
    connect_timeout: int = 30,
) -> connection:
    """Return a psycopg2 connection with retry/backoff semantics."""
    last_exc: Optional[Exception] = None
    for attempt in range(max(1, retries)):
        try:
            return psycopg2.connect(
                database=settings.database_name,
                user=settings.db_username,
                password=settings.password,
                host=settings.host,
                port=settings.port,
                connect_timeout=connect_timeout,
            )
        except psycopg2.OperationalError as exc:
            last_exc = exc
            if attempt == retries - 1:
                logger.error(
                    "DB connect failed after %s attempts: %s",
                    retries,
                    exc,
                )
                raise
            sleep_for = backoff_base**attempt
            logger.warning(
                "DB connect attempt %s/%s failed (%s). Retrying in %.1fs",
                attempt + 1,
                retries,
                exc,
                sleep_for,
            )
            time.sleep(sleep_for)
    if last_exc:
        raise last_exc
    raise RuntimeError("get_connection failed without raising OperationalError")
