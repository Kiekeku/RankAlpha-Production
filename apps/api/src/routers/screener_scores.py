from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    MVScreenerScoresLatest,
)

from ..database import get_db

router = APIRouter(tags=["screener"], prefix="/api/v1/screener")


class ScoreItem(dict):
    pass


@router.get("/scores")
def list_screener_scores(
    db: Session = Depends(get_db),
    position_side: str = Query("both", pattern="^(long|short|both)$"),
    normalize: bool = Query(True),
    min_score: float = Query(0.0),
    limit: int = Query(200, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    sort_by: str = Query(
        "net_score_raw",
        description="Sort key: long_score_raw, short_score_raw, net_score_raw, long_pct, short_pct, net_pct",
    ),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
):
    # This endpoint serves the latest snapshot (MV is latest-only)
    # Restrict to eligible universe (already applied in MV, but be explicit)
    # Not joining MvUniverseEligible here; MV already filtered.

    sortable = {
        "long_score_raw": MVScreenerScoresLatest.long_score_raw,
        "short_score_raw": MVScreenerScoresLatest.short_score_raw,
        "net_score_raw": MVScreenerScoresLatest.net_score_raw,
        "long_pct": MVScreenerScoresLatest.long_pct,
        "short_pct": MVScreenerScoresLatest.short_pct,
        "net_pct": MVScreenerScoresLatest.net_pct,
    }
    sort_col = sortable.get(sort_by, MVScreenerScoresLatest.net_score_raw)
    direction = asc if sort_order == "asc" else desc

    # Base selector and count with identical filters
    q = select(MVScreenerScoresLatest)
    count_q = select(func.count()).select_from(MVScreenerScoresLatest)

    # Apply side-specific min_score if requested (to both queries)
    if position_side == "long":
        filt = MVScreenerScoresLatest.long_score_raw > min_score
        q = q.where(filt)
        count_q = count_q.where(filt)
    elif position_side == "short":
        filt = MVScreenerScoresLatest.short_score_raw > min_score
        q = q.where(filt)
        count_q = count_q.where(filt)
    else:
        filt = (MVScreenerScoresLatest.long_score_raw > min_score) | (
            MVScreenerScoresLatest.short_score_raw > min_score
        )
        q = q.where(filt)
        count_q = count_q.where(filt)

    q = (
        q.order_by(direction(sort_col), asc(MVScreenerScoresLatest.symbol))
        .offset(skip)
        .limit(limit)
    )

    total_count = db.execute(count_q).scalar_one()
    rows = db.execute(q).scalars().all()
    out: List[ScoreItem] = []
    for r in rows:
        item: ScoreItem = {
            "as_of_date": r.as_of_date,
            "symbol": r.symbol,
            "long_score": float(r.long_score_raw or 0.0),
            "short_score": float(r.short_score_raw or 0.0),
            "net_score": float(r.net_score_raw or 0.0),
            "families_count_long": int(r.families_count_long or 0),
            "families_count_short": int(r.families_count_short or 0),
            "screens_count_long": int(r.screens_count_long or 0),
            "screens_count_short": int(r.screens_count_short or 0),
            "tier12_hits_long": int(r.tier12_hits_long or 0),
            "tier12_hits_short": int(r.tier12_hits_short or 0),
            "breadth_bonus_long": float(r.breadth_bonus_long or 0.0),
            "any_bonus_long": float(r.any_bonus_long or 0.0),
            "family_streak_bonus_long": float(r.family_streak_bonus_long or 0.0),
            "any_bonus_short": float(r.any_bonus_short or 0.0),
            "family_streak_bonus_short": float(r.family_streak_bonus_short or 0.0),
        }
        if normalize:
            item.update(
                {
                    "long_pct": float(r.long_pct or 0.0) if (r.long_score_raw or 0) > 0 else None,
                    "short_pct": float(r.short_pct or 0.0)
                    if (r.short_score_raw or 0) > 0
                    else None,
                    "net_pct": float(r.net_pct or 0.0) if (abs(r.net_score_raw or 0) > 0) else None,
                }
            )
        out.append(item)

    return {
        "items": out,
        "total_count": int(total_count or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }
