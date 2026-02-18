from __future__ import annotations

from tradeexec.utils import pacing


def test_coerce_seconds_handles_none_invalid_and_negative():
    assert pacing._coerce_seconds(None, 5.0) == 5.0
    assert pacing._coerce_seconds("bad", 5.0) == 5.0
    assert pacing._coerce_seconds(-1.0, 5.0) == 0.0


def test_order_pacer_paces_and_updates_last_submit(monkeypatch):
    now = 10.0
    slept: list[float] = []

    def fake_monotonic() -> float:
        return now

    def fake_sleep(seconds: float) -> None:
        nonlocal now
        slept.append(seconds)
        now += float(seconds)

    monkeypatch.setattr(pacing.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(pacing.time, "sleep", fake_sleep)

    pacer = pacing.OrderPacer(seconds=5.0)

    pacer.pace()  # first submit should not sleep (last_submit=0)
    assert slept == []

    now = 12.0
    pacer.pace()
    assert slept and abs(slept[-1] - 3.0) < 1e-6


def test_order_pacer_zero_seconds_is_noop(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(pacing.time, "sleep", lambda s: slept.append(s))
    pacer = pacing.OrderPacer(seconds=0.0)
    pacer.pace()
    assert slept == []
