from __future__ import annotations

from types import SimpleNamespace

from tradeexec.settings import AccountConfig
from tradeexec.trade_execution import ExecutionProgram


def test_retrieve_account_values_maintenance_window_downshifts_log_level(monkeypatch, caplog):
    monkeypatch.setattr("tradeexec.trade_execution.is_broker_sentry_quiet_hours", lambda: True)

    ledger_error = RuntimeError(
        "IbkrClient: Reached max retries (3) for GET https://api.ibkr.com/v1/api/portfolio/DU1/ledger {}"
    )

    cfg = AccountConfig(
        account_number="DU1",
        broker_oauth_consumer_key="x",
        broker_oauth_access_token="x",
        broker_oauth_access_token_secret="x",
    )
    prog = ExecutionProgram(cfg)
    prog.broker_ib = SimpleNamespace(
        get_account_summary=lambda: (_ for _ in ()).throw(ledger_error)
    )

    with caplog.at_level("WARNING"):
        vals = prog.retrieve_account_values()

    assert vals == {}
    assert any("maintenance window" in rec.message.lower() for rec in caplog.records)
    assert not any(rec.levelname == "ERROR" for rec in caplog.records)


def test_retrieve_account_values_remote_disconnected_is_treated_as_maintenance(monkeypatch, caplog):
    monkeypatch.setattr("tradeexec.trade_execution.is_broker_sentry_quiet_hours", lambda: True)

    conn_error = RuntimeError(
        "ProtocolError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
    )

    cfg = AccountConfig(
        account_number="DU1",
        broker_oauth_consumer_key="x",
        broker_oauth_access_token="x",
        broker_oauth_access_token_secret="x",
    )
    prog = ExecutionProgram(cfg)
    prog.broker_ib = SimpleNamespace(get_account_summary=lambda: (_ for _ in ()).throw(conn_error))

    with caplog.at_level("WARNING"):
        vals = prog.retrieve_account_values()

    assert vals == {}
    assert any("maintenance window" in rec.message.lower() for rec in caplog.records)
    assert not any(rec.levelname == "ERROR" for rec in caplog.records)


def test_retrieve_account_values_rate_limit_is_treated_as_maintenance(monkeypatch, caplog):
    monkeypatch.setattr("tradeexec.trade_execution.is_broker_sentry_quiet_hours", lambda: True)

    rate_error = RuntimeError("HTTP 429 Too Many Requests from IBKR")

    cfg = AccountConfig(
        account_number="DU1",
        broker_oauth_consumer_key="x",
        broker_oauth_access_token="x",
        broker_oauth_access_token_secret="x",
    )
    prog = ExecutionProgram(cfg)
    prog.broker_ib = SimpleNamespace(get_account_summary=lambda: (_ for _ in ()).throw(rate_error))

    with caplog.at_level("WARNING"):
        vals = prog.retrieve_account_values()

    assert vals == {}
    assert any("maintenance window" in rec.message.lower() for rec in caplog.records)
    assert not any(rec.levelname == "ERROR" for rec in caplog.records)
