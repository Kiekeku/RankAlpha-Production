from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, Optional, Sequence

import psycopg2
from psycopg2.extras import execute_values

from apps.common.src.settings_base import BaseAppSettings


class BatchWriter:
    """
    Lightweight helper for high-throughput writes where psycopg2 is preferred.

    Services should prefer SQLAlchemy for most work; use this only for
    bulk inserts/updates that benefit from `execute_values` or explicit
    autocommit control.
    """

    def __init__(
        self,
        *,
        settings: Optional[BaseAppSettings] = None,
        dsn: Optional[str] = None,
        page_size: int = 500,
    ) -> None:
        self.page_size = page_size
        if dsn:
            # DSN provided explicitly; avoid loading Settings to allow env-less usage.
            self.settings = settings  # may be None
            self.dsn = dsn
        else:
            self.settings = settings or BaseAppSettings()
            self.dsn = (
                f"dbname={self.settings.database_name} "
                f"user={self.settings.db_username} "
                f"password={self.settings.password} "
                f"host={self.settings.host} "
                f"port={self.settings.port}"
            )

    @contextmanager
    def connect(self, *, autocommit: bool = False):
        """Context-managed psycopg2 connection."""
        conn = psycopg2.connect(self.dsn)
        conn.autocommit = autocommit
        try:
            yield conn
            if not autocommit:
                conn.commit()
        finally:
            conn.close()

    def execute_values(
        self,
        sql: str,
        values: Sequence[Sequence[Any]] | Iterable[Sequence[Any]],
        *,
        page_size: Optional[int] = None,
        autocommit: bool = False,
    ) -> int:
        """Execute an INSERT/UPSERT using psycopg2.extras.execute_values."""
        with self.connect(autocommit=autocommit) as conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, values, page_size=page_size or self.page_size)
                return cur.rowcount or 0
