import sys
import types
from typing import Any, Dict


def _install_stub_ibind_and_settings():
    for name in [
        "tradeexec.core.ib",
        "ibind",
        "ibind.oauth",
        "ibind.oauth.oauth1a",
        "tradeexec.settings",
    ]:
        sys.modules.pop(name, None)

    oauth_mod = types.ModuleType("ibind.oauth.oauth1a")

    class OAuth1aConfig:  # type: ignore
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def verify_config(self) -> None:
            return

    oauth_mod.OAuth1aConfig = OAuth1aConfig
    sys.modules["ibind.oauth"] = types.ModuleType("ibind.oauth")
    sys.modules["ibind.oauth.oauth1a"] = oauth_mod

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
            self.initialize_calls = 0
            self.receive_calls = 0
            self.get_calls: list[tuple[str, Dict[str, Any] | None]] = []

        def receive_brokerage_accounts(self) -> None:  # pragma: no cover
            self.receive_calls += 1

        def initialize_brokerage_session(self) -> None:  # pragma: no cover
            self.initialize_calls += 1

        def portfolio_accounts(self):  # pragma: no cover
            return StubResp([{"accountId": self.account_id}])

        def get(self, path: str, params: Dict[str, Any] | None = None):
            self.get_calls.append((path, params))
            if path == "iserver/account/trades" and params is not None:
                raise RuntimeError("unsupported since")
            if path == "iserver/account/trades":
                return StubResp({"trades": [{"symbol": "AAPL"}]})
            return StubResp({})

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

    fake_settings_mod = types.ModuleType("tradeexec.settings")

    class _S:
        ib_account_id = "DUTEST"
        ib_cacert_path = None

        def get_ib_oauth_params(self):  # pragma: no cover
            return {}

    fake_settings_mod.settings = _S()
    sys.modules["tradeexec.settings"] = fake_settings_mod


def test_request_with_retry_reinitializes_after_bridge_error(monkeypatch):
    _install_stub_ibind_and_settings()
    from tradeexec.core.ib import IBInterfacing

    ib = IBInterfacing(use_global_settings=False, account_id="DU1")
    ib._retry_base_delay = 0
    ib._retry_jitter = 0
    ib._retry_attempts = 2

    calls = {"count": 0, "reinit": 0}

    def _reinit() -> None:
        calls["reinit"] += 1

    def _flaky():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("no bridge available")
        return "ok"

    monkeypatch.setattr(ib, "_reinitialize_bridge", _reinit)
    out = ib._request_with_retry("unit_test", _flaky)
    assert out == "ok"
    assert calls["count"] == 2
    assert calls["reinit"] == 1


def test_get_recent_trades_throttles_and_falls_back(monkeypatch):
    _install_stub_ibind_and_settings()
    from tradeexec.core.ib import IBInterfacing

    ib = IBInterfacing(use_global_settings=False, account_id="DU1")
    seen_categories: list[str | None] = []
    original_throttle = ib._throttle

    def _capture(category=None):
        seen_categories.append(category)
        return original_throttle(category)

    monkeypatch.setattr(ib, "_throttle", _capture)
    out = ib.get_recent_trades(lookback_seconds := 900)
    assert out == [{"symbol": "AAPL"}]
    assert any(c == "trades" for c in seen_categories)
    trade_calls = [
        item
        for item in ib.client.get_calls  # type: ignore[attr-defined]
        if item[0] == "iserver/account/trades"
    ]
    assert trade_calls[0] == ("iserver/account/trades", {"since": lookback_seconds})
    assert trade_calls[1] == ("iserver/account/trades", None)
