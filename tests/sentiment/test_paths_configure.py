from __future__ import annotations

import pytest

from apps.sentiment.src import paths
from apps.sentiment.src.settings import Settings


@pytest.fixture(autouse=True)
def _base_env(monkeypatch):
    monkeypatch.setenv("DATABASE_NAME", "db")
    monkeypatch.setenv("DB_USERNAME", "user")
    monkeypatch.setenv("PASSWORD", "pass")
    monkeypatch.setenv("HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")


def test_configure_paths_updates_module_globals(tmp_path):
    s = Settings(
        _env_file=None,
        sentiment_data_dir=str(tmp_path / "data"),
        sentiment_output_dir=str(tmp_path / "out"),
        sentiment_schedule_file=str(tmp_path / "sched" / "analysis_schedule.json"),
    )
    data_dir = paths.configure_paths(s)
    assert data_dir == str(tmp_path / "data")
    assert paths.OUTPUT_DIR == str(tmp_path / "out")
    assert str(paths.SCHEDULE_FILE).endswith("analysis_schedule.json")


def test_configure_paths_defaults_to_data_dir(tmp_path):
    s = Settings(_env_file=None, sentiment_data_dir=str(tmp_path))
    paths.configure_paths(s)
    assert paths.OUTPUT_DIR == str(tmp_path / "company_reports")
