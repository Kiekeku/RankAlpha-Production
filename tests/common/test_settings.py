import os

from apps.common.src.settings_base import BaseAppSettings


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_NAME", "db")
    monkeypatch.setenv("DB_USERNAME", "user")
    monkeypatch.setenv("PASSWORD", "pass")
    monkeypatch.setenv("HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")
    

    settings = BaseAppSettings()
    assert settings.database_name == "db"
    assert settings.db_username == "user"
    assert settings.password == "pass"
    assert settings.host == "localhost"
    assert settings.port == 5432
  
