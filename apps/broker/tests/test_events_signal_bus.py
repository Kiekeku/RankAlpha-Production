import asyncio

import pytest
from tradeexec.events import RealTimeSignal, SignalBus


@pytest.mark.asyncio
async def test_subscribe_creates_distinct_queues():
    bus = SignalBus()
    q1 = await bus.subscribe("DU111")
    q2 = await bus.subscribe("DU222")
    assert q1 is not q2


@pytest.mark.asyncio
async def test_publish_delivers_to_account_queue():
    bus = SignalBus()
    q = await bus.subscribe("DU123")

    sig = RealTimeSignal(account="DU123", symbol="AAPL", action="buy", quantity=10)
    await bus.publish(sig)

    got = await asyncio.wait_for(q.get(), timeout=1)
    assert got == sig


@pytest.mark.asyncio
async def test_publish_multiple_fifo_order():
    bus = SignalBus()
    q = await bus.subscribe("DU999")

    s1 = RealTimeSignal(account="DU999", symbol="MSFT", action="buy", quantity=1)
    s2 = RealTimeSignal(account="DU999", symbol="MSFT", action="sell", quantity=1)

    await bus.publish(s1)
    await bus.publish(s2)

    g1 = await asyncio.wait_for(q.get(), timeout=1)
    g2 = await asyncio.wait_for(q.get(), timeout=1)
    assert [g1, g2] == [s1, s2]
