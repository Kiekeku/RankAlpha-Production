# tradeexec/events.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class RealTimeSignal:
    account: str  # IB account number (e.g. DU-changeme)
    symbol: str
    action: str  # 'buy' | 'sell' | 'exit'
    quantity: Optional[int] = None
    order_type: str = "MKT"  # 'MKT' | 'LMT' | 'STP' | 'MOC'
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    system: Optional[str] = None
    tag: Optional[str] = None
    custom_string: Optional[str] = None


class SignalBus:
    """In‑memory per‑account async queues. Keep it simple and fast."""

    def __init__(self) -> None:
        self._queues: Dict[str, asyncio.Queue[RealTimeSignal]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, account: str) -> asyncio.Queue[RealTimeSignal]:
        async with self._lock:
            q = self._queues.get(account)
            if q is None:
                q = asyncio.Queue()
                self._queues[account] = q
            return q

    async def publish(self, signal: RealTimeSignal) -> None:
        async with self._lock:
            q = self._queues.get(signal.account)
            if q is None:
                q = asyncio.Queue()
                self._queues[signal.account] = q
            await q.put(signal)
