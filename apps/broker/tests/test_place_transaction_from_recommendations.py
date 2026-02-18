import sys
import types
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta


def _install_stubs_for_recommendations(rec):
    # Stub apps.common.src.models with minimal classes used by code
    models = types.ModuleType("apps.common.src.models")

    class FactTradeRecommendation:  # pragma: no cover (placeholder for isinstance usage)
        pass

    class DimSource:  # pragma: no cover
        source_key = 1

    # Attach a stock attribute shim if missing
    if not hasattr(rec, "stock"):

        class _Stock:
            symbol = getattr(rec, "symbol", "AAPL")

        rec.stock = _Stock()

    models.FactTradeRecommendation = FactTradeRecommendation
    models.DimSource = DimSource
    sys.modules["apps.common.src.models"] = models

    # Stub apps.common.src.crud.upsert_trade_recommendation
    crud = types.ModuleType("apps.common.src.crud")
    calls = {"upserts": []}

    def upsert_trade_recommendation(session, payload):  # pragma: no cover
        calls["upserts"].append(payload)
        return uuid.uuid4()

    crud.upsert_trade_recommendation = upsert_trade_recommendation
    sys.modules["apps.common.src.crud"] = crud

    return calls


def _get_session_stub(rec):
    class QueryStub:
        def __init__(self, result):
            self._result = result

        def join(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return [self._result]

        def update(self, *args, **kwargs):  # fallback path no-op
            return 0

    class SessionStub:
        def query(self, model):
            return QueryStub(rec)

    @contextmanager
    def get_session():
        yield SessionStub()

    return get_session


def test_place_from_recommendation_fixed_shares(monkeypatch):
    # Build a fake recommendation row
    class Rec:
        recommendation_id = uuid.uuid4()
        action = "BUY"
        order_type = "LIMIT"
        recommended_price = 182.5
        limit_price = 182.5
        stop_trigger_price = None
        take_profit_price = None
        stop_loss_price = None
        size_shares = 10
        size_percent = None
        strategy_name = "UnitSystem"
        is_live = False
        valid_from_ts = datetime.now(UTC) - timedelta(minutes=1)
        expiry_ts = None

        class stock:  # noqa
            symbol = "AAPL"

    rec = Rec()
    calls = _install_stubs_for_recommendations(rec)

    from tradeexec.order import place_transaction as m

    # Stub DB session
    monkeypatch.setattr(m, "get_session", _get_session_stub(rec))

    # Stub IB
    placed = {}

    class IBStub:
        def get_positions(self):
            return []

        def get_open_orders(self):
            return []

        def get_available_fund(self):
            return 100000.0

        def get_market_data(self, symbol: str, exchange: str | None = None):
            return {"last": 183.0}

        def place_order(self, position_settings, price_hint=None):
            placed["ps"] = position_settings
            return [1234]

    pt = m.PlaceTransaction(
        ib_interface=IBStub(),
        account_number="DU_TEST",
        allowed_systems=["UnitSystem"],
    )

    # Avoid Telegram confirmation
    monkeypatch.setattr(m.PlaceTransaction, "_confirm", lambda self, t, ps: True)

    # Act
    pt.execute()

    # Assert one order placed with expected size/type
    ps = placed["ps"]
    assert ps.symbol == "AAPL"
    assert ps.size == 10
    assert ps.order_type == "Limit"
    # Upsert called with is_live=True
    assert calls["upserts"], "expected upsert_trade_recommendation to be called"
    assert any(p.get("is_live") is True for p in calls["upserts"])  # type: ignore


def test_place_from_recommendation_percent_sizing(monkeypatch):
    # Build a fake recommendation row (2.5% sizing)
    class Rec:
        recommendation_id = uuid.uuid4()
        action = "BUY"
        order_type = "MARKET"
        recommended_price = 100.0
        limit_price = None
        stop_trigger_price = None
        take_profit_price = None
        stop_loss_price = None
        size_shares = None
        size_percent = 2.5
        strategy_name = "UnitSystem"
        is_live = False
        valid_from_ts = datetime.now(UTC) - timedelta(minutes=1)
        expiry_ts = None

        class stock:  # noqa
            symbol = "MSFT"

    rec = Rec()
    calls = _install_stubs_for_recommendations(rec)

    from tradeexec.order import place_transaction as m

    monkeypatch.setattr(m, "get_session", _get_session_stub(rec))

    placed = {}

    class IBStub:
        def get_positions(self):
            return []

        def get_open_orders(self):
            return []

        def get_available_fund(self):
            return 100000.0  # 100k

        def get_market_data(self, symbol: str, exchange: str | None = None):
            return {"last": rec.recommended_price}

        def place_order(self, position_settings, price_hint=None):
            placed["ps"] = position_settings
            return [4321]

    pt = m.PlaceTransaction(
        ib_interface=IBStub(),
        account_number="DU_TEST",
        allowed_systems=["UnitSystem"],
    )
    monkeypatch.setattr(m.PlaceTransaction, "_confirm", lambda self, t, ps: True)

    pt.execute()

    ps = placed["ps"]
    assert ps.symbol == "MSFT"
    # 2.5% of 100k at $100 ⇒ 25 shares
    assert ps.size == 25
    assert ps.order_type == "Market"
    assert any(p.get("is_live") is True for p in calls["upserts"])  # type: ignore


def test_recommendation_confirm_sees_finalized_params(monkeypatch):
    # Regression: confirm should happen after size/order params are finalized
    class Rec:
        recommendation_id = uuid.uuid4()
        action = "SELL"
        order_type = "LIMIT"
        recommended_price = 182.5
        limit_price = 182.5
        stop_trigger_price = None
        take_profit_price = None
        stop_loss_price = None
        size_shares = 10
        size_percent = None
        strategy_name = "UnitSystem"
        is_live = False
        valid_from_ts = datetime.now(UTC) - timedelta(minutes=1)
        expiry_ts = None

        class stock:  # noqa
            symbol = "AAPL"

    rec = Rec()
    _install_stubs_for_recommendations(rec)

    from tradeexec.order import place_transaction as m

    monkeypatch.setattr(m, "get_session", _get_session_stub(rec))

    placed = {}

    class IBStub:
        def get_positions(self):
            return []

        def get_open_orders(self):
            return []

        def get_available_fund(self):
            return 100000.0

        def get_market_data(self, symbol: str, exchange: str | None = None):
            return {"last": rec.recommended_price}

        def place_order(self, position_settings, price_hint=None):
            placed["ps"] = position_settings
            return [123]

    def _confirm(self, t, ps):
        assert ps.symbol == "AAPL"
        assert ps.size == 10
        assert ps.order_type == "Limit"
        assert ps.limit_price == 182.5
        assert ps.position_type == "Short"
        return True

    pt = m.PlaceTransaction(
        ib_interface=IBStub(),
        account_number="DU_TEST",
        allowed_systems=["UnitSystem"],
    )
    monkeypatch.setattr(m.PlaceTransaction, "_confirm", _confirm)

    pt.execute()
    assert placed["ps"].order_type == "Limit"


def test_place_from_recommendation_stop_sizes_to_position(monkeypatch):
    class Rec:
        recommendation_id = uuid.uuid4()
        action = "SELL"
        order_type = "STOP"
        recommended_price = None
        limit_price = None
        stop_trigger_price = 95.0
        take_profit_price = None
        stop_loss_price = None
        size_shares = None
        size_percent = None
        strategy_name = "UnitSystem"
        is_live = False
        valid_from_ts = datetime.now(UTC) - timedelta(minutes=1)
        expiry_ts = None

        class stock:  # noqa
            symbol = "AAPL"

    rec = Rec()
    _install_stubs_for_recommendations(rec)

    from tradeexec.order import place_transaction as m

    monkeypatch.setattr(m, "get_session", _get_session_stub(rec))

    placed = {}

    class IBStub:
        def get_positions(self):
            return [{"symbol": "AAPL", "position": 12}]

        def get_open_orders(self):
            return []

        def place_order(self, position_settings, price_hint=None):
            placed["ps"] = position_settings
            return [456]

    def _confirm(self, t, ps):
        assert ps.symbol == "AAPL"
        assert ps.order_type == "Stop"
        assert ps.stop_price == 95.0
        # sizes to the live IB position
        assert ps.size == 12
        # long position -> SELL stop
        assert ps.position_type == "Short"
        return True

    pt = m.PlaceTransaction(
        ib_interface=IBStub(),
        account_number="DU_TEST",
        allowed_systems=["UnitSystem"],
    )
    monkeypatch.setattr(m.PlaceTransaction, "_confirm", _confirm)

    pt.execute()
    assert placed["ps"].size == 12


def test_place_from_recommendation_trailing_stop_sizes_to_position(monkeypatch):
    class Rec:
        recommendation_id = uuid.uuid4()
        action = "SELL"
        order_type = "TRAIL"
        recommended_price = None
        limit_price = None
        stop_trigger_price = None
        take_profit_price = None
        stop_loss_price = None
        size_shares = None
        size_percent = None
        strategy_name = "UnitSystem"
        is_live = False
        valid_from_ts = datetime.now(UTC) - timedelta(minutes=1)
        expiry_ts = None
        preconditions = {"trail_percent": 2.5}

        class stock:  # noqa
            symbol = "AAPL"

    rec = Rec()
    _install_stubs_for_recommendations(rec)

    from tradeexec.order import place_transaction as m

    monkeypatch.setattr(m, "get_session", _get_session_stub(rec))

    placed = {}

    class IBStub:
        def get_positions(self):
            return [{"symbol": "AAPL", "position": 12}]

        def get_open_orders(self):
            return []

        def place_order(self, position_settings, price_hint=None):
            placed["ps"] = position_settings
            return [789]

    def _confirm(self, t, ps):
        assert ps.symbol == "AAPL"
        assert ps.order_type == "TrailingStop"
        assert ps.trail_percent == 2.5
        assert ps.size == 12
        assert ps.position_type == "Short"
        return True

    pt = m.PlaceTransaction(
        ib_interface=IBStub(),
        account_number="DU_TEST",
        allowed_systems=["UnitSystem"],
    )
    monkeypatch.setattr(m.PlaceTransaction, "_confirm", _confirm)

    pt.execute()
    assert placed["ps"].size == 12
