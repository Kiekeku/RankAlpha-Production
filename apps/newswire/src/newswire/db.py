from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.common.src.settings_base import BaseAppSettings as Settings


def make_engine():
    s = Settings()
    port = getattr(s, "db_port", None)
    if port is None:
        port = s.port
    url = f"postgresql+psycopg2://{s.db_username}:{s.password}@{s.host}:{port}/{s.database_name}"
    return create_engine(url, pool_pre_ping=True, future=True)


def session_factory() -> sessionmaker[Session]:
    engine = make_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
