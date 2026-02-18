from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.common.src.settings_base import BaseAppSettings


def make_connection_url(settings: Optional[BaseAppSettings] = None) -> str:
    """Build a SQLAlchemy/psycopg2 connection URL from shared settings."""
    s = settings or BaseAppSettings()
    return f"postgresql+psycopg2://{s.db_username}:{s.password}@{s.host}:{s.port}/{s.database_name}"


def get_engine(
    *,
    settings: Optional[BaseAppSettings] = None,
    echo: Optional[bool] = None,
    pool_pre_ping: bool = True,
    future: bool = True,
    url_override: Optional[str] = None,
) -> Engine:
    """Return a shared SQLAlchemy engine."""
    # If a URL/DSN override is provided, do not instantiate Settings (avoids env requirements)
    if url_override:
        url = url_override
        s = settings  # may be None; echo defaults handled below
    else:
        s = settings or BaseAppSettings()
        url = make_connection_url(s)
    engine_kwargs: dict[str, object] = {
        "echo": (s.db_echo if (s and echo is None) else echo),
        "pool_pre_ping": pool_pre_ping,
        "future": future,
    }
    # Optional QueuePool tuning (primarily for FastAPI services under concurrency).
    if s is not None:
        pool_size = getattr(s, "db_pool_size", None)
        max_overflow = getattr(s, "db_max_overflow", None)
        pool_timeout = getattr(s, "db_pool_timeout_seconds", None)
        pool_recycle = getattr(s, "db_pool_recycle_seconds", None)
        if pool_size is not None:
            engine_kwargs["pool_size"] = int(pool_size)
            # Prefer LIFO under bursty traffic to reduce idle connection churn.
            engine_kwargs["pool_use_lifo"] = True
        if max_overflow is not None:
            engine_kwargs["max_overflow"] = int(max_overflow)
        if pool_timeout is not None:
            engine_kwargs["pool_timeout"] = int(pool_timeout)
        if pool_recycle is not None:
            engine_kwargs["pool_recycle"] = int(pool_recycle)

    return create_engine(
        url,
        **engine_kwargs,  # type: ignore[arg-type]
    )


def get_session_factory(
    *,
    engine: Optional[Engine] = None,
    settings: Optional[BaseAppSettings] = None,
    autocommit: bool = False,
    autoflush: bool = False,
) -> sessionmaker[Session]:
    """Create a scoped session factory bound to the shared engine."""
    eng = engine or get_engine(settings=settings)
    return sessionmaker(
        bind=eng,
        autocommit=autocommit,
        autoflush=autoflush,
        future=True,
    )


@contextmanager
def session_scope(factory: Optional[sessionmaker] = None) -> Generator[Session, None, None]:
    """
    Provide a transactional scope around a series of operations.
    Mirrors the pattern used by FastAPI dependencies and scripts.
    """
    SessionLocal = factory or get_session_factory()
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
