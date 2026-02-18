from apps.common.src.ai.budget import BudgetLedger, Budget


def test_reserve_tokens_rollback_on_over_limit():
    b = Budget(max_requests_per_min=100, max_tokens_per_day=100, max_cost_usd_per_day=1000.0)
    ledger = BudgetLedger(service="testsvc", budget=b)
    # Reserve 90 tokens OK
    ledger.reserve_tokens(90)
    # Next reserve would exceed by 10; expect rollback to keep at 90
    try:
        ledger.reserve_tokens(20)
        assert False, "expected token budget exceeded"
    except RuntimeError:
        pass
    # Inspect internal counter value
    key = ledger._k("tokens", ledger._date_str())  # type: ignore[attr-defined]
    assert int(ledger.counter.get(key)) == 90


def test_reserve_rpm_rollback_on_over_limit():
    b = Budget(max_requests_per_min=1, max_tokens_per_day=1000, max_cost_usd_per_day=1000.0)
    ledger = BudgetLedger(service="rpmsvc", budget=b)
    # First request OK
    ledger.reserve_request()
    # Second should rollback
    try:
        ledger.reserve_request()
        assert False, "expected rpm limit"
    except RuntimeError:
        pass
    key = ledger._k("rpm")  # type: ignore[attr-defined]
    assert int(ledger.counter.get(key)) == 1

