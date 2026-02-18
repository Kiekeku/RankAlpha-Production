from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from apps.portfolio.src import main as portfolio_main


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, *, scalars_results=None, execute_results=None):
        self._scalars_results = [_Rows(r) for r in (scalars_results or [])]
        self._execute_results = [_Rows(r) for r in (execute_results or [])]

    def scalars(self, *_args, **_kwargs):
        return self._scalars_results.pop(0)

    def execute(self, *_args, **_kwargs):
        return self._execute_results.pop(0)


def test_compute_nav_returns_none_when_any_close_price_missing(monkeypatch):
    portfolio = SimpleNamespace(
        portfolio_id=uuid.uuid4(),
        portfolio_name="Broker Test",
        currency_code="USD",
    )
    position = SimpleNamespace(stock_key=1, quantity=Decimal("10"))
    session = _FakeSession(
        scalars_results=[
            [position],  # PortfolioPosition rows
            [],  # PortfolioCashPosition rows
        ],
        execute_results=[
            [(1, "USD", "AAPL")],  # DimStock lookup
        ],
    )
    monkeypatch.setattr(portfolio_main, "_close_px_by_stock", lambda *_args, **_kwargs: {})

    nav = portfolio_main._compute_nav_for_portfolio(session, portfolio=portfolio, date_key=20260116)
    assert nav is None


def test_rollup_uses_historical_nav_fallback_without_reseeding(monkeypatch):
    model_portfolio = SimpleNamespace(
        portfolio_id=uuid.uuid4(),
        portfolio_name="Model Core",
        portfolio_kind="MODEL",
        currency_code="USD",
    )
    session = _FakeSession(
        scalars_results=[
            [model_portfolio],  # select(Portfolio)
        ],
        execute_results=[
            [],  # select TARGET weights from PortfolioRunPosition
        ],
    )

    @contextmanager
    def _fake_scope():
        yield session

    upsert_calls: list[dict] = []
    pnl_calls: list[dict] = []
    monkeypatch.setattr(portfolio_main, "session_scope", _fake_scope)
    monkeypatch.setattr(
        portfolio_main,
        "_latest_trading_day_before",
        lambda *_args, **kwargs: date(2026, 1, 15)
        if kwargs.get("before") == date(2026, 1, 16)
        else date(2026, 1, 14),
    )

    def _fake_resolve_date_key(_session, as_of):
        if as_of == date(2026, 1, 16):
            return 20260116
        if as_of == date(2026, 1, 15):
            return 20260115
        return 20260114

    monkeypatch.setattr(portfolio_main, "_resolve_date_key", _fake_resolve_date_key)
    monkeypatch.setattr(portfolio_main, "_get_nav", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        portfolio_main,
        "_latest_nav_on_or_before",
        lambda *_args, **_kwargs: Decimal("123.45"),
    )
    monkeypatch.setattr(
        portfolio_main,
        "ensure_model_construction_run",
        lambda *_args, **_kwargs: uuid.uuid4(),
    )
    monkeypatch.setattr(
        portfolio_main,
        "upsert_nav",
        lambda *_args, **kwargs: upsert_calls.append(kwargs),
    )
    monkeypatch.setattr(
        portfolio_main,
        "_upsert_daily_total_pnl",
        lambda *_args, **kwargs: pnl_calls.append(kwargs),
    )

    updated = portfolio_main.rollup_performance(
        SimpleNamespace(portfolio_nav_skip_zero=False),
        as_of_date=date(2026, 1, 16),
    )

    assert updated == 1
    assert len(upsert_calls) == 1
    assert upsert_calls[0]["date_key"] == 20260116
    assert upsert_calls[0]["nav_base_ccy"] == 123.45
    assert len(pnl_calls) == 1
    assert pnl_calls[0]["total_pnl"] == Decimal("0")
