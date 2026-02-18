from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from apps.api.src.database import get_db
from apps.api.src.security.dependencies import (
    extract_bearer_token,
    get_optional_user_with_db,
    is_internal_bearer_token,
)
from apps.api.src.security.principals import AuthUserPrincipal
from apps.api.src.settings import Settings
from apps.api.src.utils.settings_cache import make_cached_getter
from apps.common.src.crud import (
    get_model_strategy_performance_view,
    get_portfolio_performance_view,
    get_portfolio_position_attribution_view,
    get_portfolio_snapshot_view,
    get_portfolio_top_contrib_view,
    get_portfolio_turnover_view,
    get_risk_dashboard_view,
)
from apps.common.src.models import (
    DimStock,
    Portfolio,
    PortfolioOrderIntent,
    PortfolioRun,
    PortfolioRunArtifact,
    PortfolioRunRiskReport,
)

router = APIRouter(
    tags=["portfolios"],
    prefix="/api/v1/portfolios",
)

_get_settings = make_cached_getter(lambda: Settings())


def _is_internal(authorization: str | None) -> bool:
    token = extract_bearer_token(authorization)
    return is_internal_bearer_token(token, _get_settings())


def _can_read_portfolio(
    portfolio: Portfolio,
    principal: AuthUserPrincipal | None,
    *,
    authorization: str | None,
) -> bool:
    if bool(getattr(portfolio, "is_public", False)) and bool(
        getattr(portfolio, "is_visible", False)
    ):
        return True
    if _is_internal(authorization):
        return True
    if principal is None:
        return False
    if principal.has_role("admin"):
        return True
    owner_id = getattr(portfolio, "portfolio_owner_id", None)
    return owner_id is not None and int(owner_id) == int(principal.user_id)


def _require_portfolio_read_access(
    db: Session,
    *,
    portfolio_id: UUID,
    principal: AuthUserPrincipal | None,
    authorization: str | None,
) -> Portfolio:
    p = db.get(Portfolio, portfolio_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    if not _can_read_portfolio(p, principal, authorization=authorization):
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return p


def _can_see_drafts(
    portfolio: Portfolio,
    principal: AuthUserPrincipal | None,
    *,
    authorization: str | None,
) -> bool:
    if _is_internal(authorization):
        return True
    if principal is None:
        return False
    if principal.has_role("admin"):
        return True
    owner_id = getattr(portfolio, "portfolio_owner_id", None)
    return owner_id is not None and int(owner_id) == int(principal.user_id)


class PortfolioSummary(BaseModel):
    portfolio_id: UUID
    portfolio_name: str
    portfolio_kind: str
    currency_code: str
    description: Optional[str] = None
    is_public: bool
    is_visible: bool


@router.get("", response_model=List[PortfolioSummary])
def list_portfolios(
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
    kind: Optional[str] = Query(None, description="Filter by portfolio_kind (BROKER|MODEL|SLEEVE)"),
    include_private: bool = Query(
        False,
        description="Include private portfolios you can access (requires auth or internal token).",
    ),
):
    kind_norm = kind.strip().upper() if kind else None
    internal = _is_internal(authorization)

    q = select(Portfolio)
    if include_private:
        if not internal and principal is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not internal and principal is not None and not principal.has_role("admin"):
            q = q.where(
                (Portfolio.portfolio_owner_id == principal.user_id)
                | (Portfolio.is_public.is_(True) & Portfolio.is_visible.is_(True))
            )
    else:
        q = q.where(Portfolio.is_public.is_(True)).where(Portfolio.is_visible.is_(True))

    if kind_norm:
        q = q.where(Portfolio.portfolio_kind == kind_norm)

    q = q.order_by(Portfolio.portfolio_kind.asc(), Portfolio.portfolio_name.asc())
    rows = list(db.scalars(q).all())
    return [
        PortfolioSummary(
            portfolio_id=p.portfolio_id,
            portfolio_name=p.portfolio_name,
            portfolio_kind=str(p.portfolio_kind),
            currency_code=str(p.currency_code),
            description=p.description,
            is_public=bool(getattr(p, "is_public", False)),
            is_visible=bool(getattr(p, "is_visible", False)),
        )
        for p in rows
    ]


class PortfolioDetail(PortfolioSummary):
    broker_name: Optional[str] = None
    broker_account_id: Optional[str] = None


@router.get("/{portfolio_id}", response_model=PortfolioDetail)
def get_portfolio(
    portfolio_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
):
    p = _require_portfolio_read_access(
        db,
        portfolio_id=portfolio_id,
        principal=principal,
        authorization=authorization,
    )
    return PortfolioDetail(
        portfolio_id=p.portfolio_id,
        portfolio_name=p.portfolio_name,
        portfolio_kind=str(p.portfolio_kind),
        currency_code=str(p.currency_code),
        broker_name=getattr(p, "broker_name", None),
        broker_account_id=getattr(p, "broker_account_id", None),
        description=p.description,
        is_public=bool(getattr(p, "is_public", False)),
        is_visible=bool(getattr(p, "is_visible", False)),
    )


class PerformanceItem(BaseModel):
    full_date: date
    nav_base_ccy: float
    daily_return: Optional[float] = None


@router.get("/{portfolio_id}/performance", response_model=List[PerformanceItem])
def get_performance(
    portfolio_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
    since: Optional[date] = Query(None),
):
    p = _require_portfolio_read_access(
        db,
        portfolio_id=portfolio_id,
        principal=principal,
        authorization=authorization,
    )
    rows = get_portfolio_performance_view(db, portfolio_name=p.portfolio_name, since=since)
    return [
        PerformanceItem(
            full_date=r.full_date,
            nav_base_ccy=float(r.nav_base_ccy),
            daily_return=float(r.daily_return) if r.daily_return is not None else None,
        )
        for r in rows
    ]


class StrategyPerformanceItem(BaseModel):
    full_date: date
    source_name: str
    strategy_name: str
    nav_base_ccy: float
    daily_return: Optional[float] = None


@router.get("/{portfolio_id}/strategy-performance", response_model=List[StrategyPerformanceItem])
def get_strategy_performance(
    portfolio_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
    since: Optional[date] = Query(None),
):
    p = _require_portfolio_read_access(
        db,
        portfolio_id=portfolio_id,
        principal=principal,
        authorization=authorization,
    )
    if str(getattr(p, "portfolio_kind", "")).upper() != "MODEL":
        raise HTTPException(
            status_code=422, detail="strategy-performance is only supported for MODEL portfolios"
        )

    rows = get_model_strategy_performance_view(db, portfolio_id=p.portfolio_id, since=since)
    return [
        StrategyPerformanceItem(
            full_date=r.full_date,
            source_name=str(r.source_name),
            strategy_name=str(r.strategy_name),
            nav_base_ccy=float(r.nav_base_ccy),
            daily_return=float(r.daily_return) if r.daily_return is not None else None,
        )
        for r in rows
    ]


class PositionAttributionItem(BaseModel):
    full_date: date
    symbol: str
    qty_prev: float
    qty_end: Optional[float] = None
    pnl_base: Optional[float] = None
    return_base: Optional[float] = None
    weight_prev_pct: Optional[float] = None
    contribution_pct: Optional[float] = None


@router.get("/{portfolio_id}/attribution", response_model=List[PositionAttributionItem])
def get_position_attribution(
    portfolio_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
    since: Optional[date] = Query(None),
):
    p = _require_portfolio_read_access(
        db,
        portfolio_id=portfolio_id,
        principal=principal,
        authorization=authorization,
    )
    rows = get_portfolio_position_attribution_view(db, portfolio_id=p.portfolio_id, since=since)
    return [
        PositionAttributionItem(
            full_date=r.full_date,
            symbol=str(r.symbol),
            qty_prev=float(r.qty_prev) if r.qty_prev is not None else 0.0,
            qty_end=float(r.qty_end) if r.qty_end is not None else None,
            pnl_base=float(r.pnl_base) if r.pnl_base is not None else None,
            return_base=float(r.return_base) if r.return_base is not None else None,
            weight_prev_pct=float(r.weight_prev_pct) if r.weight_prev_pct is not None else None,
            contribution_pct=float(r.contribution_pct) if r.contribution_pct is not None else None,
        )
        for r in rows
    ]


class SnapshotItem(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    quantity: float
    avg_cost: Optional[float] = None
    last_close: Optional[float] = None
    market_value: Optional[float] = None
    nav: Optional[float] = None
    weight_pct: Optional[float] = None
    last_update_ts: Optional[datetime] = None


@router.get("/{portfolio_id}/snapshot", response_model=List[SnapshotItem])
def get_snapshot(
    portfolio_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
):
    p = _require_portfolio_read_access(
        db,
        portfolio_id=portfolio_id,
        principal=principal,
        authorization=authorization,
    )
    rows = get_portfolio_snapshot_view(db, portfolio_name=p.portfolio_name)
    return [
        SnapshotItem(
            symbol=str(r.symbol),
            company_name=r.company_name,
            quantity=float(r.quantity),
            avg_cost=float(r.avg_cost) if r.avg_cost is not None else None,
            last_close=float(r.last_close) if r.last_close is not None else None,
            market_value=float(r.market_value) if r.market_value is not None else None,
            nav=float(r.nav) if r.nav is not None else None,
            weight_pct=float(r.weight_pct) if r.weight_pct is not None else None,
            last_update_ts=r.last_update_ts,
        )
        for r in rows
    ]


class TurnoverItem(BaseModel):
    full_date: date
    notional_traded: float
    nav_base_ccy: float
    turnover_pct: Optional[float] = None


@router.get("/{portfolio_id}/turnover", response_model=List[TurnoverItem])
def get_turnover(
    portfolio_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
    since: Optional[date] = Query(None),
):
    p = _require_portfolio_read_access(
        db,
        portfolio_id=portfolio_id,
        principal=principal,
        authorization=authorization,
    )
    rows = get_portfolio_turnover_view(db, portfolio_name=p.portfolio_name, since=since)
    return [
        TurnoverItem(
            full_date=r.full_date,
            notional_traded=float(r.notional_traded),
            nav_base_ccy=float(r.nav_base_ccy),
            turnover_pct=float(r.turnover_pct) if r.turnover_pct is not None else None,
        )
        for r in rows
    ]


class TopContributorItem(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    quantity: float
    close_px: Optional[float] = None
    unreal_pnl: Optional[float] = None


@router.get("/{portfolio_id}/top-contributors", response_model=List[TopContributorItem])
def get_top_contributors(
    portfolio_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
    limit: int = Query(20, ge=1, le=200),
):
    p = _require_portfolio_read_access(
        db,
        portfolio_id=portfolio_id,
        principal=principal,
        authorization=authorization,
    )
    rows = get_portfolio_top_contrib_view(db, portfolio_name=p.portfolio_name, limit=limit)
    return [
        TopContributorItem(
            symbol=str(r.symbol),
            company_name=r.company_name,
            quantity=float(r.quantity),
            close_px=float(r.close_px) if r.close_px is not None else None,
            unreal_pnl=float(r.unreal_pnl) if r.unreal_pnl is not None else None,
        )
        for r in rows
    ]


class RiskDashboardItem(BaseModel):
    full_date: date
    var_95_1d: Optional[float] = None
    beta_spx: Optional[float] = None
    liq_days: Optional[float] = None


@router.get("/{portfolio_id}/risk", response_model=List[RiskDashboardItem])
def get_risk_dashboard(
    portfolio_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
    since: Optional[date] = Query(None),
):
    p = _require_portfolio_read_access(
        db,
        portfolio_id=portfolio_id,
        principal=principal,
        authorization=authorization,
    )
    rows = get_risk_dashboard_view(db, portfolio_name=p.portfolio_name, since=since)
    return [
        RiskDashboardItem(
            full_date=r.full_date,
            var_95_1d=float(r.var_95_1d) if r.var_95_1d is not None else None,
            beta_spx=float(r.beta_spx) if r.beta_spx is not None else None,
            liq_days=float(r.liq_days) if r.liq_days is not None else None,
        )
        for r in rows
    ]


class RunItem(BaseModel):
    run_id: UUID
    run_kind: str
    as_of_date: date
    run_seq: int
    status: str
    created_at: datetime
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None


@router.get("/{portfolio_id}/runs", response_model=List[RunItem])
def list_runs(
    portfolio_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
    limit: int = Query(200, ge=1, le=1000),
):
    p = _require_portfolio_read_access(
        db, portfolio_id=portfolio_id, principal=principal, authorization=authorization
    )
    can_see_drafts = _can_see_drafts(p, principal, authorization=authorization)

    q = (
        select(PortfolioRun)
        .where(PortfolioRun.portfolio_id == portfolio_id)
        .order_by(desc(PortfolioRun.as_of_date), desc(PortfolioRun.run_seq))
        .limit(limit)
    )
    if not can_see_drafts:
        q = q.where(PortfolioRun.status.in_(["APPROVED", "SUPERSEDED"]))

    rows = list(db.scalars(q).all())
    return [
        RunItem(
            run_id=r.run_id,
            run_kind=str(r.run_kind),
            as_of_date=r.as_of_date,
            run_seq=int(r.run_seq),
            status=str(r.status),
            created_at=r.created_at,
            approved_at=r.approved_at,
            approved_by=r.approved_by,
        )
        for r in rows
    ]


class OrderItem(BaseModel):
    order_id: UUID
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


@router.get("/{portfolio_id}/runs/{run_id}/orders", response_model=List[OrderItem])
def list_run_orders(
    portfolio_id: UUID,
    run_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
):
    p = _require_portfolio_read_access(
        db, portfolio_id=portfolio_id, principal=principal, authorization=authorization
    )
    run = db.get(PortfolioRun, run_id)
    if run is None or run.portfolio_id != portfolio_id:
        raise HTTPException(status_code=404, detail="Run not found")

    can_see_drafts = _can_see_drafts(p, principal, authorization=authorization)
    if not can_see_drafts and str(run.status).upper() not in {"APPROVED", "SUPERSEDED"}:
        raise HTTPException(status_code=404, detail="Run not found")

    q = (
        select(PortfolioOrderIntent, DimStock.symbol)
        .select_from(PortfolioOrderIntent)
        .join(DimStock, DimStock.stock_key == PortfolioOrderIntent.stock_key)
        .where(PortfolioOrderIntent.run_id == run_id)
        .order_by(PortfolioOrderIntent.line_no.asc())
    )
    rows = db.execute(q).all()
    out: list[OrderItem] = []
    for order, symbol in rows:
        out.append(
            OrderItem(
                order_id=order.order_id,
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


class RunArtifactItem(BaseModel):
    artifact_type: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@router.get("/{portfolio_id}/runs/{run_id}/artifacts", response_model=List[RunArtifactItem])
def list_run_artifacts(
    portfolio_id: UUID,
    run_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
):
    p = _require_portfolio_read_access(
        db, portfolio_id=portfolio_id, principal=principal, authorization=authorization
    )
    run = db.get(PortfolioRun, run_id)
    if run is None or run.portfolio_id != portfolio_id:
        raise HTTPException(status_code=404, detail="Run not found")
    can_see_drafts = _can_see_drafts(p, principal, authorization=authorization)
    if not can_see_drafts and str(run.status).upper() not in {"APPROVED", "SUPERSEDED"}:
        raise HTTPException(status_code=404, detail="Run not found")
    rows = list(
        db.scalars(
            select(PortfolioRunArtifact)
            .where(PortfolioRunArtifact.run_id == run_id)
            .order_by(PortfolioRunArtifact.artifact_type.asc())
        ).all()
    )
    return [
        RunArtifactItem(
            artifact_type=str(r.artifact_type),
            payload=dict(r.payload or {}),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


class RunRiskCheckItem(BaseModel):
    check_code: str
    severity: str
    status: str
    metric_value: Optional[float] = None
    threshold_value: Optional[float] = None
    details: dict[str, Any]


class RunRiskReportItem(BaseModel):
    evaluated_at: datetime
    status: str
    summary: dict[str, Any]
    checks: List[RunRiskCheckItem]


@router.get("/{portfolio_id}/runs/{run_id}/risk", response_model=RunRiskReportItem)
def get_run_risk_report(
    portfolio_id: UUID,
    run_id: UUID,
    db: Session = Depends(get_db),
    principal: AuthUserPrincipal | None = Depends(get_optional_user_with_db),
    authorization: str | None = Header(default=None),
):
    p = _require_portfolio_read_access(
        db, portfolio_id=portfolio_id, principal=principal, authorization=authorization
    )
    run = db.get(PortfolioRun, run_id)
    if run is None or run.portfolio_id != portfolio_id:
        raise HTTPException(status_code=404, detail="Run not found")
    can_see_drafts = _can_see_drafts(p, principal, authorization=authorization)
    if not can_see_drafts and str(run.status).upper() not in {"APPROVED", "SUPERSEDED"}:
        raise HTTPException(status_code=404, detail="Run not found")
    report = db.get(PortfolioRunRiskReport, run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Risk report not found")

    checks = list(getattr(report, "checks", []) or [])
    return RunRiskReportItem(
        evaluated_at=report.evaluated_at,
        status=str(report.status),
        summary=dict(report.summary or {}),
        checks=[
            RunRiskCheckItem(
                check_code=str(c.check_code),
                severity=str(c.severity),
                status=str(c.status),
                metric_value=float(c.metric_value) if c.metric_value is not None else None,
                threshold_value=float(c.threshold_value) if c.threshold_value is not None else None,
                details=dict(c.details or {}),
            )
            for c in checks
        ],
    )
