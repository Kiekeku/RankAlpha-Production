from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from apps.common.src.models import Portfolio, PortfolioRun
from apps.common.src.portfolio.construction import generate_broker_rebalance_run


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
    def __init__(self, *, run, broker, scalar_values, execute_results, scalars_results):
        self._run = run
        self._broker = broker
        self._scalar_values = list(scalar_values)
        self._execute_results = [
            _FakeResult(rows) if not isinstance(rows, _FakeResult) else rows for rows in execute_results
        ]
        self._scalars_results = [
            _FakeScalarResult(rows) if not isinstance(rows, _FakeScalarResult) else rows
            for rows in scalars_results
        ]

    def get(self, model, key):
        if model is PortfolioRun and key == self._run.run_id:
            return self._run
        if model is Portfolio and key == self._broker.portfolio_id:
            return self._broker
        return None

    def scalar(self, *_args, **_kwargs):
        return self._scalar_values.pop(0)

    def execute(self, *_args, **_kwargs):
        return self._execute_results.pop(0)

    def scalars(self, *_args, **_kwargs):
        return self._scalars_results.pop(0)

    def flush(self):
        return None


def test_broker_rebalance_applies_cash_buffer_and_clamps_long_only(monkeypatch):
    run_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    portfolio_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    run = SimpleNamespace(
        run_id=run_id,
        portfolio_id=portfolio_id,
        run_kind="BROKER_REBALANCE",
        as_of_date=date(2026, 1, 16),
        policy_id=1,
    )
    broker = SimpleNamespace(
        portfolio_id=portfolio_id,
        portfolio_kind="BROKER",
        currency_code="USD",
    )
    policy = SimpleNamespace(
        policy_id=1,
        constraints={
            "nav": {"min_cash_buffer_pct": 1.0},
            "exposure": {"long_only": True},
            "liquidity": {"adv20_usd_min": 0.0, "max_adv_pct_per_order": 0.0},
        },
    )

    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_policy_for_run",
        lambda *_args, **_kwargs: policy,
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction.ensure_model_construction_run",
        lambda *_args, **_kwargs: uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_date_key",
        lambda *_args, **_kwargs: 20260116,
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._next_trading_day",
        lambda *_args, **_kwargs: date(2026, 1, 17),
    )

    sub = SimpleNamespace(
        subscription_id=1,
        sizing_method="USE_SIGNAL_SIZE",
        default_notional_pct_nav=None,
        default_risk_budget_bps=None,
    )
    rec = SimpleNamespace(
        recommendation_id=uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
        stock_key=1,
        action="SELL",
        size_shares=Decimal("100"),
        size_percent=None,
        risk_budget_bps=None,
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._get_active_signal_subscriptions",
        lambda *_args, **_kwargs: [sub],
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._load_signal_recommendations",
        lambda *_args, **_kwargs: [(sub, rec)],
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction.upsert_order_intents",
        lambda *_args, **_kwargs: [uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")],
    )

    dep = SimpleNamespace(
        deployment_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        model_portfolio_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        allocation_pct=100.0,
        sleeve_portfolio_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
    )
    pos = SimpleNamespace(stock_key=1, quantity=Decimal("100"))
    cash = SimpleNamespace(currency_code="USD", cash_amount=Decimal("0"))

    execute_results = [
        [],  # delete PortfolioRunInput
        [],  # insert PortfolioRunInput
        [(1, Decimal("20"))],  # model weights
        [(pos, "AAPL", "USD")],  # baseline positions
        [(1, Decimal("10"))],  # close prices
        [],  # delete PortfolioRunSignalInput
        [],  # insert PortfolioRunSignalInput
        [],  # delete PortfolioRunPosition
        [],  # insert baseline equity
        [],  # insert baseline cash
        [],  # insert target cash (target equities clamped to zero)
        [],  # delete PortfolioOrderIntent
        [],  # insert PortfolioRunArtifact
        [],  # update PortfolioRun
    ]
    scalars_results = [
        [dep],  # deployments
        [cash],  # cash rows
    ]

    session = _FakeSession(
        run=run,
        broker=broker,
        scalar_values=[None],  # broker NLV (None => reconstructed)
        execute_results=execute_results,
        scalars_results=scalars_results,
    )

    summary = generate_broker_rebalance_run(session, run_id=run_id, generated_by="tester")

    assert summary["nav_anchor_base"] == 1000.0
    assert summary["min_cash_buffer_pct"] == 1.0
    assert summary["investable_nav"] == 990.0
    assert summary["clamped_negative_target_stock_keys"] == [1]


def test_broker_rebalance_rejects_over_100_allocation_without_margin(monkeypatch):
    run_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaab")
    portfolio_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbc")
    run = SimpleNamespace(
        run_id=run_id,
        portfolio_id=portfolio_id,
        run_kind="BROKER_REBALANCE",
        as_of_date=date(2026, 1, 16),
        policy_id=1,
    )
    broker = SimpleNamespace(
        portfolio_id=portfolio_id,
        portfolio_kind="BROKER",
        currency_code="USD",
    )
    dep_a = SimpleNamespace(
        deployment_id=uuid.uuid4(),
        model_portfolio_id=uuid.uuid4(),
        allocation_pct=70.0,
        sleeve_portfolio_id=uuid.uuid4(),
    )
    dep_b = SimpleNamespace(
        deployment_id=uuid.uuid4(),
        model_portfolio_id=uuid.uuid4(),
        allocation_pct=40.0,
        sleeve_portfolio_id=uuid.uuid4(),
    )
    policy = SimpleNamespace(policy_id=1, constraints={"exposure": {"allow_margin": False}})
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_policy_for_run",
        lambda *_args, **_kwargs: policy,
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction.ensure_model_construction_run",
        lambda *_args, **_kwargs: uuid.uuid4(),
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_date_key",
        lambda *_args, **_kwargs: 20260116,
    )
    session = _FakeSession(
        run=run,
        broker=broker,
        scalar_values=[],
        execute_results=[],
        scalars_results=[[dep_a, dep_b]],
    )
    with pytest.raises(ValueError, match="allow_margin"):
        generate_broker_rebalance_run(session, run_id=run_id, generated_by="tester")


def test_broker_rebalance_allows_margin_and_enforces_cap(monkeypatch):
    run_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaac")
    portfolio_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbd")
    run = SimpleNamespace(
        run_id=run_id,
        portfolio_id=portfolio_id,
        run_kind="BROKER_REBALANCE",
        as_of_date=date(2026, 1, 16),
        policy_id=1,
    )
    broker = SimpleNamespace(
        portfolio_id=portfolio_id,
        portfolio_kind="BROKER",
        currency_code="USD",
    )
    dep_a = SimpleNamespace(
        deployment_id=uuid.uuid4(),
        model_portfolio_id=uuid.uuid4(),
        allocation_pct=80.0,
        sleeve_portfolio_id=uuid.uuid4(),
    )
    dep_b = SimpleNamespace(
        deployment_id=uuid.uuid4(),
        model_portfolio_id=uuid.uuid4(),
        allocation_pct=60.0,
        sleeve_portfolio_id=uuid.uuid4(),
    )
    policy = SimpleNamespace(
        policy_id=1,
        constraints={
            "exposure": {"allow_margin": True, "max_gross_exposure_pct": 130.0},
        },
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_policy_for_run",
        lambda *_args, **_kwargs: policy,
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction.ensure_model_construction_run",
        lambda *_args, **_kwargs: uuid.uuid4(),
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_date_key",
        lambda *_args, **_kwargs: 20260116,
    )
    session = _FakeSession(
        run=run,
        broker=broker,
        scalar_values=[],
        execute_results=[],
        scalars_results=[[dep_a, dep_b]],
    )
    with pytest.raises(ValueError, match="max_gross_exposure_pct"):
        generate_broker_rebalance_run(session, run_id=run_id, generated_by="tester")


def test_broker_rebalance_margin_summary_includes_allocation(monkeypatch):
    run_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaad")
    portfolio_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbe")
    run = SimpleNamespace(
        run_id=run_id,
        portfolio_id=portfolio_id,
        run_kind="BROKER_REBALANCE",
        as_of_date=date(2026, 1, 16),
        policy_id=1,
    )
    broker = SimpleNamespace(
        portfolio_id=portfolio_id,
        portfolio_kind="BROKER",
        currency_code="USD",
    )
    policy = SimpleNamespace(
        policy_id=1,
        constraints={
            "nav": {"min_cash_buffer_pct": 1.0},
            "exposure": {
                "long_only": True,
                "allow_margin": True,
                "max_gross_exposure_pct": 150.0,
            },
            "liquidity": {"adv20_usd_min": 0.0, "max_adv_pct_per_order": 0.0},
        },
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_policy_for_run",
        lambda *_args, **_kwargs: policy,
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction.ensure_model_construction_run",
        lambda *_args, **_kwargs: uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccd"),
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_date_key",
        lambda *_args, **_kwargs: 20260116,
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._next_trading_day",
        lambda *_args, **_kwargs: date(2026, 1, 17),
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._get_active_signal_subscriptions",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._load_signal_recommendations",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction.upsert_order_intents",
        lambda *_args, **_kwargs: [],
    )

    dep = SimpleNamespace(
        deployment_id=uuid.UUID("11111111-1111-1111-1111-111111111112"),
        model_portfolio_id=uuid.UUID("22222222-2222-2222-2222-222222222223"),
        allocation_pct=120.0,
        sleeve_portfolio_id=uuid.UUID("33333333-3333-3333-3333-333333333334"),
    )
    pos = SimpleNamespace(stock_key=1, quantity=Decimal("100"))
    cash = SimpleNamespace(currency_code="USD", cash_amount=Decimal("0"))

    execute_results = [
        [],  # delete PortfolioRunInput
        [],  # insert PortfolioRunInput
        [(1, Decimal("20"))],  # model weights
        [(pos, "AAPL", "USD")],  # baseline positions
        [(1, Decimal("10"))],  # close prices
        [],  # delete PortfolioRunSignalInput
        [],  # delete PortfolioRunPosition
        [],  # insert baseline equity
        [],  # insert baseline cash
        [],  # insert target equities
        [],  # insert target cash
        [],  # delete PortfolioOrderIntent
        [],  # insert PortfolioRunArtifact
        [],  # update PortfolioRun
    ]
    scalars_results = [
        [dep],  # deployments
        [cash],  # cash rows
    ]
    session = _FakeSession(
        run=run,
        broker=broker,
        scalar_values=[None],  # broker NLV
        execute_results=execute_results,
        scalars_results=scalars_results,
    )

    summary = generate_broker_rebalance_run(session, run_id=run_id, generated_by="tester")
    assert summary["constraints_used"]["allow_margin"] is True
    assert summary["constraints_used"]["max_gross_exposure_pct"] == 150.0
    assert summary["constraints_used"]["total_deployment_allocation_pct"] == 120.0


def test_broker_rebalance_long_only_round_lot_residual_short_errors(monkeypatch):
    run_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaae")
    portfolio_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbf")
    run = SimpleNamespace(
        run_id=run_id,
        portfolio_id=portfolio_id,
        run_kind="BROKER_REBALANCE",
        as_of_date=date(2026, 1, 16),
        policy_id=1,
    )
    broker = SimpleNamespace(
        portfolio_id=portfolio_id,
        portfolio_kind="BROKER",
        currency_code="USD",
    )
    policy = SimpleNamespace(
        policy_id=1,
        constraints={
            "nav": {"min_cash_buffer_pct": 0.0},
            "exposure": {"long_only": True},
            "position_limits": {"round_lot_size": 100, "allow_fractional_shares": False},
        },
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_policy_for_run",
        lambda *_args, **_kwargs: policy,
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction.ensure_model_construction_run",
        lambda *_args, **_kwargs: uuid.uuid4(),
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_date_key",
        lambda *_args, **_kwargs: 20260116,
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._next_trading_day",
        lambda *_args, **_kwargs: date(2026, 1, 17),
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._get_active_signal_subscriptions",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._load_signal_recommendations",
        lambda *_args, **_kwargs: [],
    )

    dep = SimpleNamespace(
        deployment_id=uuid.uuid4(),
        model_portfolio_id=uuid.uuid4(),
        allocation_pct=0.0,
        sleeve_portfolio_id=uuid.uuid4(),
    )
    pos = SimpleNamespace(stock_key=1, quantity=Decimal("-50"))
    cash = SimpleNamespace(currency_code="USD", cash_amount=Decimal("0"))
    session = _FakeSession(
        run=run,
        broker=broker,
        scalar_values=[None],  # broker NLV
        execute_results=[
            [],  # delete PortfolioRunInput
            [],  # insert PortfolioRunInput
            [],  # model weights
            [(pos, "AAPL", "USD")],  # baseline positions
            [(1, Decimal("10"))],  # close prices
        ],
        scalars_results=[
            [dep],  # deployments
            [cash],  # cash rows
        ],
    )
    with pytest.raises(ValueError, match="residual short positions"):
        generate_broker_rebalance_run(session, run_id=run_id, generated_by="tester")


def test_broker_rebalance_rejects_fractional_share_config(monkeypatch):
    run_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaf")
    portfolio_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbc0")
    run = SimpleNamespace(
        run_id=run_id,
        portfolio_id=portfolio_id,
        run_kind="BROKER_REBALANCE",
        as_of_date=date(2026, 1, 16),
        policy_id=1,
    )
    broker = SimpleNamespace(
        portfolio_id=portfolio_id,
        portfolio_kind="BROKER",
        currency_code="USD",
    )
    policy = SimpleNamespace(
        policy_id=1,
        constraints={
            "position_limits": {"allow_fractional_shares": True},
            "exposure": {"long_only": True},
        },
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_policy_for_run",
        lambda *_args, **_kwargs: policy,
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction.ensure_model_construction_run",
        lambda *_args, **_kwargs: uuid.uuid4(),
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._resolve_date_key",
        lambda *_args, **_kwargs: 20260116,
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._next_trading_day",
        lambda *_args, **_kwargs: date(2026, 1, 17),
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._get_active_signal_subscriptions",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "apps.common.src.portfolio.construction._load_signal_recommendations",
        lambda *_args, **_kwargs: [],
    )
    dep = SimpleNamespace(
        deployment_id=uuid.uuid4(),
        model_portfolio_id=uuid.uuid4(),
        allocation_pct=100.0,
        sleeve_portfolio_id=uuid.uuid4(),
    )
    pos = SimpleNamespace(stock_key=1, quantity=Decimal("10"))
    cash = SimpleNamespace(currency_code="USD", cash_amount=Decimal("0"))
    session = _FakeSession(
        run=run,
        broker=broker,
        scalar_values=[None],  # broker NLV
        execute_results=[
            [],  # delete PortfolioRunInput
            [],  # insert PortfolioRunInput
            [(1, Decimal("10"))],  # model weights
            [(pos, "AAPL", "USD")],  # baseline positions
            [(1, Decimal("10"))],  # close prices
        ],
        scalars_results=[
            [dep],  # deployments
            [cash],  # cash rows
        ],
    )
    with pytest.raises(ValueError, match="allow_fractional_shares=true is not supported"):
        generate_broker_rebalance_run(session, run_id=run_id, generated_by="tester")
