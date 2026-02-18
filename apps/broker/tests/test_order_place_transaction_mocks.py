import sys
import types


def _install_stubs_for_place_transaction():
    # Stub tradeexec.core.ib module to avoid importing heavy deps
    core_ib = types.ModuleType("tradeexec.core.ib")

    class IBInterfacing:  # pragma: no cover - only for import typing
        pass

    core_ib.IBInterfacing = IBInterfacing
    sys.modules["tradeexec.core.ib"] = core_ib

    # Stub sqlalchemy symbols used by module import
    sa = types.ModuleType("sqlalchemy")

    def and_(*args, **kwargs):  # pragma: no cover
        return ("AND", args)

    def or_(*args, **kwargs):  # pragma: no cover
        return ("OR", args)

    sa.and_ = and_
    sa.or_ = or_
    sys.modules["sqlalchemy"] = sa

    # Stub database model to satisfy imports, though not used in this test
    dbmod = types.ModuleType("tradeexec.database.model")

    class TradeTransaction:  # pragma: no cover
        pass

    class SystemTransaction:  # pragma: no cover
        pass

    class Portfolio:  # pragma: no cover
        pass

    class TradeExecutionAudit:  # pragma: no cover
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def get_session():  # pragma: no cover
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield object()

        return _cm()

    dbmod.TradeTransaction = TradeTransaction
    dbmod.SystemTransaction = SystemTransaction
    dbmod.Portfolio = Portfolio
    dbmod.TradeExecutionAudit = TradeExecutionAudit
    dbmod.get_session = get_session
    sys.modules["tradeexec.database.model"] = dbmod


def test_maybe_optimize_limit_long():
    _install_stubs_for_place_transaction()
    from tradeexec.order.place_transaction import PlaceTransaction, PositionSettings

    class StubIB:
        def get_market_data(self, symbol: str, exchange: str | None = None):
            # bid/ask with 1.0 spread -> quarter = 0.25
            return {"bid": 100.0, "ask": 101.0}

    pt = PlaceTransaction(ib_interface=StubIB(), optimize_price=True)
    ps = PositionSettings(symbol="AAPL", size=1, position_type="Long", order_type="Limit")
    pt._maybe_optimize_limit(ps)
    # For Long, target = max(bid, min(ps.limit or mid, mid - quarter)) => max(100, min(None->mid, 100.5-0.25=100.25))=100.25
    assert abs(ps.limit_price - 100.25) < 1e-6


def test_maybe_optimize_limit_short():
    _install_stubs_for_place_transaction()
    from tradeexec.order.place_transaction import PlaceTransaction, PositionSettings

    class StubIB:
        def get_market_data(self, symbol: str, exchange: str | None = None):
            return {"bid": 200.0, "ask": 202.0}

    pt = PlaceTransaction(ib_interface=StubIB(), optimize_price=True)
    ps = PositionSettings(symbol="MSFT", size=1, position_type="Short", order_type="Limit")
    pt._maybe_optimize_limit(ps)
    # For Short, target = min(ask, max(ps.limit or mid, mid + quarter)) = min(202, max(mid, mid+0.5)) = mid+0.5
    assert abs(ps.limit_price - ((200.0 + 202.0) / 2 + 0.5)) < 1e-6
