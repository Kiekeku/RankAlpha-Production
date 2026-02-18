from contextlib import contextmanager


def test_execute_places_only_after_params_finalized(monkeypatch):
    # Import target module
    from tradeexec.order import place_transaction as m

    # ---- Stub DB session that returns one pending TradeTransaction ----
    class DummyTxn:
        Ticker = "AAPL"
        TradeType = "buy"
        OrderType = "market"
        Price = None
        TransactionDate = None
        Size = None
        SizePercent = 10.0
        System = "UnitTest"
        PositionID = None
        ProfitTargetPercent = None
        StopLossPercent = None
        ExecutionNote = None
        OrderPlaced = None
        OrderPlacedTime = None

    class QueryStub:
        def __init__(self, result):
            self._result = result

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return [self._result]

    class SessionStub:
        def query(self, model):
            return QueryStub(DummyTxn())

        def add(self, obj):
            pass

    @contextmanager
    def get_session_stub():
        yield SessionStub()

    monkeypatch.setattr(m, "get_session", get_session_stub)

    # ---- Stub IB that records place_order calls and enforces size>0 ----
    calls = []

    class IBStub:
        def get_positions(self):
            return []

        def get_open_orders(self):
            return []

        def place_order(self, position_settings, price_hint=None):
            # Assert we never place with zero size
            assert position_settings.size and position_settings.size > 0
            calls.append(
                (position_settings.symbol, position_settings.size, position_settings.order_type)
            )
            return [12345]

    pt = m.PlaceTransaction(ib_interface=IBStub())

    # Avoid unrelated branches
    monkeypatch.setattr(m.PlaceTransaction, "_is_overridden", lambda self, s, t: False)
    monkeypatch.setattr(m.PlaceTransaction, "_expire_stale_order", lambda self, t: False)
    monkeypatch.setattr(m.PlaceTransaction, "_already_live_for_account", lambda self, s, t: False)
    monkeypatch.setattr(m.PlaceTransaction, "_calculate_transaction_size", lambda self, t: 10)
    monkeypatch.setattr(m.PlaceTransaction, "_confirm", lambda self, t, ps: True)

    # Act
    pt.execute()

    # Assert exactly one placement, and it used the computed size
    assert len(calls) == 1
    sym, size, otype = calls[0]
    assert sym == "AAPL"
    assert size == 10
    assert otype.lower() in (
        "market",
        "marketonclose",
        "marketonopen",
        "limit",
        "stop",
        "stoplimit",
        "trailingstop",
    )


def test_execute_prefetched_live_keys_skip_per_row_check(monkeypatch):
    from tradeexec.order import place_transaction as m

    class DummyTxn:
        Ticker = "AAPL"
        TradeType = "buy"
        OrderType = "market"
        Price = None
        TransactionDate = None
        Size = None
        SizePercent = 10.0
        System = "UnitTest"
        PositionID = None
        ProfitTargetPercent = None
        StopLossPercent = None
        ExecutionNote = None
        OrderPlaced = None
        OrderPlacedTime = None

    class QueryStub:
        def __init__(self, result):
            self._result = result

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return [self._result]

    class SessionStub:
        def query(self, model):
            return QueryStub(DummyTxn())

        def add(self, obj):
            pass

    @contextmanager
    def get_session_stub():
        yield SessionStub()

    monkeypatch.setattr(m, "get_session", get_session_stub)

    placed = []

    class IBStub:
        def get_positions(self):
            return []

        def get_open_orders(self):
            return []

        def place_order(self, position_settings, price_hint=None):
            placed.append(position_settings)
            return [111]

    pt = m.PlaceTransaction(ib_interface=IBStub())
    monkeypatch.setattr(m.PlaceTransaction, "_is_overridden", lambda self, s, t: False)
    monkeypatch.setattr(m.PlaceTransaction, "_expire_stale_order", lambda self, t: False)
    monkeypatch.setattr(
        m.PlaceTransaction,
        "_already_live_for_account",
        lambda self, s, t: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    monkeypatch.setattr(
        m.PlaceTransaction,
        "_prefetch_live_recommendation_keys",
        lambda self, s, txns: {(m.date.today(), "AAPL", "BUY")},
    )

    pt.execute()
    assert placed == []


def test_execute_falls_back_to_per_row_live_check_when_prefetch_unavailable(monkeypatch):
    from tradeexec.order import place_transaction as m

    class DummyTxn:
        Ticker = "AAPL"
        TradeType = "buy"
        OrderType = "market"
        Price = None
        TransactionDate = None
        Size = None
        SizePercent = 10.0
        System = "UnitTest"
        PositionID = None
        ProfitTargetPercent = None
        StopLossPercent = None
        ExecutionNote = None
        OrderPlaced = None
        OrderPlacedTime = None

    class QueryStub:
        def __init__(self, result):
            self._result = result

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return [self._result]

    class SessionStub:
        def query(self, model):
            return QueryStub(DummyTxn())

        def add(self, obj):
            pass

    @contextmanager
    def get_session_stub():
        yield SessionStub()

    monkeypatch.setattr(m, "get_session", get_session_stub)

    placed = []

    class IBStub:
        def get_positions(self):
            return []

        def get_open_orders(self):
            return []

        def place_order(self, position_settings, price_hint=None):
            placed.append(position_settings)
            return [111]

    pt = m.PlaceTransaction(ib_interface=IBStub())
    monkeypatch.setattr(m.PlaceTransaction, "_is_overridden", lambda self, s, t: False)
    monkeypatch.setattr(m.PlaceTransaction, "_expire_stale_order", lambda self, t: False)
    monkeypatch.setattr(
        m.PlaceTransaction, "_prefetch_live_recommendation_keys", lambda self, s, txns: None
    )
    calls = {"count": 0}

    def _already_live(self, session, txn):
        calls["count"] += 1
        return True

    monkeypatch.setattr(m.PlaceTransaction, "_already_live_for_account", _already_live)

    pt.execute()
    assert calls["count"] == 1
    assert placed == []
