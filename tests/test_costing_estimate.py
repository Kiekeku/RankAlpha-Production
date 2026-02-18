from apps.common.src.ai.costing import preflight_estimate_cost, reconcile_cost


def test_preflight_and_reconcile_zero_pricing():
    # With default pricing.yaml placeholders, costs are zero but tokens should be > 0
    model = "gpt-4o-mini"
    est_tokens, est_cost = preflight_estimate_cost(model, "system", "hello world")
    assert isinstance(est_tokens, int) and est_tokens > 0
    assert est_cost >= 0.0
    # Reconcile using synthetic usage
    ti, to, actual = reconcile_cost(model, {"usage": {"prompt_tokens": est_tokens, "completion_tokens": 10}, "text": "out"}, est_tokens)
    assert ti == est_tokens
    assert to == 10
    assert actual >= 0.0

