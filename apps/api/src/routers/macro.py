from __future__ import annotations

import bisect
from datetime import date
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import VwMacroSeries

from ..database import get_db

router = APIRouter(tags=["macro"], prefix="/api/v1/macro")

LIQUIDITY_SERIES: Dict[str, str] = {
    "on_rrp": "US_ON_RRP",
    "tga": "US_TGA_BAL",
}

NET_LIQUIDITY_COMPONENTS: Dict[str, str] = {
    "walcl": "US_FED_WALCL",
    "tga": "US_TGA_BAL",
    "on_rrp": "US_ON_RRP",
}

FED_BALANCE_SHEET_SERIES: Dict[str, str] = {
    "walcl": "US_FED_WALCL",
    "wshosho": "US_FED_WSHOSHO",
    "treast": "US_FED_TREAST",
    "mbst": "US_FED_MBST",
}

DXY_SERIES: Dict[str, str] = {
    "level": "US_DXY_LEVEL",
    "ma50": "US_DXY_MA50",
    "ma100": "US_DXY_MA100",
    "ma200": "US_DXY_MA200",
    "roc_1m": "US_DXY_ROC_1M",
    "roc_3m": "US_DXY_ROC_3M",
    "roc_6m": "US_DXY_ROC_6M",
    "z_3y": "US_DXY_Z_3Y",
    "pctl_5y": "US_DXY_PCTL_5Y",
    "regime_state": "US_DXY_REGIME_STATE",
    "shock_up_flag": "US_DXY_SHOCK_UP_FLAG",
    "shock_down_flag": "US_DXY_SHOCK_DOWN_FLAG",
    "risk_score": "US_DXY_RISK_SCORE",
}

PUT_CALL_SERIES: Dict[str, str] = {
    "total": "#CBOEPC",
    "equity": "#CBOEPCE",
    "spx": "#CBOEPCSPX",
    "index": "#CBOEPCI",
}

REAL_RATES_SERIES: Dict[str, str] = {
    "tips10y": "US_TIPS_10Y_REAL_YIELD",
}


def _compute_regime(
    rrp_latest: Optional[float],
    rrp_prev: Optional[float],
    tga_latest: Optional[float],
    tga_prev: Optional[float],
) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """Return (regime_label, rrp_delta_mn, tga_delta_mn) using the supplied rule set."""
    if rrp_latest is None or tga_latest is None or rrp_prev is None or tga_prev is None:
        return None, None, None

    rrp_delta = rrp_latest - rrp_prev  # millions USD
    tga_delta = tga_latest - tga_prev  # millions USD

    rrp_bil = rrp_latest / 1_000.0  # billions USD

    regime: Optional[str] = None
    if rrp_bil > 300 and rrp_delta < 0 and tga_delta <= 0:
        regime = "Amplified Easing"
    elif 100 < rrp_bil <= 300:
        regime = "Neutral / Cushioning Phase"
    elif rrp_bil <= 100 and tga_delta > 0:
        regime = "Reserve Drain / Tightening"
    elif rrp_bil <= 100 and tga_delta < 0:
        regime = "Liquidity Inflection / Easing"

    return regime, rrp_delta, tga_delta


def _compute_net_liquidity_rows(
    *,
    walcl_rows: List[Tuple[date, Optional[float]]],
    tga_rows: List[Tuple[date, Optional[float]]],
    rrp_rows: List[Tuple[date, Optional[float]]],
) -> List[Dict[str, object]]:
    """Compute net liquidity anchored to WALCL observation dates.

    All inputs should be sorted ascending by date and in **millions USD**.
    """
    tga_dates = [d for d, _ in tga_rows]
    rrp_dates = [d for d, _ in rrp_rows]

    tga_values = [v for _, v in tga_rows]
    rrp_values = [v for _, v in rrp_rows]

    out: List[Dict[str, object]] = []
    for walcl_date, walcl_mn in walcl_rows:
        tga_idx = bisect.bisect_right(tga_dates, walcl_date) - 1
        rrp_idx = bisect.bisect_right(rrp_dates, walcl_date) - 1

        tga_mn = tga_values[tga_idx] if tga_idx >= 0 else None
        rrp_mn = rrp_values[rrp_idx] if rrp_idx >= 0 else None

        net_mn: Optional[float]
        if walcl_mn is None or tga_mn is None or rrp_mn is None:
            net_mn = None
        else:
            net_mn = walcl_mn - tga_mn - rrp_mn

        out.append(
            {
                "as_of_date": walcl_date,
                "walcl_mn": walcl_mn,
                "tga_mn": tga_mn,
                "on_rrp_mn": rrp_mn,
                "net_liquidity_mn": net_mn,
                "net_liquidity_trn": (net_mn / 1_000_000.0) if net_mn is not None else None,
            }
        )
    return out


@router.get("/liquidity/latest")
def liquidity_latest(db: Session = Depends(get_db)):
    codes = list(LIQUIDITY_SERIES.values())
    subq = (
        select(
            VwMacroSeries.series_code,
            VwMacroSeries.as_of_date,
            VwMacroSeries.value,
            func.row_number()
            .over(partition_by=VwMacroSeries.series_code, order_by=desc(VwMacroSeries.as_of_date))
            .label("rn"),
        )
        .where(VwMacroSeries.series_code.in_(codes))
        .subquery()
    )
    latest_rows = db.execute(
        select(subq.c.series_code, subq.c.as_of_date, subq.c.value).where(subq.c.rn == 1)
    ).all()
    latest = {
        r.series_code: {
            "as_of_date": r.as_of_date,
            "value": float(r.value) if r.value is not None else None,
        }
        for r in latest_rows
    }

    # Fetch previous observations (latest-1) for deltas
    prev_subq = (
        select(
            VwMacroSeries.series_code,
            VwMacroSeries.as_of_date,
            VwMacroSeries.value,
            func.row_number()
            .over(partition_by=VwMacroSeries.series_code, order_by=desc(VwMacroSeries.as_of_date))
            .label("rn"),
        )
        .where(VwMacroSeries.series_code.in_(codes))
        .subquery()
    )
    prev_rows = db.execute(
        select(prev_subq.c.series_code, prev_subq.c.as_of_date, prev_subq.c.value).where(
            prev_subq.c.rn == 2
        )
    ).all()
    prev = {
        r.series_code: {
            "as_of_date": r.as_of_date,
            "value": float(r.value) if r.value is not None else None,
        }
        for r in prev_rows
    }

    # Resolve reference date (latest common max)
    ref_date: Optional[date] = None
    payload = {}
    for logical, code in LIQUIDITY_SERIES.items():
        payload[logical] = latest.get(code, {"as_of_date": None, "value": None})
        if payload[logical]["as_of_date"] is not None:
            if ref_date is None or payload[logical]["as_of_date"] > ref_date:
                ref_date = payload[logical]["as_of_date"]

    rrp = payload.get("on_rrp", {})
    tga = payload.get("tga", {})
    regime, rrp_delta, tga_delta = _compute_regime(
        rrp.get("value"),
        prev.get("US_ON_RRP", {}).get("value"),
        tga.get("value"),
        prev.get("US_TGA_BAL", {}).get("value"),
    )

    return {
        "as_of_date": ref_date,
        "regime": regime,
        "rrp_change_mn": rrp_delta,
        "tga_change_mn": tga_delta,
        "rrp_value_bil": (rrp.get("value") / 1_000) if rrp.get("value") is not None else None,
        "tga_value_bil": (tga.get("value") / 1_000) if tga.get("value") is not None else None,
        **payload,
    }


@router.get("/liquidity/series")
def liquidity_series(
    db: Session = Depends(get_db),
    series: str = Query(..., pattern="^(on_rrp|tga)$"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    code = LIQUIDITY_SERIES.get(series)
    if not code:
        raise HTTPException(status_code=404, detail=f"Series '{series}' not supported")

    q = select(VwMacroSeries).where(VwMacroSeries.series_code == code)
    if start_date:
        q = q.where(VwMacroSeries.as_of_date >= start_date)
    if end_date:
        q = q.where(VwMacroSeries.as_of_date <= end_date)

    order_col = (
        asc(VwMacroSeries.as_of_date) if sort_order == "asc" else desc(VwMacroSeries.as_of_date)
    )
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(order_col).offset(skip).limit(limit)).scalars().all()

    items = [
        {"as_of_date": r.as_of_date, "value": float(r.value) if r.value is not None else None}
        for r in rows
    ]
    return {
        "series": series,
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }


@router.get("/real-rates/tips10y/series")
def tips10y_real_yield_series(
    db: Session = Depends(get_db),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    code = REAL_RATES_SERIES["tips10y"]
    q = select(VwMacroSeries).where(VwMacroSeries.series_code == code)
    if start_date:
        q = q.where(VwMacroSeries.as_of_date >= start_date)
    if end_date:
        q = q.where(VwMacroSeries.as_of_date <= end_date)

    order_col = (
        asc(VwMacroSeries.as_of_date) if sort_order == "asc" else desc(VwMacroSeries.as_of_date)
    )
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(order_col).offset(skip).limit(limit)).scalars().all()

    items = [
        {"as_of_date": r.as_of_date, "value": float(r.value) if r.value is not None else None}
        for r in rows
    ]
    return {
        "series": "tips10y",
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }


@router.get("/liquidity/net-liquidity/latest")
def net_liquidity_latest(
    db: Session = Depends(get_db),
    lookback_weeks: int = Query(
        260,
        ge=30,
        le=1040,
        description="Lookback window in weeks used for the derived series and z-scores",
    ),
):
    """Return net liquidity anchored to WALCL weekly observations.

    Net liquidity is defined as: WALCL - TGA - ON_RRP (levels, in millions USD).
    """
    walcl_code = NET_LIQUIDITY_COMPONENTS["walcl"]
    tga_code = NET_LIQUIDITY_COMPONENTS["tga"]
    rrp_code = NET_LIQUIDITY_COMPONENTS["on_rrp"]

    walcl_rows_raw = db.execute(
        select(VwMacroSeries.as_of_date, VwMacroSeries.value)
        .where(VwMacroSeries.series_code == walcl_code)
        .order_by(desc(VwMacroSeries.as_of_date))
        .limit(lookback_weeks)
    ).all()
    if not walcl_rows_raw:
        return {"status": "empty"}

    walcl_rows_raw.reverse()  # asc
    walcl_rows: List[Tuple[date, Optional[float]]] = [
        (r.as_of_date, float(r.value) if r.value is not None else None) for r in walcl_rows_raw
    ]
    start = walcl_rows[0][0]
    end = walcl_rows[-1][0]

    def _load_series(code: str) -> List[Tuple[date, Optional[float]]]:
        rows = db.execute(
            select(VwMacroSeries.as_of_date, VwMacroSeries.value)
            .where(VwMacroSeries.series_code == code, VwMacroSeries.as_of_date <= end)
            .order_by(asc(VwMacroSeries.as_of_date))
        ).all()
        # Keep only what we need to anchor; include a small buffer before `start` in case WALCL date is a holiday.
        buf_start = date.fromordinal(max(start.toordinal() - 14, date.min.toordinal()))
        return [
            (r.as_of_date, float(r.value) if r.value is not None else None)
            for r in rows
            if r.as_of_date >= buf_start
        ]

    tga_rows = _load_series(tga_code)
    rrp_rows = _load_series(rrp_code)

    items = _compute_net_liquidity_rows(walcl_rows=walcl_rows, tga_rows=tga_rows, rrp_rows=rrp_rows)
    latest = next((row for row in reversed(items) if row.get("net_liquidity_mn") is not None), None)
    if not latest:
        return {"status": "empty"}

    series_values = [r.get("net_liquidity_mn") for r in items]

    def _delta_at_lag(lag_weeks: int) -> Optional[float]:
        if len(series_values) <= lag_weeks:
            return None
        latest_val = series_values[-1]
        prev_val = series_values[-1 - lag_weeks]
        if latest_val is None or prev_val is None:
            return None
        return float(latest_val) - float(prev_val)

    delta_4w_mn = _delta_at_lag(4)
    delta_13w_mn = _delta_at_lag(13)

    def _zscore_latest(lag_weeks: int) -> Optional[float]:
        deltas: List[float] = []
        for i in range(lag_weeks, len(series_values)):
            cur = series_values[i]
            prev = series_values[i - lag_weeks]
            if cur is None or prev is None:
                continue
            deltas.append(float(cur) - float(prev))
        if len(deltas) < 30:
            return None
        mu = sum(deltas) / len(deltas)
        var = sum((d - mu) ** 2 for d in deltas) / (len(deltas) - 1)
        sd = var**0.5
        latest_delta = deltas[-1]
        if sd <= 1e-12:
            return None
        return (latest_delta - mu) / sd

    delta_4w_z = _zscore_latest(4)
    delta_13w_z = _zscore_latest(13)

    net_mn = latest.get("net_liquidity_mn")
    return {
        "as_of_date": latest.get("as_of_date"),
        "net_liquidity_mn": net_mn,
        "net_liquidity_trn": latest.get("net_liquidity_trn"),
        "delta_4w_mn": delta_4w_mn,
        "delta_13w_mn": delta_13w_mn,
        "delta_4w_trn": (delta_4w_mn / 1_000_000.0) if delta_4w_mn is not None else None,
        "delta_13w_trn": (delta_13w_mn / 1_000_000.0) if delta_13w_mn is not None else None,
        "delta_4w_z": delta_4w_z,
        "delta_13w_z": delta_13w_z,
        "components": {
            "walcl": {"series_code": walcl_code, "value_mn": latest.get("walcl_mn")},
            "tga": {"series_code": tga_code, "value_mn": latest.get("tga_mn")},
            "on_rrp": {"series_code": rrp_code, "value_mn": latest.get("on_rrp_mn")},
        },
    }


@router.get("/liquidity/net-liquidity/series")
def net_liquidity_series(
    db: Session = Depends(get_db),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(520, ge=10, le=5000),
    skip: int = Query(0, ge=0),
):
    """Return a weekly net liquidity series anchored to WALCL observation dates."""
    walcl_code = NET_LIQUIDITY_COMPONENTS["walcl"]
    tga_code = NET_LIQUIDITY_COMPONENTS["tga"]
    rrp_code = NET_LIQUIDITY_COMPONENTS["on_rrp"]

    walcl_q = select(VwMacroSeries.as_of_date, VwMacroSeries.value).where(
        VwMacroSeries.series_code == walcl_code
    )
    if start_date:
        walcl_q = walcl_q.where(VwMacroSeries.as_of_date >= start_date)
    if end_date:
        walcl_q = walcl_q.where(VwMacroSeries.as_of_date <= end_date)

    walcl_total = db.execute(select(func.count()).select_from(walcl_q.subquery())).scalar_one()
    order_col = (
        asc(VwMacroSeries.as_of_date) if sort_order == "asc" else desc(VwMacroSeries.as_of_date)
    )
    walcl_rows_raw = db.execute(walcl_q.order_by(order_col).offset(skip).limit(limit)).all()
    if not walcl_rows_raw:
        return {
            "items": [],
            "total_count": int(walcl_total or 0),
            "page": (skip // limit) + 1,
            "page_size": limit,
        }

    # For alignment, we need WALCL dates in ascending order
    walcl_rows_raw_sorted = sorted(walcl_rows_raw, key=lambda r: r.as_of_date)
    walcl_rows: List[Tuple[date, Optional[float]]] = [
        (r.as_of_date, float(r.value) if r.value is not None else None)
        for r in walcl_rows_raw_sorted
    ]

    span_start = walcl_rows[0][0]
    span_end = walcl_rows[-1][0]
    buf_start = date.fromordinal(max(span_start.toordinal() - 14, date.min.toordinal()))

    def _load_series(code: str) -> List[Tuple[date, Optional[float]]]:
        rows = db.execute(
            select(VwMacroSeries.as_of_date, VwMacroSeries.value)
            .where(
                VwMacroSeries.series_code == code,
                VwMacroSeries.as_of_date >= buf_start,
                VwMacroSeries.as_of_date <= span_end,
            )
            .order_by(asc(VwMacroSeries.as_of_date))
        ).all()
        return [(r.as_of_date, float(r.value) if r.value is not None else None) for r in rows]

    tga_rows = _load_series(tga_code)
    rrp_rows = _load_series(rrp_code)

    items = _compute_net_liquidity_rows(walcl_rows=walcl_rows, tga_rows=tga_rows, rrp_rows=rrp_rows)
    if sort_order == "desc":
        items.reverse()

    return {
        "items": items,
        "total_count": int(walcl_total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }


@router.get("/fed-balance-sheet/latest")
def fed_balance_sheet_latest(db: Session = Depends(get_db)):
    codes = list(FED_BALANCE_SHEET_SERIES.values())
    subq = (
        select(
            VwMacroSeries.series_code,
            VwMacroSeries.as_of_date,
            VwMacroSeries.value,
            func.row_number()
            .over(partition_by=VwMacroSeries.series_code, order_by=desc(VwMacroSeries.as_of_date))
            .label("rn"),
        )
        .where(VwMacroSeries.series_code.in_(codes))
        .subquery()
    )
    rows = db.execute(
        select(subq.c.series_code, subq.c.as_of_date, subq.c.value).where(subq.c.rn == 1)
    ).all()
    payload = {
        logical: {
            "as_of_date": next((r.as_of_date for r in rows if r.series_code == code), None),
            "value": next(
                (
                    float(r.value) if r.value is not None else None
                    for r in rows
                    if r.series_code == code
                ),
                None,
            ),
        }
        for logical, code in FED_BALANCE_SHEET_SERIES.items()
    }

    ref_date: Optional[date] = None
    for entry in payload.values():
        if entry["as_of_date"] and (ref_date is None or entry["as_of_date"] > ref_date):
            ref_date = entry["as_of_date"]

    walcl = payload.get("walcl", {}).get("value")
    wshosho = payload.get("wshosho", {}).get("value")
    treast = payload.get("treast", {}).get("value")
    mbst = payload.get("mbst", {}).get("value")

    # Values are in millions USD in the DB for these FRED series.
    walcl_trn = (walcl / 1_000_000.0) if walcl is not None else None
    wshosho_trn = (wshosho / 1_000_000.0) if wshosho is not None else None
    treast_trn = (treast / 1_000_000.0) if treast is not None else None
    mbst_trn = (mbst / 1_000_000.0) if mbst is not None else None

    wshosho_share_of_walcl = (
        (wshosho / walcl) if (wshosho is not None and walcl not in (None, 0)) else None
    )
    treast_share_of_wshosho = (
        (treast / wshosho) if (treast is not None and wshosho not in (None, 0)) else None
    )
    mbst_share_of_wshosho = (
        (mbst / wshosho) if (mbst is not None and wshosho not in (None, 0)) else None
    )

    return {
        "as_of_date": ref_date,
        "walcl_trn": walcl_trn,
        "wshosho_trn": wshosho_trn,
        "treast_trn": treast_trn,
        "mbst_trn": mbst_trn,
        "wshosho_share_of_walcl": wshosho_share_of_walcl,
        "treast_share_of_wshosho": treast_share_of_wshosho,
        "mbst_share_of_wshosho": mbst_share_of_wshosho,
        **payload,
    }


@router.get("/fed-balance-sheet/series")
def fed_balance_sheet_series(
    db: Session = Depends(get_db),
    series: str = Query(..., pattern="^(" + "|".join(FED_BALANCE_SHEET_SERIES.keys()) + ")$"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    code = FED_BALANCE_SHEET_SERIES.get(series)
    if not code:
        raise HTTPException(status_code=404, detail=f"Series '{series}' not supported")

    q = select(VwMacroSeries).where(VwMacroSeries.series_code == code)
    if start_date:
        q = q.where(VwMacroSeries.as_of_date >= start_date)
    if end_date:
        q = q.where(VwMacroSeries.as_of_date <= end_date)

    order_col = (
        asc(VwMacroSeries.as_of_date) if sort_order == "asc" else desc(VwMacroSeries.as_of_date)
    )
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(order_col).offset(skip).limit(limit)).scalars().all()

    items = [
        {"as_of_date": r.as_of_date, "value": float(r.value) if r.value is not None else None}
        for r in rows
    ]
    return {
        "series": series,
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }


@router.get("/dxy/latest")
def dxy_latest(db: Session = Depends(get_db)):
    codes = list(DXY_SERIES.values())
    subq = (
        select(
            VwMacroSeries.series_code,
            VwMacroSeries.as_of_date,
            VwMacroSeries.value,
            func.row_number()
            .over(partition_by=VwMacroSeries.series_code, order_by=desc(VwMacroSeries.as_of_date))
            .label("rn"),
        )
        .where(VwMacroSeries.series_code.in_(codes))
        .subquery()
    )
    rows = db.execute(
        select(subq.c.series_code, subq.c.as_of_date, subq.c.value).where(subq.c.rn == 1)
    ).all()
    payload = {
        logical: {
            "as_of_date": next((r.as_of_date for r in rows if r.series_code == code), None),
            "value": next(
                (
                    float(r.value) if r.value is not None else None
                    for r in rows
                    if r.series_code == code
                ),
                None,
            ),
        }
        for logical, code in DXY_SERIES.items()
    }
    # reference date: latest across retrieved series
    ref_date: Optional[date] = None
    for entry in payload.values():
        if entry["as_of_date"] and (ref_date is None or entry["as_of_date"] > ref_date):
            ref_date = entry["as_of_date"]

    # convenience label
    regime_val = payload.get("regime_state", {}).get("value")
    regime_label = None
    if regime_val is not None:
        if regime_val > 0:
            regime_label = "USD_BULL"
        elif regime_val < 0:
            regime_label = "USD_BEAR"
        else:
            regime_label = "USD_TRANSITION"

    return {"as_of_date": ref_date, "regime_label": regime_label, **payload}


@router.get("/dxy/series")
def dxy_series(
    db: Session = Depends(get_db),
    series: str = Query(..., pattern="^(" + "|".join(DXY_SERIES.keys()) + ")$"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    code = DXY_SERIES.get(series)
    if not code:
        raise HTTPException(status_code=404, detail=f"Series '{series}' not supported")

    q = select(VwMacroSeries).where(VwMacroSeries.series_code == code)
    if start_date:
        q = q.where(VwMacroSeries.as_of_date >= start_date)
    if end_date:
        q = q.where(VwMacroSeries.as_of_date <= end_date)

    order_col = (
        asc(VwMacroSeries.as_of_date) if sort_order == "asc" else desc(VwMacroSeries.as_of_date)
    )
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(order_col).offset(skip).limit(limit)).scalars().all()

    items = [
        {"as_of_date": r.as_of_date, "value": float(r.value) if r.value is not None else None}
        for r in rows
    ]
    return {
        "series": series,
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }


@router.get("/put-call/latest")
def put_call_latest(db: Session = Depends(get_db)):
    codes = list(PUT_CALL_SERIES.values())
    subq = (
        select(
            VwMacroSeries.series_code,
            VwMacroSeries.as_of_date,
            VwMacroSeries.value,
            func.row_number()
            .over(partition_by=VwMacroSeries.series_code, order_by=desc(VwMacroSeries.as_of_date))
            .label("rn"),
        )
        .where(VwMacroSeries.series_code.in_(codes))
        .subquery()
    )
    rows = db.execute(
        select(subq.c.series_code, subq.c.as_of_date, subq.c.value).where(subq.c.rn == 1)
    ).all()
    payload = {
        logical: {
            "as_of_date": next((r.as_of_date for r in rows if r.series_code == code), None),
            "value": next(
                (
                    float(r.value) if r.value is not None else None
                    for r in rows
                    if r.series_code == code
                ),
                None,
            ),
        }
        for logical, code in PUT_CALL_SERIES.items()
    }

    ref_date: Optional[date] = None
    for entry in payload.values():
        if entry["as_of_date"] and (ref_date is None or entry["as_of_date"] > ref_date):
            ref_date = entry["as_of_date"]

    return {"as_of_date": ref_date, **payload}


@router.get("/put-call/series")
def put_call_series(
    db: Session = Depends(get_db),
    series: str = Query(..., pattern="^(" + "|".join(PUT_CALL_SERIES.keys()) + ")$"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    code = PUT_CALL_SERIES.get(series)
    if not code:
        raise HTTPException(status_code=404, detail=f"Series '{series}' not supported")

    q = select(VwMacroSeries).where(VwMacroSeries.series_code == code)
    if start_date:
        q = q.where(VwMacroSeries.as_of_date >= start_date)
    if end_date:
        q = q.where(VwMacroSeries.as_of_date <= end_date)

    order_col = (
        asc(VwMacroSeries.as_of_date) if sort_order == "asc" else desc(VwMacroSeries.as_of_date)
    )
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(order_col).offset(skip).limit(limit)).scalars().all()

    items = [
        {"as_of_date": r.as_of_date, "value": float(r.value) if r.value is not None else None}
        for r in rows
    ]
    return {
        "series": series,
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }
