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

    # Stub ibind.oauth.oauth1a.OAuth1aConfig
    oauth_mod = types.ModuleType("ibind.oauth.oauth1a")

    class OAuth1aConfig:  # type: ignore
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def verify_config(self) -> None:
            # accept anything in tests
            return

    oauth_mod.OAuth1aConfig = OAuth1aConfig

    # Stub ibind root
    ibind_mod = types.ModuleType("ibind")

    class StubResp:
        def __init__(self, data: Any) -> None:
            self.data = data

    class IbkrClient:  # type: ignore
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.account_id = "TEST"
            self._calls = {"snapshot": 0}

        # Pre-reqs
        def receive_brokerage_accounts(self) -> None:  # pragma: no cover
            return

        def portfolio_accounts(self) -> None:  # pragma: no cover
            return

        # Market data snapshot
        def live_marketdata_snapshot(self, *, conids, fields):  # type: ignore[no-redef]
            self._calls["snapshot"] += 1
            # Return data with required field codes
            data = [
                {
                    "31": "100.0",
                    "55": "99.5",
                    "84": "100.5",
                    "7741": "98.0",
                    "conid": int(conids[0]),
                }
            ]
            return StubResp(data)

        # Generic GET
        def get(self, path: str, params: Dict[str, Any] | None = None):
            if path.endswith("/ledger"):
                return StubResp({"USD": {"cashbalance": 1000.0, "funds": 800.0}})
            if path.endswith("secdef/info"):
                return StubResp([{"symbol": "AAPL"}])
            return StubResp({})

        def post(self, path: str, **kwargs: Any):  # for logout in close()
            return StubResp({"ok": True})

    def StockQuery(
        symbol: str, contract_conditions: Dict[str, Any] | None = None
    ):  # pragma: no cover
        return {"symbol": symbol, "cond": contract_conditions or {}}

    def make_order_request(*args: Any, **kwargs: Any):  # pragma: no cover
        return {"args": args, "kwargs": kwargs}

    class QuestionType:  # pragma: no cover
        pass

    ibind_mod.IbkrClient = IbkrClient
    ibind_mod.StockQuery = StockQuery
    ibind_mod.QuestionType = QuestionType
    ibind_mod.make_order_request = make_order_request

    sys.modules["ibind"] = ibind_mod
    sys.modules["ibind.oauth"] = types.ModuleType("ibind.oauth")
    sys.modules["ibind.oauth.oauth1a"] = oauth_mod

    # Stub tradeexec.settings.settings so importing ib module doesn't require pydantic
    fake_settings_mod = types.ModuleType("tradeexec.settings")

    class _S:  # minimal surface
        ib_account_id = "DUTEST"
        ib_cacert_path = None

        def get_ib_oauth_params(self):  # pragma: no cover
            return {}

    fake_settings_mod.settings = _S()
    sys.modules["tradeexec.settings"] = fake_settings_mod


def test_ib_get_market_data_parses_fields(monkeypatch):
    _install_stub_ibind_and_settings()
    # Import lazily after stubbing
    from tradeexec.core.ib import IBInterfacing

    ib = IBInterfacing(use_global_settings=False)
    out = ib.get_market_data(conid=265598)
    assert out["bid"] == 99.5
    assert out["ask"] == 100.5
    assert out["last"] == 100.0
    assert out["close"] == 98.0
    ib.close()


def test_ib_get_account_summary_and_symbol_lookup():
    _install_stub_ibind_and_settings()
    from tradeexec.core.ib import IBInterfacing

    ib = IBInterfacing(use_global_settings=False, account_id="DU1")
    summary = ib.get_account_summary()
    assert isinstance(summary, dict)
    assert "USD" in summary

    # Contract info path returns list -> first element used
    sym = ib.get_symbol_from_contract_id("123")
    assert sym == "AAPL"
    ib.close()
