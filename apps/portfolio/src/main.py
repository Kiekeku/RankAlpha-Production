from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal
from typing import Callable, Iterable

from sqlalchemy import delete, desc, func, select
from sqlalchemy.dialects.postgresql import insert

from apps.common.src.crud import upsert_nav
from apps.common.src.db.session import session_scope
from apps.common.src.logging import get_logger, setup_logging
from apps.common.src.models import (
    DimDate,
    DimStock,
    FactModelStrategyNav,
    FactPortfolioBrokerNlv,
    FactPortfolioNav,
    FactPortfolioPnl,
    FactPortfolioPositionHist,
    FactSecurityPrice,
    Portfolio,
    PortfolioCashPosition,
    PortfolioPosition,
    PortfolioRunArtifact,
    PortfolioRunPosition,
)
from apps.common.src.portfolio.construction import (
    create_portfolio_run,
    ensure_model_construction_run,
    generate_broker_rebalance_run,
)
from apps.common.src.portfolio.fx import FXConfig, fx_mid_px
from apps.portfolio.src.settings import Settings

logger = get_logger("portfolio")


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"Invalid date: {value}") from exc


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"Invalid UUID: {value}") from exc


def _resolve_date_key(session, as_of_date: date) -> int:
    date_key = session.scalar(select(DimDate.date_key).where(DimDate.full_date == as_of_date))
    if date_key is None:
        raise ValueError(f"Date {as_of_date} not found in dim_date")
    return int(date_key)


def _latest_trading_day_before(session, *, before: date) -> date:
    d = session.scalar(
        select(DimDate.full_date)
        .where(DimDate.full_date < before)
        .where(DimDate.is_trading_day.is_(True))
        .order_by(DimDate.full_date.desc())
        .limit(1)
    )
    if d is None:
        raise ValueError(f"Unable to resolve latest trading day before {before}")
    return d


def _close_px_by_stock(session, *, date_key: int, stock_keys: Iterable[int]) -> dict[int, Decimal]:
    rows = session.execute(
        select(FactSecurityPrice.stock_key, FactSecurityPrice.close_px)
        .where(FactSecurityPrice.date_key == date_key)
        .where(FactSecurityPrice.stock_key.in_(list(stock_keys)))
    ).all()
    return {int(k): (px or Decimal("0")) for k, px in rows}


def _compute_nav_for_portfolio(session, *, portfolio: Portfolio, date_key: int) -> Decimal | None:
    base_ccy = str(getattr(portfolio, "currency_code", "USD") or "USD").upper()
    fx_cache: dict[tuple[int, str, str, str, int, bool], Decimal | None] = {}

    positions = list(
        session.scalars(
            select(PortfolioPosition).where(
                PortfolioPosition.portfolio_id == portfolio.portfolio_id
            )
        ).all()
    )
    cash = list(
        session.scalars(
            select(PortfolioCashPosition).where(
                PortfolioCashPosition.portfolio_id == portfolio.portfolio_id
            )
        ).all()
    )

    if not positions and not cash:
        return None

    stock_keys = {int(p.stock_key) for p in positions}
    px_by_stock = (
        _close_px_by_stock(session, date_key=date_key, stock_keys=stock_keys) if stock_keys else {}
    )

    equity_value = Decimal("0")
    missing_prices: list[str] = []
    if positions:
        from apps.common.src.models import DimStock  # local import to keep CLI import-light

        stock_rows = session.execute(
            select(DimStock.stock_key, DimStock.currency_code, DimStock.symbol).where(
                DimStock.stock_key.in_(list(stock_keys))
            )
        ).all()
        ccy_by_stock = {int(k): str(ccy or "").upper() for k, ccy, _sym in stock_rows}
        sym_by_stock = {int(k): str(sym or k) for k, _ccy, sym in stock_rows}

        missing_fx: set[str] = set()
        for pos in positions:
            qty = Decimal(pos.quantity or 0)
            px_local = px_by_stock.get(int(pos.stock_key), Decimal("0"))
            if qty != 0 and px_local <= 0:
                missing_prices.append(sym_by_stock.get(int(pos.stock_key), str(pos.stock_key)))
                continue
            local_ccy = ccy_by_stock.get(int(pos.stock_key), base_ccy) or base_ccy
            fx = fx_mid_px(
                session,
                date_key=int(date_key),
                from_ccy=local_ccy,
                to_ccy=base_ccy,
                cfg=FXConfig(
                    pivot_ccy="USD", max_lookback_days=30, fallback_to_last_available=True
                ),
                cache=fx_cache,
            )
            if fx is None:
                missing_fx.add(local_ccy)
                continue
            equity_value += qty * px_local * fx
        if missing_fx:
            logger.warning(
                "Missing FX rates for %s->%s on date_key=%s; skipping NAV for %s",
                sorted(missing_fx),
                base_ccy,
                date_key,
                portfolio.portfolio_name,
            )
            return None
    if missing_prices:
        logger.warning(
            "Missing close prices for %s on date_key=%s; skipping NAV for %s",
            sorted(set(missing_prices)),
            date_key,
            portfolio.portfolio_name,
        )
        return None

    cash_value = Decimal("0")
    missing_fx_cash: set[str] = set()
    for c in cash:
        ccy = str(getattr(c, "currency_code", "") or "").upper() or base_ccy
        amt = Decimal(c.cash_amount or 0)
        fx = fx_mid_px(
            session,
            date_key=int(date_key),
            from_ccy=ccy,
            to_ccy=base_ccy,
            cfg=FXConfig(pivot_ccy="USD", max_lookback_days=30, fallback_to_last_available=True),
            cache=fx_cache,
        )
        if fx is None:
            missing_fx_cash.add(ccy)
            continue
        cash_value += amt * fx
    if missing_fx_cash:
        logger.warning(
            "Missing FX rates for %s->%s on date_key=%s; skipping NAV for %s",
            sorted(missing_fx_cash),
            base_ccy,
            date_key,
            portfolio.portfolio_name,
        )
        return None

    return equity_value + cash_value


def sync_nav(settings: Settings, *, as_of_date: date | None) -> int:
    with session_scope() as session:
        if as_of_date is None:
            as_of_date = _latest_trading_day_before(session, before=date.today())
        date_key = _resolve_date_key(session, as_of_date)

        portfolios = list(session.scalars(select(Portfolio)).all())
        updated = 0
        for p in portfolios:
            nav = _compute_nav_for_portfolio(session, portfolio=p, date_key=date_key)
            if nav is None:
                continue
            if settings.portfolio_nav_skip_zero and nav == 0:
                continue
            upsert_nav(
                session,
                date_key=date_key,
                portfolio_id=p.portfolio_id,
                nav_base_ccy=float(nav),
                gross_leverage=None,
                inflow=None,
                outflow=None,
            )
            updated += 1

        logger.info("Upserted NAV rows: %s (as_of_date=%s)", updated, as_of_date)
        return updated


def _upsert_daily_total_pnl(
    session, *, date_key: int, portfolio_id: uuid.UUID, total_pnl: Decimal
) -> None:
    stmt = (
        insert(FactPortfolioPnl)
        .values(
            date_key=int(date_key),
            portfolio_id=portfolio_id,
            unrealised_pnl=float(total_pnl),
            realised_pnl=None,
            dividend_income=None,
            fees=None,
        )
        .on_conflict_do_update(
            constraint="fact_portfolio_pnl_pkey",
            set_={
                "unrealised_pnl": float(total_pnl),
                "realised_pnl": None,
                "dividend_income": None,
                "fees": None,
            },
        )
    )
    session.execute(stmt)


def _upsert_model_strategy_nav(
    session,
    *,
    date_key: int,
    model_portfolio_id: uuid.UUID,
    source_key: int,
    strategy_name: str,
    nav_base_ccy: Decimal,
) -> None:
    stmt = (
        insert(FactModelStrategyNav)
        .values(
            date_key=int(date_key),
            model_portfolio_id=model_portfolio_id,
            source_key=int(source_key),
            strategy_name=str(strategy_name),
            nav_base_ccy=float(nav_base_ccy),
        )
        .on_conflict_do_update(
            index_elements=[
                FactModelStrategyNav.date_key,
                FactModelStrategyNav.model_portfolio_id,
                FactModelStrategyNav.source_key,
                FactModelStrategyNav.strategy_name,
            ],
            set_={"nav_base_ccy": float(nav_base_ccy), "load_ts": func.now()},
        )
    )
    session.execute(stmt)


def _get_nav(session, *, date_key: int, portfolio_id: uuid.UUID) -> Decimal | None:
    nav = session.scalar(
        select(FactPortfolioNav.nav_base_ccy)
        .where(FactPortfolioNav.date_key == int(date_key))
        .where(FactPortfolioNav.portfolio_id == portfolio_id)
        .limit(1)
    )
    if nav is None:
        return None
    try:
        return Decimal(nav)
    except Exception:
        return None


def _latest_nav_on_or_before(session, *, date_key: int, portfolio_id: uuid.UUID) -> Decimal | None:
    nav = session.scalar(
        select(FactPortfolioNav.nav_base_ccy)
        .where(FactPortfolioNav.date_key <= int(date_key))
        .where(FactPortfolioNav.portfolio_id == portfolio_id)
        .order_by(desc(FactPortfolioNav.date_key))
        .limit(1)
    )
    if nav is None:
        return None
    try:
        return Decimal(nav)
    except Exception:
        return None


def _compute_weighted_return_base(
    *,
    weights: dict[int, Decimal],
    close_prev: dict[int, Decimal],
    close_today: dict[int, Decimal],
    ccy_by_stock: dict[int, str],
    base_ccy: str,
    fx_prev: Callable[[str], Decimal | None],
    fx_today: Callable[[str], Decimal | None],
) -> tuple[Decimal, list[dict[str, str]]]:
    missing_inputs: list[dict[str, str]] = []
    portfolio_ret = Decimal("0")

    for stock_key, w in weights.items():
        px0 = close_prev.get(int(stock_key), Decimal("0"))
        px1 = close_today.get(int(stock_key), Decimal("0"))
        if px0 <= 0 or px1 <= 0:
            missing_inputs.append({"stock_key": str(stock_key), "reason": "missing_close_px"})
            continue

        local_ccy = (ccy_by_stock.get(int(stock_key), base_ccy) or base_ccy).upper()
        fx0 = fx_prev(local_ccy)
        fx1 = fx_today(local_ccy)
        if fx0 is None or fx1 is None:
            missing_inputs.append(
                {
                    "stock_key": str(stock_key),
                    "reason": f"missing_fx_{local_ccy}_to_{base_ccy.upper()}",
                }
            )
            continue

        # Base-currency close-to-close return.
        r = (px1 * fx1) / (px0 * fx0) - Decimal("1")
        portfolio_ret += w * r

    return portfolio_ret, missing_inputs


def rollup_performance(settings: Settings, *, as_of_date: date | None) -> int:
    """Compute and persist daily NAV/P&L for portfolios.

    Notes:
    - BROKER portfolios: prefers broker NLV (`fact_portfolio_broker_nlv`) for NAV.
    - MODEL portfolios: computes a close-to-close synthetic NAV using model TARGET weights
      from the *previous* trading day (held over the day being evaluated).
    - This is a close-based approximation (no intraday fills, slippage, financing, borrow).
    """
    with session_scope() as session:
        if as_of_date is None:
            as_of_date = _latest_trading_day_before(session, before=date.today())
        prev_date = _latest_trading_day_before(session, before=as_of_date)

        date_key = _resolve_date_key(session, as_of_date)
        prev_date_key = _resolve_date_key(session, prev_date)

        portfolios = list(session.scalars(select(Portfolio)).all())
        updated = 0

        for p in portfolios:
            kind = str(getattr(p, "portfolio_kind", "") or "").upper()
            base_ccy = str(getattr(p, "currency_code", "USD") or "USD").upper()
            fx_cache_prev: dict[tuple[int, str, str, str, int, bool], Decimal | None] = {}
            fx_cache_today: dict[tuple[int, str, str, str, int, bool], Decimal | None] = {}

            if kind == "BROKER":
                nlv = session.scalar(
                    select(FactPortfolioBrokerNlv.nlv_base_ccy)
                    .where(FactPortfolioBrokerNlv.date_key == int(date_key))
                    .where(FactPortfolioBrokerNlv.portfolio_id == p.portfolio_id)
                    .limit(1)
                )
                if nlv is None:
                    continue
                nav_today = Decimal(nlv)
                upsert_nav(
                    session,
                    date_key=date_key,
                    portfolio_id=p.portfolio_id,
                    nav_base_ccy=float(nav_today),
                    gross_leverage=None,
                    inflow=None,
                    outflow=None,
                )
                nav_prev = _get_nav(session, date_key=prev_date_key, portfolio_id=p.portfolio_id)
                if nav_prev is not None:
                    _upsert_daily_total_pnl(
                        session,
                        date_key=date_key,
                        portfolio_id=p.portfolio_id,
                        total_pnl=(nav_today - nav_prev),
                    )
                updated += 1
                continue

            if kind != "MODEL":
                continue

            nav_prev = _get_nav(session, date_key=prev_date_key, portfolio_id=p.portfolio_id)
            if nav_prev is None:
                historical_nav = _latest_nav_on_or_before(
                    session, date_key=prev_date_key, portfolio_id=p.portfolio_id
                )
                if historical_nav is not None:
                    nav_prev = historical_nav
                    logger.warning(
                        "Using last available NAV for %s (%s) at/before prev_date=%s",
                        p.portfolio_name,
                        p.portfolio_id,
                        prev_date,
                    )
                else:
                    # Seed a synthetic starting NAV only when no history exists at all.
                    nav_prev = Decimal("100")
                    upsert_nav(
                        session,
                        date_key=prev_date_key,
                        portfolio_id=p.portfolio_id,
                        nav_base_ccy=float(nav_prev),
                        gross_leverage=None,
                        inflow=None,
                        outflow=None,
                    )

            # Use weights from previous trading day over the evaluated day.
            model_run_id = ensure_model_construction_run(
                session,
                model_portfolio_id=uuid.UUID(str(p.portfolio_id)),
                as_of_date=prev_date,
                created_by="portfolio.rollup_performance",
            )
            rows = session.execute(
                select(PortfolioRunPosition.stock_key, PortfolioRunPosition.weight_pct)
                .where(PortfolioRunPosition.run_id == model_run_id)
                .where(PortfolioRunPosition.position_role == "TARGET")
                .where(PortfolioRunPosition.instrument_type == "EQUITY")
            ).all()
            weights: dict[int, Decimal] = {
                int(k): (Decimal(w or 0) / Decimal("100"))
                for k, w in rows
                if k is not None and w is not None
            }

            if not weights:
                upsert_nav(
                    session,
                    date_key=date_key,
                    portfolio_id=p.portfolio_id,
                    nav_base_ccy=float(nav_prev),
                    gross_leverage=None,
                    inflow=None,
                    outflow=None,
                )
                _upsert_daily_total_pnl(
                    session, date_key=date_key, portfolio_id=p.portfolio_id, total_pnl=Decimal("0")
                )
                updated += 1
                continue

            stock_keys = list(weights.keys())
            close_prev = _close_px_by_stock(session, date_key=prev_date_key, stock_keys=stock_keys)
            close_today = _close_px_by_stock(session, date_key=date_key, stock_keys=stock_keys)

            stock_rows = session.execute(
                select(DimStock.stock_key, DimStock.currency_code).where(
                    DimStock.stock_key.in_(stock_keys)
                )
            ).all()
            ccy_by_stock = {int(k): str(ccy or "").upper() for k, ccy in stock_rows}

            portfolio_ret, missing_inputs = _compute_weighted_return_base(
                weights=weights,
                close_prev=close_prev,
                close_today=close_today,
                ccy_by_stock=ccy_by_stock,
                base_ccy=base_ccy,
                fx_prev=lambda ccy: fx_mid_px(
                    session,
                    date_key=int(prev_date_key),
                    from_ccy=ccy,
                    to_ccy=base_ccy,
                    cfg=FXConfig(
                        pivot_ccy="USD", max_lookback_days=30, fallback_to_last_available=True
                    ),
                    cache=fx_cache_prev,
                ),
                fx_today=lambda ccy: fx_mid_px(
                    session,
                    date_key=int(date_key),
                    from_ccy=ccy,
                    to_ccy=base_ccy,
                    cfg=FXConfig(
                        pivot_ccy="USD", max_lookback_days=30, fallback_to_last_available=True
                    ),
                    cache=fx_cache_today,
                ),
            )

            if missing_inputs:
                logger.warning(
                    "Skipping model NAV rollup for %s (%s): missing inputs (as_of_date=%s prev_date=%s) %s",
                    p.portfolio_name,
                    p.portfolio_id,
                    as_of_date,
                    prev_date,
                    missing_inputs[:10],
                )
                continue

            nav_today = nav_prev * (Decimal("1") + portfolio_ret)
            upsert_nav(
                session,
                date_key=date_key,
                portfolio_id=p.portfolio_id,
                nav_base_ccy=float(nav_today),
                gross_leverage=None,
                inflow=None,
                outflow=None,
            )
            _upsert_daily_total_pnl(
                session,
                date_key=date_key,
                portfolio_id=p.portfolio_id,
                total_pnl=(nav_today - nav_prev),
            )

            # Persist model position history snapshot (effective for as_of_date; derived from prev close weights).
            session.execute(
                delete(FactPortfolioPositionHist)
                .where(FactPortfolioPositionHist.effective_date == as_of_date)
                .where(FactPortfolioPositionHist.portfolio_id == p.portfolio_id)
            )
            for stock_key, w in weights.items():
                if w == 0:
                    continue
                px0 = close_prev.get(int(stock_key), Decimal("0"))
                if px0 <= 0:
                    continue
                local_ccy = (ccy_by_stock.get(int(stock_key), base_ccy) or base_ccy).upper()
                fx0 = fx_mid_px(
                    session,
                    date_key=int(prev_date_key),
                    from_ccy=local_ccy,
                    to_ccy=base_ccy,
                    cfg=FXConfig(
                        pivot_ccy="USD", max_lookback_days=30, fallback_to_last_available=True
                    ),
                    cache=fx_cache_prev,
                )
                if fx0 is None:
                    continue
                close0_base = px0 * fx0
                if close0_base <= 0:
                    continue
                qty = (nav_prev * w) / close0_base
                session.execute(
                    insert(FactPortfolioPositionHist)
                    .values(
                        effective_date=as_of_date,
                        portfolio_id=p.portfolio_id,
                        stock_key=int(stock_key),
                        quantity=qty,
                        avg_cost=None,
                        run_id=model_run_id,
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            FactPortfolioPositionHist.effective_date,
                            FactPortfolioPositionHist.portfolio_id,
                            FactPortfolioPositionHist.stock_key,
                        ],
                        set_={"quantity": qty, "avg_cost": None, "run_id": model_run_id},
                    )
                )

            # Persist per-strategy NAV series for attribution (best-effort).
            strat_payload = session.scalar(
                select(PortfolioRunArtifact.payload)
                .where(PortfolioRunArtifact.run_id == model_run_id)
                .where(PortfolioRunArtifact.artifact_type == "model_strategy_weights")
                .limit(1)
            )
            if isinstance(strat_payload, dict):
                strategies = strat_payload.get("strategies") or []
                if isinstance(strategies, list):
                    for s in strategies:
                        if not isinstance(s, dict):
                            continue
                        source_key = s.get("source_key")
                        strategy_name = s.get("strategy_name")
                        alloc_weight_pct = s.get("alloc_weight_pct")
                        if source_key is None or strategy_name is None or alloc_weight_pct is None:
                            continue
                        try:
                            alloc_frac = Decimal(str(alloc_weight_pct)) / Decimal("100")
                        except Exception:
                            continue
                        if alloc_frac < 0:
                            continue

                        nav_prev_s = nav_prev * alloc_frac
                        prev_exists = session.scalar(
                            select(FactModelStrategyNav.nav_base_ccy)
                            .where(FactModelStrategyNav.date_key == int(prev_date_key))
                            .where(FactModelStrategyNav.model_portfolio_id == p.portfolio_id)
                            .where(FactModelStrategyNav.source_key == int(source_key))
                            .where(FactModelStrategyNav.strategy_name == str(strategy_name))
                            .limit(1)
                        )
                        if prev_exists is None:
                            _upsert_model_strategy_nav(
                                session,
                                date_key=prev_date_key,
                                model_portfolio_id=p.portfolio_id,
                                source_key=int(source_key),
                                strategy_name=str(strategy_name),
                                nav_base_ccy=nav_prev_s,
                            )

                        pos = s.get("positions") or []
                        if not isinstance(pos, list):
                            continue
                        strat_weights: dict[int, Decimal] = {}
                        for item in pos:
                            if not isinstance(item, dict):
                                continue
                            sk = item.get("stock_key")
                            wp = item.get("weight_pct")
                            if sk is None or wp is None:
                                continue
                            try:
                                strat_weights[int(sk)] = Decimal(str(wp)) / Decimal("100")
                            except Exception:
                                continue

                        contrib, missing_s = _compute_weighted_return_base(
                            weights=strat_weights,
                            close_prev=close_prev,
                            close_today=close_today,
                            ccy_by_stock=ccy_by_stock,
                            base_ccy=base_ccy,
                            fx_prev=lambda ccy: fx_mid_px(
                                session,
                                date_key=int(prev_date_key),
                                from_ccy=ccy,
                                to_ccy=base_ccy,
                                cfg=FXConfig(
                                    pivot_ccy="USD",
                                    max_lookback_days=30,
                                    fallback_to_last_available=True,
                                ),
                                cache=fx_cache_prev,
                            ),
                            fx_today=lambda ccy: fx_mid_px(
                                session,
                                date_key=int(date_key),
                                from_ccy=ccy,
                                to_ccy=base_ccy,
                                cfg=FXConfig(
                                    pivot_ccy="USD",
                                    max_lookback_days=30,
                                    fallback_to_last_available=True,
                                ),
                                cache=fx_cache_today,
                            ),
                        )
                        if missing_s:
                            continue
                        # `contrib` is the contribution to total portfolio return (i.e., sum(w_i * r_i)
                        # where weights are already scaled by alloc_frac). Convert to a sleeve return.
                        nav_prev_s = nav_prev * alloc_frac
                        sleeve_ret = Decimal("0")
                        if alloc_frac > 0:
                            sleeve_ret = contrib / alloc_frac
                        nav_today_s = nav_prev_s * (Decimal("1") + sleeve_ret)
                        _upsert_model_strategy_nav(
                            session,
                            date_key=date_key,
                            model_portfolio_id=p.portfolio_id,
                            source_key=int(source_key),
                            strategy_name=str(strategy_name),
                            nav_base_ccy=nav_today_s,
                        )

            updated += 1

        logger.info(
            "Rolled up NAV/PnL rows: %s (as_of_date=%s prev_date=%s)",
            updated,
            as_of_date,
            prev_date,
        )
        return updated


def build_model_run(
    settings: Settings,
    *,
    model_portfolio_id: uuid.UUID,
    as_of_date: date | None,
    created_by: str | None,
) -> uuid.UUID:
    with session_scope() as session:
        if as_of_date is None:
            as_of_date = _latest_trading_day_before(session, before=date.today())
        run_id = ensure_model_construction_run(
            session,
            model_portfolio_id=model_portfolio_id,
            as_of_date=as_of_date,
            created_by=created_by,
        )
        logger.info(
            "Ensured model run: %s (model_portfolio_id=%s as_of_date=%s)",
            run_id,
            model_portfolio_id,
            as_of_date,
        )
        return run_id


def build_broker_run(
    settings: Settings,
    *,
    broker_portfolio_id: uuid.UUID,
    as_of_date: date | None,
    policy_id: int | None,
    created_by: str | None,
) -> uuid.UUID:
    with session_scope() as session:
        if as_of_date is None:
            as_of_date = _latest_trading_day_before(session, before=date.today())
        run = create_portfolio_run(
            session,
            portfolio_id=broker_portfolio_id,
            run_kind="BROKER_REBALANCE",
            as_of_date=as_of_date,
            policy_id=policy_id,
            created_by=created_by,
        )
        generate_broker_rebalance_run(
            session, run_id=uuid.UUID(str(run.run_id)), generated_by=created_by
        )
        logger.info(
            "Generated broker run: %s (broker_portfolio_id=%s as_of_date=%s)",
            run.run_id,
            broker_portfolio_id,
            as_of_date,
        )
        return uuid.UUID(str(run.run_id))


def main() -> None:
    parser = argparse.ArgumentParser(prog="rankalpha-portfolio", add_help=True)
    sub = parser.add_subparsers(dest="cmd", required=True)

    nav_p = sub.add_parser("sync-nav", help="Compute and upsert daily NAV for portfolios.")
    nav_p.add_argument("--as-of-date", type=_parse_date, default=None)

    perf_p = sub.add_parser(
        "rollup-performance",
        help="Compute daily NAV/PnL for BROKER (from broker NLV) and MODEL (synthetic) portfolios.",
    )
    perf_p.add_argument("--as-of-date", type=_parse_date, default=None)

    model_p = sub.add_parser(
        "build-model-run", help="Build (and auto-approve) a MODEL_CONSTRUCTION run."
    )
    model_p.add_argument("--model-portfolio-id", type=_parse_uuid, required=True)
    model_p.add_argument("--as-of-date", type=_parse_date, default=None)
    model_p.add_argument("--created-by", type=str, default=None)

    broker_p = sub.add_parser(
        "build-broker-run", help="Build a BROKER_REBALANCE run from deployments/models."
    )
    broker_p.add_argument("--broker-portfolio-id", type=_parse_uuid, required=True)
    broker_p.add_argument("--as-of-date", type=_parse_date, default=None)
    broker_p.add_argument("--policy-id", type=int, default=None)
    broker_p.add_argument("--created-by", type=str, default=None)

    args = parser.parse_args()
    settings = Settings()
    setup_logging(settings.log_level)

    if args.cmd == "sync-nav":
        sync_nav(settings, as_of_date=args.as_of_date)
        return
    if args.cmd == "rollup-performance":
        rollup_performance(settings, as_of_date=args.as_of_date)
        return
    if args.cmd == "build-model-run":
        build_model_run(
            settings,
            model_portfolio_id=args.model_portfolio_id,
            as_of_date=args.as_of_date,
            created_by=args.created_by,
        )
        return
    if args.cmd == "build-broker-run":
        build_broker_run(
            settings,
            broker_portfolio_id=args.broker_portfolio_id,
            as_of_date=args.as_of_date,
            policy_id=args.policy_id,
            created_by=args.created_by,
        )
        return

    raise SystemExit(2)


if __name__ == "__main__":
    main()
