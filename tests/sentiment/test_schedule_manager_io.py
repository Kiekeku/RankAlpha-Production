from __future__ import annotations

from datetime import date

from apps.sentiment.src import schedule_manager as sm


def test_save_and_load_schedule_round_trips_dates(tmp_path):
    f = tmp_path / "analysis_schedule.json"
    schedule = {
        "1": {"company_name": "Acme", "symbol": "ACME", "analysis_dates": [date(2025, 1, 1)]}
    }
    sm.save_schedule(f, schedule)
    loaded = sm.load_schedule(f)
    assert loaded["1"]["analysis_dates"] == [date(2025, 1, 1)]


def test_save_schedule_deduplicates_dates(tmp_path):
    f = tmp_path / "analysis_schedule.json"
    schedule = {
        "1": {
            "company_name": "Acme",
            "symbol": "ACME",
            "analysis_dates": [date(2025, 1, 2), date(2025, 1, 2), date(2025, 1, 1)],
        }
    }
    sm.save_schedule(f, schedule)
    loaded = sm.load_schedule(f)
    assert loaded["1"]["analysis_dates"] == [date(2025, 1, 1), date(2025, 1, 2)]


def test_clean_schedule_removes_duplicates_and_persists(tmp_path):
    f = tmp_path / "analysis_schedule.json"
    sm.save_schedule(
        f,
        {"1": {"company_name": "Acme", "symbol": "ACME", "analysis_dates": [date(2025, 1, 1), date(2025, 1, 1)]}},
    )
    cleaned = sm.clean_schedule(f)
    assert cleaned["1"]["analysis_dates"] == [date(2025, 1, 1)]
    reloaded = sm.load_schedule(f)
    assert reloaded["1"]["analysis_dates"] == [date(2025, 1, 1)]


def test_remove_date_from_schedule_is_idempotent(tmp_path):
    f = tmp_path / "analysis_schedule.json"
    sm.save_schedule(
        f,
        {"1": {"company_name": "Acme", "symbol": "ACME", "analysis_dates": [date(2025, 1, 1), date(2025, 1, 2)]}},
    )
    sm.remove_date_from_schedule(f, "1", date(2025, 1, 1))
    sm.remove_date_from_schedule(f, "1", date(2025, 1, 1))
    loaded = sm.load_schedule(f)
    assert loaded["1"]["analysis_dates"] == [date(2025, 1, 2)]


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):  # pragma: no cover - no-op for test cursor
        return None

    def fetchall(self):
        return self._rows


def test_update_schedule_with_catalysts_gracefully_handles_bad_schedule_json(tmp_path):
    f = tmp_path / "analysis_schedule.json"
    f.write_text("{bad json", encoding="utf-8")
    cursor = _Cursor(rows=[(date(2025, 1, 10),)])

    out = sm.update_schedule_with_catalysts(
        schedule_file=f,
        stock_key="1",
        company_name="Acme",
        symbol="ACME",
        analysis_id="a1",
        cursor=cursor,
    )
    assert out == 0


def test_update_schedule_with_catalysts_gracefully_handles_lock_errors(tmp_path, monkeypatch):
    f = tmp_path / "analysis_schedule.json"
    cursor = _Cursor(rows=[(date(2025, 1, 10),)])

    def _raise_lock(_path):
        raise OSError("lock failure")

    monkeypatch.setattr(sm, "_schedule_lock", _raise_lock)
    out = sm.update_schedule_with_catalysts(
        schedule_file=f,
        stock_key="1",
        company_name="Acme",
        symbol="ACME",
        analysis_id="a1",
        cursor=cursor,
    )
    assert out == 0
