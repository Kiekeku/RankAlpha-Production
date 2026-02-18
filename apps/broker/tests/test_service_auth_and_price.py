from __future__ import annotations

import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException


def _import_service(monkeypatch):
    # Avoid OTLP socket probes during import-time instrumentation.
    import apps.common.src.observability as obs

    monkeypatch.setattr(obs, "instrument_fastapi_app", lambda *_a, **_k: None)
    # Some tests stub these modules in sys.modules; ensure `tradeexec.service`
    # imports with a predictable surface area.
    sys.modules.pop("tradeexec.settings", None)
    sys.modules.pop("tradeexec.reports.daily", None)

    # Keep service import lightweight and network-free.
    import types

    daily_mod = types.ModuleType("tradeexec.reports.daily")

    class DailyReport:  # type: ignore
        def __init__(self, *args, **kwargs) -> None:  # pragma: no cover
            return

        def email_report(self) -> None:  # pragma: no cover
            return

    daily_mod.DailyReport = DailyReport
    sys.modules["tradeexec.reports.daily"] = daily_mod

    sys.modules.pop("tradeexec.service", None)
    from tradeexec import service  # noqa: PLC0415 (import inside helper)

    return service


def test_extract_bearer(monkeypatch):
    service = _import_service(monkeypatch)

    assert service._extract_bearer(None) is None
    assert service._extract_bearer("Basic abc") is None
    assert service._extract_bearer("Bearer  ") is None
    assert service._extract_bearer("Bearer test") == "test"


@pytest.mark.asyncio
async def test_require_service_token_errors(monkeypatch):
    service = _import_service(monkeypatch)

    monkeypatch.setattr(service.settings, "service_token", None, raising=False)
    with pytest.raises(HTTPException) as exc:
        await service._require_service_token(authorization=None, service_token_header=None)
    assert exc.value.status_code == 503

    monkeypatch.setattr(service.settings, "service_token", "t", raising=False)
    with pytest.raises(HTTPException) as exc:
        await service._require_service_token(authorization=None, service_token_header=None)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        await service._require_service_token(
            authorization="Bearer wrong", service_token_header=None
        )
    assert exc.value.status_code == 401

    await service._require_service_token(authorization=None, service_token_header="t")


def test_ttl_cache_expires(monkeypatch):
    service = _import_service(monkeypatch)

    now = 0.0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr(service.time, "monotonic", fake_monotonic)
    cache = service._TTLCache(ttl_seconds=1.0)
    cache.set(("k",), "v")
    assert cache.get(("k",)) == "v"

    now = 1.01
    assert cache.get(("k",)) is None


@pytest.mark.asyncio
async def test_health_endpoint(monkeypatch):
    service = _import_service(monkeypatch)

    async def to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(service, "_probe_ib_connection", lambda _prog: (True, None))

    dummy_prog = SimpleNamespace(is_running=True)
    monkeypatch.setattr(service, "programs", {"DU1": dummy_prog})
    monkeypatch.setattr(
        service,
        "account_status",
        {"DU1": service.Status(account="DU1", executing=True)},
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=service.app), base_url="http://test"
    ) as client:
        res = await client.get("/health?probe=true")
    assert res.status_code == 200
    payload = res.json()
    assert payload["DU1"]["ib_connected"] is True


@pytest.mark.asyncio
async def test_price_endpoint_maps_fields(monkeypatch):
    service = _import_service(monkeypatch)

    async def to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(service.settings, "service_token", "token", raising=False)

    dummy_prog = SimpleNamespace(
        account_config=SimpleNamespace(account_number="DU1"),
        market_ib=object(),
        broker_ib=None,
    )
    monkeypatch.setattr(service, "programs", {"DU1": dummy_prog})

    def fake_fetch(_prog, _symbol, _exchange):
        return {"55": "99.5", "84": "100.5", "31": "100.0", "86": "98.0", "83": "0.12"}

    monkeypatch.setattr(service, "_fetch_snapshot_with_program", fake_fetch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=service.app), base_url="http://test"
    ) as client:
        res = await client.get("/price/AAPL", headers={"X-RA-Service-Token": "token"})
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "AAPL"
    assert data["bid"] == 99.5
    assert data["ask"] == 100.5
    assert data["last"] == 100.0
    assert data["close"] == 98.0
    assert data["change_pct"] == 0.12


@pytest.mark.asyncio
async def test_price_endpoint_no_contracts_returns_404(monkeypatch):
    service = _import_service(monkeypatch)

    async def to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(service.settings, "service_token", "token", raising=False)

    dummy_prog = SimpleNamespace(
        account_config=SimpleNamespace(account_number="DU1"),
        market_ib=None,
        broker_ib=None,
    )
    monkeypatch.setattr(service, "programs", {"DU1": dummy_prog})

    def fake_fetch(_prog, _symbol, _exchange):
        raise RuntimeError("no contracts found")

    monkeypatch.setattr(service, "_fetch_snapshot_with_program", fake_fetch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=service.app), base_url="http://test"
    ) as client:
        res = await client.get("/price/NOPE", headers={"X-RA-Service-Token": "token"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_price_endpoint_no_contracts_returns_404_without_exception(monkeypatch, caplog):
    service = _import_service(monkeypatch)

    async def to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(service.settings, "service_token", "token", raising=False)

    dummy_prog = SimpleNamespace(
        account_config=SimpleNamespace(account_number="DU1"),
        market_ib=None,
        broker_ib=None,
    )
    monkeypatch.setattr(service, "programs", {"DU1": dummy_prog})

    def fake_fetch(_prog, _symbol, _exchange):
        raise RuntimeError("No contracts found for PBR-A.")

    monkeypatch.setattr(service, "_fetch_snapshot_with_program", fake_fetch)

    with caplog.at_level("INFO"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=service.app), base_url="http://test"
        ) as client:
            res = await client.get("/price/PBR-A", headers={"X-RA-Service-Token": "token"})
    assert res.status_code == 404
    assert res.json()["detail"] == "Symbol not found"
    assert not any(rec.levelname == "ERROR" for rec in caplog.records)


@pytest.mark.asyncio
async def test_price_endpoint_quiet_hours_suppresses_maintenance_exception(monkeypatch, caplog):
    service = _import_service(monkeypatch)

    async def to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(service.settings, "service_token", "token", raising=False)
    monkeypatch.setenv("BROKER_SENTRY_QUIET_HOURS_ENABLED", "true")
    monkeypatch.setenv("BROKER_SENTRY_QUIET_HOURS_START_ET", "0")
    monkeypatch.setenv("BROKER_SENTRY_QUIET_HOURS_END_ET", "23")

    dummy_prog = SimpleNamespace(
        account_config=SimpleNamespace(account_number="DU1"),
        market_ib=None,
        broker_ib=None,
    )
    monkeypatch.setattr(service, "programs", {"DU1": dummy_prog})

    def fake_fetch(_prog, _symbol, _exchange):
        raise RuntimeError(
            "ProtocolError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
        )

    monkeypatch.setattr(service, "_fetch_snapshot_with_program", fake_fetch)

    with caplog.at_level("WARNING"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=service.app), base_url="http://test"
        ) as client:
            res = await client.get("/price/AAPL", headers={"X-RA-Service-Token": "token"})

    assert res.status_code == 502
    assert res.json()["detail"] == "Snapshot price request failed"
    assert not any(rec.levelname == "ERROR" for rec in caplog.records)


@pytest.mark.asyncio
async def test_prev_close_endpoint_no_value_returns_502(monkeypatch):
    service = _import_service(monkeypatch)

    async def to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(service.settings, "service_token", "token", raising=False)

    dummy_prog = SimpleNamespace(
        account_config=SimpleNamespace(account_number="DU1"),
        market_ib=None,
        broker_ib=None,
    )
    monkeypatch.setattr(service, "programs", {"DU1": dummy_prog})

    def fake_prev_close(*_a, **_k):
        return (None, None, {}, "snapshot")

    monkeypatch.setattr(service, "_fetch_prev_close_with_program", fake_prev_close)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=service.app), base_url="http://test"
    ) as client:
        res = await client.get("/price/prev-close/AAPL", headers={"X-RA-Service-Token": "token"})
    assert res.status_code == 502


@pytest.mark.asyncio
async def test_prev_close_endpoint_no_contracts_suppressed(monkeypatch, caplog):
    service = _import_service(monkeypatch)

    async def to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(service.settings, "service_token", "token", raising=False)

    dummy_prog = SimpleNamespace(
        account_config=SimpleNamespace(account_number="DU1"),
        market_ib=None,
        broker_ib=None,
    )
    monkeypatch.setattr(service, "programs", {"DU1": dummy_prog})

    def fake_prev_close(*_a, **_k):
        raise RuntimeError("No contracts found for AGRI.")

    monkeypatch.setattr(service, "_fetch_prev_close_with_program", fake_prev_close)

    with caplog.at_level("INFO"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=service.app), base_url="http://test"
        ) as client:
            res = await client.get(
                "/price/prev-close/AGRI", headers={"X-RA-Service-Token": "token"}
            )
    assert res.status_code == 502
    assert res.json()["detail"] == "Previous close request failed"
    assert not any(rec.levelname == "ERROR" for rec in caplog.records)


@pytest.mark.asyncio
async def test_prev_close_endpoint_quiet_hours_suppresses_exception(monkeypatch):
    service = _import_service(monkeypatch)

    async def to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(service.settings, "service_token", "token", raising=False)
    monkeypatch.setenv("BROKER_SENTRY_QUIET_HOURS_ENABLED", "true")
    # Make every hour "quiet" for the test.
    monkeypatch.setenv("BROKER_SENTRY_QUIET_HOURS_START_ET", "0")
    monkeypatch.setenv("BROKER_SENTRY_QUIET_HOURS_END_ET", "23")

    dummy_prog = SimpleNamespace(
        account_config=SimpleNamespace(account_number="DU1"),
        market_ib=None,
        broker_ib=None,
    )
    monkeypatch.setattr(service, "programs", {"DU1": dummy_prog})

    def fake_prev_close(*_a, **_k):
        raise RuntimeError("No contracts found for AGRI.")

    monkeypatch.setattr(service, "_fetch_prev_close_with_program", fake_prev_close)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=service.app), base_url="http://test"
    ) as client:
        res = await client.get("/price/prev-close/AGRI", headers={"X-RA-Service-Token": "token"})
    assert res.status_code == 502
    assert res.json()["detail"] == "Previous close request failed"


def test_service_helpers_parsers(monkeypatch):
    service = _import_service(monkeypatch)

    assert service._parse_year_month("2025-12-01") == (2025, 12)
    assert service._parse_year_month("202512") == (2025, 12)
    assert service._parse_year_month("bad") == (None, None)

    assert service._normalize_sec_type(None) == "STK"
    assert service._normalize_sec_type("stock") == "STK"
    assert service._normalize_sec_type("futures") == "FUT"
    assert service._normalize_sec_type("forex") == "CASH"


def test_prev_close_quiet_hours_weekends(monkeypatch):
    service = _import_service(monkeypatch)

    monkeypatch.setenv("BROKER_SENTRY_QUIET_HOURS_ENABLED", "true")
    monkeypatch.setenv("BROKER_SENTRY_QUIET_HOURS_START_ET", "20")
    monkeypatch.setenv("BROKER_SENTRY_QUIET_HOURS_END_ET", "6")
    monkeypatch.setenv("BROKER_SENTRY_QUIET_WEEKENDS_ET", "true")

    et = service.ZoneInfo("America/New_York")
    saturday_noon = service.datetime(2026, 1, 3, 12, 0, tzinfo=et)
    assert service._is_prev_close_sentry_quiet_hours(saturday_noon) is True


def test_resolve_account_program(monkeypatch):
    service = _import_service(monkeypatch)

    monkeypatch.setattr(service, "programs", {})
    with pytest.raises(HTTPException) as exc:
        service._resolve_account_program(None)
    assert exc.value.status_code == 503

    prog = SimpleNamespace()
    monkeypatch.setattr(service, "programs", {"DU1": prog})
    account, resolved = service._resolve_account_program(None)
    assert account == "DU1"
    assert resolved is prog

    with pytest.raises(HTTPException) as exc:
        service._resolve_account_program("UNKNOWN")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_price_endpoint_sec_type_reuses_prev_close_snapshot(monkeypatch):
    service = _import_service(monkeypatch)

    async def to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    class _FailIfCalled:
        def get_market_data(self, **_kwargs):
            raise AssertionError("unexpected fallback get_market_data call")

    monkeypatch.setattr(service.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(service.settings, "service_token", "token", raising=False)
    dummy_prog = SimpleNamespace(
        account_config=SimpleNamespace(account_number="DU1"),
        market_ib=_FailIfCalled(),
        broker_ib=None,
    )
    monkeypatch.setattr(service, "programs", {"DU1": dummy_prog})

    def fake_prev_close(*_a, **_k):
        return (95.0, None, {"31": "96.5", "86": "95.0"}, "snapshot")

    monkeypatch.setattr(service, "_fetch_prev_close_with_program", fake_prev_close)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=service.app), base_url="http://test"
    ) as client:
        res = await client.get(
            "/price/SR3?sec_type=FUT",
            headers={"X-RA-Service-Token": "token"},
        )

    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "SR3"
    assert data["last"] == 96.5
    assert data["close"] == 95.0
