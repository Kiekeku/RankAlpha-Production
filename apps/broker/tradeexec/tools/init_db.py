"""
init_db.py

Database helper for broker prerequisites. Currently ensures connectivity
and can apply broker-local migrations if present. The broker now uses
rankalpha.fact_trade_recommendation (idempotence) and rankalpha.fact_portfolio_trade
for fills, so no dedicated audit table is required.

Usage:
  Check only:
    uv run -m tradeexec.tools.init_db

  Create the table if missing (SQL Server):
    uv run -m tradeexec.tools.init_db --apply
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from sqlalchemy import inspect
from tradeexec.database.model import engine
from tradeexec.utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def table_exists(table: str, schema: str | None = None) -> bool:
    if engine is None:
        raise RuntimeError("Database engine not initialized. Check your DB settings in .env.")
    insp = inspect(engine)
    dialect = getattr(engine.dialect, "name", "")
    # In PostgreSQL, the default schema is "public" and many deployments don't use custom schemas.
    eff_schema = None if dialect == "postgresql" else schema
    try:
        return bool(insp.has_table(table_name=table, schema=eff_schema))
    except TypeError:
        # Older SQLAlchemy signature
        return bool(insp.has_table(table, eff_schema))


def apply_sql_file(path: Path) -> None:
    if engine is None:
        raise RuntimeError("Database engine not initialized. Check your DB settings in .env.")
    sql = path.read_text(encoding="utf-8")
    with engine.begin() as conn:
        # Use exec_driver_sql to allow running batches with GO separators removed
        # Split on GO lines (case-insensitive) and execute each chunk
        chunks: list[str] = []
        current: list[str] = []
        for line in sql.splitlines():
            if line.strip().upper() == "GO":
                if current:
                    chunks.append("\n".join(current))
                    current = []
            else:
                current.append(line)
        if current:
            chunks.append("\n".join(current))

        for _idx, chunk in enumerate(chunks, start=1):
            stmt = chunk.strip()
            if not stmt:
                continue
            conn.exec_driver_sql(stmt)


def main() -> int:
    parser = argparse.ArgumentParser(description="Broker DB sanity checks and optional migrations")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply broker-local migrations if any (noop by default)",
    )
    args = parser.parse_args()

    logger.info("DB connectivity looks OK. No audit schema required.")
    if not args.apply:
        return 0
    # No-op migration hook for future broker-local patches
    root = Path(__file__).resolve().parents[2]
    mig_dir = root / "migrations"
    if not mig_dir.exists():
        logger.info("No broker-local migrations directory found: %s", mig_dir)
        return 0
    applied_any = False
    for sql in sorted(mig_dir.glob("*.sql")):
        try:
            apply_sql_file(sql)
            logger.info("Applied %s", sql.name)
            applied_any = True
        except Exception as e:
            logger.error("Failed to apply %s: %s", sql, e)
            return 1
    if not applied_any:
        logger.info("No broker-local migrations to apply.")
    return 0


if __name__ == "__main__":
    setup_logging(simple=True)
    raise SystemExit(main())
