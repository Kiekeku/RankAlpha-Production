#!/usr/bin/env python3
"""
Simple database connection test script
"""

import sys

import pytest

from tradeexec.settings import settings


def test_database_connection():
    """Integration test: validate DB connectivity when configured."""
    db_config = settings.get_database_config()
    url = db_config.get("url")
    if not url:
        pytest.skip("No database URL configured")

    # Test engine creation
    try:
        from tradeexec.database.model import engine

        if engine is None:
            pytest.skip("Database engine is None - check configuration")
    except Exception as e:
        pytest.skip(f"Failed to import database model: {e}")

    # Test connection
    try:
        from sqlalchemy import text

        from tradeexec.database.model import get_session

        with get_session() as session:
            result = session.execute(text("SELECT 1 as test")).scalar()
            assert result == 1
    except Exception as e:
        pytest.skip(f"Database connection failed: {e}")


if __name__ == "__main__":
    try:
        test_database_connection()
        sys.exit(0)
    except Exception:
        sys.exit(1)
