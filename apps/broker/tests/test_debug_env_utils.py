from __future__ import annotations

from tradeexec.tools import debug_env


def test_mask_handles_empty_short_and_long_strings():
    assert debug_env.mask("") == ""
    assert debug_env.mask("abc", show=4) == "***"
    assert debug_env.mask("abcd", show=4) == "****"
    assert debug_env.mask("abcdef", show=2).startswith("ab…")


def test_list_env_candidates_filters_account_keys(monkeypatch):
    monkeypatch.setenv("ACCOUNT1_ACCOUNT_NUMBER", "DU123")
    monkeypatch.setenv("ACCOUNT1_BROKER_OAUTH_CONSUMER_KEY", "ck")
    monkeypatch.setenv("ACCOUNT1_BROKER_OAUTH_ACCESS_TOKEN", "at")
    monkeypatch.setenv("ACCOUNT1_OTHER", "nope")
    monkeypatch.setenv("NOTACCOUNT1_BROKER_OAUTH_ACCESS_TOKEN", "nope")

    keys = debug_env.list_env_candidates()
    assert "ACCOUNT1_ACCOUNT_NUMBER" in keys
    assert "ACCOUNT1_BROKER_OAUTH_CONSUMER_KEY" in keys
    assert "ACCOUNT1_BROKER_OAUTH_ACCESS_TOKEN" in keys
    assert "ACCOUNT1_OTHER" not in keys
    assert "NOTACCOUNT1_BROKER_OAUTH_ACCESS_TOKEN" not in keys
