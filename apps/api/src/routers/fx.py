from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.orm import Session

from apps.common.src.models import DimDate, FactFxRate

from ..database import get_db

router = APIRouter(tags=["macro"], prefix="/api/v1/fx")


_CCY_ALIASES: dict[str, list[str]] = {
    # Some environments store onshore CNY but callers may request CNH; treat as aliases for dashboard context.
    "CNH": ["CNH", "CNY"],
    "CNY": ["CNY", "CNH"],
}


def _expand_ccy(ccy: str) -> list[str]:
    c = (ccy or "").strip().upper()
    return _CCY_ALIASES.get(c, [c])


def _parse_pairs(raw: str) -> List[Tuple[str, str, str]]:
    """Parse comma-separated FX pairs (e.g., 'USDJPY,CNHUSD') into (from,to,pair)."""
    if not raw:
        return []
    out: List[Tuple[str, str, str]] = []
    for token in raw.split(","):
        p = (token or "").strip().upper().replace("/", "").replace("-", "")
        if not p:
            continue
        if len(p) != 6 or not p.isalpha():
            raise HTTPException(
                status_code=422, detail=f"Invalid FX pair '{token}'. Expected format like USDJPY."
            )
        frm, to = p[:3], p[3:]
        if (frm, to, p) not in out:
            out.append((frm, to, p))
    return out


@router.get("/latest")
def fx_latest(
    db: Session = Depends(get_db),
    pairs: str = Query(..., description="Comma-separated FX pairs like USDJPY,CNHUSD"),
):
    pair_list = _parse_pairs(pairs)
    if not pair_list:
        return {"status": "empty"}

    conds = []
    for frm, to, _pair in pair_list:
        from_candidates = _expand_ccy(frm)
        to_candidates = _expand_ccy(to)
        # Most FX is stored as a single direction (from->to). Allow aliases (CNH/CNY) for either leg.
        for f in from_candidates:
            for t in to_candidates:
                conds.append(and_(FactFxRate.from_ccy == f, FactFxRate.to_ccy == t))
    subq = (
        select(
            FactFxRate.from_ccy,
            FactFxRate.to_ccy,
            DimDate.full_date.label("as_of_date"),
            FactFxRate.mid_px,
            func.row_number()
            .over(
                partition_by=(FactFxRate.from_ccy, FactFxRate.to_ccy),
                order_by=desc(DimDate.full_date),
            )
            .label("rn"),
        )
        .select_from(FactFxRate)
        .join(DimDate, DimDate.date_key == FactFxRate.date_key)
        .where(or_(*conds))
        .subquery()
    )
    rows = db.execute(
        select(subq.c.from_ccy, subq.c.to_ccy, subq.c.as_of_date, subq.c.mid_px).where(
            subq.c.rn == 1
        )
    ).all()
    if not rows:
        return {"status": "empty"}

    payload: Dict[str, Dict[str, object]] = {}
    ref_date: Optional[date] = None
    for frm, to, pair in pair_list:
        from_candidates = set(_expand_ccy(frm))
        to_candidates = set(_expand_ccy(to))
        candidates = [
            r for r in rows if r.from_ccy in from_candidates and r.to_ccy in to_candidates
        ]
        # Prefer exact match if present; otherwise take the most recent among alias candidates.
        exact = next((r for r in candidates if r.from_ccy == frm and r.to_ccy == to), None)
        match = exact or (max(candidates, key=lambda r: r.as_of_date) if candidates else None)
        payload[pair] = {
            "pair": pair,
            "from_ccy": frm,
            "to_ccy": to,
            "as_of_date": match.as_of_date if match else None,
            "mid_px": float(match.mid_px) if (match and match.mid_px is not None) else None,
        }
        d = payload[pair]["as_of_date"]
        if isinstance(d, date) and (ref_date is None or d > ref_date):
            ref_date = d

    return {"as_of_date": ref_date, "pairs": payload}


@router.get("/series")
def fx_series(
    db: Session = Depends(get_db),
    pair: str = Query(..., pattern="^[A-Za-z]{3}[A-Za-z]{3}$", description="FX pair like USDJPY"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    p = pair.strip().upper()
    frm, to = p[:3], p[3:]
    from_candidates = _expand_ccy(frm)
    to_candidates = _expand_ccy(to)

    q = (
        select(DimDate.full_date.label("as_of_date"), FactFxRate.mid_px)
        .select_from(FactFxRate)
        .join(DimDate, DimDate.date_key == FactFxRate.date_key)
        .where(
            or_(
                *[
                    and_(FactFxRate.from_ccy == f, FactFxRate.to_ccy == t)
                    for f in from_candidates
                    for t in to_candidates
                ]
            )
        )
    )
    if start_date:
        q = q.where(DimDate.full_date >= start_date)
    if end_date:
        q = q.where(DimDate.full_date <= end_date)

    order_col = asc(DimDate.full_date) if sort_order == "asc" else desc(DimDate.full_date)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(order_col).offset(skip).limit(limit)).all()
    items = [
        {"as_of_date": r.as_of_date, "mid_px": float(r.mid_px) if r.mid_px is not None else None}
        for r in rows
    ]
    return {
        "pair": p,
        "from_ccy": frm,
        "to_ccy": to,
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }
