from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from redis.exceptions import RedisError
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from apps.api.src.cache import _get_client as get_redis_client
from apps.api.src.database import SessionLocal
from apps.api.src.settings import Settings
from apps.api.src.utils.cache_codec import (
    deserialize_compressed_json,
    serialize_compressed_json,
)
from apps.common.src.models import DimDate, DimStock, FactSecurityPrice
from apps.common.src.observability import (
    get_or_create_counter,
    get_or_create_histogram,
)

PRICE_CACHE_HITS = get_or_create_counter(
    "price_history_cache_hits_total",
    "Number of price history cache hits",
)
PRICE_CACHE_MISSES = get_or_create_counter(
    "price_history_cache_misses_total",
    "Number of price history cache misses",
)
PRICE_CACHE_WARMS = get_or_create_counter(
    "price_history_cache_warm_total",
    "Number of price history warm operations",
)
PRICE_CACHE_WARM_FAILURES = get_or_create_counter(
    "price_history_cache_warm_failures_total",
    "Number of price history warm failures",
)
PRICE_CACHE_WARM_SECONDS = get_or_create_histogram(
    "price_history_cache_warm_seconds",
    "Duration of price history warm operations (seconds)",
    buckets=(
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    ),
)


@dataclass(slots=True)
class PriceHistoryCacheEntry:
    symbol: str
    items: list[dict[str, Any]]
    total_count: int
    last_trade_date: Optional[str]
    refreshed_at: str
    etag: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "items": self.items,
            "total_count": self.total_count,
            "last_trade_date": self.last_trade_date,
            "refreshed_at": self.refreshed_at,
            "etag": self.etag,
        }


def _iso_utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class PriceHistoryCache:
    """Read-through cache for full symbol price history payloads.

    - Stores payloads in Redis using gzip'd JSON encoded via base64 strings.
    - Persists a companion metadata key with a lightweight ETag hash and timestamps.
    - Warm operations can be triggered eagerly (admin endpoint/ingestion) or lazily.
    """

    def __init__(self, *, ttl_seconds: Optional[int] = None) -> None:
        settings = Settings()
        default_ttl = int(getattr(settings, "price_history_cache_ttl_seconds", None) or 26 * 3600)
        self.ttl_seconds = int(ttl_seconds or default_ttl)
        self.meta_ttl_seconds = max(self.ttl_seconds, 26 * 3600)
        self.head_items = max(
            0,
            min(
                int(getattr(settings, "price_history_cache_head_items", None) or 800),
                5000,
            ),
        )

    @staticmethod
    def _payload_key(symbol: str) -> str:
        return f"prices:history:{symbol.upper()}"

    @staticmethod
    def _head_key(symbol: str) -> str:
        return f"prices:history:head:{symbol.upper()}"

    @staticmethod
    def _meta_key(symbol: str) -> str:
        return f"prices:history:meta:{symbol.upper()}"

    @staticmethod
    def _serialize(payload: dict[str, Any]) -> str:
        return serialize_compressed_json(payload)

    @staticmethod
    def _deserialize(raw: str) -> dict[str, Any]:
        return deserialize_compressed_json(raw)

    def get(self, symbol: str) -> Optional[PriceHistoryCacheEntry]:
        key = self._payload_key(symbol)
        try:
            client = get_redis_client()
            raw = client.get(key)
        except (RedisError, ConnectionError, OSError):
            PRICE_CACHE_MISSES.inc()
            return None

        if not raw:
            PRICE_CACHE_MISSES.inc()
            return None

        try:
            payload = self._deserialize(raw)
            items_raw = payload.get("items", [])
            entry = PriceHistoryCacheEntry(
                symbol=payload.get("symbol", symbol.upper()),
                items=items_raw if isinstance(items_raw, list) else list(items_raw or []),
                total_count=int(payload.get("total_count", 0) or 0),
                last_trade_date=payload.get("last_trade_date"),
                refreshed_at=payload.get("refreshed_at", ""),
                etag=payload.get("etag"),
            )
            PRICE_CACHE_HITS.inc()
            return entry
        except Exception:
            PRICE_CACHE_WARM_FAILURES.inc()
            return None

    def get_head(self, symbol: str) -> Optional[PriceHistoryCacheEntry]:
        """Return a truncated "recent history" entry to reduce JSON decode overhead.

        Intended for the common /api/v1/prices/history case with skip=0 and no date filters.
        """
        if self.head_items <= 0:
            return None
        key = self._head_key(symbol)
        try:
            client = get_redis_client()
            raw = client.get(key)
        except (RedisError, ConnectionError, OSError):
            PRICE_CACHE_MISSES.inc()
            return None

        if not raw:
            PRICE_CACHE_MISSES.inc()
            return None

        try:
            payload = self._deserialize(raw)
            items_raw = payload.get("items", [])
            entry = PriceHistoryCacheEntry(
                symbol=payload.get("symbol", symbol.upper()),
                items=items_raw if isinstance(items_raw, list) else list(items_raw or []),
                total_count=int(payload.get("total_count", 0) or 0),
                last_trade_date=payload.get("last_trade_date"),
                refreshed_at=payload.get("refreshed_at", ""),
                etag=payload.get("etag"),
            )
            PRICE_CACHE_HITS.inc()
            return entry
        except Exception:
            PRICE_CACHE_WARM_FAILURES.inc()
            return None

    def warm(
        self, symbol: str, *, session: Session | None = None, force: bool = False
    ) -> Optional[PriceHistoryCacheEntry]:
        """Fetch symbol history from Postgres and store it in Redis."""
        PRICE_CACHE_WARMS.inc()
        start = datetime.utcnow()
        local_session: Session | None = None
        try:
            db = session
            if db is None:
                local_session = SessionLocal()
                db = local_session

            latest_trf = func.first_value(FactSecurityPrice.total_return_factor).over(
                partition_by=FactSecurityPrice.stock_key,
                order_by=FactSecurityPrice.date_key.desc(),
            )
            adjusted_close = case(
                (
                    (FactSecurityPrice.total_return_factor.isnot(None))
                    & (FactSecurityPrice.total_return_factor > 0),
                    func.round(
                        FactSecurityPrice.close_px
                        * latest_trf
                        / FactSecurityPrice.total_return_factor,
                        4,
                    ),
                ),
                else_=FactSecurityPrice.close_px,
            )

            stmt = (
                select(
                    DimStock.symbol,
                    DimStock.company_name,
                    DimDate.full_date.label("price_date"),
                    FactSecurityPrice.open_px,
                    FactSecurityPrice.high_px,
                    FactSecurityPrice.low_px,
                    FactSecurityPrice.close_px,
                    adjusted_close.label("adj_close_px"),
                    FactSecurityPrice.volume,
                )
                .join(DimStock, DimStock.stock_key == FactSecurityPrice.stock_key)
                .join(DimDate, DimDate.date_key == FactSecurityPrice.date_key)
                .where(DimStock.symbol == symbol.upper())
                .order_by(DimDate.full_date.desc())
            )
            rows = db.execute(stmt).all()
            items: list[dict[str, Any]] = []
            last_date: Optional[str] = None
            for row in rows:
                price_date = row.price_date.isoformat() if row.price_date else None
                if last_date is None and price_date:
                    last_date = price_date
                items.append(
                    {
                        "symbol": row.symbol,
                        "company_name": row.company_name,
                        "price_date": price_date,
                        "open_px": float(row.open_px) if row.open_px is not None else None,
                        "high_px": float(row.high_px) if row.high_px is not None else None,
                        "low_px": float(row.low_px) if row.low_px is not None else None,
                        "close_px": float(row.close_px) if row.close_px is not None else None,
                        "adj_close_px": float(row.adj_close_px)
                        if row.adj_close_px is not None
                        else None,
                        "volume": int(row.volume) if row.volume is not None else None,
                    }
                )

            refreshed_at = _iso_utc_now()
            etag_source = f"{symbol.upper()}:{last_date}:{len(items)}"
            etag = hashlib.sha1(etag_source.encode("utf-8")).hexdigest()
            payload = PriceHistoryCacheEntry(
                symbol=symbol.upper(),
                items=items,
                total_count=len(items),
                last_trade_date=last_date,
                refreshed_at=refreshed_at,
                etag=etag,
            )

            if items or force:
                client = get_redis_client()
                serialized = self._serialize(payload.to_dict())
                head_payload = payload.to_dict()
                if self.head_items > 0:
                    head_payload["items"] = items[: self.head_items]
                    serialized_head = self._serialize(head_payload)
                meta = json.dumps(
                    {
                        "symbol": payload.symbol,
                        "last_trade_date": payload.last_trade_date,
                        "refreshed_at": payload.refreshed_at,
                        "etag": payload.etag,
                        "items": payload.total_count,
                    },
                    default=str,
                )
                pipe = client.pipeline(transaction=False)
                pipe.setex(self._payload_key(symbol), self.ttl_seconds, serialized)
                if self.head_items > 0:
                    pipe.setex(self._head_key(symbol), self.ttl_seconds, serialized_head)
                else:
                    pipe.delete(self._head_key(symbol))
                pipe.setex(self._meta_key(symbol), self.meta_ttl_seconds, meta)
                pipe.execute()
            return payload
        except Exception:
            PRICE_CACHE_WARM_FAILURES.inc()
            return None
        finally:
            duration = (datetime.utcnow() - start).total_seconds()
            PRICE_CACHE_WARM_SECONDS.observe(duration)
            if local_session is not None:
                local_session.close()

    def warm_many(
        self, symbols: Sequence[str], *, session: Session | None = None, force: bool = False
    ) -> dict[str, bool]:
        """Warm multiple symbols sequentially. Returns per-symbol success map."""
        results: dict[str, bool] = {}
        for sym in symbols:
            entry = self.warm(sym, session=session, force=force)
            results[sym.upper()] = bool(entry)
        return results
