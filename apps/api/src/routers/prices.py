from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from apps.api.src.security import (
    AuthUserPrincipal,
    extract_bearer_token,
    get_optional_user_with_db,
    is_internal_bearer_token,
)
from apps.common.src.models import DimStock, VwLatestAdjClose, VwStockPriceHistory

from ..cache import get_json, make_key, set_json
from ..database import get_db
from ..http_client import get_async_client, get_sync_client
from ..services.prices import PriceHistoryCache
from ..settings import Settings
from ..utils.coerce import coerce_float, coerce_positive_float
from ..utils.company import CompanyNameSanitizerMixin
from ..utils.date_range import parse_iso_date_range
from ..utils.settings_cache import make_cached_getter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["prices"], prefix="/api/v1/prices")
price_cache = PriceHistoryCache()
_live_price_prefetch_tasks: Dict[str, asyncio.Task] = {}
_PREFETCH_MIN_TTL_SECONDS = 5
_BROKER_DOWN_KEY = "broker_live_down_v1"
_broker_down_until: float = 0.0
_EASTERN_TZ = ZoneInfo("America/New_York")
_LIVE_PRICE_OUTLIER_RATIO = 4.0
_EXCHANGE_HINT_MAP = {
    "NASDAQ": "NASDAQ",
    "NASDAQ GS": "NASDAQ",
    "NASDAQ GM": "NASDAQ",
    "NASDAQ CM": "NASDAQ",
    "NYSE": "NYSE",
    "NYSE ARCA": "ARCA",
    "ARCA": "ARCA",
    "NYSE AMERICAN": "AMEX",
    "NYSE MKT": "AMEX",
    "AMEX": "AMEX",
    "CBOE BZX": "BATS",
    "BZX": "BATS",
    "BATS": "BATS",
    "OTC": "SMART",
    "OTCQB": "SMART",
    "OTCQX": "SMART",
    "OTCMKTS": "SMART",
    "PINK": "SMART",
    "INDEX": "SMART",
    "UNKNOWN": "SMART",
}


_get_settings = make_cached_getter(lambda: Settings())


class PriceHistoryItem(CompanyNameSanitizerMixin, BaseModel):
    symbol: str
    company_name: Optional[str] = None
    price_date: date
    open_px: Optional[float] = None
    high_px: Optional[float] = None
    low_px: Optional[float] = None
    close_px: Optional[float] = None
    adj_close_px: Optional[float] = None
    volume: Optional[int] = None


class PriceHistoryList(BaseModel):
    items: List[PriceHistoryItem]
    total_count: int
    page: int
    page_size: int


@router.get("/history", response_model=PriceHistoryList)
def get_history(
    symbol: str = Query(..., description="Ticker symbol (e.g., AAPL)"),
    db: Session = Depends(get_db),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    symbol_upper = symbol.upper()
    df, dt = parse_iso_date_range(date_from, date_to)

    head_entry = price_cache.get_head(symbol_upper)
    entry = None
    if head_entry is not None:
        if df is None and dt is None and (skip + limit) <= len(head_entry.items):
            entry = head_entry
        elif df is not None and head_entry.items:
            try:
                oldest_raw = head_entry.items[-1].get("price_date")
                oldest = date.fromisoformat(str(oldest_raw)) if oldest_raw else None
            except ValueError:
                oldest = None
            if oldest is not None and df >= oldest:
                entry = head_entry

    if entry is None:
        entry = price_cache.get(symbol_upper)
    if entry is None:
        entry = price_cache.warm(symbol_upper, session=db)

    if entry is not None:
        # Fast path: no date filters -> don't materialize/parse the full history list.
        if df is None and dt is None:
            total_count = int(entry.total_count or len(entry.items))
            paged_raw = entry.items[skip : skip + limit]
            items: list[PriceHistoryItem] = []
            for raw in paged_raw:
                price_date_raw = raw.get("price_date")
                if not price_date_raw:
                    continue
                try:
                    price_dt = date.fromisoformat(str(price_date_raw))
                except ValueError:
                    continue
                items.append(
                    PriceHistoryItem(
                        symbol=raw.get("symbol", symbol_upper),
                        company_name=raw.get("company_name"),
                        price_date=price_dt,
                        open_px=raw.get("open_px"),
                        high_px=raw.get("high_px"),
                        low_px=raw.get("low_px"),
                        close_px=raw.get("close_px"),
                        adj_close_px=raw.get("adj_close_px"),
                        volume=raw.get("volume"),
                    )
                )
            return PriceHistoryList(
                items=items, total_count=total_count, page=skip // limit + 1, page_size=limit
            )

        # Filtered path: stream results and break early when possible (history is sorted desc).
        matched = 0
        items: list[PriceHistoryItem] = []
        for raw in entry.items:
            price_date_raw = raw.get("price_date")
            if not price_date_raw:
                continue
            try:
                price_dt = date.fromisoformat(str(price_date_raw))
            except ValueError:
                # Skip malformed entries; they will be corrected on next warm
                continue
            if dt and price_dt > dt:
                # Too new: keep scanning until we reach the requested end date.
                continue
            if df and price_dt < df:
                # Too old: since list is desc, we can stop.
                break
            if matched >= skip and len(items) < limit:
                items.append(
                    PriceHistoryItem(
                        symbol=raw.get("symbol", symbol_upper),
                        company_name=raw.get("company_name"),
                        price_date=price_dt,
                        open_px=raw.get("open_px"),
                        high_px=raw.get("high_px"),
                        low_px=raw.get("low_px"),
                        close_px=raw.get("close_px"),
                        adj_close_px=raw.get("adj_close_px"),
                        volume=raw.get("volume"),
                    )
                )
            matched += 1

        return PriceHistoryList(
            items=items, total_count=matched, page=skip // limit + 1, page_size=limit
        )

    # Fallback: cache unavailable; query Postgres directly
    criteria = [VwStockPriceHistory.symbol == symbol_upper]
    if df:
        criteria.append(VwStockPriceHistory.price_date >= df)
    if dt:
        criteria.append(VwStockPriceHistory.price_date <= dt)

    total_count = (
        db.execute(select(func.count()).select_from(VwStockPriceHistory).where(*criteria)).scalar()
        or 0
    )

    rows = (
        db.execute(
            select(VwStockPriceHistory)
            .where(*criteria)
            .order_by(desc(VwStockPriceHistory.price_date))
            .offset(skip)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    items = [
        PriceHistoryItem(
            symbol=r.symbol,
            company_name=getattr(r, "company_name", None),
            price_date=r.price_date,
            open_px=float(r.open_px) if r.open_px is not None else None,
            high_px=float(r.high_px) if r.high_px is not None else None,
            low_px=float(r.low_px) if r.low_px is not None else None,
            close_px=float(r.close_px) if r.close_px is not None else None,
            adj_close_px=float(r.adj_close_px) if r.adj_close_px is not None else None,
            volume=int(r.volume) if r.volume is not None else None,
        )
        for r in rows
    ]
    return PriceHistoryList(
        items=items, total_count=total_count, page=skip // limit + 1, page_size=limit
    )


class LatestAdjItem(CompanyNameSanitizerMixin, BaseModel):
    symbol: str
    company_name: Optional[str] = None
    price_date: date
    close_px: Optional[float] = None
    adj_close_px: Optional[float] = None


class LatestAdjList(BaseModel):
    items: List[LatestAdjItem]
    total_count: int
    page: int
    page_size: int


class LivePrice(BaseModel):
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    close: Optional[float] = None
    change_pct: Optional[float] = None
    account: Optional[str] = None
    is_realtime: Optional[bool] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


def _can_use_broker_live_price(
    principal: AuthUserPrincipal | None,
    settings: Settings,
    *,
    authorization: str | None,
) -> bool:
    """Allow broker fan-out only for authenticated users (or trusted internal tokens)."""
    if principal is not None:
        return True
    token = extract_bearer_token(authorization)
    return is_internal_bearer_token(token, settings)


def _is_broker_quiet_hours(now_et: datetime | None = None) -> bool:
    enabled = (os.getenv("BROKER_SENTRY_QUIET_HOURS_ENABLED") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if not enabled:
        return False
    quiet_weekends = (os.getenv("BROKER_SENTRY_QUIET_WEEKENDS_ET") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    try:
        start_hour = int((os.getenv("BROKER_SENTRY_QUIET_HOURS_START_ET") or "20").strip())
        end_hour = int((os.getenv("BROKER_SENTRY_QUIET_HOURS_END_ET") or "6").strip())
    except Exception:
        start_hour, end_hour = 20, 6
    if start_hour < 0 or start_hour > 23 or end_hour < 0 or end_hour > 23:
        start_hour, end_hour = 20, 6

    now = now_et or datetime.now(tz=_EASTERN_TZ)
    if quiet_weekends and now.weekday() >= 5:
        return True
    hour = int(now.hour)
    if start_hour == 0 and end_hour == 23:
        return True
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _broker_down_ttl(settings: Settings) -> int:
    try:
        return max(int(settings.broker_live_down_ttl_seconds or 0), 0)
    except Exception:
        return 0


def _is_broker_down(settings: Settings) -> bool:
    global _broker_down_until
    ttl = _broker_down_ttl(settings)
    if ttl <= 0:
        return False
    now = time.time()
    if _broker_down_until and now < _broker_down_until:
        return True
    cached = get_json(_BROKER_DOWN_KEY)
    if cached is None:
        return False
    until = cached.get("until") if isinstance(cached, dict) else cached
    try:
        until_f = float(until)
    except (TypeError, ValueError):
        return False
    if now < until_f:
        _broker_down_until = until_f
        return True
    return False


def _mark_broker_down(settings: Settings) -> None:
    ttl = _broker_down_ttl(settings)
    if ttl <= 0:
        return
    until = time.time() + ttl
    global _broker_down_until
    _broker_down_until = until
    set_json(_BROKER_DOWN_KEY, {"until": until}, ttl_secs=ttl)


def _clear_broker_down() -> None:
    global _broker_down_until
    _broker_down_until = 0.0
    set_json(_BROKER_DOWN_KEY, {"until": time.time()}, ttl_secs=1)


def _should_mark_broker_down(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


@router.get("/latest", response_model=LatestAdjList)
def get_latest(
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query(None, description="Filter to a single symbol"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    sort_by: str = Query("symbol", pattern="^(symbol|date)$"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    prefer_live: bool = Query(
        True,
        description="Try broker live price first (symbol-only), fallback to DB.",
    ),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
):
    settings = _get_settings()
    sym = (symbol or "").strip().upper() if symbol else None
    broker_quiet = _is_broker_quiet_hours()
    can_use_broker = _can_use_broker_live_price(principal, settings, authorization=authorization)
    broker_ttl = max(int(getattr(settings, "broker_price_cache_seconds", 0) or 0), 0)
    if can_use_broker and prefer_live and sym and skip == 0 and not broker_quiet:
        broker_key = make_key("px_latest_live_v1", {"symbol": sym})
        if broker_ttl > 0:
            cached_live = get_json(broker_key)
            if isinstance(cached_live, dict):
                try:
                    item = LatestAdjItem(**cached_live)
                except Exception:
                    item = None
                if item is not None:
                    return LatestAdjList(
                        items=[item],
                        total_count=1,
                        page=1,
                        page_size=limit,
                    )
        timeout_seconds = min(float(settings.broker_service_timeout_seconds or 5), 5.0)
        live_item = _try_broker_latest(sym, settings, timeout_seconds=timeout_seconds)
        if live_item:
            if broker_ttl > 0:
                set_json(broker_key, live_item.model_dump(), ttl_secs=broker_ttl)
            return LatestAdjList(
                items=[live_item],
                total_count=1,
                page=1,
                page_size=limit,
            )
    ttl = int(settings.cache_ttl_default or 300)
    key = make_key(
        "px_latest",
        {
            "symbol": (symbol or "").upper(),
            "skip": skip,
            "limit": limit,
            "sort_by": sort_by,
            "sort_order": sort_order,
        },
    )
    cached = get_json(key)
    if cached is not None:
        return cached

    criteria = []
    if symbol:
        criteria.append(VwLatestAdjClose.symbol == symbol.upper())

    order_col = (
        desc(VwLatestAdjClose.price_date)
        if sort_by == "date" and sort_order == "desc"
        else asc(VwLatestAdjClose.price_date)
        if sort_by == "date"
        else desc(VwLatestAdjClose.symbol)
        if sort_order == "desc"
        else asc(VwLatestAdjClose.symbol)
    )

    total_count = (
        db.execute(select(func.count()).select_from(VwLatestAdjClose).where(*criteria)).scalar()
        or 0
    )

    rows = (
        db.execute(
            select(VwLatestAdjClose).where(*criteria).order_by(order_col).offset(skip).limit(limit)
        )
        .scalars()
        .all()
    )
    items = [
        LatestAdjItem(
            symbol=r.symbol,
            company_name=getattr(r, "company_name", None),
            price_date=r.price_date,
            close_px=float(r.close_px) if r.close_px is not None else None,
            adj_close_px=float(r.adj_close_px) if r.adj_close_px is not None else None,
        )
        for r in rows
    ]
    result = LatestAdjList(
        items=items, total_count=total_count, page=skip // limit + 1, page_size=limit
    )
    set_json(key, result.model_dump(), ttl_secs=ttl)
    return result


def _try_broker_latest(
    symbol: str,
    settings: Settings,
    *,
    timeout_seconds: float,
    account: Optional[str] = None,
    exchange: Optional[str] = None,
) -> Optional[LatestAdjItem]:
    if not settings.broker_service_url:
        return None
    service_token = (settings.broker_service_token or "").strip()
    if not service_token:
        return None
    if _is_broker_down(settings):
        return None

    params: Dict[str, str] = {}
    if account:
        params["account"] = account
    if exchange:
        params["exchange"] = exchange

    raw_base = settings.broker_service_url.strip()
    parsed = urlparse(raw_base)
    if not parsed.scheme or not parsed.netloc:
        return None
    url = f"{raw_base.rstrip('/')}/price/{symbol}"

    try:
        client = get_sync_client()
        response = client.get(
            url,
            params=params or None,
            headers={"X-RA-Service-Token": service_token},
            timeout=timeout_seconds,
        )
    except httpx.RequestError as exc:
        logger.warning(
            "[api:/prices/latest] broker request error symbol=%s timeout=%ss error=%s",
            symbol,
            timeout_seconds,
            str(exc),
        )
        _mark_broker_down(settings)
        return None

    if response.status_code != 200:
        logger.info(
            "[api:/prices/latest] broker non-200 status=%s symbol=%s",
            response.status_code,
            symbol,
        )
        if _should_mark_broker_down(response.status_code):
            _mark_broker_down(settings)
        return None

    data = response.json() if response.content else {}
    if not isinstance(data, dict):
        return None
    last_px = coerce_positive_float(data.get("last"))
    close_px = coerce_positive_float(data.get("close"))
    px = last_px or close_px
    if px is None:
        return None
    _clear_broker_down()
    price_date = datetime.now(timezone.utc).date()
    return LatestAdjItem(
        symbol=data.get("symbol", symbol),
        company_name=None,
        price_date=price_date,
        close_px=px,
        adj_close_px=px,
    )


def _latest_close_snapshot(db: Session, symbol: str) -> Optional[Dict[str, Any]]:
    row = (
        db.execute(select(VwLatestAdjClose).where(VwLatestAdjClose.symbol == symbol).limit(1))
        .scalars()
        .first()
    )
    close_val: Optional[float] = None
    price_date = None
    source_label = "close"
    if row:
        adj_close = getattr(row, "adj_close_px", None)
        close_px = getattr(row, "close_px", None)
        if adj_close is not None:
            close_val = float(adj_close)
        elif close_px is not None:
            close_val = float(close_px)
        price_date = getattr(row, "price_date", None)

    cached_val: Optional[float] = None
    cached_date: Optional[str] = None
    try:
        cached_entry = price_cache.get_head(symbol)
        if cached_entry is None:
            cached_entry = price_cache.get(symbol)
        if cached_entry and cached_entry.items:
            for raw in cached_entry.items:
                candidate = raw.get("adj_close_px")
                if candidate is None:
                    candidate = raw.get("close_px")
                candidate = coerce_positive_float(candidate)
                if candidate is None:
                    continue
                cached_val = candidate
                cached_date = raw.get("price_date")
                break
    except Exception:
        cached_val = None
        cached_date = None

    if close_val is None and cached_val is None:
        return None

    if close_val is None and cached_val is not None:
        close_val = cached_val
        source_label = "close-cache"
        price_date = cached_date
    elif close_val is not None and cached_val is not None:
        ratio = max(close_val, cached_val) / min(close_val, cached_val)
        if ratio >= _LIVE_PRICE_OUTLIER_RATIO:
            logger.warning(
                "[api:/prices/live] close mismatch symbol=%s view=%s cache=%s ratio=%.2f",
                symbol,
                close_val,
                cached_val,
                ratio,
            )
            close_val = cached_val
            source_label = "close-cache"
            price_date = cached_date or price_date

    if close_val is None:
        return None

    raw_meta = {
        "source": source_label,
        "price_date": price_date.isoformat()
        if isinstance(price_date, (datetime, date))
        else price_date,
    }
    raw_meta = {k: v for k, v in raw_meta.items() if v is not None}
    return LivePrice(
        symbol=getattr(row, "symbol", symbol) if row else symbol,
        close=close_val,
        last=None,
        account=None,
        is_realtime=False,
        raw=raw_meta,
    ).model_dump()


def _guard_live_price(
    db: Session,
    symbol: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    live_val = coerce_positive_float(payload.get("last") or payload.get("close"))
    if live_val is None:
        return payload
    fallback = _latest_close_snapshot(db, symbol)
    if not fallback:
        return payload
    fallback_val = coerce_positive_float(fallback.get("close"))
    if fallback_val is None:
        return payload
    ratio = max(live_val, fallback_val) / min(live_val, fallback_val)
    if ratio < _LIVE_PRICE_OUTLIER_RATIO:
        return payload
    if payload.get("is_realtime") is True:
        raw = payload.get("raw")
        if not isinstance(raw, dict):
            raw = {}
        raw.update({"fallback_close": fallback_val, "fallback_ratio": ratio})
        payload["raw"] = raw
        logger.warning(
            "[api:/prices/live] outlier detected (realtime passthrough) symbol=%s live=%s fallback=%s ratio=%.2f",
            symbol,
            live_val,
            fallback_val,
            ratio,
        )
        return payload
    logger.warning(
        "[api:/prices/live] outlier detected symbol=%s live=%s fallback=%s ratio=%.2f",
        symbol,
        live_val,
        fallback_val,
        ratio,
    )
    return fallback


def _prefetch_task_key(symbol: str, account: Optional[str], exchange: Optional[str]) -> str:
    return f"{symbol}:{account or ''}:{exchange or ''}"


def _resolve_exchange_hint(
    db: Session,
    symbol: str,
    exchange: Optional[str],
) -> Optional[str]:
    if exchange:
        candidate = _normalize_exchange_hint(exchange)
        return candidate or "SMART"
    if db is None or not hasattr(db, "execute"):
        return "SMART"
    row = (
        db.execute(select(DimStock.exchange).where(DimStock.symbol == symbol).limit(1))
        .scalars()
        .first()
    )
    if row:
        candidate = _normalize_exchange_hint(row)
        if candidate:
            return candidate
    return "SMART"


def _normalize_exchange_hint(exchange: Optional[str]) -> Optional[str]:
    if not exchange:
        return None
    candidate = " ".join(str(exchange).strip().upper().split())
    if not candidate:
        return None
    mapped = _EXCHANGE_HINT_MAP.get(candidate)
    if mapped:
        return mapped
    return candidate


def _cache_live_price(cache_key: str, payload: Dict[str, Any], ttl: int) -> None:
    if ttl <= 0 or not payload:
        return
    normalized = dict(payload)
    # Ensure cached payload explicitly marks realtime to avoid ambiguity/leaks.
    normalized["is_realtime"] = (
        True if normalized.get("is_realtime") is None else bool(normalized.get("is_realtime"))
    )
    set_json(cache_key, normalized, ttl_secs=ttl)
    logger.info(
        "[api:/prices/live] cache set symbol=%s ttl=%s",
        normalized.get("symbol"),
        ttl,
    )


def _cached_is_realtime(payload: Any) -> Optional[bool]:
    if not isinstance(payload, dict):
        return None
    if "is_realtime" not in payload:
        return None
    return bool(payload.get("is_realtime"))


def _schedule_live_price_prefetch(
    symbol: str,
    account: Optional[str],
    exchange: Optional[str],
    settings: Settings,
    cache_key: str,
    ttl: int,
) -> None:
    max_tasks = int(getattr(settings, "prices_live_prefetch_max_tasks", 250) or 0)
    if _is_broker_down(settings) or _is_broker_quiet_hours():
        return
    if max_tasks > 0 and len(_live_price_prefetch_tasks) >= max_tasks:
        logger.warning(
            "[api:/prices/live] prefetch skipped (queue full) symbol=%s account=%s exchange=%s max=%s",
            symbol,
            account or "(default)",
            exchange or "(none)",
            max_tasks,
        )
        return
    task_key = _prefetch_task_key(symbol, account, exchange)
    existing = _live_price_prefetch_tasks.get(task_key)
    if existing and not existing.done():
        return

    async def _runner() -> None:
        try:
            result = await _request_broker_live_price(symbol, account, exchange, settings)
            _cache_live_price(cache_key, result, ttl)
        except HTTPException as exc:
            logger.warning(
                "[api:/prices/live] background fetch failed symbol=%s account=%s exchange=%s status=%s detail=%s",
                symbol,
                account or "(default)",
                exchange or "(none)",
                exc.status_code,
                exc.detail,
            )
        except Exception as exc:
            logger.warning(
                "[api:/prices/live] background fetch error symbol=%s account=%s exchange=%s error=%s",
                symbol,
                account or "(default)",
                exchange or "(none)",
                exc,
            )
        finally:
            _live_price_prefetch_tasks.pop(task_key, None)

    _live_price_prefetch_tasks[task_key] = asyncio.create_task(_runner())


async def _request_broker_live_price(
    symbol: str,
    account: Optional[str],
    exchange: Optional[str],
    settings: Settings,
) -> Dict[str, Any]:
    return await _request_broker_live_price_with_fallback(
        symbol, account, exchange, settings, allow_fallback=True
    )


async def _request_broker_live_price_with_fallback(
    symbol: str,
    account: Optional[str],
    exchange: Optional[str],
    settings: Settings,
    *,
    allow_fallback: bool,
) -> Dict[str, Any]:
    if _is_broker_down(settings) or _is_broker_quiet_hours():
        raise HTTPException(status_code=503, detail="Broker service unavailable")
    params: Dict[str, str] = {}
    if account:
        params["account"] = account
    if exchange:
        params["exchange"] = exchange

    raw_base = settings.broker_service_url.strip()
    parsed = urlparse(raw_base)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(
            status_code=503,
            detail=f"Invalid BROKER_SERVICE_URL: '{raw_base}'. Example: http://broker:8000",
        )
    base_url = raw_base.rstrip("/")
    url = f"{base_url}/price/{symbol}"
    timeout = float(settings.broker_service_timeout_seconds or 4)
    headers: Dict[str, str] = {}
    service_token = (settings.broker_service_token or "").strip()
    if not service_token:
        raise HTTPException(status_code=503, detail="BROKER_SERVICE_TOKEN not configured")
    headers["X-RA-Service-Token"] = service_token
    logger.info(
        "[api:/prices/live] fetch symbol=%s account=%s exchange=%s url=%s timeout=%ss",
        symbol,
        account or "(default)",
        exchange or "(none)",
        url,
        timeout,
    )

    try:
        client = get_async_client()
        response = await client.get(
            url,
            params=params,
            headers=headers or None,
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        logger.warning(
            "[api:/prices/live] broker request error symbol=%s account=%s exchange=%s: %s",
            symbol,
            account or "(default)",
            exchange or "(none)",
            str(exc),
        )
        _mark_broker_down(settings)
        raise HTTPException(status_code=502, detail="Broker service unreachable")

    if response.status_code != 200:
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": response.text or "Broker service error"}

        detail_obj = payload if isinstance(payload, dict) else {"detail": str(payload)}
        status = response.status_code
        logger.warning(
            "[api:/prices/live] broker non-200 status=%s symbol=%s account=%s exchange=%s detail=%s",
            response.status_code,
            symbol,
            account or "(default)",
            exchange or "(none)",
            detail_obj,
        )
        if status == 404 and allow_fallback and exchange and exchange.strip().upper() != "SMART":
            logger.info(
                "[api:/prices/live] retrying with SMART exchange symbol=%s account=%s exchange=%s",
                symbol,
                account or "(default)",
                exchange,
            )
            return await _request_broker_live_price_with_fallback(
                symbol,
                account,
                None,
                settings,
                allow_fallback=False,
            )
        if _should_mark_broker_down(response.status_code):
            _mark_broker_down(settings)
        if status >= 500:
            status = 502
        raise HTTPException(status_code=status, detail=detail_obj.get("detail", detail_obj))

    data = response.json()
    try:
        raw_preview = list((data.get("raw") or {}).keys())[:12] if isinstance(data, dict) else []
        logger.info(
            "[api:/prices/live] broker 200 symbol=%s account=%s keys=%s",
            symbol,
            account or "(default)",
            raw_preview,
        )
    except Exception:
        pass

    raw_payload = data.get("raw") if isinstance(data, dict) else {}
    _clear_broker_down()
    result = LivePrice(
        symbol=data.get("symbol", symbol),
        bid=coerce_float(data.get("bid")),
        ask=coerce_float(data.get("ask")),
        last=coerce_float(data.get("last")),
        close=coerce_float(data.get("close")),
        change_pct=coerce_float(data.get("change_pct") or data.get("83")),
        account=data.get("account") or account,
        is_realtime=True,
        raw=raw_payload if isinstance(raw_payload, dict) else {},
    ).model_dump()
    return result


@router.get("/live/{symbol}", response_model=LivePrice)
async def get_live_price(
    symbol: str,
    account: Optional[str] = Query(
        None, description="Override broker account (defaults to first configured)"
    ),
    exchange: Optional[str] = Query(None, description="Optional exchange hint for contract lookup"),
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
):
    settings = _get_settings()
    sym = symbol.upper()
    exchange_hint = _resolve_exchange_hint(db, sym, exchange)
    cfg_ttl = max(int(settings.broker_price_cache_seconds or 0), 0)
    broker_quiet = _is_broker_quiet_hours()
    can_use_broker = _can_use_broker_live_price(principal, settings, authorization=authorization)
    cache_key = make_key(
        "live_price", {"symbol": sym, "account": account or "", "exchange": exchange_hint or ""}
    )
    cached = get_json(cache_key)
    cached_is_rt = _cached_is_realtime(cached)
    if isinstance(cached, dict) and (can_use_broker or cached_is_rt is False):
        logger.info(
            "[api:/prices/live] cache hit symbol=%s account=%s exchange=%s",
            sym,
            account or "(default)",
            exchange_hint or "(none)",
        )
        if cached_is_rt is False:
            return cached
        guarded = _guard_live_price(db, sym, cached)
        if guarded is not cached:
            _cache_live_price(cache_key, guarded, cfg_ttl)
            return guarded
        if can_use_broker and cached_is_rt is None:
            return {**cached, "is_realtime": True}
        return cached

    fallback = _latest_close_snapshot(db, sym)
    if fallback:
        if (
            can_use_broker
            and settings.broker_service_url
            and (getattr(settings, "broker_service_token", None) or "")
            and not broker_quiet
        ):
            prefetch_ttl = cfg_ttl if cfg_ttl > 0 else _PREFETCH_MIN_TTL_SECONDS
            _schedule_live_price_prefetch(
                sym, account, exchange_hint, settings, cache_key, prefetch_ttl
            )
        return fallback

    if broker_quiet:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker service unavailable during quiet hours",
        )

    if not can_use_broker:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for realtime quotes",
        )

    if not settings.broker_service_url:
        raise HTTPException(status_code=503, detail="Broker service URL not configured")

    result = await _request_broker_live_price(sym, account, exchange_hint, settings)
    guarded = _guard_live_price(db, sym, result)
    _cache_live_price(cache_key, guarded, cfg_ttl)
    return guarded
