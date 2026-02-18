from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from apps.common.src.models import Portfolio
from apps.common.src.portfolio.construction import _evaluate_broker_run_risk


@dataclass
class _FakeResult:
    rows: list

    def all(self):
        return self.rows


@dataclass
class _FakeScalarResult:
    rows: list

    def all(self):
        return self.rows


class _FakeSession:
    def __init__(self, *, portfolio, scalar_values, execute_results, scalars_results):
        self._portfolio = portfolio
        self._scalar_values = list(scalar_values)
        self._execute_results = [
            _FakeResult(rows) if not isinstance(rows, _FakeResult) else rows for rows in execute_results
        ]
        self._scalars_results = [
            _FakeScalarResult(rows) if not isinstance(rows, _FakeScalarResult) else rows
            for rows in scalars_results
        ]

    def get(self, model, key):
        if model is Portfolio and key == self._portfolio.portfolio_id:
            return self._portfolio
        return None

    def scalar(self, *_args, **_kwargs):
        return self._scalar_values.pop(0)

    def execute(self, *_args, **_kwargs):
        return self._execute_results.pop(0)

    def scalars(self, *_args, **_kwargs):
        return self._scalars_results.pop(0)


def test_evaluate_broker_risk_short_sell_keeps_nav_constant():
    portfolio_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    run_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    run = SimpleNamespace(
        run_id=run_id,
        portfolio_id=portfolio_id,
        run_kind="BROKER_REBALANCE",
        as_of_date=date(2026, 1, 16),
    )

    portfolio = SimpleNamespace(
        portfolio_id=portfolio_id,
        currency_code="USD",
    )

    policy = SimpleNamespace(
        policy_id=1,
        constraints={
            "exposure": {"long_only": False, "max_leverage": 2.0},
            "liquidity": {"adv20_usd_min": 0.0, "max_adv_pct_per_order": 0.0},
        },
    )

    cash_row = SimpleNamespace(currency_code="USD", quantity=Decimal("1000"))
    order = SimpleNamespace(
        order_id=uuid.uuid4(),
        line_no=1,
        stock_key=1,
        action="SELL",
        qty_shares=Decimal("10"),
        order_type="MARKET",
        time_in_force="DAY",
        limit_price=None,
        stop_trigger_price=None,
    )

    session = _FakeSession(
        portfolio=portfolio,
        scalar_values=[20260116],
        execute_results=[
            [],  # baseline run positions (none)
            [(order, "AAPL", "USD")],  # orders
            [(1, Decimal("10"))],  # close px
        ],
        scalars_results=[
            [cash_row],  # baseline cash
        ],
    )

    status, summary, checks = _evaluate_broker_run_risk(session, run=run, policy=policy)
    assert status == "PASS"
    assert summary["baseline_nav_usd"] == 1000.0
    assert summary["target_nav_usd"] == 1000.0

    by_code = {c["check_code"]: c for c in checks}
    assert by_code["MAX_LEVERAGE"]["status"] == "PASS"


def test_evaluate_broker_risk_fails_when_fx_missing_for_orders_even_without_base_book():
    portfolio_id = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    run_id = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    run = SimpleNamespace(
        run_id=run_id,
        portfolio_id=portfolio_id,
        run_kind="BROKER_REBALANCE",
        as_of_date=date(2026, 1, 16),
    )

    portfolio = SimpleNamespace(
        portfolio_id=portfolio_id,
        currency_code="USD",
    )

    policy = SimpleNamespace(
        policy_id=1,
        constraints={
            "exposure": {"long_only": False},
            "liquidity": {"adv20_usd_min": 0.0, "max_adv_pct_per_order": 0.0},
        },
    )

    cash_row = SimpleNamespace(currency_code="USD", quantity=Decimal("0"))
    order = SimpleNamespace(
        order_id=uuid.uuid4(),
        line_no=1,
        stock_key=1,
        action="BUY",
        qty_shares=Decimal("10"),
        order_type="MARKET",
        time_in_force="DAY",
        limit_price=None,
        stop_trigger_price=None,
    )

    session = _FakeSession(
        portfolio=portfolio,
        # scalar() calls:
        # - resolve as_of_date_key
        # - FX direct lookup
        # - FX inverse lookup (attempted if direct missing)
        scalar_values=[20260116, None, None],
        execute_results=[
            [],  # baseline run positions (none)
            [(order, "7203", "JPY")],  # orders (non-base currency)
            [(1, Decimal("100"))],  # close px
        ],
        scalars_results=[
            [cash_row],  # baseline cash
        ],
    )

    status, _summary, checks = _evaluate_broker_run_risk(session, run=run, policy=policy)
    assert status == "FAIL"
    by_code = {c["check_code"]: c for c in checks}
    assert by_code["FX_RATE_AVAILABLE"]["status"] == "FAIL"


def test_evaluate_broker_risk_supports_non_base_positions_when_fx_available():
    portfolio_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    run_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    run = SimpleNamespace(
        run_id=run_id,
        portfolio_id=portfolio_id,
        run_kind="BROKER_REBALANCE",
        as_of_date=date(2026, 1, 16),
    )

    portfolio = SimpleNamespace(
        portfolio_id=portfolio_id,
        currency_code="USD",
    )

    policy = SimpleNamespace(
        policy_id=1,
        constraints={
            "nav": {"min_cash_buffer_pct": 0.0},
            "position_limits": {"max_name_weight_pct": 100.0},
            "exposure": {"long_only": False},
            "liquidity": {"adv20_usd_min": 0.0, "max_adv_pct_per_order": 0.0},
        },
    )

    non_base_pos = SimpleNamespace(stock_key=1, quantity=Decimal("10"))

    session = _FakeSession(
        portfolio=portfolio,
        scalar_values=[20260116, Decimal("0.0063")],
        execute_results=[
            [(non_base_pos, "7203", "JPY")],  # baseline run positions (non-base)
            [],  # orders
            [(1, Decimal("100"))],  # close px
        ],
        scalars_results=[
            [],  # baseline cash
        ],
    )

    status, _summary, checks = _evaluate_broker_run_risk(session, run=run, policy=policy)
    assert status == "PASS"
    by_code = {c["check_code"]: c for c in checks}
    assert by_code["FX_RATE_AVAILABLE"]["status"] == "PASS"


def test_evaluate_broker_risk_supports_percent_exposure_alias_for_max_leverage():
    portfolio_id = uuid.UUID("99999999-aaaa-bbbb-cccc-dddddddddddd")
    run_id = uuid.UUID("77777777-2222-3333-4444-555555555556")
    run = SimpleNamespace(
        run_id=run_id,
        portfolio_id=portfolio_id,
        run_kind="BROKER_REBALANCE",
        as_of_date=date(2026, 1, 16),
    )

    portfolio = SimpleNamespace(
        portfolio_id=portfolio_id,
        currency_code="USD",
    )

    policy = SimpleNamespace(
        policy_id=1,
        constraints={
            "exposure": {"long_only": False, "max_gross_exposure_pct": 100.0},
            "liquidity": {"adv20_usd_min": 0.0, "max_adv_pct_per_order": 0.0},
        },
    )

    cash_row = SimpleNamespace(currency_code="USD", quantity=Decimal("1000"))
    order = SimpleNamespace(
        order_id=uuid.uuid4(),
        line_no=1,
        stock_key=1,
        action="BUY",
        qty_shares=Decimal("150"),
        order_type="MARKET",
        time_in_force="DAY",
        limit_price=None,
        stop_trigger_price=None,
    )

    session = _FakeSession(
        portfolio=portfolio,
        scalar_values=[20260116],
        execute_results=[
            [],  # baseline run positions (none)
            [(order, "AAPL", "USD")],  # orders
            [(1, Decimal("10"))],  # close px
        ],
        scalars_results=[
            [cash_row],  # baseline cash
        ],
    )

    status, _summary, checks = _evaluate_broker_run_risk(session, run=run, policy=policy)
    assert status == "FAIL"
    by_code = {c["check_code"]: c for c in checks}
    assert by_code["MAX_LEVERAGE"]["status"] == "FAIL"
