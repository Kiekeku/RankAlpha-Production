from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, condecimal, constr
from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from apps.api.src.database import get_db
from apps.api.src.http_client import get_sync_client
from apps.api.src.security.dependencies import require_admin_access
from apps.api.src.settings import Settings
from apps.common.src.crud import get_or_create_stock_any, get_trade_recommendations_view
from apps.common.src.models import (
    DimDate,
    DimStock,
    FactPortfolioBrokerNlv,
    FactPortfolioNav,
    FactPortfolioPositionAttribution,
    FactPortfolioPositionHist,
    FactSecurityPrice,
    Portfolio,
    PortfolioCashPosition,
    PortfolioDeployment,
    PortfolioOrderIntent,
    PortfolioPosition,
    PortfolioRun,
)
from apps.common.src.portfolio.construction import (
    approve_run,
    create_portfolio_run,
    evaluate_run_risk,
    get_or_create_deployment,
    get_or_create_portfolio,
    set_order_approval,
    upsert_order_intents,
)
from apps.common.src.portfolio.fx import FXConfig, fx_mid_px

router = APIRouter(
    tags=["portfolio"],
    prefix="/api/v1/portfolio",
    dependencies=[Depends(require_admin_access)],
)

_settings = Settings()

PercentType = condecimal(max_digits=6, decimal_places=2, ge=0, le=100)
AllocationPercentType = condecimal(max_digits=6, decimal_places=2, ge=0, le=9999.99)
WeightType = condecimal(max_digits=12, decimal_places=6)
QtyType = condecimal(max_digits=20, decimal_places=4)


def _normalize_service_token(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return ""
    return t[7:].strip() if t.lower().startswith("bearer ") else t


class PortfolioItem(BaseModel):
    portfolio_id: UUID
    portfolio_name: str
    portfolio_kind: str
    currency_code: str
    broker_name: Optional[str] = None
    broker_account_id: Optional[str] = None
    is_public: bool
    is_visible: bool
    portfolio_owner_id: Optional[int] = None
    description: Optional[str] = None


class CreatePortfolioRequest(BaseModel):
    portfolio_name: constr(strip_whitespace=True, min_length=1, max_length=50)
    portfolio_kind: Literal["BROKER", "MODEL", "SLEEVE"]
    currency_code: constr(strip_whitespace=True, min_length=3, max_length=3) = "USD"
    broker_name: Optional[constr(strip_whitespace=True, max_length=32)] = None
    broker_account_id: Optional[constr(strip_whitespace=True, max_length=64)] = None
    is_public: Optional[bool] = None
    is_visible: Optional[bool] = None
    portfolio_owner_id: Optional[int] = None
    description: Optional[str] = None


class CreatePortfolioResponse(BaseModel):
    portfolio_id: UUID


class TradeRecommendationItem(BaseModel):
    recommendation_id: UUID
    recommendation_date: date
    symbol: str
    source_name: str
    source_version: Optional[str] = None
    action: str
    recommended_price: Optional[float] = None
    order_type: Optional[str] = None
    time_in_force: Optional[str] = None
    limit_price: Optional[float] = None
    stop_trigger_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    size_shares: Optional[int] = None
    size_percent: Optional[float] = None
    strategy_name: Optional[str] = None
    is_live: Optional[bool] = None
    create_ts: Optional[datetime] = None


@router.get(
    "/trade-recommendations",
    response_model=List[TradeRecommendationItem],
)
def list_trade_recommendations(
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query(None),
    since: Optional[date] = Query(None),
    is_live: Optional[bool] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
):
    rows = get_trade_recommendations_view(db, symbol=symbol, since=since, is_live=is_live)
    rows = rows[:limit]
    return [
        TradeRecommendationItem(
            recommendation_id=r.recommendation_id,
            recommendation_date=r.recommendation_date,
            symbol=str(r.symbol),
            source_name=str(r.source_name),
            source_version=str(getattr(r, "source_version", "") or "") or None,
            action=str(r.action),
            recommended_price=float(r.recommended_price)
            if r.recommended_price is not None
            else None,
            order_type=str(getattr(r, "order_type", "") or "") or None,
            time_in_force=str(getattr(r, "time_in_force", "") or "") or None,
            limit_price=float(r.limit_price) if r.limit_price is not None else None,
            stop_trigger_price=float(r.stop_trigger_price)
            if r.stop_trigger_price is not None
            else None,
            stop_loss_price=float(r.stop_loss_price) if r.stop_loss_price is not None else None,
            take_profit_price=float(r.take_profit_price)
            if r.take_profit_price is not None
            else None,
            size_shares=int(r.size_shares) if r.size_shares is not None else None,
            size_percent=float(r.size_percent) if r.size_percent is not None else None,
            strategy_name=str(getattr(r, "strategy_name", "") or "") or None,
            is_live=bool(r.is_live) if r.is_live is not None else None,
            create_ts=r.create_ts,
        )
        for r in rows
    ]


@router.get("/portfolios", response_model=List[PortfolioItem])
def list_portfolios(
    db: Session = Depends(get_db),
    kind: Optional[str] = Query(None, description="Filter by portfolio_kind (BROKER|MODEL|SLEEVE)"),
):
    q = select(Portfolio)
    if kind:
        q = q.where(Portfolio.portfolio_kind == kind.strip().upper())
    q = q.order_by(Portfolio.portfolio_kind.asc(), Portfolio.portfolio_name.asc())
    rows = db.scalars(q).all()
    return [
        PortfolioItem(
            portfolio_id=r.portfolio_id,
            portfolio_name=r.portfolio_name,
            portfolio_kind=str(r.portfolio_kind),
            currency_code=r.currency_code,
            broker_name=getattr(r, "broker_name", None),
            broker_account_id=getattr(r, "broker_account_id", None),
            is_public=bool(getattr(r, "is_public", False)),
            is_visible=bool(getattr(r, "is_visible", False)),
            portfolio_owner_id=getattr(r, "portfolio_owner_id", None),
            description=r.description,
        )
        for r in rows
    ]


@router.post(
    "/portfolios",
    response_model=CreatePortfolioResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_portfolio(
    payload: CreatePortfolioRequest,
    db: Session = Depends(get_db),
):
    is_public = payload.is_public
    is_visible = payload.is_visible
    owner_id = payload.portfolio_owner_id
    kind = payload.portfolio_kind.strip().upper()

    if is_visible is True and is_public is None:
        is_public = True

    if is_public is True and kind != "MODEL":
        raise HTTPException(
            status_code=422, detail="is_public portfolios must have portfolio_kind=MODEL"
        )
    if is_visible is True and is_public is not True:
        raise HTTPException(status_code=422, detail="is_visible requires is_public=true")
    if is_public is True and owner_id is not None:
        raise HTTPException(
            status_code=422, detail="Public portfolios cannot set portfolio_owner_id"
        )

    with db.begin():
        pid = get_or_create_portfolio(
            db,
            portfolio_name=payload.portfolio_name,
            portfolio_kind=kind,
            currency_code=payload.currency_code,
            broker_name=payload.broker_name,
            broker_account_id=payload.broker_account_id,
            is_public=is_public,
            is_visible=is_visible,
            portfolio_owner_id=owner_id,
            description=payload.description,
        )
    return CreatePortfolioResponse(portfolio_id=pid)


class UpdatePortfolioRequest(BaseModel):
    portfolio_name: Optional[constr(strip_whitespace=True, min_length=1, max_length=50)] = None
    currency_code: Optional[constr(strip_whitespace=True, min_length=3, max_length=3)] = None
    broker_name: Optional[constr(strip_whitespace=True, max_length=32)] = None
    broker_account_id: Optional[constr(strip_whitespace=True, max_length=64)] = None
    is_public: Optional[bool] = None
    is_visible: Optional[bool] = None
    portfolio_owner_id: Optional[int] = None
    description: Optional[str] = None


@router.patch("/portfolios/{portfolio_id}", response_model=PortfolioItem)
def update_portfolio(
    portfolio_id: UUID,
    payload: UpdatePortfolioRequest,
    db: Session = Depends(get_db),
):
    with db.begin():
        p = db.get(Portfolio, portfolio_id)
        if p is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        if payload.portfolio_name is not None:
            p.portfolio_name = payload.portfolio_name
        if payload.currency_code is not None:
            p.currency_code = payload.currency_code.upper()
        if payload.broker_name is not None:
            p.broker_name = payload.broker_name
        if payload.broker_account_id is not None:
            p.broker_account_id = payload.broker_account_id
        if payload.description is not None:
            p.description = payload.description

        kind = str(getattr(p, "portfolio_kind", "")).upper()
        next_public = bool(p.is_public) if payload.is_public is None else bool(payload.is_public)
        next_visible = (
            bool(p.is_visible) if payload.is_visible is None else bool(payload.is_visible)
        )
        next_owner_id = (
            getattr(p, "portfolio_owner_id", None)
            if payload.portfolio_owner_id is None
            else payload.portfolio_owner_id
        )

        if next_visible and not next_public:
            raise HTTPException(status_code=422, detail="is_visible requires is_public=true")
        if next_public and kind != "MODEL":
            raise HTTPException(
                status_code=422, detail="Only MODEL portfolios can be public/visible"
            )
        if next_public:
            next_owner_id = None

        p.is_public = next_public
        p.is_visible = next_visible
        p.portfolio_owner_id = next_owner_id

        # Ensure p has any DB defaults applied before we serialize.
        db.flush()
        db.refresh(p)
    return PortfolioItem(
        portfolio_id=p.portfolio_id,
        portfolio_name=p.portfolio_name,
        portfolio_kind=str(p.portfolio_kind),
        currency_code=p.currency_code,
        broker_name=getattr(p, "broker_name", None),
        broker_account_id=getattr(p, "broker_account_id", None),
        is_public=bool(p.is_public),
        is_visible=bool(p.is_visible),
        portfolio_owner_id=getattr(p, "portfolio_owner_id", None),
        description=p.description,
    )


class UpsertBrokerNlvRequest(BaseModel):
    as_of_date: date
    nlv_base_ccy: float = Field(..., ge=0)
    gross_leverage: Optional[float] = None
    currency_code: Optional[constr(strip_whitespace=True, min_length=3, max_length=3)] = None
    source_system: Optional[constr(strip_whitespace=True, min_length=1, max_length=64)] = None


class UpsertBrokerNlvResponse(BaseModel):
    ok: bool
    date_key: int
    portfolio_id: UUID


class IngestBrokerFillsRequest(BaseModel):
    portfolio_id: Optional[UUID] = None
    broker_account_id: Optional[str] = None
    lookback_seconds: int = Field(default=36 * 3600, ge=60, le=7 * 24 * 3600)


class IngestBrokerFillsResponse(BaseModel):
    ok: bool
    lookback_seconds: int
    portfolios_processed: int
    fills_inserted: int
    inserted_by_account: Dict[str, int] = Field(default_factory=dict)


@router.post(
    "/portfolios/{portfolio_id}/broker-nlv",
    response_model=UpsertBrokerNlvResponse,
    status_code=status.HTTP_201_CREATED,
)
def upsert_broker_nlv(
    portfolio_id: UUID,
    payload: UpsertBrokerNlvRequest,
    db: Session = Depends(get_db),
):
    # Must begin before *any* DB access; SQLAlchemy 2.x autobegins on first use.
    with db.begin():
        p = db.get(Portfolio, portfolio_id)
        if p is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        if str(getattr(p, "portfolio_kind", "")).upper() != "BROKER":
            raise HTTPException(
                status_code=422, detail="broker-nlv can only be set for BROKER portfolios"
            )

        date_key = db.scalar(
            select(DimDate.date_key).where(DimDate.full_date == payload.as_of_date)
        )
        if date_key is None:
            raise HTTPException(status_code=422, detail="as_of_date not found in dim_date")

        currency_code = (
            payload.currency_code or getattr(p, "currency_code", "USD") or "USD"
        ).upper()
        stmt = (
            insert(FactPortfolioBrokerNlv)
            .values(
                date_key=int(date_key),
                portfolio_id=portfolio_id,
                currency_code=currency_code,
                nlv_base_ccy=float(payload.nlv_base_ccy),
                gross_leverage=payload.gross_leverage,
                source_system=payload.source_system,
            )
            .on_conflict_do_update(
                index_elements=[
                    FactPortfolioBrokerNlv.date_key,
                    FactPortfolioBrokerNlv.portfolio_id,
                ],
                set_={
                    "currency_code": currency_code,
                    "nlv_base_ccy": float(payload.nlv_base_ccy),
                    "gross_leverage": payload.gross_leverage,
                    "source_system": payload.source_system,
                    "load_ts": func.now(),
                },
            )
        )
        db.execute(stmt)
    return UpsertBrokerNlvResponse(ok=True, date_key=int(date_key), portfolio_id=portfolio_id)


@router.post(
    "/broker-fills/ingest",
    response_model=IngestBrokerFillsResponse,
)
def ingest_broker_fills(
    payload: IngestBrokerFillsRequest,
    db: Session = Depends(get_db),
):
    """Trigger fill ingestion on the broker service (writes to `fact_portfolio_trade`).

    Orchestration lives in the API to keep a single entry point while avoiding any broker->API write calls.
    """
    if not _settings.broker_service_url:
        raise HTTPException(status_code=503, detail="BROKER_SERVICE_URL not configured")
    service_token = _normalize_service_token(_settings.broker_service_token or "")
    if not service_token:
        raise HTTPException(status_code=503, detail="BROKER_SERVICE_TOKEN not configured")

    q = select(Portfolio).where(Portfolio.portfolio_kind == "BROKER")
    if payload.portfolio_id:
        q = q.where(Portfolio.portfolio_id == payload.portfolio_id)
    if payload.broker_account_id:
        q = q.where(Portfolio.broker_account_id == payload.broker_account_id)
    q = q.where(Portfolio.broker_account_id.is_not(None))
    portfolios = list(db.scalars(q).all())
    if not portfolios:
        return IngestBrokerFillsResponse(
            ok=True,
            lookback_seconds=int(payload.lookback_seconds),
            portfolios_processed=0,
            fills_inserted=0,
            inserted_by_account={},
        )

    base_url = _settings.broker_service_url.strip().rstrip("/")
    headers = {"X-RA-Service-Token": service_token}
    timeout = float(_settings.broker_service_timeout_seconds or 4)
    client = get_sync_client()

    inserted_by_account: dict[str, int] = {}
    fills_inserted = 0
    portfolios_with_account = [
        p for p in portfolios if str(getattr(p, "broker_account_id", "") or "").strip()
    ]
    portfolios_processed = len(portfolios_with_account)

    accounts = sorted(
        {
            str(getattr(p, "broker_account_id", "") or "").strip()
            for p in portfolios_with_account
            if p is not None
        }
    )
    for account in accounts:
        if not account:
            continue
        try:
            resp = client.post(
                f"{base_url}/fills/ingest/{account}",
                headers=headers,
                timeout=timeout,
                json={"lookback_seconds": int(payload.lookback_seconds)},
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Broker fills ingest request failed for {account}: {type(exc).__name__}: {exc}",
            ) from exc
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Broker fills ingest failed for {account}: {resp.status_code} {resp.text[:200]}",
            )
        data = resp.json() if resp.content else {}
        try:
            inserted = int(data.get("inserted") or 0)
        except Exception:
            inserted = 0
        inserted_by_account[account] = int(inserted_by_account.get(account, 0)) + inserted
        fills_inserted += inserted

    return IngestBrokerFillsResponse(
        ok=True,
        lookback_seconds=int(payload.lookback_seconds),
        portfolios_processed=portfolios_processed,
        fills_inserted=fills_inserted,
        inserted_by_account=inserted_by_account,
    )


class SyncBrokerHoldingsRequest(BaseModel):
    as_of_date: Optional[date] = None
    portfolio_id: Optional[UUID] = None
    broker_account_id: Optional[str] = None
    dry_run: bool = False


class SyncBrokerHoldingsResponse(BaseModel):
    ok: bool
    as_of_date: date
    synced_portfolios: int
    synced_positions: int
    synced_cash_rows: int
    missing_symbols: List[str] = Field(default_factory=list)


def _latest_trading_day_before(db: Session, *, before: date) -> date:
    d = db.scalar(
        select(DimDate.full_date)
        .where(DimDate.full_date < before)
        .where(DimDate.is_trading_day.is_(True))
        .order_by(DimDate.full_date.desc())
        .limit(1)
    )
    if d is None:
        raise HTTPException(status_code=422, detail="Unable to resolve previous trading day")
    return d


def _fx_mid_px(
    db: Session,
    *,
    date_key: int,
    from_ccy: str,
    to_ccy: str,
    fallback_to_last_available: bool = True,
    cache: dict[tuple[int, str, str, str, int, bool], Decimal | None] | None = None,
) -> float | None:
    px = fx_mid_px(
        db,
        date_key=int(date_key),
        from_ccy=from_ccy,
        to_ccy=to_ccy,
        cfg=FXConfig(
            pivot_ccy="USD",
            max_lookback_days=30,
            fallback_to_last_available=bool(fallback_to_last_available),
        ),
        cache=cache,
    )
    if px is None:
        return None
    try:
        return float(px)
    except Exception:
        return None


@router.post(
    "/broker-holdings/sync",
    response_model=SyncBrokerHoldingsResponse,
)
def sync_broker_holdings(
    payload: SyncBrokerHoldingsRequest,
    db: Session = Depends(get_db),
):
    """Fetch broker holdings from the broker service and persist to `portfolio_position`/cash + history."""
    if not _settings.broker_service_url:
        raise HTTPException(status_code=503, detail="BROKER_SERVICE_URL not configured")
    service_token = _normalize_service_token(_settings.broker_service_token or "")
    if not service_token:
        raise HTTPException(status_code=503, detail="BROKER_SERVICE_TOKEN not configured")

    as_of = payload.as_of_date or _latest_trading_day_before(db, before=date.today())
    date_key = db.scalar(select(DimDate.date_key).where(DimDate.full_date == as_of))
    if date_key is None:
        raise HTTPException(status_code=422, detail="as_of_date not found in dim_date")

    q = select(Portfolio).where(Portfolio.portfolio_kind == "BROKER")
    if payload.portfolio_id:
        q = q.where(Portfolio.portfolio_id == payload.portfolio_id)
    if payload.broker_account_id:
        q = q.where(Portfolio.broker_account_id == payload.broker_account_id)
    q = q.where(Portfolio.broker_account_id.is_not(None))
    portfolios = list(db.scalars(q).all())
    if not portfolios:
        return SyncBrokerHoldingsResponse(
            ok=True,
            as_of_date=as_of,
            synced_portfolios=0,
            synced_positions=0,
            synced_cash_rows=0,
            missing_symbols=[],
        )

    base_url = _settings.broker_service_url.strip().rstrip("/")
    headers = {"X-RA-Service-Token": service_token}
    timeout = float(_settings.broker_service_timeout_seconds or 4)
    client = get_sync_client()

    synced_portfolios = 0
    synced_positions = 0
    synced_cash_rows = 0
    missing_symbols: set[str] = set()
    snapshot_cache: dict[str, dict] = {}

    for p in portfolios:
        account = str(getattr(p, "broker_account_id", "") or "").strip()
        if not account:
            continue
        if account not in snapshot_cache:
            try:
                resp = client.get(
                    f"{base_url}/snapshot/{account}", headers=headers, timeout=timeout
                )
            except httpx.RequestError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Broker snapshot request failed for {account}: {type(exc).__name__}: {exc}",
                ) from exc
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Broker snapshot failed for {account}: {resp.status_code} {resp.text[:200]}",
                )
            snapshot_cache[account] = resp.json() if resp.content else {}
        data = snapshot_cache.get(account) or {}

        positions = data.get("positions") or []
        cash_by_ccy = data.get("cash_by_ccy") or {}

        stock_key_by_symbol: dict[str, int] = {}
        portfolio_missing_symbols: set[str] = set()
        symbols: set[str] = set()
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            sym = str(pos.get("symbol") or "").upper().strip()
            if sym:
                symbols.add(sym)
        if symbols:
            rows = db.execute(
                select(DimStock.symbol, DimStock.stock_key).where(
                    DimStock.symbol.in_(sorted(symbols))
                )
            ).all()
            stock_key_by_symbol = {str(sym).upper(): int(k) for sym, k in rows}

        existing = db.execute(
            select(
                PortfolioPosition.stock_key, PortfolioPosition.quantity, PortfolioPosition.open_date
            ).where(PortfolioPosition.portfolio_id == p.portfolio_id)
        ).all()
        existing_by_stock = {
            int(sk): {"qty": float(qty or 0), "open_date": od} for sk, qty, od in existing
        }

        snapshot_run_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"rankalpha://broker_snapshot/{p.portfolio_id}/{as_of.isoformat()}"
        )

        position_by_stock: dict[int, dict[str, Any]] = {}
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            sym = str(pos.get("symbol") or "").upper().strip()
            if not sym:
                continue
            stock_key = stock_key_by_symbol.get(sym)
            if stock_key is None:
                ccy = str(pos.get("currency_code") or "").upper().strip() or None
                if payload.dry_run:
                    portfolio_missing_symbols.add(sym)
                    continue
                try:
                    stock_key = int(get_or_create_stock_any(db, sym, currency_code=ccy))
                    stock_key_by_symbol[sym] = stock_key
                except Exception:
                    portfolio_missing_symbols.add(sym)
                    continue
            qty_raw = pos.get("quantity")
            try:
                qty = float(qty_raw)
            except Exception:
                continue
            if qty == 0:
                continue
            avg_cost = pos.get("avg_cost")
            avg_cost_f = None
            try:
                if avg_cost is not None:
                    avg_cost_f = float(avg_cost)
            except Exception:
                avg_cost_f = None

            k = int(stock_key)
            if k not in position_by_stock:
                prev = existing_by_stock.get(k)
                if prev and float(prev.get("qty") or 0) != 0 and prev.get("open_date") is not None:
                    open_date = prev["open_date"]
                else:
                    open_date = as_of
                position_by_stock[k] = {
                    "position_id": uuid.uuid4(),
                    "portfolio_id": p.portfolio_id,
                    "stock_key": k,
                    "quantity": 0.0,
                    "avg_cost": None,
                    "open_date": open_date,
                    "_w_num": 0.0,
                    "_w_den": 0.0,
                }
            row = position_by_stock[k]
            row["quantity"] = float(row.get("quantity") or 0.0) + qty
            if avg_cost_f is not None:
                w = abs(qty)
                row["_w_num"] = float(row.get("_w_num") or 0.0) + (w * avg_cost_f)
                row["_w_den"] = float(row.get("_w_den") or 0.0) + w

        new_positions: list[dict] = []
        for row in position_by_stock.values():
            qty = float(row.get("quantity") or 0.0)
            if qty == 0:
                continue
            den = float(row.get("_w_den") or 0.0)
            if den > 0:
                row["avg_cost"] = float(row.get("_w_num") or 0.0) / den
            row.pop("_w_num", None)
            row.pop("_w_den", None)
            new_positions.append(row)

        new_cash: list[dict] = []
        if isinstance(cash_by_ccy, dict):
            for ccy, amt in cash_by_ccy.items():
                ccy_u = str(ccy or "").upper().strip()
                if not ccy_u:
                    continue
                try:
                    amt_f = float(amt)
                except Exception:
                    continue
                new_cash.append(
                    {
                        "portfolio_id": p.portfolio_id,
                        "currency_code": ccy_u,
                        "cash_amount": amt_f,
                    }
                )

        if payload.dry_run:
            synced_portfolios += 1
            synced_positions += len(new_positions)
            synced_cash_rows += len(new_cash)
            missing_symbols |= portfolio_missing_symbols
            continue

        if portfolio_missing_symbols:
            # Refuse to delete/replace positions if we couldn't map all holdings.
            # This prevents persisting partial snapshots that would silently drop holdings.
            missing_symbols |= portfolio_missing_symbols
            raise HTTPException(
                status_code=422,
                detail=f"Unable to map/create DimStock for symbols: {sorted(portfolio_missing_symbols)}",
            )

        db.execute(
            delete(PortfolioPosition).where(PortfolioPosition.portfolio_id == p.portfolio_id)
        )
        db.execute(
            delete(PortfolioCashPosition).where(
                PortfolioCashPosition.portfolio_id == p.portfolio_id
            )
        )
        db.execute(
            delete(FactPortfolioPositionHist)
            .where(FactPortfolioPositionHist.portfolio_id == p.portfolio_id)
            .where(FactPortfolioPositionHist.effective_date == as_of)
        )

        if new_positions:
            db.execute(insert(PortfolioPosition).values(new_positions))
            hist_rows = [
                {
                    "effective_date": as_of,
                    "portfolio_id": p.portfolio_id,
                    "stock_key": int(r["stock_key"]),
                    "quantity": r["quantity"],
                    "avg_cost": r["avg_cost"],
                    "run_id": snapshot_run_id,
                }
                for r in new_positions
            ]
            db.execute(insert(FactPortfolioPositionHist).values(hist_rows))

        if new_cash:
            db.execute(insert(PortfolioCashPosition).values(new_cash))

        # Commit is handled by the request-scoped DB dependency, so a later failure
        # in this batch can roll back earlier portfolios (avoids partial success).
        synced_portfolios += 1
        synced_positions += len(new_positions)
        synced_cash_rows += len(new_cash)
        missing_symbols |= portfolio_missing_symbols

    return SyncBrokerHoldingsResponse(
        ok=True,
        as_of_date=as_of,
        synced_portfolios=synced_portfolios,
        synced_positions=synced_positions,
        synced_cash_rows=synced_cash_rows,
        missing_symbols=sorted(missing_symbols),
    )


class RollupBrokerAttributionRequest(BaseModel):
    as_of_date: Optional[date] = None
    portfolio_id: Optional[UUID] = None


class RollupBrokerAttributionResponse(BaseModel):
    ok: bool
    as_of_date: date
    prev_date: date
    portfolios_processed: int
    rows_upserted: int
    portfolios_skipped_no_nav_prev: int
    portfolios_skipped_no_prev_positions: int
    missing_fx_pairs: int
    missing_prices: int


@router.post(
    "/broker-attribution/rollup",
    response_model=RollupBrokerAttributionResponse,
)
def rollup_broker_attribution(
    payload: RollupBrokerAttributionRequest,
    db: Session = Depends(get_db),
):
    """Compute close-to-close attribution using the prior-day holdings snapshot.

    Uses:
    - start-of-period quantities from `fact_portfolio_position_hist` on prev trading day
    - close prices from `fact_security_price`
    - FX conversion from `fact_fx_rate`
    - portfolio NAV from `fact_portfolio_nav` on prev trading day (for weights/contribution)
    """
    portfolios_processed = 0
    rows_upserted = 0
    skipped_no_nav_prev = 0
    skipped_no_prev_positions = 0
    missing_fx_pairs = 0
    missing_prices = 0

    # Must begin before *any* DB access; SQLAlchemy 2.x autobegins on first use.
    with db.begin():
        as_of = payload.as_of_date or _latest_trading_day_before(db, before=date.today())
        prev_date = _latest_trading_day_before(db, before=as_of)

        date_key = db.scalar(select(DimDate.date_key).where(DimDate.full_date == as_of))
        prev_date_key = db.scalar(select(DimDate.date_key).where(DimDate.full_date == prev_date))
        if date_key is None or prev_date_key is None:
            raise HTTPException(status_code=422, detail="as_of_date not found in dim_date")

        q = select(Portfolio).where(Portfolio.portfolio_kind == "BROKER")
        if payload.portfolio_id:
            q = q.where(Portfolio.portfolio_id == payload.portfolio_id)
        portfolios = list(db.scalars(q).all())

        for p in portfolios:
            base_ccy = str(getattr(p, "currency_code", "USD") or "USD").upper()
            fx_cache: dict[tuple[int, str, str, str, int, bool], Decimal | None] = {}
            nav_prev = db.scalar(
                select(FactPortfolioNav.nav_base_ccy)
                .where(FactPortfolioNav.portfolio_id == p.portfolio_id)
                .where(FactPortfolioNav.date_key == int(prev_date_key))
                .limit(1)
            )
            try:
                nav_prev_f = float(nav_prev) if nav_prev is not None else None
            except Exception:
                nav_prev_f = None
            if nav_prev_f is None or nav_prev_f <= 0:
                skipped_no_nav_prev += 1
                continue

            prev_rows = db.execute(
                select(FactPortfolioPositionHist.stock_key, FactPortfolioPositionHist.quantity)
                .where(FactPortfolioPositionHist.portfolio_id == p.portfolio_id)
                .where(FactPortfolioPositionHist.effective_date == prev_date)
            ).all()
            if not prev_rows:
                skipped_no_prev_positions += 1
                continue
            qty_prev_by_stock = {int(k): float(q or 0) for k, q in prev_rows}

            end_rows = db.execute(
                select(FactPortfolioPositionHist.stock_key, FactPortfolioPositionHist.quantity)
                .where(FactPortfolioPositionHist.portfolio_id == p.portfolio_id)
                .where(FactPortfolioPositionHist.effective_date == as_of)
            ).all()
            qty_end_by_stock = {int(k): float(q or 0) for k, q in end_rows}

            stock_keys = sorted(k for k, q in qty_prev_by_stock.items() if float(q or 0) != 0)
            if not stock_keys:
                skipped_no_prev_positions += 1
                continue

            px_prev_rows = db.execute(
                select(DimStock.stock_key, DimStock.currency_code, FactSecurityPrice.close_px)
                .select_from(DimStock)
                .join(FactSecurityPrice, FactSecurityPrice.stock_key == DimStock.stock_key)
                .where(FactSecurityPrice.date_key == int(prev_date_key))
                .where(DimStock.stock_key.in_(stock_keys))
            ).all()
            px_prev = {
                int(k): (str(ccy or "").upper() or base_ccy, float(px or 0))
                for k, ccy, px in px_prev_rows
            }

            px_today_rows = db.execute(
                select(FactSecurityPrice.stock_key, FactSecurityPrice.close_px)
                .where(FactSecurityPrice.date_key == int(date_key))
                .where(FactSecurityPrice.stock_key.in_(stock_keys))
            ).all()
            px_today = {int(k): float(px or 0) for k, px in px_today_rows}

            portfolio_missing_fx = 0
            portfolio_missing_prices = 0

            for stock_key in stock_keys:
                qty_prev = float(qty_prev_by_stock.get(int(stock_key)) or 0.0)
                if qty_prev == 0:
                    continue

                ccy, close0 = px_prev.get(int(stock_key), (base_ccy, 0.0))
                close1 = float(px_today.get(int(stock_key)) or 0.0)
                if close0 <= 0 or close1 <= 0:
                    missing_prices += 1
                    portfolio_missing_prices += 1
                    continue

                fx0 = _fx_mid_px(
                    db,
                    date_key=int(prev_date_key),
                    from_ccy=ccy,
                    to_ccy=base_ccy,
                    cache=fx_cache,
                )
                fx1 = _fx_mid_px(
                    db,
                    date_key=int(date_key),
                    from_ccy=ccy,
                    to_ccy=base_ccy,
                    cache=fx_cache,
                )
                if fx0 is None or fx1 is None:
                    missing_fx_pairs += 1
                    portfolio_missing_fx += 1
                    continue

                close0_base = close0 * fx0
                close1_base = close1 * fx1
                mv_prev = qty_prev * close0_base
                pnl = qty_prev * (close1_base - close0_base)
                denom = abs(mv_prev)
                ret = (pnl / denom) if denom != 0 else None
                weight_prev_pct = (mv_prev / nav_prev_f) * 100.0 if nav_prev_f > 0 else None
                contrib_pct = (pnl / nav_prev_f) * 100.0 if nav_prev_f > 0 else None

                stmt = (
                    insert(FactPortfolioPositionAttribution)
                    .values(
                        date_key=int(date_key),
                        portfolio_id=p.portfolio_id,
                        stock_key=int(stock_key),
                        qty_prev=qty_prev,
                        qty_end=qty_end_by_stock.get(int(stock_key)),
                        close_prev_local=close0,
                        close_local=close1,
                        fx_prev=fx0,
                        fx=fx1,
                        close_prev_base=close0_base,
                        close_base=close1_base,
                        market_value_prev_base=mv_prev,
                        pnl_base=pnl,
                        return_base=ret,
                        weight_prev_pct=weight_prev_pct,
                        contribution_pct=contrib_pct,
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            FactPortfolioPositionAttribution.date_key,
                            FactPortfolioPositionAttribution.portfolio_id,
                            FactPortfolioPositionAttribution.stock_key,
                        ],
                        set_={
                            "qty_prev": qty_prev,
                            "qty_end": qty_end_by_stock.get(int(stock_key)),
                            "close_prev_local": close0,
                            "close_local": close1,
                            "fx_prev": fx0,
                            "fx": fx1,
                            "close_prev_base": close0_base,
                            "close_base": close1_base,
                            "market_value_prev_base": mv_prev,
                            "pnl_base": pnl,
                            "return_base": ret,
                            "weight_prev_pct": weight_prev_pct,
                            "contribution_pct": contrib_pct,
                            "load_ts": func.now(),
                        },
                    )
                )
                db.execute(stmt)
                rows_upserted += 1

            # Only delete stale rows once we know the recompute for this portfolio/day had full market/FX coverage.
            # Otherwise keep existing rows to avoid erasing attribution on reruns when upstream data is partial.
            if portfolio_missing_fx == 0 and portfolio_missing_prices == 0:
                db.execute(
                    delete(FactPortfolioPositionAttribution)
                    .where(FactPortfolioPositionAttribution.portfolio_id == p.portfolio_id)
                    .where(FactPortfolioPositionAttribution.date_key == int(date_key))
                    .where(~FactPortfolioPositionAttribution.stock_key.in_(stock_keys))
                )

            portfolios_processed += 1

    return RollupBrokerAttributionResponse(
        ok=True,
        as_of_date=as_of,
        prev_date=prev_date,
        portfolios_processed=portfolios_processed,
        rows_upserted=rows_upserted,
        portfolios_skipped_no_nav_prev=skipped_no_nav_prev,
        portfolios_skipped_no_prev_positions=skipped_no_prev_positions,
        missing_fx_pairs=missing_fx_pairs,
        missing_prices=missing_prices,
    )


class DeploymentItem(BaseModel):
    deployment_id: UUID
    broker_portfolio_id: UUID
    broker_portfolio_name: str
    model_portfolio_id: UUID
    model_portfolio_name: str
    sleeve_portfolio_id: UUID
    sleeve_portfolio_name: str
    allocation_pct: float
    effective_from: date
    effective_to: Optional[date] = None
    is_active: bool


class CreateDeploymentRequest(BaseModel):
    broker_portfolio_id: UUID
    model_portfolio_id: UUID
    allocation_pct: AllocationPercentType
    effective_from: Optional[date] = None
    created_by: Optional[str] = None


class CreateDeploymentResponse(BaseModel):
    deployment_id: UUID
    sleeve_portfolio_id: UUID


@router.get("/deployments", response_model=List[DeploymentItem])
def list_deployments(
    db: Session = Depends(get_db),
    broker_portfolio_id: Optional[UUID] = Query(None),
    model_portfolio_id: Optional[UUID] = Query(None),
    active_only: bool = Query(True),
):
    broker_alias = Portfolio.__table__.alias("p_broker")
    model_alias = Portfolio.__table__.alias("p_model")
    sleeve_alias = Portfolio.__table__.alias("p_sleeve")

    q = (
        select(
            PortfolioDeployment,
            broker_alias.c.portfolio_name.label("broker_name"),
            model_alias.c.portfolio_name.label("model_name"),
            sleeve_alias.c.portfolio_name.label("sleeve_name"),
        )
        .select_from(PortfolioDeployment)
        .join(broker_alias, broker_alias.c.portfolio_id == PortfolioDeployment.broker_portfolio_id)
        .join(model_alias, model_alias.c.portfolio_id == PortfolioDeployment.model_portfolio_id)
        .join(sleeve_alias, sleeve_alias.c.portfolio_id == PortfolioDeployment.sleeve_portfolio_id)
    )
    if broker_portfolio_id:
        q = q.where(PortfolioDeployment.broker_portfolio_id == broker_portfolio_id)
    if model_portfolio_id:
        q = q.where(PortfolioDeployment.model_portfolio_id == model_portfolio_id)
    if active_only:
        q = q.where(PortfolioDeployment.is_active.is_(True)).where(
            PortfolioDeployment.effective_to.is_(None)
        )

    q = q.order_by(broker_alias.c.portfolio_name.asc(), model_alias.c.portfolio_name.asc())
    rows = db.execute(q).all()
    out: List[DeploymentItem] = []
    for dep, broker_name, model_name, sleeve_name in rows:
        out.append(
            DeploymentItem(
                deployment_id=dep.deployment_id,
                broker_portfolio_id=dep.broker_portfolio_id,
                broker_portfolio_name=str(broker_name),
                model_portfolio_id=dep.model_portfolio_id,
                model_portfolio_name=str(model_name),
                sleeve_portfolio_id=dep.sleeve_portfolio_id,
                sleeve_portfolio_name=str(sleeve_name),
                allocation_pct=float(dep.allocation_pct),
                effective_from=dep.effective_from,
                effective_to=dep.effective_to,
                is_active=bool(dep.is_active),
            )
        )
    return out


@router.post(
    "/deployments",
    response_model=CreateDeploymentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_deployment(
    payload: CreateDeploymentRequest,
    db: Session = Depends(get_db),
):
    with db.begin():
        dep_id, sleeve_id = get_or_create_deployment(
            db,
            broker_portfolio_id=payload.broker_portfolio_id,
            model_portfolio_id=payload.model_portfolio_id,
            allocation_pct=float(payload.allocation_pct),
            effective_from=payload.effective_from,
            created_by=payload.created_by,
        )
    return CreateDeploymentResponse(deployment_id=dep_id, sleeve_portfolio_id=sleeve_id)


class CreateRunRequest(BaseModel):
    portfolio_id: UUID
    run_kind: Literal["MODEL_CONSTRUCTION", "BROKER_REBALANCE", "SLEEVE_BUILD"]
    as_of_date: date
    policy_id: Optional[int] = None
    created_by: Optional[str] = None


class RunItem(BaseModel):
    run_id: UUID
    portfolio_id: UUID
    portfolio_name: str
    run_kind: str
    as_of_date: date
    run_seq: int
    status: str
    policy_id: Optional[int] = None
    created_at: datetime
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    order_count: int
    approved_order_count: int


class CreateRunResponse(BaseModel):
    run_id: UUID
    run_seq: int


@router.post(
    "/runs",
    response_model=CreateRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_run(
    payload: CreateRunRequest,
    db: Session = Depends(get_db),
):
    with db.begin():
        run = create_portfolio_run(
            db,
            portfolio_id=payload.portfolio_id,
            run_kind=payload.run_kind,
            as_of_date=payload.as_of_date,
            policy_id=payload.policy_id,
            created_by=payload.created_by,
        )
    return CreateRunResponse(run_id=run.run_id, run_seq=int(run.run_seq))


@router.get("/runs", response_model=List[RunItem])
def list_runs(
    db: Session = Depends(get_db),
    portfolio_id: Optional[UUID] = Query(None),
    run_kind: Optional[str] = Query(None),
    as_of_date: Optional[date] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=1000),
):
    if portfolio_id is None and as_of_date is None:
        # Avoid accidentally scanning everything by default.
        raise HTTPException(status_code=422, detail="Provide portfolio_id or as_of_date")

    q = (
        select(
            PortfolioRun,
            Portfolio.portfolio_name,
            func.count(PortfolioOrderIntent.order_id).label("order_count"),
            func.sum(
                case(
                    (PortfolioOrderIntent.approval_status == "APPROVED", 1),
                    else_=0,
                )
            ).label("approved_order_count"),
        )
        .select_from(PortfolioRun)
        .join(Portfolio, Portfolio.portfolio_id == PortfolioRun.portfolio_id)
        .outerjoin(PortfolioOrderIntent, PortfolioOrderIntent.run_id == PortfolioRun.run_id)
        .group_by(PortfolioRun.run_id, Portfolio.portfolio_name)
        .order_by(
            PortfolioRun.as_of_date.desc(),
            PortfolioRun.run_kind.asc(),
            Portfolio.portfolio_name.asc(),
            PortfolioRun.run_seq.desc(),
        )
        .limit(limit)
    )
    if portfolio_id:
        q = q.where(PortfolioRun.portfolio_id == portfolio_id)
    if run_kind:
        q = q.where(PortfolioRun.run_kind == run_kind.strip().upper())
    if as_of_date:
        q = q.where(PortfolioRun.as_of_date == as_of_date)
    if status_filter:
        q = q.where(PortfolioRun.status == status_filter.strip().upper())

    rows = db.execute(q).all()
    out: List[RunItem] = []
    for run, portfolio_name, order_count, approved_order_count in rows:
        out.append(
            RunItem(
                run_id=run.run_id,
                portfolio_id=run.portfolio_id,
                portfolio_name=str(portfolio_name),
                run_kind=str(run.run_kind),
                as_of_date=run.as_of_date,
                run_seq=int(run.run_seq),
                status=str(run.status),
                policy_id=run.policy_id,
                created_at=run.created_at,
                approved_at=run.approved_at,
                approved_by=run.approved_by,
                order_count=int(order_count or 0),
                approved_order_count=int(approved_order_count or 0),
            )
        )
    return out


class OrderItem(BaseModel):
    order_id: UUID
    run_id: UUID
    line_no: int
    symbol: str
    action: str
    qty_shares: float
    order_type: str
    time_in_force: str
    limit_price: Optional[float] = None
    stop_trigger_price: Optional[float] = None
    target_weight_after: Optional[float] = None
    approval_status: str
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    notes: Optional[str] = None


class UpsertOrdersRequest(BaseModel):
    orders: List[Dict[str, Any]] = Field(
        default_factory=list, description="Order intent dicts (see docs)"
    )
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "orders": [
                    {
                        "line_no": 1,
                        "symbol": "AAPL",
                        "action": "BUY",
                        "qty_shares": 10,
                        "order_type": "MARKET",
                        "time_in_force": "DAY",
                        "target_weight_after": 0.05,
                        "notes": "Model sleeve entry",
                    }
                ]
            }
        }
    )


class UpsertOrdersResponse(BaseModel):
    order_ids: List[UUID]


@router.get("/runs/{run_id}/orders", response_model=List[OrderItem])
def list_run_orders(
    run_id: UUID,
    db: Session = Depends(get_db),
):
    q = (
        select(
            PortfolioOrderIntent,
            DimStock.symbol,
        )
        .select_from(PortfolioOrderIntent)
        .join(DimStock, DimStock.stock_key == PortfolioOrderIntent.stock_key)
        .where(PortfolioOrderIntent.run_id == run_id)
        .order_by(PortfolioOrderIntent.line_no.asc())
    )
    rows = db.execute(q).all()
    out: List[OrderItem] = []
    for order, symbol in rows:
        out.append(
            OrderItem(
                order_id=order.order_id,
                run_id=order.run_id,
                line_no=int(order.line_no),
                symbol=str(symbol),
                action=str(order.action),
                qty_shares=float(order.qty_shares),
                order_type=str(order.order_type),
                time_in_force=str(order.time_in_force),
                limit_price=float(order.limit_price) if order.limit_price is not None else None,
                stop_trigger_price=float(order.stop_trigger_price)
                if order.stop_trigger_price is not None
                else None,
                target_weight_after=float(order.target_weight_after)
                if order.target_weight_after is not None
                else None,
                approval_status=str(order.approval_status),
                approved_at=order.approved_at,
                approved_by=order.approved_by,
                notes=order.notes,
            )
        )
    return out


@router.post(
    "/runs/{run_id}/orders",
    response_model=UpsertOrdersResponse,
)
def upsert_run_orders(
    run_id: UUID,
    payload: UpsertOrdersRequest,
    db: Session = Depends(get_db),
):
    with db.begin():
        order_ids = upsert_order_intents(db, run_id=run_id, orders=payload.orders)
    return UpsertOrdersResponse(order_ids=order_ids)


class ApproveOrderRequest(BaseModel):
    approved_by: Optional[str] = None


class ApproveOrderResponse(BaseModel):
    ok: bool


@router.post(
    "/orders/{order_id}/approve",
    response_model=ApproveOrderResponse,
)
def approve_order_line(
    order_id: UUID,
    payload: ApproveOrderRequest,
    db: Session = Depends(get_db),
):
    with db.begin():
        set_order_approval(
            db, order_id=order_id, status="APPROVED", approved_by=payload.approved_by
        )
    return ApproveOrderResponse(ok=True)


@router.post(
    "/orders/{order_id}/reject",
    response_model=ApproveOrderResponse,
)
def reject_order_line(
    order_id: UUID,
    payload: ApproveOrderRequest,
    db: Session = Depends(get_db),
):
    with db.begin():
        set_order_approval(
            db, order_id=order_id, status="REJECTED", approved_by=payload.approved_by
        )
    return ApproveOrderResponse(ok=True)


class ApproveRunRequest(BaseModel):
    approved_by: Optional[str] = None


class ApproveRunResponse(BaseModel):
    ok: bool


@router.post(
    "/runs/{run_id}/approve",
    response_model=ApproveRunResponse,
)
def approve_run_endpoint(
    run_id: UUID,
    payload: ApproveRunRequest,
    db: Session = Depends(get_db),
):
    try:
        with db.begin():
            approve_run(db, run_id=run_id, approved_by=payload.approved_by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ApproveRunResponse(ok=True)


class EvaluateRunRiskRequest(BaseModel):
    evaluated_by: Optional[str] = None
    force: bool = False


class EvaluateRunRiskResponse(BaseModel):
    ok: bool
    status: str


@router.post(
    "/runs/{run_id}/risk/evaluate",
    response_model=EvaluateRunRiskResponse,
)
def evaluate_run_risk_endpoint(
    run_id: UUID,
    payload: EvaluateRunRiskRequest,
    db: Session = Depends(get_db),
):
    try:
        with db.begin():
            report = evaluate_run_risk(
                db, run_id=run_id, evaluated_by=payload.evaluated_by, force=payload.force
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EvaluateRunRiskResponse(ok=True, status=str(report.status))
