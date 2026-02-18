from __future__ import annotations

from datetime import date, datetime
from hmac import compare_digest
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, condecimal, constr, model_validator
from sqlalchemy.orm import Session

from apps.api.src.database import get_db
from apps.api.src.settings import Settings
from apps.api.src.utils.settings_cache import make_cached_getter
from apps.common.src.crud import upsert_trade_recommendation

_get_settings = make_cached_getter(lambda: Settings())


def _require_trading_token(
    settings: Settings = Depends(_get_settings),
    authorization: str | None = Header(default=None),
):
    """Require a Bearer token for trading ingestion routes."""
    token = (settings.trading_bearer_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trading ingestion disabled",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
        )
    supplied = authorization.removeprefix("Bearer ").strip()
    if not compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


router = APIRouter(
    prefix="/api/v1/trading",
    tags=["trading"],
    dependencies=[Depends(_require_trading_token)],
)


DecimalType = condecimal(max_digits=20, decimal_places=4)
SmallDecimalType = condecimal(max_digits=10, decimal_places=4)
PercentType = condecimal(max_digits=6, decimal_places=2)
TrailPercentType = condecimal(max_digits=6, decimal_places=2, gt=0, lt=100)


class TradeRecommendationRequest(BaseModel):
    symbol: constr(strip_whitespace=True, min_length=1, max_length=20)
    action: Literal["BUY", "SELL", "SHORT", "COVER"]
    as_of_date: date = Field(..., description="Calendar date (YYYY-MM-DD) for the recommendation")
    recommended_price: DecimalType

    source_name: constr(strip_whitespace=True, min_length=1, max_length=50) = "External-Trader"
    source_version: Optional[constr(strip_whitespace=True, max_length=20)] = "1"
    asset_type: Optional[constr(strip_whitespace=True, max_length=20)] = None
    currency_code: Optional[constr(strip_whitespace=True, min_length=3, max_length=3)] = None

    order_type: Optional[constr(strip_whitespace=True, max_length=16)] = "MARKET"
    time_in_force: Optional[constr(strip_whitespace=True, max_length=12)] = "DAY"
    valid_from_ts: Optional[datetime] = None
    expiry_ts: Optional[datetime] = None

    stop_loss_price: Optional[DecimalType] = None
    take_profit_price: Optional[DecimalType] = None
    limit_price: Optional[DecimalType] = None
    stop_trigger_price: Optional[DecimalType] = None

    size_shares: Optional[int] = Field(default=None, ge=0)
    size_percent: Optional[PercentType] = Field(default=None)

    confidence_label: Optional[constr(strip_whitespace=True, max_length=25)] = None
    timeframe_label: Optional[constr(strip_whitespace=True, max_length=25)] = None
    strategy_name: Optional[constr(strip_whitespace=True, max_length=50)] = None
    description: Optional[constr(strip_whitespace=True, max_length=1000)] = None

    portfolio_id: Optional[UUID] = None
    routing_hint: Optional[constr(strip_whitespace=True, max_length=32)] = None
    risk_budget_bps: Optional[SmallDecimalType] = None
    signal_version: Optional[constr(strip_whitespace=True, max_length=20)] = None
    model_run_id: Optional[UUID] = None

    preconditions: Optional[Dict[str, Any]] = None
    trail_percent: Optional[TrailPercentType] = Field(
        default=None,
        description="Trailing stop percent (0 < pct < 100). Required when order_type=TRAIL.",
    )
    auto_hedge: bool = False

    @model_validator(mode="after")
    def _validate_trailing_stop_percent(self) -> "TradeRecommendationRequest":
        key = (self.order_type or "").strip().upper()
        key = key.replace(" ", "").replace("_", "")
        if key in {"TRAIL", "TRAILINGSTOP", "TRAILSTOP"}:
            if self.trail_percent is None:
                raise ValueError("trail_percent is required when order_type=TRAIL")
            if self.stop_trigger_price is not None:
                raise ValueError(
                    "stop_trigger_price is not supported for TRAIL (use trail_percent)"
                )
            if self.limit_price is not None:
                raise ValueError("limit_price is not supported for TRAIL")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "symbol": "AAPL",
                "action": "BUY",
                "as_of_date": "2025-10-07",
                "recommended_price": "182.45",
                "order_type": "LIMIT",
                "limit_price": "182.50",
                "time_in_force": "DAY",
                "stop_loss_price": "175.00",
                "take_profit_price": "195.00",
                "size_percent": "2.5",
                "source_name": "Quant-Signal-01",
                "strategy_name": "Breakout-Oct",
                "portfolio_id": "5e1f79a2-4c64-4d65-b3d0-07f9c9c35321",
                "preconditions": {"max_bid_ask_spread_bps": 8},
            }
        }
    )


class TradeRecommendationResponse(BaseModel):
    recommendation_id: UUID
    status: Literal["accepted"] = "accepted"


@router.post(
    "/signals",
    status_code=status.HTTP_201_CREATED,
    response_model=TradeRecommendationResponse,
    summary="Submit a trade recommendation",
)
def submit_trade_recommendation(
    payload: TradeRecommendationRequest,
    db: Session = Depends(get_db),
):
    """Ingest a structured trade recommendation."""
    if (payload.source_name or "").strip().lower().startswith("broker::"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_name starting with broker:: is reserved for executable broker orders; submit ideas under a non-broker source and execute via approved broker runs",
        )
    data = payload.model_dump(exclude_none=True)
    data["as_of_date"] = payload.as_of_date.isoformat()
    trail_percent = data.pop("trail_percent", None)
    if trail_percent is not None:
        pre = data.get("preconditions") or {}
        if not isinstance(pre, dict):
            pre = {}
        pre = dict(pre)
        pre["trail_percent"] = float(trail_percent)
        data["preconditions"] = pre
    try:
        rec_id = upsert_trade_recommendation(db, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return TradeRecommendationResponse(recommendation_id=rec_id, status="accepted")
