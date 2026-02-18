from __future__ import annotations


def ensure_broker_portfolio(session, account_number: str):
    """Get or create the broker portfolio row for an account."""
    from sqlalchemy import select

    from apps.common.src.models import Portfolio as RaPortfolio

    existing = session.scalar(
        select(RaPortfolio).where(RaPortfolio.portfolio_name == account_number)
    )
    if existing:
        existing.portfolio_kind = "BROKER"
        existing.broker_name = existing.broker_name or "IBKR"
        existing.broker_account_id = existing.broker_account_id or account_number
        return existing

    portfolio = RaPortfolio(
        portfolio_name=account_number,
        portfolio_kind="BROKER",
        broker_name="IBKR",
        broker_account_id=account_number,
        currency_code="USD",
    )
    session.add(portfolio)
    session.flush()
    return portfolio
