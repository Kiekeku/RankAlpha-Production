import sys
import types
from datetime import datetime


def _install_stubs():
    # Some unit tests stub sqlalchemy globally; ensure the minimal surface we need
    # exists so importing fills_ingestor does not fail during collection.
    sa = types.ModuleType("sqlalchemy")

    def select(*args, **kwargs):  # pragma: no cover
        return ("select", args, kwargs)

    def update(*args, **kwargs):  # pragma: no cover
        return ("update", args, kwargs)

    sa.select = select
    sa.update = update
    sys.modules["sqlalchemy"] = sa

    dialects = types.ModuleType("sqlalchemy.dialects")
    postgresql = types.ModuleType("sqlalchemy.dialects.postgresql")

    def insert(*args, **kwargs):  # pragma: no cover
        return ("insert", args, kwargs)

    postgresql.insert = insert
    sys.modules["sqlalchemy.dialects"] = dialects
    sys.modules["sqlalchemy.dialects.postgresql"] = postgresql

    core_ib = types.ModuleType("tradeexec.core.ib")

    class IBInterfacing:  # pragma: no cover
        pass

    core_ib.IBInterfacing = IBInterfacing
    sys.modules["tradeexec.core.ib"] = core_ib

    dbmod = types.ModuleType("tradeexec.database.model")

    def get_session():  # pragma: no cover
        raise RuntimeError("not used in this unit test")

    dbmod.get_session = get_session
    sys.modules["tradeexec.database.model"] = dbmod


def test_parse_when_returns_naive_utc():
    _install_stubs()
    from tradeexec.order.fills_ingestor import FillsIngestor

    fi = FillsIngestor(ib=object(), account_number="DU_TEST")  # type: ignore[arg-type]

    dt = fi._parse_when(None)
    assert isinstance(dt, datetime)
    assert dt.tzinfo is None

    dt = fi._parse_when("2025-01-01T10:00:00Z")
    assert dt.tzinfo is None
    assert dt.isoformat().startswith("2025-01-01T10:00:00")

    dt = fi._parse_when(1735689600000)  # 2025-01-01T00:00:00Z (ms)
    assert dt.tzinfo is None
