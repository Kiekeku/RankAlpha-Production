from __future__ import annotations

from datetime import date
from typing import List, Optional, Tuple, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.orm import Session, aliased

from apps.common.src.models import (
    DimDate,
    DimSource,
    DimStock,
    DimStyle,
    FactScreenerRank,
    FactScreenerRankChange,
    MVScreenerBreadth,
    MvScreenerBreadthFlow,
    VLatestScreenerConsensus,
    VLatestScreenerValues,
)

from ..database import get_db
from ..utils.company import CompanyNameSanitizerMixin
from ..utils.setup_taxonomy import SETUP_TAXONOMY_SLUGS, setup_bucket_for_hit

ALLOWED_CHANGE_TYPES = {"entered", "reentered", "dropped"}


class ScreenerConsensusItem(CompanyNameSanitizerMixin, BaseModel):
    as_of_date: date
    symbol: str
    position_side: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    exchange: Optional[str] = None
    primary_source: Optional[str] = None
    primary_style: Optional[str] = None
    appearances: float
    styles_distinct: float
    sources_distinct: float
    rank_best: Optional[int] = None
    rank_avg: Optional[float] = None
    rank_median: Optional[float] = None
    min_style_rank_pct: Optional[float] = None
    long_score_raw: Optional[float] = None
    short_score_raw: Optional[float] = None
    net_score_raw: Optional[float] = None
    families_count_long: Optional[int] = None
    families_count_short: Optional[int] = None
    screens_count_long: Optional[int] = None
    screens_count_short: Optional[int] = None
    tier12_hits_long: Optional[int] = None
    tier12_hits_short: Optional[int] = None
    breadth_bonus_long: Optional[float] = None
    any_bonus_long: Optional[float] = None
    family_streak_bonus_long: Optional[float] = None
    any_bonus_short: Optional[float] = None
    family_streak_bonus_short: Optional[float] = None
    long_pct: Optional[float] = None
    short_pct: Optional[float] = None
    net_pct: Optional[float] = None
    consensus_score: Optional[float] = None


class ScreenerConsensusList(BaseModel):
    items: List[ScreenerConsensusItem]
    total_count: int
    page: int
    page_size: int


class OptionCount(BaseModel):
    name: str
    count: int


router = APIRouter(tags=["screener"], prefix="/api/v1/screener")


SETUP_MIN_WINDOW_DAYS = 3


def _setup_bucket_for_hit(
    *,
    style_name: Optional[str],
    source_name: Optional[str],
) -> tuple[str, Optional[str], bool]:
    """Return (bucket_label, bucket_slug, interactive) for a screener hit."""
    return setup_bucket_for_hit(style_name=style_name, source_name=source_name)


def _setup_side_from_position(position_side: Optional[str]) -> str:
    return "bearish" if (position_side or "").strip().lower() == "short" else "bullish"


def _setup_strength(net_score_3d: float, total_3d: float) -> str:
    if total_3d <= 0:
        return "weak"
    dominance = abs(net_score_3d) / total_3d if total_3d else 0.0
    abs_net = abs(net_score_3d)
    if abs_net >= 4.0 or dominance >= 0.7:
        return "strong"
    if abs_net >= 2.0 or dominance >= 0.4:
        return "medium"
    return "weak"


class SetupChip(BaseModel):
    label: str
    slug: Optional[str] = None
    interactive: bool = False
    bias: str  # bullish|bearish
    streak_days: int
    weight_3d: float


class SetupDeveloping(BaseModel):
    streak_days: int = 0
    labels: List[str] = Field(default_factory=list)
    extra_count: int = 0


class SetupSummaryItem(BaseModel):
    as_of_date: date
    symbol: str
    bullish: List[SetupChip]
    bullish_extra_count: int
    bullish_developing: SetupDeveloping
    bearish: List[SetupChip]
    bearish_extra_count: int
    bearish_developing: SetupDeveloping
    bullish_weight_3d: float
    bearish_weight_3d: float
    net_score_3d: float
    net_bias: str  # bullish|bearish|neutral
    net_strength: str  # weak|medium|strong


class SetupSummaryResponse(BaseModel):
    items: List[SetupSummaryItem]


class SetupHit(BaseModel):
    as_of_date: date
    bucket: str
    bucket_slug: Optional[str] = None
    bucket_interactive: bool = False
    bias: str
    style: Optional[str] = None
    source: str
    rank_value: Optional[int] = None
    weight: float
    style_weight: float
    source_weight: float


class SetupHitsDay(BaseModel):
    as_of_date: date
    hits: List[SetupHit]


class SetupSymbolResponse(BaseModel):
    summary: SetupSummaryItem
    days: List[SetupHitsDay]
    focus_slug: Optional[str] = None


def _setup_latest_date_key(db: Session) -> Optional[int]:
    return db.execute(select(func.max(FactScreenerRank.date_key))).scalar_one_or_none()


def _setup_available_screener_days(
    db: Session,
    *,
    limit: int,
) -> list[tuple[int, date]]:
    rows = db.execute(
        select(DimDate.date_key, DimDate.full_date)
        .select_from(FactScreenerRank)
        .join(DimDate, DimDate.date_key == FactScreenerRank.date_key)
        .distinct()
        .order_by(DimDate.full_date.desc())
        .limit(limit)
    ).all()
    return [(int(date_key), cast(date, full_date)) for date_key, full_date in rows]


def _compute_setup_summaries(
    db: Session,
    *,
    symbols: list[str],
    window_days: int,
    lookback_days: int = 252,
) -> tuple[date, dict[str, SetupSummaryItem]]:
    if window_days < SETUP_MIN_WINDOW_DAYS:
        raise HTTPException(
            status_code=400, detail=f"window_days must be >= {SETUP_MIN_WINDOW_DAYS}"
        )
    if not symbols:
        raise HTTPException(status_code=400, detail="symbols is required")

    latest_date_key = _setup_latest_date_key(db)
    if latest_date_key is None:
        raise HTTPException(status_code=404, detail="No screener data available")

    latest_full_date = db.execute(
        select(DimDate.full_date).where(DimDate.date_key == latest_date_key)
    ).scalar_one_or_none()
    if latest_full_date is None:
        raise HTTPException(status_code=404, detail="No screener dates available")

    trading_days = _setup_available_screener_days(db, limit=max(lookback_days, window_days))
    if not trading_days:
        raise HTTPException(status_code=404, detail="No screener days available for lookback")

    trading_dates_desc = [d for _k, d in trading_days]
    last_window = trading_days[:window_days]
    last_window_set = set(d for _k, d in last_window)
    lookback_date_keys = [k for k, _d in trading_days]

    symbols_norm = [s.strip().upper() for s in symbols if s and s.strip()]
    if not symbols_norm:
        raise HTTPException(status_code=400, detail="symbols is required")
    if len(symbols_norm) > 300:
        raise HTTPException(status_code=400, detail="Too many symbols; max 300")

    rows = db.execute(
        select(
            DimStock.symbol,
            DimDate.full_date,
            DimStyle.style_name,
            DimStyle.position_side,
            DimStyle.screener_weight,
            DimSource.source_name,
            DimSource.screener_weight,
            FactScreenerRank.rank_value,
        )
        .select_from(FactScreenerRank)
        .join(DimStock, DimStock.stock_key == FactScreenerRank.stock_key)
        .join(DimDate, DimDate.date_key == FactScreenerRank.date_key)
        .join(DimSource, DimSource.source_key == FactScreenerRank.source_key)
        .outerjoin(DimStyle, DimStyle.style_key == FactScreenerRank.style_key)
        .where(
            and_(
                DimStock.symbol.in_(symbols_norm), FactScreenerRank.date_key.in_(lookback_date_keys)
            )
        )
    ).all()

    presence: dict[tuple[str, str, str], set[date]] = {}
    weight_3d: dict[tuple[str, str, str], float] = {}
    bucket_meta: dict[tuple[str, str, str], tuple[Optional[str], bool]] = {}
    keys_by_symbol_side: dict[str, dict[str, set[tuple[str, str, str]]]] = {}

    bullish_total_by_symbol: dict[str, float] = {s: 0.0 for s in symbols_norm}
    bearish_total_by_symbol: dict[str, float] = {s: 0.0 for s in symbols_norm}

    for (
        symbol,
        as_of_date,
        style_name,
        position_side,
        style_weight,
        source_name,
        source_weight,
        _rank_value,
    ) in rows:
        sym = str(symbol).upper()
        side = _setup_side_from_position(position_side)
        bucket_label, bucket_slug, bucket_interactive = _setup_bucket_for_hit(
            style_name=style_name, source_name=source_name
        )
        key = (sym, side, bucket_label)
        side_keys = keys_by_symbol_side.setdefault(sym, {"bullish": set(), "bearish": set()})
        side_keys[side].add(key)

        dates = presence.get(key)
        if dates is None:
            dates = set()
            presence[key] = dates
        dates.add(as_of_date)

        if as_of_date in last_window_set:
            sw = float(style_weight or 1.0)
            srcw = float(source_weight or 1.0)
            w = sw * srcw
            weight_3d[key] = weight_3d.get(key, 0.0) + w
            if side == "bullish":
                bullish_total_by_symbol[sym] = bullish_total_by_symbol.get(sym, 0.0) + w
            else:
                bearish_total_by_symbol[sym] = bearish_total_by_symbol.get(sym, 0.0) + w

        bucket_meta[key] = (bucket_slug, bucket_interactive)

    def streak_for(key: tuple[str, str, str]) -> int:
        dates = presence.get(key, set())
        streak = 0
        for d in trading_dates_desc:
            if d in dates:
                streak += 1
            else:
                break
        return streak

    out: dict[str, SetupSummaryItem] = {}
    for sym in symbols_norm:
        sym_side_keys = keys_by_symbol_side.get(sym, {})
        bullish_keys = list(sym_side_keys.get("bullish", set()))
        bearish_keys = list(sym_side_keys.get("bearish", set()))

        def build_side(
            keys: list[tuple[str, str, str]],
        ) -> tuple[list[SetupChip], int, SetupDeveloping]:
            if not keys:
                return [], 0, SetupDeveloping(streak_days=0, labels=[], extra_count=0)

            streaks = {k: streak_for(k) for k in keys}
            setups = [k for k in keys if streaks.get(k, 0) >= window_days]
            setups_sorted = sorted(setups, key=lambda k: weight_3d.get(k, 0.0), reverse=True)
            extra = max(0, len(setups_sorted) - 3)
            top = setups_sorted[:3]
            chips: list[SetupChip] = []
            for k in top:
                _sym, side, label = k
                slug, interactive = bucket_meta.get(k, (None, False))
                chips.append(
                    SetupChip(
                        label=label,
                        slug=slug,
                        interactive=bool(slug and interactive),
                        bias=side,
                        streak_days=int(streaks.get(k, 0)),
                        weight_3d=float(weight_3d.get(k, 0.0)),
                    )
                )

            if chips:
                return chips, extra, SetupDeveloping(streak_days=0, labels=[], extra_count=0)

            developing_candidates = [k for k in keys if 0 < streaks.get(k, 0) < window_days]
            if not developing_candidates:
                return [], 0, SetupDeveloping(streak_days=0, labels=[], extra_count=0)

            best_streak = max(streaks[k] for k in developing_candidates)
            best = [k for k in developing_candidates if streaks[k] == best_streak]
            best_sorted = sorted(best, key=lambda k: weight_3d.get(k, 0.0), reverse=True)
            labels = [k[2] for k in best_sorted[:2]]
            extra_count = max(0, len(best_sorted) - 2)
            return (
                [],
                0,
                SetupDeveloping(
                    streak_days=int(best_streak), labels=labels, extra_count=extra_count
                ),
            )

        bullish_chips, bullish_extra, bullish_dev = build_side(bullish_keys)
        bearish_chips, bearish_extra, bearish_dev = build_side(bearish_keys)

        bull_total = float(bullish_total_by_symbol.get(sym, 0.0))
        bear_total = float(bearish_total_by_symbol.get(sym, 0.0))
        net = bull_total - bear_total
        total = bull_total + bear_total
        if net > 0.0001:
            net_bias = "bullish"
        elif net < -0.0001:
            net_bias = "bearish"
        else:
            net_bias = "neutral"

        out[sym] = SetupSummaryItem(
            as_of_date=latest_full_date,
            symbol=sym,
            bullish=bullish_chips,
            bullish_extra_count=int(bullish_extra),
            bullish_developing=bullish_dev,
            bearish=bearish_chips,
            bearish_extra_count=int(bearish_extra),
            bearish_developing=bearish_dev,
            bullish_weight_3d=bull_total,
            bearish_weight_3d=bear_total,
            net_score_3d=net,
            net_bias=net_bias,
            net_strength=_setup_strength(net_score_3d=net, total_3d=total),
        )

    return latest_full_date, out


@router.get("/setups/summary", response_model=SetupSummaryResponse)
def get_setup_summaries(
    db: Session = Depends(get_db),
    symbols: List[str] = Query(..., description="Symbols to summarize (repeat query param)"),
    window_days: int = Query(3, ge=SETUP_MIN_WINDOW_DAYS, le=20),
):
    latest_date, summaries = _compute_setup_summaries(db, symbols=symbols, window_days=window_days)
    items = [
        summaries[s.upper()] for s in symbols if s and s.strip() and s.strip().upper() in summaries
    ]
    return SetupSummaryResponse(items=items)


@router.get("/setups/symbol", response_model=SetupSymbolResponse)
def get_setup_symbol_view(
    db: Session = Depends(get_db),
    symbol: str = Query(..., min_length=1, max_length=20),
    window_days: int = Query(3, ge=SETUP_MIN_WINDOW_DAYS, le=20),
    focus_slug: Optional[str] = Query(
        None, description="Optional focus bucket slug (e.g., momentum, breakout)"
    ),
):
    sym = symbol.strip().upper()
    _latest_date, summaries = _compute_setup_summaries(db, symbols=[sym], window_days=window_days)
    summary = summaries.get(sym)
    if summary is None:
        raise HTTPException(status_code=404, detail="Symbol not found in latest screener snapshot")

    if focus_slug is not None:
        focus_norm = focus_slug.strip().lower()
        if focus_norm and focus_norm not in SETUP_TAXONOMY_SLUGS:
            raise HTTPException(status_code=400, detail="Invalid focus_slug")
    else:
        focus_norm = None

    latest_date_key = _setup_latest_date_key(db)
    if latest_date_key is None:
        raise HTTPException(status_code=404, detail="No screener data available")
    latest_full_date = db.execute(
        select(DimDate.full_date).where(DimDate.date_key == latest_date_key)
    ).scalar_one_or_none()
    if latest_full_date is None:
        raise HTTPException(status_code=404, detail="No screener dates available")
    window_days_rows = _setup_available_screener_days(db, limit=window_days)
    window_date_keys = [k for k, _d in window_days_rows]

    hit_rows = db.execute(
        select(
            DimDate.full_date,
            DimStyle.style_name,
            DimStyle.position_side,
            DimStyle.screener_weight,
            DimSource.source_name,
            DimSource.screener_weight,
            FactScreenerRank.rank_value,
        )
        .select_from(FactScreenerRank)
        .join(DimStock, DimStock.stock_key == FactScreenerRank.stock_key)
        .join(DimDate, DimDate.date_key == FactScreenerRank.date_key)
        .join(DimSource, DimSource.source_key == FactScreenerRank.source_key)
        .outerjoin(DimStyle, DimStyle.style_key == FactScreenerRank.style_key)
        .where(and_(DimStock.symbol == sym, FactScreenerRank.date_key.in_(window_date_keys)))
        .order_by(DimDate.full_date.desc())
    ).all()

    hits_by_date: dict[date, list[SetupHit]] = {d: [] for _k, d in window_days_rows}
    for (
        as_of_date,
        style_name,
        position_side,
        style_weight,
        source_name,
        source_weight,
        rank_value,
    ) in hit_rows:
        bucket_label, bucket_slug, bucket_interactive = _setup_bucket_for_hit(
            style_name=style_name, source_name=source_name
        )
        side = _setup_side_from_position(position_side)
        sw = float(style_weight or 1.0)
        srcw = float(source_weight or 1.0)
        w = sw * srcw
        if focus_norm and bucket_slug != focus_norm:
            continue
        hits_by_date.setdefault(as_of_date, []).append(
            SetupHit(
                as_of_date=as_of_date,
                bucket=bucket_label,
                bucket_slug=bucket_slug,
                bucket_interactive=bool(bucket_slug and bucket_interactive),
                bias=side,
                style=style_name,
                source=str(source_name),
                rank_value=int(rank_value) if rank_value is not None else None,
                weight=w,
                style_weight=sw,
                source_weight=srcw,
            )
        )

    days: list[SetupHitsDay] = []
    for _k, d in window_days_rows:
        hits = hits_by_date.get(d, [])
        hits.sort(key=lambda h: h.weight, reverse=True)
        days.append(SetupHitsDay(as_of_date=d, hits=hits))

    return SetupSymbolResponse(summary=summary, days=days, focus_slug=focus_norm)


# Centralized style → regime bias map for breadth signing.
# If a style is not listed, we fall back to position_side ('short' → Bearish, else Bullish).
STYLE_REGIME_MAP: dict[str, str] = {
    "Momentum": "Bullish",
    "Pullback": "Bullish",
    "QualityGrowth": "Bullish",
    "ValueGARP": "Bullish",
    "Value": "Bullish",
    "Growth": "Bullish",
    "IPO": "Bullish",
    "EarningsPost": "Bullish",
    "Squeeze": "Bullish",
    "ShortSqueeze": "Bullish",
    "MeanRev": "Bearish",
    "Short": "Bearish",
    "MeanReversion": "Bearish",
    "Defensive": "Bearish",
    "EarningsPre": "Bearish",
}


def _normalize_bias_filter(
    bias: Optional[str],
    position_side: Optional[str] = None,
) -> Optional[str]:
    """Normalize request bias/position inputs to Bullish/Bearish labels."""
    if bias is not None:
        normalized = bias.strip().lower()
        if normalized not in {"all", "bullish", "bearish"}:
            raise HTTPException(
                status_code=400, detail="bias must be one of: all, bullish, bearish"
            )
        if normalized == "all" or normalized == "":
            return None
        return "Bullish" if normalized == "bullish" else "Bearish"

    if position_side:
        side = position_side.strip().lower()
        return "Bullish" if side == "long" else "Bearish"

    return None


def _style_bias(style_name: str, position_side: Optional[str]) -> tuple[str, int]:
    label = STYLE_REGIME_MAP.get(style_name)
    if label is None:
        label = "Bearish" if (position_side or "").lower() == "short" else "Bullish"
    sign = 1 if label == "Bullish" else -1
    return label, sign


def _style_source_tokens(styles: Optional[List[str]]) -> List[Tuple[str, Tuple[str, ...]]]:
    """Map selected styles to (token, excludes) tuples for source filtering."""
    tokens: List[Tuple[str, Tuple[str, ...]]] = []
    if not styles:
        return tokens
    seen = set()
    for style_name in styles:
        if not style_name:
            continue
        normalized = style_name.strip().lower()
        if not normalized:
            continue
        if normalized == "momentum":
            token = "momo"
            excludes = ("short-momo",)
        elif normalized == "earningspost":
            token = "earnings-post"
            excludes = ()
        elif normalized == "earningspre":
            token = "earnings-pre"
            excludes = ()
        elif normalized == "defensive":
            token = "lowbeta"
            excludes = ()
        elif normalized == "short":
            token = "short"
            excludes = ("shortsqueeze",)
        else:
            token = normalized
            excludes = ()
        key = (token, excludes)
        if key not in seen:
            seen.add(key)
            tokens.append(key)
    return tokens


class ScreenerChangeItem(CompanyNameSanitizerMixin, BaseModel):
    change_date: date
    symbol: str
    position_side: Optional[str] = None
    regime_bias: Optional[str] = None
    company_name: Optional[str] = None
    sector: Optional[str] = None
    exchange: Optional[str] = None
    source: str
    source_weight: Optional[float] = None
    style: Optional[str] = None
    style_weight: Optional[float] = None
    change_weight: Optional[float] = None
    change_type: str
    current_rank: Optional[int] = None
    previous_rank: Optional[int] = None
    rank_delta: Optional[int] = None
    last_seen_date: Optional[date] = None
    days_since_last_seen: Optional[int] = None
    absent_trading_days: Optional[int] = None


class ScreenerChangeList(BaseModel):
    items: List[ScreenerChangeItem]
    total_count: int
    page: int
    page_size: int


@router.get("/consensus", response_model=ScreenerConsensusList)
def list_screener_consensus(
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query(None, description="Filter by symbol (exact)"),
    style: Optional[str] = Query(None, description="Deprecated – use 'styles'. Single style name."),
    styles: Optional[List[str]] = Query(None, description="Filter by one or more styles"),
    style_logic: str = Query(
        "any",
        pattern="^(any|all)$",
        description="When multiple styles are provided: any (OR) or all (AND)",
    ),
    source: Optional[str] = Query(
        None, description="Deprecated – use 'sources'. Single source name."
    ),
    sources: Optional[List[str]] = Query(None, description="Filter by one or more sources"),
    source_logic: str = Query(
        "any",
        pattern="^(any|all)$",
        description="When multiple sources are provided: any (OR) or all (AND)",
    ),
    position_side: Optional[str] = Query(
        None, pattern="^(long|short)$", description="Filter by position side (long or short)"
    ),
    appearances_min: int = Query(0, ge=0),
    styles_min: int = Query(0, ge=0),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    sort_by: str = Query(
        "consensus_score",
        description="Sort key: consensus_score, appearances, styles_distinct, sources_distinct, rank_best, min_style_rank_pct, symbol",
    ),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
):
    # Build filters once
    filters = [DimStock.is_active.is_(True)]
    if symbol:
        filters.append(VLatestScreenerConsensus.symbol == symbol.upper())
    if appearances_min > 0:
        filters.append(VLatestScreenerConsensus.appearances >= appearances_min)
    if styles_min > 0:
        filters.append(VLatestScreenerConsensus.styles_distinct >= styles_min)
    # Normalize multi-select inputs (support legacy single params too)
    styles_filter = [s for s in (styles or []) if s]
    if style:
        styles_filter.append(style)
    sources_filter = [s for s in (sources or []) if s]
    if source:
        sources_filter.append(source)

    if styles_filter:
        # include symbols that matched the selected styles (ANY or ALL) via latest values view
        base = select(VLatestScreenerValues.symbol).where(
            VLatestScreenerValues.style.in_(styles_filter)
        )
        if style_logic == "all" and len(styles_filter) > 1:
            sym_by_style = base.group_by(VLatestScreenerValues.symbol).having(
                func.count(func.distinct(VLatestScreenerValues.style)) >= len(styles_filter)
            )
        else:
            sym_by_style = base.distinct()
        filters.append(VLatestScreenerConsensus.symbol.in_(sym_by_style))

    if sources_filter:
        # include symbols that matched the selected sources (ANY or ALL) via latest values view
        base = select(VLatestScreenerValues.symbol).where(
            VLatestScreenerValues.source.in_(sources_filter)
        )
        if source_logic == "all" and len(sources_filter) > 1:
            sym_by_source = base.group_by(VLatestScreenerValues.symbol).having(
                func.count(func.distinct(VLatestScreenerValues.source)) >= len(sources_filter)
            )
        else:
            sym_by_source = base.distinct()
        filters.append(VLatestScreenerConsensus.symbol.in_(sym_by_source))

    if position_side:
        filters.append(VLatestScreenerConsensus.position_side == position_side.lower())

    # Resolve sort column
    sortable = {
        "consensus_score": VLatestScreenerConsensus.consensus_score,
        "appearances": VLatestScreenerConsensus.appearances,
        "styles_distinct": VLatestScreenerConsensus.styles_distinct,
        "sources_distinct": VLatestScreenerConsensus.sources_distinct,
        "rank_best": VLatestScreenerConsensus.rank_best,
        "min_style_rank_pct": VLatestScreenerConsensus.min_style_rank_pct,
        "symbol": VLatestScreenerConsensus.symbol,
        "position_side": VLatestScreenerConsensus.position_side,
        "long_score_raw": VLatestScreenerConsensus.long_score_raw,
        "short_score_raw": VLatestScreenerConsensus.short_score_raw,
        "net_score_raw": VLatestScreenerConsensus.net_score_raw,
        "long_pct": VLatestScreenerConsensus.long_pct,
        "short_pct": VLatestScreenerConsensus.short_pct,
        "net_pct": VLatestScreenerConsensus.net_pct,
    }
    sort_col = sortable.get(sort_by, VLatestScreenerConsensus.consensus_score)
    direction = asc if sort_order == "asc" else desc

    # Count query
    count_stmt = (
        select(func.count())
        .select_from(VLatestScreenerConsensus)
        .join(DimStock, DimStock.symbol == VLatestScreenerConsensus.symbol)
        .where(and_(*filters))
    )
    total_count = db.execute(count_stmt).scalar_one()

    # Paged query with ordering
    q = (
        select(VLatestScreenerConsensus)
        .join(DimStock, DimStock.symbol == VLatestScreenerConsensus.symbol)
        .where(and_(*filters))
        .order_by(direction(sort_col), asc(VLatestScreenerConsensus.symbol))
        .offset(skip)
        .limit(limit)
    )
    rows = db.execute(q).scalars().all()
    items = [
        ScreenerConsensusItem(
            as_of_date=row.full_date,
            symbol=row.symbol,
            position_side=row.position_side,
            company_name=row.company_name,
            sector=row.sector,
            exchange=row.exchange,
            primary_source=row.primary_source,
            primary_style=row.primary_style,
            appearances=float(row.appearances or 0),
            styles_distinct=float(row.styles_distinct or 0),
            sources_distinct=float(row.sources_distinct or 0),
            rank_best=row.rank_best,
            rank_avg=float(row.rank_avg) if row.rank_avg is not None else None,
            rank_median=float(row.rank_median) if row.rank_median is not None else None,
            min_style_rank_pct=float(row.min_style_rank_pct)
            if row.min_style_rank_pct is not None
            else None,
            long_score_raw=float(row.long_score_raw) if row.long_score_raw is not None else None,
            short_score_raw=float(row.short_score_raw) if row.short_score_raw is not None else None,
            net_score_raw=float(row.net_score_raw) if row.net_score_raw is not None else None,
            families_count_long=int(row.families_count_long)
            if row.families_count_long is not None
            else None,
            families_count_short=int(row.families_count_short)
            if row.families_count_short is not None
            else None,
            screens_count_long=int(row.screens_count_long)
            if row.screens_count_long is not None
            else None,
            screens_count_short=int(row.screens_count_short)
            if row.screens_count_short is not None
            else None,
            tier12_hits_long=int(row.tier12_hits_long)
            if row.tier12_hits_long is not None
            else None,
            tier12_hits_short=int(row.tier12_hits_short)
            if row.tier12_hits_short is not None
            else None,
            breadth_bonus_long=float(row.breadth_bonus_long)
            if row.breadth_bonus_long is not None
            else None,
            any_bonus_long=float(row.any_bonus_long) if row.any_bonus_long is not None else None,
            family_streak_bonus_long=float(row.family_streak_bonus_long)
            if row.family_streak_bonus_long is not None
            else None,
            any_bonus_short=float(row.any_bonus_short) if row.any_bonus_short is not None else None,
            family_streak_bonus_short=float(row.family_streak_bonus_short)
            if row.family_streak_bonus_short is not None
            else None,
            long_pct=float(row.long_pct) if row.long_pct is not None else None,
            short_pct=float(row.short_pct) if row.short_pct is not None else None,
            net_pct=float(row.net_pct) if row.net_pct is not None else None,
            consensus_score=float(row.consensus_score) if row.consensus_score is not None else None,
        )
        for row in rows
    ]
    return ScreenerConsensusList(
        items=items,
        total_count=int(total_count or 0),
        page=(skip // limit) + 1,
        page_size=limit,
    )


# Note: Non-meta styles/sources endpoints were removed as unused in this repo.


@router.get("/styles/meta", response_model=List[OptionCount])
def list_screener_styles_meta(
    db: Session = Depends(get_db),
    position_side: Optional[str] = Query(
        None,
        pattern="^(long|short)$",
        description="(Deprecated) legacy long/short filter. Use 'bias' instead.",
    ),
    bias: Optional[str] = Query(
        None,
        description="Optional regime bias filter. Accepts 'all' (default), 'bullish', or 'bearish'.",
    ),
):
    """List all styles with distinct symbol counts, optionally filtered by regime bias."""

    normalized_bias = _normalize_bias_filter(bias, position_side)
    q = (
        select(
            DimStyle.style_name,
            func.count(func.distinct(VLatestScreenerValues.symbol)).label("cnt"),
        )
        .select_from(DimStyle)
        .outerjoin(VLatestScreenerValues, VLatestScreenerValues.style == DimStyle.style_name)
        .group_by(DimStyle.style_name)
        .order_by(asc(DimStyle.style_name))
    )

    rows = db.execute(q).all()
    items: List[OptionCount] = []
    for style_name, cnt in rows:
        if not style_name:
            continue
        regime_bias = STYLE_REGIME_MAP.get(style_name)
        if normalized_bias and regime_bias != normalized_bias:
            continue
        items.append(OptionCount(name=style_name, count=int(cnt or 0)))
    return items


@router.get("/changes", response_model=ScreenerChangeList)
def list_screener_changes(
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query(None, description="Filter by symbol (exact, case-insensitive)"),
    styles: Optional[List[str]] = Query(None, description="Filter by styles (case-sensitive)"),
    position_side: Optional[str] = Query(
        None, pattern="^(long|short)$", description="Filter by position side (long or short)"
    ),
    sources: Optional[List[str]] = Query(None, description="Filter by source names"),
    change_types: Optional[List[str]] = Query(
        None, description="Limit to change types: entered, reentered, dropped"
    ),
    start_date: Optional[date] = Query(None, description="Earliest change date (inclusive)"),
    end_date: Optional[date] = Query(None, description="Latest change date (inclusive)"),
    latest_only: bool = Query(
        True, description="When true, restrict to the most recent change date"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    sort_by: str = Query(
        "change_date",
        description="Sort key: change_date, symbol, change_type, current_rank, previous_rank, rank_delta, absent_trading_days, days_since_last_seen",
    ),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
):
    filters = [DimStock.is_active.is_(True)]

    if symbol:
        filters.append(DimStock.symbol == symbol.upper())

    if styles:
        styles_norm = [s for s in styles if s]
        if styles_norm:
            filters.append(DimStyle.style_name.in_(styles_norm))

    if position_side:
        filters.append(DimStyle.position_side == position_side.lower())

    if sources:
        sources_norm = [s for s in sources if s]
        if sources_norm:
            filters.append(DimSource.source_name.in_(sources_norm))

    if change_types:
        normalized = {ct.lower() for ct in change_types if ct}
        unknown = normalized - ALLOWED_CHANGE_TYPES
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"Unsupported change_type(s): {', '.join(sorted(unknown))}"
            )
        filters.append(FactScreenerRankChange.change_type.in_(sorted(normalized)))
    else:
        filters.append(FactScreenerRankChange.change_type.in_(sorted(ALLOWED_CHANGE_TYPES)))

    if start_date:
        filters.append(DimDate.full_date >= start_date)
    if end_date:
        filters.append(DimDate.full_date <= end_date)

    if latest_only and not start_date and not end_date:
        latest_date_subq = select(func.max(FactScreenerRankChange.change_date_key))
        filters.append(FactScreenerRankChange.change_date_key == latest_date_subq.scalar_subquery())

    sortable = {
        "change_date": DimDate.full_date,
        "symbol": DimStock.symbol,
        "change_type": FactScreenerRankChange.change_type,
        "current_rank": FactScreenerRankChange.current_rank,
        "previous_rank": FactScreenerRankChange.previous_rank,
        "rank_delta": FactScreenerRankChange.rank_delta,
        "absent_trading_days": FactScreenerRankChange.absent_trading_days,
        "days_since_last_seen": FactScreenerRankChange.days_since_last_seen,
    }
    sort_col = sortable.get(sort_by, DimDate.full_date)
    direction = asc if sort_order == "asc" else desc

    base_from = (
        select(FactScreenerRankChange.change_id)
        .select_from(FactScreenerRankChange)
        .join(DimDate, DimDate.date_key == FactScreenerRankChange.change_date_key)
        .join(DimStock, DimStock.stock_key == FactScreenerRankChange.stock_key)
        .join(DimSource, DimSource.source_key == FactScreenerRankChange.source_key)
        .outerjoin(DimStyle, DimStyle.style_key == FactScreenerRankChange.style_key)
        .where(and_(*filters))
    )
    total_count = db.execute(select(func.count()).select_from(base_from.subquery())).scalar_one()

    last_seen_dim = aliased(DimDate)
    data_stmt = (
        select(
            DimDate.full_date.label("change_date"),
            DimStock.symbol,
            DimStock.company_name,
            DimStock.sector,
            DimStock.exchange,
            DimSource.source_name,
            DimSource.screener_weight.label("source_weight"),
            DimStyle.style_name,
            DimStyle.position_side,
            DimStyle.screener_weight.label("style_weight"),
            FactScreenerRankChange.change_type,
            FactScreenerRankChange.current_rank,
            FactScreenerRankChange.previous_rank,
            FactScreenerRankChange.rank_delta,
            last_seen_dim.full_date.label("last_seen_date"),
            FactScreenerRankChange.days_since_last_seen,
            FactScreenerRankChange.absent_trading_days,
            (DimStyle.screener_weight * DimSource.screener_weight).label("change_weight"),
        )
        .select_from(FactScreenerRankChange)
        .join(DimDate, DimDate.date_key == FactScreenerRankChange.change_date_key)
        .join(DimStock, DimStock.stock_key == FactScreenerRankChange.stock_key)
        .join(DimSource, DimSource.source_key == FactScreenerRankChange.source_key)
        .outerjoin(DimStyle, DimStyle.style_key == FactScreenerRankChange.style_key)
        .outerjoin(
            last_seen_dim, last_seen_dim.date_key == FactScreenerRankChange.last_seen_date_key
        )
        .where(and_(*filters))
        .order_by(direction(sort_col), desc(DimStock.symbol))
        .offset(skip)
        .limit(limit)
    )

    rows = db.execute(data_stmt).all()

    items = []
    for row in rows:
        # Determine regime bias for styling/clients (reuse map from breadth)
        try:
            rbias, _ = _style_bias(row.style_name or "", row.position_side)
        except Exception:
            rbias = None
        items.append(
            ScreenerChangeItem(
                change_date=row.change_date,
                symbol=row.symbol,
                company_name=row.company_name,
                sector=row.sector,
                exchange=row.exchange,
                source=row.source_name,
                source_weight=float(row.source_weight) if row.source_weight is not None else None,
                style=row.style_name,
                style_weight=float(row.style_weight) if row.style_weight is not None else None,
                change_weight=float(row.change_weight) if row.change_weight is not None else None,
                position_side=row.position_side,
                regime_bias=rbias,
                change_type=row.change_type,
                current_rank=row.current_rank,
                previous_rank=row.previous_rank,
                rank_delta=row.rank_delta,
                last_seen_date=row.last_seen_date,
                days_since_last_seen=row.days_since_last_seen,
                absent_trading_days=row.absent_trading_days,
            )
        )

    return ScreenerChangeList(
        items=items,
        total_count=int(total_count or 0),
        page=(skip // limit) + 1,
        page_size=limit,
    )


@router.get("/sources/meta", response_model=List[OptionCount])
def list_screener_sources_meta(
    db: Session = Depends(get_db),
    position_side: Optional[str] = Query(
        None, pattern="^(long|short)$", description="Filter by position side (long or short)"
    ),
    prefix: Optional[str] = Query(
        None,
        min_length=1,
        description="Optional case-insensitive prefix filter for source names (e.g., 'RA').",
    ),
    styles: Optional[List[str]] = Query(
        None,
        description="Optional list of selected styles; when provided, only sources whose name contains one of the styles (Momentum → 'momo') are returned.",
    ),
):
    """List all screener sources (exclude_from_screener != true) and latest-day distinct symbol counts (0 when absent)."""
    if position_side:
        q = (
            select(
                DimSource.source_name,
                func.count(
                    func.distinct(
                        func.nullif(
                            func.case(
                                (
                                    VLatestScreenerValues.position_side == position_side.lower(),
                                    VLatestScreenerValues.symbol,
                                ),
                                else_=None,
                            ),
                            None,
                        )
                    )
                ).label("cnt"),
            )
            .select_from(DimSource)
            .where(DimSource.exclude_from_screener.isnot(True))
            .outerjoin(VLatestScreenerValues, VLatestScreenerValues.source == DimSource.source_name)
            .group_by(DimSource.source_name)
            .order_by(asc(DimSource.source_name))
        )
    else:
        q = (
            select(
                DimSource.source_name,
                func.count(func.distinct(VLatestScreenerValues.symbol)).label("cnt"),
            )
            .select_from(DimSource)
            .where(DimSource.exclude_from_screener.isnot(True))
            .outerjoin(VLatestScreenerValues, VLatestScreenerValues.source == DimSource.source_name)
            .group_by(DimSource.source_name)
            .order_by(asc(DimSource.source_name))
        )
    rows = db.execute(q).all()
    normalized_prefix = prefix.upper() if prefix else None
    style_filters = _style_source_tokens(styles)
    items: List[OptionCount] = []
    for source_name, cnt in rows:
        if not source_name:
            continue
        if normalized_prefix and not source_name.upper().startswith(normalized_prefix):
            continue
        if style_filters:
            normalized_source = source_name.lower()
            matched = False
            for token, excludes in style_filters:
                if token not in normalized_source:
                    continue
                if excludes and any(ex in normalized_source for ex in excludes):
                    continue
                matched = True
                break
            if not matched:
                continue
        items.append(OptionCount(name=source_name, count=int(cnt or 0)))
    return items


class ScreenerBreadthItem(BaseModel):
    change_date: date
    style_key: int
    style_name: str
    position_side: str
    regime_bias: str
    entered_count: float
    reentered_count: float
    dropped_count: float
    eligible_count: float
    entered_pct: float
    dropped_pct: float
    net_pct: float
    net_pct_signed: float
    entered_pct_avg_5d: float
    dropped_pct_avg_5d: float
    net_pct_avg_5d: float
    net_pct_avg_5d_signed: float


class ScreenerBreadthList(BaseModel):
    items: List[ScreenerBreadthItem]
    total_count: int
    page: int
    page_size: int


@router.get("/breadth", response_model=ScreenerBreadthList)
def list_screener_breadth(
    db: Session = Depends(get_db),
    styles: Optional[List[str]] = Query(None, description="Filter by style name"),
    position_side: Optional[str] = Query(
        None, pattern="^(long|short)$", description="Filter by position side (long or short)"
    ),
    start_date: Optional[date] = Query(None, description="Earliest change date (inclusive)"),
    end_date: Optional[date] = Query(None, description="Latest change date (inclusive)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
):
    filters = []
    if styles:
        valid_styles = [s for s in styles if s]
        if valid_styles:
            filters.append(MVScreenerBreadth.style_name.in_(valid_styles))
    if position_side:
        filters.append(MVScreenerBreadth.position_side == position_side.lower())
    if start_date:
        filters.append(MVScreenerBreadth.change_date >= start_date)
    if end_date:
        filters.append(MVScreenerBreadth.change_date <= end_date)

    base_query = (
        select(MVScreenerBreadth).where(and_(*filters)) if filters else select(MVScreenerBreadth)
    )

    count_stmt = select(func.count()).select_from(base_query.subquery())
    total_count = db.execute(count_stmt).scalar_one()

    order_clause = (
        asc(MVScreenerBreadth.change_date)
        if sort_order == "asc"
        else desc(MVScreenerBreadth.change_date)
    )

    data_stmt = base_query.order_by(order_clause).offset(skip).limit(limit)

    rows = db.execute(data_stmt).scalars().all()

    items: list[ScreenerBreadthItem] = []
    for row in rows:
        rbias, sign = _style_bias(row.style_name, row.position_side)
        entered_pct = float(row.entered_pct or 0.0)
        dropped_pct = float(row.dropped_pct or 0.0)
        net_pct = float(row.net_pct or 0.0)
        net_pct_avg_5d = float(row.net_pct_avg_5d or 0.0)
        items.append(
            ScreenerBreadthItem(
                change_date=row.change_date,
                style_key=row.style_key,
                style_name=row.style_name,
                position_side=row.position_side,
                regime_bias=rbias,
                entered_count=float(row.entered_count or 0.0),
                reentered_count=float(row.reentered_count or 0.0),
                dropped_count=float(row.dropped_count or 0.0),
                eligible_count=float(row.eligible_count or 0.0),
                entered_pct=entered_pct,
                dropped_pct=dropped_pct,
                net_pct=net_pct,
                net_pct_signed=sign * net_pct,
                entered_pct_avg_5d=float(row.entered_pct_avg_5d or 0.0),
                dropped_pct_avg_5d=float(row.dropped_pct_avg_5d or 0.0),
                net_pct_avg_5d=net_pct_avg_5d,
                net_pct_avg_5d_signed=sign * net_pct_avg_5d,
            )
        )

    return ScreenerBreadthList(
        items=items,
        total_count=int(total_count or 0),
        page=(skip // limit) + 1,
        page_size=limit,
    )


class ScreenerBreadthFlowItem(BaseModel):
    change_date: date
    canonical_name: str
    regime_bias: str
    entered_count: float
    dropped_count: float
    continuers_count: float
    eligible_count: float
    entered_pct: float
    dropped_pct: float
    continuers_pct: float
    net_pct_us: float
    net_pct_us_signed: float
    churn_pct: float
    churn_pct_signed: float


class ScreenerBreadthFlowList(BaseModel):
    items: List[ScreenerBreadthFlowItem]
    total_count: int
    page: int
    page_size: int


@router.get("/breadth/flow", response_model=ScreenerBreadthFlowList)
def list_screener_breadth_flow(
    db: Session = Depends(get_db),
    styles: Optional[List[str]] = Query(None, description="Filter by canonical style name"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
):
    filters = []
    if styles:
        good = [s for s in styles if s]
        if good:
            filters.append(MvScreenerBreadthFlow.canonical_name.in_(good))
    if start_date:
        filters.append(MvScreenerBreadthFlow.change_date >= start_date)
    if end_date:
        filters.append(MvScreenerBreadthFlow.change_date <= end_date)

    base_query = (
        select(MvScreenerBreadthFlow).where(and_(*filters))
        if filters
        else select(MvScreenerBreadthFlow)
    )
    count_stmt = select(func.count()).select_from(base_query.subquery())
    total_count = db.execute(count_stmt).scalar_one()

    order_clause = (
        asc(MvScreenerBreadthFlow.change_date)
        if sort_order == "asc"
        else desc(MvScreenerBreadthFlow.change_date)
    )
    rows = db.execute(base_query.order_by(order_clause).offset(skip).limit(limit)).scalars().all()

    items: list[ScreenerBreadthFlowItem] = []
    for row in rows:
        name = row.canonical_name
        rbias, sign = _style_bias(name, None)
        net_pct_us = float(row.net_pct_us or 0.0)
        churn_pct = float(row.churn_pct or 0.0)
        items.append(
            ScreenerBreadthFlowItem(
                change_date=row.change_date,
                canonical_name=name,
                regime_bias=rbias,
                entered_count=float(row.entered_count or 0.0),
                dropped_count=float(row.dropped_count or 0.0),
                continuers_count=float(row.continuers_count or 0.0),
                eligible_count=float(row.eligible_count or 0.0),
                entered_pct=float(row.entered_pct or 0.0),
                dropped_pct=float(row.dropped_pct or 0.0),
                continuers_pct=float(row.continuers_pct or 0.0),
                net_pct_us=net_pct_us,
                net_pct_us_signed=sign * net_pct_us,
                churn_pct=churn_pct,
                churn_pct_signed=sign * churn_pct,
            )
        )

    return ScreenerBreadthFlowList(
        items=items,
        total_count=int(total_count or 0),
        page=(skip // limit) + 1,
        page_size=limit,
    )
