from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from apps.common.src.models import FactSpxVixVrp, VwVixTermStructureLatest

from ..database import get_db

router = APIRouter(tags=["macro"], prefix="/api/v1")


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


@router.get("/vol-regime")
def get_vol_regime_latest(
    db: Session = Depends(get_db),
    underlying_symbol: str = Query("SPX/VIX", description="Underlying symbol for the VIX curve"),
):
    stmt = (
        select(VwVixTermStructureLatest)
        .where(VwVixTermStructureLatest.underlying_symbol == underlying_symbol)
        .order_by(desc(VwVixTermStructureLatest.date_key))
        .limit(1)
    )
    row = db.execute(stmt).scalars().first()
    if not row:
        return {"status": "empty"}

    vrp_row = (
        db.query(FactSpxVixVrp)
        .filter(FactSpxVixVrp.underlying_symbol == underlying_symbol)
        # Term-structure snapshots can be ahead of the last computed VRP row
        # (e.g., intraday curve updates). Use the latest VRP observation up to
        # the curve date_key so the UI shows values when available.
        .filter(FactSpxVixVrp.date_key <= row.date_key)
        .order_by(desc(FactSpxVixVrp.date_key))
        .first()
    )

    return {
        "underlying_symbol": row.underlying_symbol,
        "as_of_date": row.as_of_date,
        "vix_1d": _to_float(row.vix_1d),
        "vix_9d": _to_float(row.vix_9d),
        "vix_1m": _to_float(row.vix_1m),
        "vix_3m": _to_float(row.vix_3m),
        "vix_6m": _to_float(row.vix_6m),
        "vix_1y": _to_float(row.vix_1y),
        "slope_1d_9d": _to_float(row.slope_1d_9d),
        "slope_9d_1m": _to_float(row.slope_9d_1m),
        "slope_1m_3m": _to_float(row.slope_1m_3m),
        "slope_3m_6m": _to_float(row.slope_3m_6m),
        "slope_6m_1y": _to_float(row.slope_6m_1y),
        "curve_slope": _to_float(row.curve_slope),
        "ratio_1m_3m": _to_float(row.ratio_1m_3m),
        "ratio_1m_6m": _to_float(row.ratio_1m_6m),
        "ratio_3m_1y": _to_float(row.ratio_3m_1y),
        "num_inversions": row.num_inversions,
        "is_contango": bool(row.is_contango) if row.is_contango is not None else None,
        "is_contango_full": bool(row.is_contango_full)
        if row.is_contango_full is not None
        else None,
        "is_backwardation_front": bool(row.is_backwardation_front)
        if row.is_backwardation_front is not None
        else None,
        "is_backwardation_short": bool(row.is_backwardation_short)
        if row.is_backwardation_short is not None
        else None,
        "regime": row.regime,
        "risk_flag": row.risk_flag,
        "rv_30d_var": _to_float(vrp_row.rv_30d_var) if vrp_row else None,
        "iv_30d_var": _to_float(vrp_row.iv_30d_var) if vrp_row else None,
        "vrp_30d": _to_float(vrp_row.vrp_30d) if vrp_row else None,
        "vrp_regime": vrp_row.vrp_regime if vrp_row else None,
        "vrp_state": vrp_row.vrp_state if vrp_row else None,
        "vol_state": vrp_row.vol_state if vrp_row else None,
    }
