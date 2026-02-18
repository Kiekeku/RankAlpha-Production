import logging

import pytest

from apps.common.src.ai.budget import BudgetLedger, Budget
from apps.common.src.ai.notifications import BudgetAlertEvent


def test_budget_rpm_tokens_cost_caps():
    b = Budget(max_requests_per_min=2, max_tokens_per_day=100, max_cost_usd_per_day=1.0)
    led = BudgetLedger(service="testsvc", budget=b)
    # First request ok
    led.reserve_request()
    led.reserve_tokens(50)
    led.reserve_cost(0.5)
    # Second request ok
    led.reserve_request()
    led.reserve_tokens(25)
    led.reserve_cost(0.25)
    # Third request should exceed RPM
    try:
        led.reserve_request()
        assert False, "expected RPM limit"
    except RuntimeError:
        pass


def test_budget_guard_logs_snapshot(caplog):
    ledger = BudgetLedger(service="logsvc", budget=Budget(max_requests_per_min=1, max_tokens_per_day=10, max_cost_usd_per_day=5.0))
    ledger.reserve_request()
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError):
            ledger.reserve_request()
    guard_records = [rec for rec in caplog.records if rec.message == "Budget guard triggered"]
    assert guard_records, "expected guardrail log when RPM limit exceeded"
    record = guard_records[-1]
    assert getattr(record, "guard", "") == "requests_per_minute"
    usage = getattr(record, "budget_usage", {})
    assert usage.get("guard") == "requests_per_minute"
    assert usage.get("rpm_limit_per_minute") == float(ledger.budget.max_requests_per_min)
    assert usage.get("rpm_used_last_minute", 0.0) >= 1.0
    # Token/cost categories should still be present in the snapshot
    assert "tokens_used_today" in usage
    assert "cost_used_today" in usage


def test_budget_alerts_fire_once_per_threshold():
    events: list[BudgetAlertEvent] = []

    def handler(evt: BudgetAlertEvent) -> None:
        events.append(evt)

    b = Budget(max_requests_per_min=100, max_tokens_per_day=100, max_cost_usd_per_day=1000.0)
    ledger = BudgetLedger(service="svc", budget=b, alert_handler=handler)

    # First call: 50 tokens (no alert)
    res1 = ledger.begin_call(tokens_estimate=50, cost_estimate_usd=0.0)
    ledger.commit(tokens_in=40, tokens_out=10, actual_cost_usd=0.0, reservation=res1)
    assert not events

    # Second call pushes usage to 90 tokens -> triggers 80% alert
    res2 = ledger.begin_call(tokens_estimate=40, cost_estimate_usd=0.0)
    ledger.commit(tokens_in=40, tokens_out=0, actual_cost_usd=0.0, reservation=res2)
    assert len(events) == 1
    assert events[0].service == "svc"
    assert events[0].metric == "tokens"
    assert events[0].threshold == 0.80

    # Third call pushes usage over 100% -> triggers 100% alert once
    res3 = ledger.begin_call(tokens_estimate=10, cost_estimate_usd=0.0)
    ledger.commit(tokens_in=10, tokens_out=0, actual_cost_usd=0.0, reservation=res3)
    assert len(events) == 2
    assert events[1].threshold == 1.00

    # Additional commit should not emit duplicate alerts for same thresholds
    try:
        ledger.begin_call(tokens_estimate=1, cost_estimate_usd=0.0)
    except RuntimeError:
        pass
    assert len(events) == 2
