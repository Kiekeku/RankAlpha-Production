"""Shared database helpers for SQLAlchemy and batch writes.

This package centralizes connection/session creation so services
can avoid duplicating DSN handling and commit/rollback patterns.
"""

from .batch import BatchWriter
from .session import (
    get_engine,
    get_session_factory,
    make_connection_url,
    session_scope,
)

__all__ = [
    "make_connection_url",
    "get_engine",
    "get_session_factory",
    "session_scope",
    "BatchWriter",
]
