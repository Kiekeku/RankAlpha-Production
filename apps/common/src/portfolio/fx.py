from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apps.common.src.models import DimDate, FactFxRate


@dataclass(frozen=True)
class FXConfig:
    pivot_ccy: str = "USD"
    max_lookback_days: int = 30
    fallback_to_last_available: bool = True


def _fetch_mid_px(
    session: Session,
    *,
    date_key: int,
    from_ccy: str,
    to_ccy: str,
    cfg: FXConfig,
) -> Optional[Decimal]:
    q = (
        select(FactFxRate.mid_px)
        .where(FactFxRate.from_ccy == from_ccy)
        .where(FactFxRate.to_ccy == to_ccy)
    )

    if cfg.fallback_to_last_available:
        current_full_date = (
            select(DimDate.full_date).where(DimDate.date_key == int(date_key)).scalar_subquery()
        )
        lookback_days = max(int(cfg.max_lookback_days), 0)
        cutoff_full_date = None
        if lookback_days > 0:
            cutoff_full_date = current_full_date - text(f"interval '{lookback_days} days'")

        q = q.where(FactFxRate.date_key <= int(date_key))
        if cutoff_full_date is not None:
            q = (
                q.join(DimDate, DimDate.date_key == FactFxRate.date_key)
                .where(DimDate.full_date <= current_full_date)
                .where(DimDate.full_date >= cutoff_full_date)
            )
        q = q.order_by(FactFxRate.date_key.desc()).limit(1)
    else:
        q = q.where(FactFxRate.date_key == int(date_key)).limit(1)

    px = session.scalar(q)
    if px is None:
        return None
    try:
        d = Decimal(px)
    except Exception:
        return None
    return d if d > 0 else None


def fx_mid_px(
    session: Session,
    *,
    date_key: int,
    from_ccy: str,
    to_ccy: str,
    cfg: FXConfig | None = None,
    cache: dict[tuple[int, str, str, str, int, bool], Optional[Decimal]] | None = None,
) -> Optional[Decimal]:
    """Resolve FX mid price from `from_ccy` to `to_ccy` on/near `date_key`.

    Supports:
    - direct pair
    - inverse pair
    - triangulation via cfg.pivot_ccy (default USD)
    - bounded fallback lookback (cfg.max_lookback_days) when cfg.fallback_to_last_available=True
    """
    cfg = cfg or FXConfig()

    f = (from_ccy or "").upper()
    t = (to_ccy or "").upper()
    if not f or not t:
        return None
    if f == t:
        return Decimal("1")

    pivot = (cfg.pivot_ccy or "USD").upper()
    key = (
        int(date_key),
        f,
        t,
        pivot,
        int(cfg.max_lookback_days),
        bool(cfg.fallback_to_last_available),
    )
    if cache is not None and key in cache:
        return cache[key]

    # 1) direct
    direct = _fetch_mid_px(session, date_key=int(date_key), from_ccy=f, to_ccy=t, cfg=cfg)
    if direct is not None:
        if cache is not None:
            cache[key] = direct
        return direct

    # 2) inverse
    inv = _fetch_mid_px(session, date_key=int(date_key), from_ccy=t, to_ccy=f, cfg=cfg)
    if inv is not None and inv > 0:
        out = Decimal("1") / inv
        if cache is not None:
            cache[key] = out
        return out

    # 3) triangulate via pivot (default USD)
    if f != pivot and t != pivot:
        f_to_p = fx_mid_px(
            session, date_key=int(date_key), from_ccy=f, to_ccy=pivot, cfg=cfg, cache=cache
        )
        p_to_t = fx_mid_px(
            session, date_key=int(date_key), from_ccy=pivot, to_ccy=t, cfg=cfg, cache=cache
        )
        if f_to_p is not None and p_to_t is not None:
            out = f_to_p * p_to_t
            if cache is not None:
                cache[key] = out
            return out

    if cache is not None:
        cache[key] = None
    return None


__all__ = ["FXConfig", "fx_mid_px"]
