from apps.api.src.settings import Settings


def test_api_async_logging_defaults_bounded(monkeypatch):
    monkeypatch.setenv("DATABASE_NAME", "rankalpha")
    monkeypatch.setenv("DB_USERNAME", "rankalpha")
    monkeypatch.setenv("PASSWORD", "rankalpha")
    monkeypatch.setenv("HOST", "database")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.delenv("API_ASYNC_LOGGING_ENABLED", raising=False)
    monkeypatch.delenv("ASYNC_LOGGING_ENABLED", raising=False)
    monkeypatch.delenv("API_ASYNC_LOGGING_QUEUE_MAXSIZE", raising=False)
    monkeypatch.delenv("ASYNC_LOGGING_QUEUE_MAXSIZE", raising=False)

    settings = Settings()

    assert settings.api_async_logging_enabled is True
    assert settings.api_async_logging_queue_maxsize == 10000
