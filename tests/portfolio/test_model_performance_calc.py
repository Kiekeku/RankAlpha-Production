from __future__ import annotations

from decimal import Decimal

from apps.portfolio.src.main import _compute_weighted_return_base


def test_compute_weighted_return_base_handles_fx_and_shorts():
    weights = {1: Decimal("0.5"), 2: Decimal("-0.5")}
    close_prev = {1: Decimal("100"), 2: Decimal("50")}
    close_today = {1: Decimal("110"), 2: Decimal("45")}
    ccy_by_stock = {1: "USD", 2: "EUR"}

    fx_prev = lambda ccy: Decimal("1") if ccy == "USD" else Decimal("1.2")
    fx_today = lambda ccy: Decimal("1") if ccy == "USD" else Decimal("1.1")

    ret, missing = _compute_weighted_return_base(
        weights=weights,
        close_prev=close_prev,
        close_today=close_today,
        ccy_by_stock=ccy_by_stock,
        base_ccy="USD",
        fx_prev=fx_prev,
        fx_today=fx_today,
    )

    # Stock 1: +10% * 0.5 = +0.05
    # Stock 2 base return: (45*1.1)/(50*1.2) - 1 = 0.825 - 1 = -0.175
    # Short weight: -0.5 * -0.175 = +0.0875
    assert missing == []
    assert ret == Decimal("0.1375")


def test_compute_weighted_return_base_reports_missing_inputs():
    ret, missing = _compute_weighted_return_base(
        weights={1: Decimal("1")},
        close_prev={1: Decimal("0")},
        close_today={1: Decimal("100")},
        ccy_by_stock={1: "USD"},
        base_ccy="USD",
        fx_prev=lambda _ccy: Decimal("1"),
        fx_today=lambda _ccy: Decimal("1"),
    )
    assert ret == Decimal("0")
    assert missing and missing[0]["reason"] == "missing_close_px"

