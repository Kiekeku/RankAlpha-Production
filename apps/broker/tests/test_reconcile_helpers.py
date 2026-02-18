import sys
import types


def _install_stub_core_ib():
    mod = types.ModuleType("tradeexec.core.ib")

    class IBInterfacing:  # pragma: no cover - only for type hints
        pass

    mod.IBInterfacing = IBInterfacing
    sys.modules["tradeexec.core.ib"] = mod
    # Minimal sqlalchemy stub to satisfy module import
    if "sqlalchemy" not in sys.modules:
        sa = types.ModuleType("sqlalchemy")
        sys.modules["sqlalchemy"] = sa
    # Minimal DB model stubs to avoid importing real SQLAlchemy
    dbmod = types.ModuleType("tradeexec.database.model")

    class TradeTransaction:  # pragma: no cover
        pass

    class SystemRunStatus:  # pragma: no cover
        pass

    class SystemTransaction:  # pragma: no cover
        pass

    class Portfolio:  # pragma: no cover
        pass

    def get_session():  # pragma: no cover
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield object()

        return _cm()

    dbmod.TradeTransaction = TradeTransaction
    dbmod.SystemRunStatus = SystemRunStatus
    dbmod.SystemTransaction = SystemTransaction
    dbmod.Portfolio = Portfolio
    dbmod.get_session = get_session
    sys.modules["tradeexec.database.model"] = dbmod


def test_extract_order_info_variants():
    _install_stub_core_ib()
    from tradeexec.order.reconcile_positions import ReconcilePosition

    # Basic flattened order
    o1 = {"ticker": "AAPL", "action": "buy", "orderType": "LMT"}
    assert ReconcilePosition._extract_order_info(o1) == ("AAPL", "Buy", "LMT")

    # Nested contract/order
    o2 = {"contract": {"symbol": "MSFT"}, "order": {"side": "sell", "type": "MKT"}}
    assert ReconcilePosition._extract_order_info(o2) == ("MSFT", "Sell", "MKT")


def test_extract_position_info_variants():
    _install_stub_core_ib()
    from tradeexec.order.reconcile_positions import ReconcilePosition

    p1 = {"symbol": "AAPL", "position": 10, "avgCost": 123.45, "secType": "STK"}
    assert ReconcilePosition._extract_position_info(p1) == ("AAPL", 10.0, 123.45, "STK")

    p2 = {"ticker": "MSFT", "pos": -5, "avg_price": 250.0, "securityType": "ETF"}
    assert ReconcilePosition._extract_position_info(p2) == ("MSFT", -5.0, 250.0, "ETF")
