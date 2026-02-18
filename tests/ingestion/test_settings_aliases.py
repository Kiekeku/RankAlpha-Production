from __future__ import annotations

import pytest
from apps.ingestion.src.settings import Settings


@pytest.fixture(autouse=True)
def _base_env(monkeypatch):
    monkeypatch.setenv("DATABASE_NAME", "db")
    monkeypatch.setenv("DB_USERNAME", "user")
    monkeypatch.setenv("PASSWORD", "pass")
    monkeypatch.setenv("HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")


def test_ingestion_settings_alias_choices_for_broker_service(monkeypatch):
    monkeypatch.setenv("INGESTION_BROKER_SERVICE_URL", "http://broker:8000")
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "auth-token")
    s = Settings()
    assert s.broker_service_url == "http://broker:8000"
    # AUTH_SERVICE_TOKEN is accepted for both fields by design
    assert s.broker_service_token == "auth-token"
    assert s.auth_service_token == "auth-token"


def test_ingestion_settings_broker_token_prefers_explicit_broker_token(monkeypatch):
    monkeypatch.setenv("BROKER_SERVICE_TOKEN", "broker-token")
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "auth-token")
    s = Settings()
    assert s.broker_service_token == "broker-token"
    assert s.auth_service_token == "auth-token"
    assert s.ingestion_symbol_success_min_ratio == 0.85
