from __future__ import annotations

from newswire import queue_worker


def test_consume_llm_queue_budget_caps_within_window(monkeypatch):
    monkeypatch.setenv("NEWS_LLM_QUEUE_MAX_EVENTS", "2")
    monkeypatch.setenv("NEWS_LLM_QUEUE_WINDOW_SEC", "300")
    queue_worker._LLM_QUEUE_WINDOW_STARTED = 0.0
    queue_worker._LLM_QUEUE_WINDOW_COUNT = 0
    now = 1000.0

    def _mono() -> float:
        return now

    monkeypatch.setattr(queue_worker.time, "monotonic", _mono)
    assert queue_worker._consume_llm_queue_budget() is True
    assert queue_worker._consume_llm_queue_budget() is True
    assert queue_worker._consume_llm_queue_budget() is False


def test_consume_llm_queue_budget_resets_after_window(monkeypatch):
    monkeypatch.setenv("NEWS_LLM_QUEUE_MAX_EVENTS", "1")
    monkeypatch.setenv("NEWS_LLM_QUEUE_WINDOW_SEC", "60")
    queue_worker._LLM_QUEUE_WINDOW_STARTED = 0.0
    queue_worker._LLM_QUEUE_WINDOW_COUNT = 0
    now = 1000.0

    def _mono() -> float:
        return now

    monkeypatch.setattr(queue_worker.time, "monotonic", _mono)
    assert queue_worker._consume_llm_queue_budget() is True
    assert queue_worker._consume_llm_queue_budget() is False
    now = 1061.0
    assert queue_worker._consume_llm_queue_budget() is True
