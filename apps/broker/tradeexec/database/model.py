"""
SQLAlchemy models for the QuantDB schema.

This module defines a handful of ORM classes that correspond to
commonly used tables in the original QuantDB database.  The
definition here is intentionally minimalist – it only includes
columns that are accessed by the ported code in this repository.
If your installation requires additional fields you can safely
extend these classes with extra mapped columns.

The module also exposes a convenience ``get_session`` context
manager to acquire a SQLAlchemy session bound to the configured
engine.  See ``tradeexec.settings`` for database configuration.

Examples
--------

```
from tradeexec.database.model import get_session, TradeTransaction

with get_session() as session:
    # Query unfilled trade transactions
    unfilled = (
        session.query(TradeTransaction)
        .filter(TradeTransaction.OrderPlaced.is_(None))
        .all()
    )
    print(unfilled)
```
"""

from contextlib import contextmanager
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    create_engine,
)
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

# Import centralized settings
from ..settings import settings

# ---------------------------------------------------------------------------
# Engine creation (PostgreSQL via SQLAlchemy URL)
# ---------------------------------------------------------------------------
db_config = settings.get_database_config()
engine = None

try:
    url = db_config.get("url")
    if url:
        engine = create_engine(url, echo=db_config.get("echo", False))
    else:
        # Incomplete configuration – disable the engine gracefully
        engine = None
except Exception as e:
    # Fail gracefully if any import or connection error occurs
    print(f"Info: Failed to create database engine: {e}")
    engine = None


# ---------------------------------------------------------------------------
# Base class for declarative models
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


# ---------------------------------------------------------------------------
# Core table models
# ---------------------------------------------------------------------------


class Credential(Base):
    """Represents the [dbo].[Credential] table."""

    __tablename__ = "Credential"

    Account: Mapped[str] = mapped_column(String, primary_key=True)
    UserName: Mapped[str] = mapped_column(String)
    Password: Mapped[str] = mapped_column(String)


class IndustryCompany(Base):
    """Represents the [dbo].[IndustryCompany] table with a composite key."""

    __tablename__ = "IndustryCompany"

    IndustryName: Mapped[str] = mapped_column(String, primary_key=True, nullable=False)
    CompanySymbol: Mapped[str] = mapped_column(String, primary_key=True, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["IndustryName"], ["Industry.IndustryName"]),
        ForeignKeyConstraint(["CompanySymbol"], ["Company.Symbol"]),
    )

    def __repr__(self) -> str:
        return f"IndustryCompany({self.IndustryName!r}, {self.CompanySymbol!r})"


class IndexMembership(Base):
    """Represents the [dbo].[IndexMembership] table with a composite key."""

    __tablename__ = "IndexMembership"

    IndexSymbol: Mapped[str] = mapped_column(String, primary_key=True, nullable=False)
    CompanySymbol: Mapped[str] = mapped_column(String, primary_key=True, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["IndexSymbol"], ["Index.Ticker"]),
        ForeignKeyConstraint(["CompanySymbol"], ["Company.Symbol"]),
    )

    def __repr__(self) -> str:
        return f"IndexMembership({self.IndexSymbol!r}, {self.CompanySymbol!r})"


class TradeTransaction(Base):
    """
    Represents the [dbo].[TradeTransaction] table.

    Only the subset of columns referenced by the translated code are
    declared here.  Extend this class with additional columns as your
    application requires.
    """

    __tablename__ = "TradeTransaction"

    ID: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    Ticker: Mapped[str] = mapped_column(String(50), nullable=False)
    TickerID: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    TransactionDate: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    Price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    Size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    Exchange: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    Description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    OrderType: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    TradeType: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    OrderPlaced: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    FilledPrice: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    StopLossPercent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ProfitTargetPercent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    LastPrice: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    System: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    OrderPlacedTime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    SizePercent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ManualPlaced: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    PaperFilledDate: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    PaperFilledSize: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    CreateDate: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ExecutionNote: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    CustomString: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    ControllerSize: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    PositionID: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    PaperFilledPrice: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    LastUpdated: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"TradeTransaction(ID={self.ID!r}, Ticker={self.Ticker!r}, System={self.System!r})"


# ---------------------------------------------------------------------------
# Additional models required by the ReconcilePosition translation
# ---------------------------------------------------------------------------


class SystemRunStatus(Base):
    """
    Represents the [dbo].[SystemRunStatus] table.

    This table tracks the last successful execution date of a trading
    system.  The translation of ``ReconcilePosition`` uses this
    information to compute the earliest date from which to consider
    historical executions when reconciling positions.
    """

    __tablename__ = "SystemRunStatus"

    System: Mapped[str] = mapped_column(String(100), primary_key=True)
    LastSuccessfulRun: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"SystemRunStatus(System={self.System!r}, LastSuccessfulRun={self.LastSuccessfulRun!r})"
        )


class SystemTransaction(Base):
    """
    Represents the [dbo].[SystemTransactions] table.

    A simplified representation of open system positions.  Only the
    columns accessed by the reconciliation logic are declared here.
    """

    __tablename__ = "SystemTransactions"

    PositionID: Mapped[str] = mapped_column(String(50), primary_key=True)
    System: Mapped[str] = mapped_column(String(100), nullable=False)
    Ticker: Mapped[str] = mapped_column(String(50), nullable=False)
    TransactionType: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    OpenDate: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    CloseDate: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    CurrentSize: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    Exchange: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    EntryPrice: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return f"SystemTransaction(PositionID={self.PositionID!r}, System={self.System!r}, Ticker={self.Ticker!r})"


class Portfolio(Base):
    """
    Represents the [dbo].[Portfolios] table.

    This table stores manually entered positions for an account.  Only
    the fields referenced by the reconciliation logic are included.
    """

    __tablename__ = "Portfolios"

    ID: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    Account: Mapped[str] = mapped_column(String(50), nullable=False)
    Ticker: Mapped[str] = mapped_column(String(50), nullable=False)
    EffStartDate: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    EffEndDate: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"Portfolio(ID={self.ID!r}, Account={self.Account!r}, Ticker={self.Ticker!r})"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def get_automapped_base():
    """
    Reflect all tables in the connected database into an automapped base.

    Returns
    -------
    DeclarativeMeta
        A declarative base with classes generated for every reflected table.
    """
    if engine is None:
        raise RuntimeError("Database engine not initialized. Check your database configuration.")
    metadata = MetaData()
    metadata.reflect(bind=engine)
    AutomapBase = automap_base(metadata=metadata)
    AutomapBase.prepare()
    return AutomapBase


# Audit table removed – idempotence is handled via rankalpha.fact_trade_recommendation


# Session factory
SessionLocal = None
if engine is not None:
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def get_session():
    """
    Provide a transactional scope around a series of operations.

    Yields
    ------
    Session
        A SQLAlchemy session bound to the configured engine.
    """
    if SessionLocal is None:
        raise RuntimeError("Database not configured. Please check your database settings.")
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
