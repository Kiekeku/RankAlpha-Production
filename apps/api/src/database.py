from typing import Generator

from sqlalchemy.orm import Session

from apps.common.src.db import get_engine, get_session_factory

from .settings import Settings

# Use API-specific Settings to avoid env leakage from other services
_api_settings = Settings()
engine = get_engine(settings=_api_settings)
SessionLocal = get_session_factory(engine=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency – yield a session per‑request and commit/rollback safely."""
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
