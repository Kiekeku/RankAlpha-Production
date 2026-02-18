import sys
import types
from typing import Any, Dict

import pytest


def _install_stub_ibind_and_settings():
    # Ensure we import tradeexec.core.ib fresh with stubs
    for name in [
        "tradeexec.core.ib",
        "ibind",
        "ibind.oauth",
        "ibind.oauth.oauth1a",
        "tradeexec.settings",
    ]:
        sys.modules.pop(name, None)

    # Stub ibind.oauth.oauth1a.OAuth1aConfig
    oauth_mod = types.ModuleType("ibind.oauth.oauth1a")

    class OAuth1aConfig:  # type: ignore
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def verify_config(self) -> None:
            return

    oauth_mod.OAuth1aConfig = OAuth1aConfig
    sys.modules["ibind.oauth"] = types.ModuleType("ibind.oauth")
    sys.modules["ibind.oauth.oauth1a"] = oauth_mod

    # Stub ibind root
    ibind_mod = types.ModuleType("ibind")

    class StubResp:
        def __init__(self, data: Any) -> None:
            self.data = data

    class QuestionType:  # pragma: no cover
        PRICE_PERCENTAGE_CONSTRAINT = "PRICE_PERCENTAGE_CONSTRAINT"
        ORDER_VALUE_LIMIT = "ORDER_VALUE_LIMIT"
        MISSING_MARKET_DATA = "MISSING_MARKET_DATA"
        STOP_ORDER_RISKS = "STOP_ORDER_RISKS"

    class IbkrClient:  # type: ignore
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.account_id = "TEST"
            self.last_place_request = None
            self.place_requests = []
            self.last_cancel_kwargs: Dict[str, Any] | None = None

        def receive_brokerage_accounts(self) -> None:  # pragma: no cover
            return

        def portfolio_accounts(self):  # pragma: no cover
            return StubResp([{"accountId": self.account_id}])

        def get(self, path: str, params: Dict[str, Any] | None = None):  # pragma: no cover
            return StubResp({})

        def place_order(self, request, answers, account_id):  # type: ignore[no-redef]
            self.last_place_request = request
            self.place_requests.append(request)
            return StubResp({"orderId": 123})

        def cancel_order(self, **kwargs: Any):  # pragma: no cover
            self.last_cancel_kwargs = kwargs
            return StubResp({"ok": True})

    def StockQuery(
        symbol: str, contract_conditions: Dict[str, Any] | None = None
    ):  # pragma: no cover
        return {"symbol": symbol, "cond": contract_conditions or {}}

    def make_order_request(*args: Any, **kwargs: Any):  # pragma: no cover
        return {"args": args, "kwargs": kwargs}

    ibind_mod.IbkrClient = IbkrClient
    ibind_mod.StockQuery = StockQuery
    ibind_mod.QuestionType = QuestionType
    ibind_mod.make_order_request = make_order_request
    sys.modules["ibind"] = ibind_mod

    # Stub tradeexec.settings.settings so importing ib module doesn't require apps.common
    fake_settings_mod = types.ModuleType("tradeexec.settings")

    class _S:  # minimal surface
        ib_account_id = "DUTEST"
        ib_cacert_path = None

        def get_ib_oauth_params(self):  # pragma: no cover
            return {}

    fake_settings_mod.settings = _S()
    sys.modules["tradeexec.settings"] = fake_settings_mod


def test_ib_place_order_normalizes_market_limit_stoplimit():
    _install_stub_ibind_and_settings()
    from tradeexec.core.ib import IBInterfacing

    ib = IBInterfacing(use_global_settings=False, account_id="DU1")

    ib.place_order(conid=1, order_type="Market", side="BUY", quantity=1)
    req = ib.client.last_place_request  # type: ignore[attr-defined]
    assert req["kwargs"]["order_type"] == "MKT"
    assert req["kwargs"].get("price") is None

    ib.place_order(conid=1, order_type="Limit", side="BUY", quantity=1, limit_price=100.0)
    req = ib.client.last_place_request  # type: ignore[attr-defined]
    assert req["kwargs"]["order_type"] == "LMT"
    assert req["kwargs"]["price"] == 100.0

    ib.place_order(
        conid=1,
        order_type="StopLimit",
        side="BUY",
        quantity=1,
        limit_price=100.12,
        stop_price=99.87,
    )
    req = ib.client.last_place_request  # type: ignore[attr-defined]
    assert req["kwargs"]["order_type"] == "STP LMT"
    assert abs(req["kwargs"]["price"] - 100.12) < 1e-9
    assert abs(req["kwargs"]["aux_price"] - 99.87) < 1e-9


def test_ib_place_order_normalizes_trailing_stop():
    _install_stub_ibind_and_settings()
    from tradeexec.core.ib import IBInterfacing

    ib = IBInterfacing(use_global_settings=False, account_id="DU1")

    with pytest.raises(ValueError):
        ib.place_order(conid=1, order_type="TrailingStop", side="SELL", quantity=5)

    ib.place_order(conid=1, order_type="TRAIL", side="SELL", quantity=5, trail_percent=2.5)
    req = ib.client.last_place_request  # type: ignore[attr-defined]
    assert req["kwargs"]["order_type"] == "TRAIL"
    assert req.get("trailingType") == "%"
    assert req.get("trailingAmt") == 2.5


def test_ib_place_order_futures_sets_manual_indicator_and_stable_coid():
    _install_stub_ibind_and_settings()
    from tradeexec.core.ib import IBInterfacing

    ib = IBInterfacing(use_global_settings=False, account_id="DU1")

    ib.place_order(
        conid=1,
        sec_type="FUT",
        order_type="LIMIT",
        side="BUY",
        quantity=1,
        limit_price=100.0,
        idempotency_key="rec-123",
    )
    ib.place_order(
        conid=1,
        sec_type="FUT",
        order_type="LIMIT",
        side="BUY",
        quantity=1,
        limit_price=100.0,
        idempotency_key="rec-123",
    )

    req1 = ib.client.place_requests[0]  # type: ignore[attr-defined]
    req2 = ib.client.place_requests[1]  # type: ignore[attr-defined]
    assert req1["manualIndicator"] is False
    assert req1["kwargs"]["coid"] == req2["kwargs"]["coid"]
    assert req1["kwargs"]["coid"].startswith("ra-")


def test_ib_cancel_order_futures_sets_manual_indicator():
    _install_stub_ibind_and_settings()
    from tradeexec.core.ib import IBInterfacing

    ib = IBInterfacing(use_global_settings=False, account_id="DU1")
    ib.cancel_order(123, sec_type="FUT")
    payload = ib.client.last_cancel_kwargs  # type: ignore[attr-defined]
    assert payload is not None
    assert payload["order_id"] == 123
    assert payload["account_id"] == "DU1"
    assert payload["manualIndicator"] is False
