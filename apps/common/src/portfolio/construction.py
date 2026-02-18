"""Portfolio construction + approvals + broker export helpers."""

from __future__ import annotations

import hashlib
import statistics
import uuid
from datetime import UTC, date, datetime, time
from decimal import ROUND_DOWN, Decimal
from typing import Any, Sequence
from typing import cast as typing_cast
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, and_, case, cast, delete, func, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimDate,
    DimSource,
    DimStock,
    FactPortfolioBrokerNlv,
    FactSecurityPrice,
    FactTradeRecommendation,
    Portfolio,
    PortfolioCashPosition,
    PortfolioDeployment,
    PortfolioModelConfigVersion,
    PortfolioOrderExport,
    PortfolioOrderIntent,
    PortfolioPolicyVersion,
    PortfolioPosition,
    PortfolioRun,
    PortfolioRunArtifact,
    PortfolioRunInput,
    PortfolioRunPosition,
    PortfolioRunRiskCheck,
    PortfolioRunRiskReport,
    PortfolioRunSignalInput,
    PortfolioSignalSubscription,
    trade_action_enum,
)
from apps.common.src.portfolio.fx import FXConfig, fx_mid_px


def _slug_sleeve_name(broker_name: str, model_name: str) -> str:
    """Return a stable, unique sleeve portfolio name (<= 50 chars)."""
    raw = f"sleeve::{broker_name}::{model_name}"
    if len(raw) <= 50:
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    head = raw[: 50 - 1 - len(digest)]
    return f"{head}-{digest}"


def _broker_source_name(account_id: str) -> str:
    return f"broker::{account_id}"


def _default_broker_expiry_ts(execution_date: date) -> datetime:
    """Default expiry is end-of-day in America/New_York (converted to UTC)."""
    try:
        tz = ZoneInfo("America/New_York")
    except Exception:
        tz = UTC
    local = datetime.combine(execution_date, time(23, 59, 59), tzinfo=tz)
    return local.astimezone(UTC)


def _eastern_today() -> date:
    try:
        tz = ZoneInfo("America/New_York")
    except Exception:
        tz = UTC
    return datetime.now(tz).date()


def _next_trading_day(session: Session, *, after_date: date) -> date:
    """Return the next trading day (dim_date.is_trading_day) strictly after `after_date`."""
    nxt = session.scalar(
        select(DimDate.full_date)
        .where(DimDate.full_date > after_date)
        .where(DimDate.is_trading_day.is_(True))
        .order_by(DimDate.full_date.asc())
        .limit(1)
    )
    if nxt is None:
        raise ValueError(f"Unable to resolve next trading day after {after_date}")
    return nxt


def _require_broker_run_execution_day(session: Session, *, run: PortfolioRun) -> date:
    """Ensure broker runs are approved only on their intended execution day D."""
    execution_date = _next_trading_day(session, after_date=typing_cast(date, run.as_of_date))
    today_et = _eastern_today()
    if execution_date != today_et:
        raise ValueError(
            f"Cannot approve broker run: execution day {execution_date} != today {today_et} (create a new run)"
        )
    return execution_date


def _risk_freshness_cutoff(session: Session, *, run: PortfolioRun) -> datetime:
    max_order_update = session.scalar(
        select(func.max(PortfolioOrderIntent.updated_at)).where(
            PortfolioOrderIntent.run_id == run.run_id
        )
    )
    max_pos_update = session.scalar(
        select(func.max(PortfolioRunPosition.updated_at)).where(
            PortfolioRunPosition.run_id == run.run_id
        )
    )
    return max(
        dt
        for dt in (
            getattr(run, "updated_at", None),
            max_order_update,
            max_pos_update,
        )
        if dt is not None
    )


def _require_fresh_risk_report(session: Session, *, run: PortfolioRun) -> None:
    """Enforce that a broker run has a fresh non-FAIL risk report before approval/export."""
    report = session.get(PortfolioRunRiskReport, run.run_id)
    if report is None:
        raise ValueError("Cannot approve broker run: risk report missing")
    status = str(report.status).upper()
    if status == "FAIL":
        raise ValueError("Cannot approve broker run: risk status FAIL")

    freshness_cutoff = _risk_freshness_cutoff(session, run=run)
    if report.evaluated_at < freshness_cutoff:
        raise ValueError("Cannot approve broker run: risk report is stale (re-evaluate risk)")


def _resolve_policy_for_run(
    session: Session, *, run: PortfolioRun
) -> PortfolioPolicyVersion | None:
    if run.policy_id is not None:
        policy = session.get(PortfolioPolicyVersion, run.policy_id)
        if policy is None:
            raise ValueError("run.policy_id not found")
        if policy.portfolio_id != run.portfolio_id:
            raise ValueError("run.policy_id does not belong to this portfolio")
        if str(run.run_kind).upper() == "BROKER_REBALANCE":
            if str(getattr(policy, "approval_status", "") or "").upper() != "APPROVED":
                raise ValueError(
                    "run.policy_id is not APPROVED (broker runs require approved policies)"
                )
        return policy

    return session.scalar(
        select(PortfolioPolicyVersion)
        .where(PortfolioPolicyVersion.portfolio_id == run.portfolio_id)
        .where(PortfolioPolicyVersion.approval_status == "APPROVED")
        .where(PortfolioPolicyVersion.effective_from <= run.as_of_date)
        .where(
            or_(
                PortfolioPolicyVersion.effective_to.is_(None),
                PortfolioPolicyVersion.effective_to > run.as_of_date,
            )
        )
        .order_by(PortfolioPolicyVersion.effective_from.desc())
        .limit(1)
    )


def _get_dict(root: Any, key: str) -> dict[str, Any]:
    if not isinstance(root, dict):
        return {}
    out = root.get(key)
    return out if isinstance(out, dict) else {}


def _get_float(root: Any, key: str, default: float | None = None) -> float | None:
    if not isinstance(root, dict):
        return default
    raw = root.get(key, default)
    if raw is None:
        return None
    try:
        return float(raw)
    except Exception:
        return default


def _get_int(root: Any, key: str, default: int | None = None) -> int | None:
    if not isinstance(root, dict):
        return default
    raw = root.get(key, default)
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return default


def _resolve_date_key(session: Session, *, full_date: date) -> int:
    date_key = session.scalar(select(DimDate.date_key).where(DimDate.full_date == full_date))
    if date_key is None:
        raise ValueError(f"Date {full_date} not found in dim_date")
    return int(date_key)


def _fx_mid_px(
    session: Session,
    *,
    date_key: int,
    from_ccy: str,
    to_ccy: str,
    fallback_to_last_available: bool = True,
    max_lookback_days: int = 30,
    pivot_ccy: str = "USD",
    cache: dict[tuple[int, str, str, str, int, bool], Decimal | None] | None = None,
) -> Decimal | None:
    return fx_mid_px(
        session,
        date_key=int(date_key),
        from_ccy=from_ccy,
        to_ccy=to_ccy,
        cfg=FXConfig(
            pivot_ccy=(pivot_ccy or "USD").upper(),
            max_lookback_days=int(max_lookback_days),
            fallback_to_last_available=bool(fallback_to_last_available),
        ),
        cache=cache,
    )


def _get_active_model_config(
    session: Session,
    *,
    model_portfolio_id: uuid.UUID,
    as_of_date: date,
) -> PortfolioModelConfigVersion:
    cfg = session.scalar(
        select(PortfolioModelConfigVersion)
        .where(PortfolioModelConfigVersion.model_portfolio_id == model_portfolio_id)
        .where(PortfolioModelConfigVersion.approval_status == "APPROVED")
        .where(PortfolioModelConfigVersion.effective_from <= as_of_date)
        .where(
            or_(
                PortfolioModelConfigVersion.effective_to.is_(None),
                PortfolioModelConfigVersion.effective_to > as_of_date,
            )
        )
        .order_by(PortfolioModelConfigVersion.effective_from.desc())
        .limit(1)
    )
    if cfg is None:
        raise ValueError(
            f"No APPROVED model config for model_portfolio_id={model_portfolio_id} as_of_date={as_of_date}"
        )
    return cfg


def _parse_model_strategy_blend(config: Any) -> list[dict[str, Any]]:
    if not isinstance(config, dict):
        raise ValueError("model config must be an object")

    blend = config.get("strategy_blend")
    if not isinstance(blend, dict):
        raise ValueError("model config requires strategy_blend object")

    raw_strategies = blend.get("strategies")
    if not isinstance(raw_strategies, list) or not raw_strategies:
        raise ValueError("model config requires non-empty strategy_blend.strategies")

    require_sum = blend.get("require_sum_to_100", True)
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    weight_sum = 0.0

    for i, raw in enumerate(raw_strategies):
        if not isinstance(raw, dict):
            raise ValueError(f"strategy_blend.strategies[{i}] must be an object")
        enabled = bool(raw.get("enabled", True))
        source_name = str(raw.get("source_name") or "").strip()
        strategy_name = str(raw.get("strategy_name") or "").strip()
        if not source_name or not strategy_name:
            raise ValueError(
                f"strategy_blend.strategies[{i}] requires source_name and strategy_name"
            )
        raw_weight = raw.get("weight_pct")
        if raw_weight is None:
            raise ValueError(f"strategy_blend.strategies[{i}].weight_pct is required")
        try:
            weight_pct = float(raw_weight)
        except Exception as exc:
            raise ValueError(f"strategy_blend.strategies[{i}].weight_pct must be a number") from exc
        if weight_pct < 0 or weight_pct > 100:
            raise ValueError(f"strategy_blend.strategies[{i}].weight_pct must be between 0 and 100")

        key = (source_name, strategy_name)
        if key in seen:
            raise ValueError(f"Duplicate strategy entry for ({source_name}, {strategy_name})")
        seen.add(key)

        if enabled:
            weight_sum += weight_pct

        items.append(
            {
                "source_name": source_name,
                "strategy_name": strategy_name,
                "weight_pct": weight_pct,
                "enabled": enabled,
                "notes": raw.get("notes"),
            }
        )

    if bool(require_sum):
        if abs(weight_sum - 100.0) > 1e-6:
            raise ValueError(f"Enabled strategy weights must sum to 100 (got {weight_sum})")

    return items


def _evaluate_broker_run_risk(
    session: Session,
    *,
    run: PortfolioRun,
    policy: PortfolioPolicyVersion | None,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Evaluate broker rebalance constraints and return (status, summary, checks)."""
    portfolio = session.get(Portfolio, run.portfolio_id)
    if portfolio is None:
        raise ValueError("run.portfolio_id not found")

    constraints = dict(getattr(policy, "constraints", {}) or {}) if policy is not None else {}
    nav_cfg = _get_dict(constraints, "nav")
    position_limits = _get_dict(constraints, "position_limits")
    liquidity = _get_dict(constraints, "liquidity")
    exposure = _get_dict(constraints, "exposure")
    fx_cfg = _get_dict(constraints, "fx")

    long_only = bool(exposure.get("long_only", True))
    max_leverage = _get_float(exposure, "max_leverage", None)
    if max_leverage is None:
        # Back-compat alias.
        max_leverage = _get_float(exposure, "max_gross_exposure", None)
    if max_leverage is None:
        max_gross_exposure_pct = _get_float(exposure, "max_gross_exposure_pct", None)
        if max_gross_exposure_pct is None:
            max_gross_exposure_pct = _get_float(exposure, "max_allocatable_exposure_pct", None)
        if max_gross_exposure_pct is not None:
            max_leverage = float(max_gross_exposure_pct) / 100.0
    min_cash_buffer_pct = _get_float(nav_cfg, "min_cash_buffer_pct", 1.0) or 0.0
    cash_buffer_hard = bool(nav_cfg.get("cash_buffer_hard", True))
    max_name_weight_pct = _get_float(position_limits, "max_name_weight_pct", 20.0) or 20.0
    min_order_notional_usd = _get_float(position_limits, "min_order_notional_usd", 100.0) or 0.0
    min_order_notional_hard = bool(position_limits.get("min_order_notional_hard", False))
    max_orders = _get_int(position_limits, "max_orders", None)
    round_lot_size = max(int(_get_int(position_limits, "round_lot_size", 1) or 1), 1)
    allow_fractional = bool(position_limits.get("allow_fractional_shares", False))

    adv20_usd_min = _get_float(liquidity, "adv20_usd_min", 10_000_000.0) or 0.0
    max_adv_pct_per_order = _get_float(liquidity, "max_adv_pct_per_order", 10.0) or 0.0
    adv_window = max(int(_get_int(liquidity, "adv_window_days", 20) or 20), 1)
    fallback_fx = bool(fx_cfg.get("fallback_to_last_available", True))
    max_lookback_days = max(int(_get_int(fx_cfg, "max_lookback_days", 30) or 30), 0)
    pivot_ccy = str(fx_cfg.get("pivot_ccy") or "USD").upper()
    fx_cache: dict[tuple[int, str, str, str, int, bool], Decimal | None] = {}

    base_ccy = str(getattr(portfolio, "currency_code", "USD") or "USD").upper()
    if base_ccy != "USD":
        # The liquidity constraints are specified in USD today.
        base_ccy = "USD"

    as_of_date_key = session.scalar(
        select(DimDate.date_key).where(DimDate.full_date == typing_cast(date, run.as_of_date))
    )
    if as_of_date_key is None:
        raise ValueError(f"Date {run.as_of_date} not found in dim_date")
    as_of_date_key_int = int(as_of_date_key)

    # ---- load baseline positions + cash (prefer run snapshot, fallback to current tables) ----
    run_pos_rows = session.execute(
        select(PortfolioRunPosition, DimStock.symbol, DimStock.currency_code)
        .select_from(PortfolioRunPosition)
        .join(DimStock, DimStock.stock_key == PortfolioRunPosition.stock_key)
        .where(PortfolioRunPosition.run_id == run.run_id)
        .where(PortfolioRunPosition.position_role == "BASELINE")
        .where(PortfolioRunPosition.instrument_type == "EQUITY")
    ).all()
    run_cash_rows = list(
        session.scalars(
            select(PortfolioRunPosition)
            .where(PortfolioRunPosition.run_id == run.run_id)
            .where(PortfolioRunPosition.position_role == "BASELINE")
            .where(PortfolioRunPosition.instrument_type == "CASH")
        ).all()
    )
    use_run_snapshot = bool(run_pos_rows or run_cash_rows)

    if use_run_snapshot:
        pos_rows = run_pos_rows
        cash_rows = run_cash_rows
    else:
        pos_rows = session.execute(
            select(PortfolioPosition, DimStock.symbol, DimStock.currency_code)
            .select_from(PortfolioPosition)
            .join(DimStock, DimStock.stock_key == PortfolioPosition.stock_key)
            .where(PortfolioPosition.portfolio_id == run.portfolio_id)
        ).all()
        cash_rows = list(
            session.scalars(
                select(PortfolioCashPosition).where(
                    PortfolioCashPosition.portfolio_id == run.portfolio_id
                )
            ).all()
        )

    baseline_shares: dict[int, Decimal] = {}
    baseline_symbols: dict[int, str] = {}
    stock_ccy_by_key: dict[int, str] = {}
    non_base_positions: list[dict[str, Any]] = []
    for pos, symbol, ccy in pos_rows:
        ccy_u = str(ccy or "").upper()
        if ccy_u and ccy_u != base_ccy:
            non_base_positions.append({"symbol": str(symbol), "currency_code": ccy_u})
        baseline_shares[int(pos.stock_key)] = Decimal(pos.quantity or 0)
        baseline_symbols[int(pos.stock_key)] = str(symbol)
        stock_ccy_by_key[int(pos.stock_key)] = ccy_u or base_ccy

    cash_by_ccy: dict[str, Decimal] = {}
    non_base_cash: list[dict[str, Any]] = []
    for c in cash_rows:
        ccy_u = str(getattr(c, "currency_code", "") or "").upper()
        amt = getattr(c, "cash_amount", None)
        if amt is None:
            amt = getattr(c, "quantity", 0)
        amt_dec = Decimal(amt or 0)
        cash_by_ccy[ccy_u or base_ccy] = cash_by_ccy.get(ccy_u or base_ccy, Decimal("0")) + amt_dec
        if ccy_u and ccy_u != base_ccy:
            non_base_cash.append({"currency_code": ccy_u, "cash_amount": float(amt_dec)})

    # ---- load orders ----
    order_rows = session.execute(
        select(PortfolioOrderIntent, DimStock.symbol, DimStock.currency_code)
        .select_from(PortfolioOrderIntent)
        .join(DimStock, DimStock.stock_key == PortfolioOrderIntent.stock_key)
        .where(PortfolioOrderIntent.run_id == run.run_id)
        .order_by(PortfolioOrderIntent.line_no.asc())
    ).all()

    deltas: dict[int, Decimal] = {}
    order_symbols: dict[int, str] = {}
    order_ccy: dict[int, str] = {}
    order_lines: list[dict[str, Any]] = []
    non_base_orders: list[dict[str, Any]] = []
    invalid_actions: list[dict[str, Any]] = []
    fractional_orders: list[dict[str, Any]] = []
    round_lot_violations: list[dict[str, Any]] = []
    parsed_orders: list[dict[str, Any]] = []
    for order, symbol, ccy in order_rows:
        sym = str(symbol)
        ccy_u = str(ccy or "").upper() or base_ccy
        order_symbols[int(order.stock_key)] = sym
        order_ccy[int(order.stock_key)] = ccy_u
        order_lines.append(
            {
                "order_id": str(order.order_id),
                "line_no": int(order.line_no),
                "symbol": sym,
                "action": str(order.action).upper(),
                "qty_shares": float(order.qty_shares or 0),
                "currency_code": ccy_u,
            }
        )

        action = str(order.action).upper()
        if action not in set(trade_action_enum.enums):
            invalid_actions.append({"line_no": int(order.line_no), "symbol": sym, "action": action})
            continue

        qty_dec = Decimal(order.qty_shares or 0)
        if qty_dec == 0:
            continue
        # Allow negative quantities (interpret as absolute magnitude; direction comes from `action`).
        if qty_dec < 0:
            qty_dec = abs(qty_dec)

        if ccy_u != base_ccy:
            non_base_orders.append(
                {"line_no": int(order.line_no), "symbol": sym, "currency_code": ccy_u}
            )

        # Shares format checks.
        qty_int = int(qty_dec)
        if not allow_fractional and qty_dec != Decimal(qty_int):
            fractional_orders.append(
                {"line_no": int(order.line_no), "symbol": sym, "qty_shares": float(qty_dec)}
            )
            continue

        if round_lot_size > 1 and qty_int % round_lot_size != 0 and not allow_fractional:
            round_lot_violations.append(
                {
                    "line_no": int(order.line_no),
                    "symbol": sym,
                    "qty_shares": qty_int,
                    "lot": round_lot_size,
                }
            )

        qty_used = qty_dec if allow_fractional else Decimal(qty_int)
        signed = qty_used if action in {"BUY", "COVER"} else -qty_used
        deltas[int(order.stock_key)] = deltas.get(int(order.stock_key), Decimal("0")) + signed
        parsed_orders.append(
            {
                "stock_key": int(order.stock_key),
                "action": action,
                "qty_shares": qty_used,
                "currency_code": ccy_u,
            }
        )

    # ---- prices ----
    stock_keys = set(baseline_shares.keys()) | set(deltas.keys())

    # ---- FX (convert everything to base_ccy for constraints) ----
    stock_ccy: dict[int, str] = {}
    for k in stock_keys:
        ccy_u = stock_ccy_by_key.get(int(k)) or order_ccy.get(int(k)) or base_ccy
        stock_ccy[int(k)] = str(ccy_u or base_ccy).upper()

    required_ccys = {
        ccy
        for ccy in (set(cash_by_ccy.keys()) | set(stock_ccy.values()))
        if ccy and ccy != base_ccy
    }
    fx_to_base: dict[str, Decimal] = {}
    missing_fx: list[dict[str, Any]] = []
    for ccy in sorted(required_ccys):
        px = _fx_mid_px(
            session,
            date_key=as_of_date_key_int,
            from_ccy=ccy,
            to_ccy=base_ccy,
            fallback_to_last_available=fallback_fx,
            max_lookback_days=max_lookback_days,
            pivot_ccy=pivot_ccy,
            cache=fx_cache,
        )
        if px is None:
            missing_fx.append({"from_ccy": ccy, "to_ccy": base_ccy})
        else:
            fx_to_base[ccy] = px

    def _fx_or_one(ccy: str) -> Decimal | None:
        c = (ccy or "").upper()
        if not c or c == base_ccy:
            return Decimal("1")
        return fx_to_base.get(c)

    close_by_stock: dict[int, Decimal] = {}
    missing_prices: list[dict[str, Any]] = []
    if stock_keys:
        px_rows = session.execute(
            select(FactSecurityPrice.stock_key, FactSecurityPrice.close_px)
            .where(FactSecurityPrice.date_key == as_of_date_key_int)
            .where(FactSecurityPrice.stock_key.in_(stock_keys))
        ).all()
        close_by_stock = {int(k): (px or Decimal("0")) for k, px in px_rows}

        for k in stock_keys:
            px = close_by_stock.get(int(k), Decimal("0"))
            if px is None or Decimal(px) <= 0:
                sym = order_symbols.get(int(k)) or baseline_symbols.get(int(k)) or str(k)
                missing_prices.append({"symbol": sym, "stock_key": int(k)})

    # ---- compute baseline + target ----
    baseline_cash_base = Decimal("0")
    for ccy_u, amt in cash_by_ccy.items():
        fx = _fx_or_one(ccy_u)
        if fx is None:
            continue
        baseline_cash_base += amt * fx

    baseline_equity = Decimal("0")
    for k, qty in baseline_shares.items():
        px_local = close_by_stock.get(int(k), Decimal("0"))
        if px_local is None or Decimal(px_local) <= 0:
            continue
        fx = _fx_or_one(stock_ccy.get(int(k), base_ccy))
        if fx is None:
            continue
        baseline_equity += qty * Decimal(px_local) * fx

    baseline_nav = baseline_equity + baseline_cash_base

    target_shares: dict[int, Decimal] = dict(baseline_shares)
    for k, d in deltas.items():
        target_shares[int(k)] = target_shares.get(int(k), Decimal("0")) + d

    negative_positions: list[dict[str, Any]] = []
    for k, qty in target_shares.items():
        if qty < 0:
            sym = order_symbols.get(int(k)) or baseline_symbols.get(int(k)) or str(k)
            negative_positions.append({"symbol": sym, "qty_shares": float(qty)})

    # approximate cash impact by currency using close px in listing currency
    est_cash_by_ccy: dict[str, Decimal] = dict(cash_by_ccy)
    small_orders: list[dict[str, Any]] = []
    order_notional_by_stock: dict[int, Decimal] = {}
    for k, d in deltas.items():
        px_local = close_by_stock.get(int(k), Decimal("0"))
        if px_local is None or Decimal(px_local) <= 0:
            continue
        ccy_u = stock_ccy.get(int(k), base_ccy)
        fx = _fx_or_one(ccy_u)
        notional_local = abs(d) * Decimal(px_local)
        if fx is None:
            # Can't compute USD notional without FX.
            continue
        notional = notional_local * fx
        order_notional_by_stock[int(k)] = notional
        if min_order_notional_usd and notional < Decimal(min_order_notional_usd):
            sym = order_symbols.get(int(k), str(k))
            small_orders.append({"symbol": sym, "notional_usd": float(notional)})
        if d > 0:
            est_cash_by_ccy[ccy_u] = est_cash_by_ccy.get(ccy_u, Decimal("0")) - notional_local
        else:
            est_cash_by_ccy[ccy_u] = est_cash_by_ccy.get(ccy_u, Decimal("0")) + notional_local

    est_cash = Decimal("0")
    for ccy_u, amt in est_cash_by_ccy.items():
        fx = _fx_or_one(ccy_u)
        if fx is None:
            continue
        est_cash += amt * fx

    target_equity = Decimal("0")
    gross_exposure = Decimal("0")
    abs_exposure_by_stock: dict[int, Decimal] = {}
    for k, qty in target_shares.items():
        if qty == 0:
            continue
        px_local = close_by_stock.get(int(k), Decimal("0"))
        if px_local is None or Decimal(px_local) <= 0:
            continue
        fx = _fx_or_one(stock_ccy.get(int(k), base_ccy))
        if fx is None:
            continue
        mv = qty * Decimal(px_local) * fx
        target_equity += mv
        abs_mv = abs(mv)
        gross_exposure += abs_mv
        abs_exposure_by_stock[int(k)] = abs_mv

    target_nav = target_equity + est_cash
    if target_nav == 0:
        target_nav = baseline_nav

    # ---- risk checks ----
    checks: list[dict[str, Any]] = []

    def _add_check(
        *,
        code: str,
        severity: str,
        status: str,
        metric_value: float | None = None,
        threshold_value: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        checks.append(
            {
                "check_code": code,
                "severity": severity,
                "status": status,
                "metric_value": metric_value,
                "threshold_value": threshold_value,
                "details": details or {},
            }
        )

    if missing_fx:
        _add_check(
            code="FX_RATE_AVAILABLE",
            severity="HARD",
            status="FAIL",
            details={
                "missing": missing_fx,
                "base_currency": base_ccy,
                "fallback_to_last_available": bool(fallback_fx),
                "orders": non_base_orders,
                "positions": non_base_positions,
                "cash": non_base_cash,
            },
        )
    else:
        _add_check(
            code="FX_RATE_AVAILABLE",
            severity="INFO",
            status="PASS",
            details={
                "base_currency": base_ccy,
                "required_currencies": sorted(required_ccys),
                "fallback_to_last_available": bool(fallback_fx),
                "orders": non_base_orders,
                "positions": non_base_positions,
                "cash": non_base_cash,
            },
        )

    has_any_balance = bool(stock_keys) or any(
        (v or Decimal("0")) != 0 for v in cash_by_ccy.values()
    )
    if (
        not missing_fx
        and not missing_prices
        and has_any_balance
        and (baseline_nav <= 0 or target_nav <= 0)
    ):
        _add_check(
            code="NAV_NONPOSITIVE",
            severity="HARD",
            status="FAIL",
            metric_value=float(target_nav),
            details={
                "baseline_nav_usd": float(baseline_nav),
                "target_nav_usd": float(target_nav),
                "cash_usd": float(baseline_cash_base),
            },
        )

    if invalid_actions:
        _add_check(
            code="ACTION_ALLOWED",
            severity="HARD",
            status="FAIL",
            details={"orders": invalid_actions},
        )
    elif long_only:
        _add_check(
            code="ACTION_ALLOWED", severity="INFO", status="PASS", details={"long_only": True}
        )

    if fractional_orders and not allow_fractional:
        _add_check(
            code="INTEGER_SHARES_REQUIRED",
            severity="HARD",
            status="FAIL",
            details={"orders": fractional_orders},
        )
    else:
        _add_check(
            code="INTEGER_SHARES_REQUIRED",
            severity="INFO",
            status="PASS",
            details={"allow_fractional_shares": allow_fractional},
        )

    if round_lot_violations:
        _add_check(
            code="ROUND_LOT",
            severity="WARN",
            status="WARN",
            threshold_value=float(round_lot_size),
            details={"orders": round_lot_violations},
        )

    if max_orders is not None:
        try:
            max_orders_i = int(max_orders)
        except Exception:
            max_orders_i = 0
        if max_orders_i > 0 and len(parsed_orders) > max_orders_i:
            _add_check(
                code="MAX_ORDERS",
                severity="HARD",
                status="FAIL",
                metric_value=float(len(parsed_orders)),
                threshold_value=float(max_orders_i),
                details={"orders_count": len(parsed_orders)},
            )
        elif max_orders_i > 0:
            _add_check(
                code="MAX_ORDERS",
                severity="INFO",
                status="PASS",
                metric_value=float(len(parsed_orders)),
                threshold_value=float(max_orders_i),
                details={"orders_count": len(parsed_orders)},
            )

    if missing_prices:
        # Missing prices are a hard fail if we need them for sizing/valuation.
        _add_check(
            code="PRICE_AVAILABLE",
            severity="HARD",
            status="FAIL",
            details={"missing": missing_prices, "as_of_date": str(run.as_of_date)},
        )

    valuation_ready = not bool(missing_fx) and not bool(missing_prices)

    if negative_positions and long_only:
        _add_check(
            code="LONG_ONLY",
            severity="HARD",
            status="FAIL",
            details={"negative_positions": negative_positions},
        )
    elif long_only:
        _add_check(code="LONG_ONLY", severity="INFO", status="PASS")

    # Name concentration
    offenders: list[dict[str, Any]] = []
    if valuation_ready and target_nav > 0:
        for k, abs_mv in abs_exposure_by_stock.items():
            wt = (abs_mv / target_nav) * Decimal("100")
            if wt > Decimal(max_name_weight_pct):
                offenders.append(
                    {
                        "symbol": order_symbols.get(int(k))
                        or baseline_symbols.get(int(k))
                        or str(k),
                        "weight_pct": float(wt),
                    }
                )
    if offenders:
        _add_check(
            code="MAX_NAME_WEIGHT_PCT",
            severity="HARD",
            status="FAIL",
            threshold_value=float(max_name_weight_pct),
            details={"offenders": offenders},
        )
    else:
        _add_check(
            code="MAX_NAME_WEIGHT_PCT",
            severity="INFO",
            status="PASS",
            threshold_value=float(max_name_weight_pct),
        )

    if valuation_ready and max_leverage is not None and target_nav > 0:
        lev = gross_exposure / target_nav
        if lev > Decimal(str(max_leverage)):
            _add_check(
                code="MAX_LEVERAGE",
                severity="HARD",
                status="FAIL",
                metric_value=float(lev),
                threshold_value=float(max_leverage),
                details={
                    "gross_exposure_usd": float(gross_exposure),
                    "nav_usd": float(target_nav),
                },
            )
        else:
            _add_check(
                code="MAX_LEVERAGE",
                severity="INFO",
                status="PASS",
                metric_value=float(lev),
                threshold_value=float(max_leverage),
                details={
                    "gross_exposure_usd": float(gross_exposure),
                    "nav_usd": float(target_nav),
                },
            )

    # Cash buffer (HARD by default for broker runs; configurable)
    if valuation_ready and target_nav > 0 and min_cash_buffer_pct > 0:
        req = (Decimal(min_cash_buffer_pct) / Decimal("100")) * target_nav
        if est_cash < req:
            _add_check(
                code="MIN_CASH_BUFFER_PCT",
                severity="HARD" if cash_buffer_hard else "WARN",
                status="FAIL" if cash_buffer_hard else "WARN",
                metric_value=float((est_cash / target_nav) * Decimal("100")),
                threshold_value=float(min_cash_buffer_pct),
                details={"cash_usd": float(est_cash), "required_cash_usd": float(req)},
            )
        else:
            _add_check(
                code="MIN_CASH_BUFFER_PCT",
                severity="INFO",
                status="PASS",
                metric_value=float((est_cash / target_nav) * Decimal("100")),
                threshold_value=float(min_cash_buffer_pct),
            )

    if valuation_ready and small_orders:
        _add_check(
            code="MIN_ORDER_NOTIONAL_USD",
            severity="HARD" if min_order_notional_hard else "WARN",
            status="FAIL" if min_order_notional_hard else "WARN",
            threshold_value=float(min_order_notional_usd),
            details={"small_orders": small_orders},
        )

    # Liquidity / ADV checks (orders only)
    if valuation_ready and (adv20_usd_min > 0 or max_adv_pct_per_order > 0):
        order_keys = [int(k) for k in deltas.keys()]
        if order_keys:
            subq = (
                select(
                    FactSecurityPrice.stock_key.label("stock_key"),
                    (FactSecurityPrice.close_px * FactSecurityPrice.volume).label("dollar_vol"),
                    func.row_number()
                    .over(
                        partition_by=FactSecurityPrice.stock_key,
                        order_by=FactSecurityPrice.date_key.desc(),
                    )
                    .label("rn"),
                )
                .join(DimDate, DimDate.date_key == FactSecurityPrice.date_key)
                .where(DimDate.full_date <= run.as_of_date)
                .where(DimDate.is_trading_day.is_(True))
                .where(FactSecurityPrice.stock_key.in_(order_keys))
                .subquery()
            )
            adv_rows = session.execute(
                select(subq.c.stock_key, func.avg(subq.c.dollar_vol).label("adv_usd"))
                .where(subq.c.rn <= adv_window)
                .group_by(subq.c.stock_key)
            ).all()
            adv_by_stock: dict[int, Decimal] = {}
            for k, adv_local in adv_rows:
                ccy_u = stock_ccy.get(int(k), base_ccy)
                fx = _fx_or_one(ccy_u)
                if fx is None:
                    continue
                adv_by_stock[int(k)] = Decimal(adv_local or 0) * fx

            adv_missing: list[dict[str, Any]] = []
            adv_too_low: list[dict[str, Any]] = []
            adv_pct_offenders: list[dict[str, Any]] = []
            for k in order_keys:
                adv = adv_by_stock.get(int(k))
                sym = order_symbols.get(int(k)) or baseline_symbols.get(int(k)) or str(k)
                if adv is None or Decimal(adv) <= 0:
                    adv_missing.append({"symbol": sym})
                    continue
                if adv20_usd_min > 0 and Decimal(adv) < Decimal(adv20_usd_min):
                    adv_too_low.append({"symbol": sym, "adv20_usd": float(adv)})
                if max_adv_pct_per_order > 0:
                    notional = order_notional_by_stock.get(int(k))
                    if notional is None:
                        continue
                    pct = (notional / Decimal(adv)) * Decimal("100")
                    if pct > Decimal(max_adv_pct_per_order):
                        adv_pct_offenders.append(
                            {"symbol": sym, "order_pct_adv": float(pct), "adv20_usd": float(adv)}
                        )

            if adv_missing:
                _add_check(
                    code="ADV_DATA_AVAILABLE",
                    severity="WARN",
                    status="WARN",
                    details={"missing": adv_missing, "window_days": adv_window},
                )
            else:
                _add_check(
                    code="ADV_DATA_AVAILABLE",
                    severity="INFO",
                    status="PASS",
                    details={"window_days": adv_window},
                )

            if adv_too_low:
                _add_check(
                    code="MIN_ADV20_USD",
                    severity="HARD",
                    status="FAIL",
                    threshold_value=float(adv20_usd_min),
                    details={"offenders": adv_too_low, "window_days": adv_window},
                )
            else:
                _add_check(
                    code="MIN_ADV20_USD",
                    severity="INFO",
                    status="PASS",
                    threshold_value=float(adv20_usd_min),
                    details={"window_days": adv_window},
                )

            if adv_pct_offenders:
                _add_check(
                    code="MAX_ORDER_PCT_ADV",
                    severity="HARD",
                    status="FAIL",
                    threshold_value=float(max_adv_pct_per_order),
                    details={"offenders": adv_pct_offenders, "window_days": adv_window},
                )
            else:
                _add_check(
                    code="MAX_ORDER_PCT_ADV",
                    severity="INFO",
                    status="PASS",
                    threshold_value=float(max_adv_pct_per_order),
                    details={"window_days": adv_window},
                )

    # derive overall status
    overall = "PASS"
    for chk in checks:
        sev = str(chk["severity"]).upper()
        st = str(chk["status"]).upper()
        if sev == "HARD" and st == "FAIL":
            overall = "FAIL"
            break
        if st == "WARN" and overall == "PASS":
            overall = "WARN"

    summary = {
        "run_id": str(run.run_id),
        "portfolio_id": str(run.portfolio_id),
        "as_of_date": str(run.as_of_date),
        "policy_id": int(policy.policy_id) if policy is not None else None,
        "baseline_nav_usd": float(baseline_nav),
        "target_nav_usd": float(target_nav),
        "baseline_cash_usd": float(baseline_cash_base),
        "target_cash_usd": float(est_cash),
        "base_currency": base_ccy,
        "constraints_used": {
            "min_cash_buffer_pct": float(min_cash_buffer_pct),
            "max_name_weight_pct": float(max_name_weight_pct),
            "min_order_notional_usd": float(min_order_notional_usd),
            "max_leverage": float(max_leverage) if max_leverage is not None else None,
            "round_lot_size": int(round_lot_size),
            "allow_fractional_shares": bool(allow_fractional),
            "adv20_usd_min": float(adv20_usd_min),
            "max_adv_pct_per_order": float(max_adv_pct_per_order),
            "adv_window_days": int(adv_window),
            "fx_fallback_to_last_available": bool(fallback_fx),
        },
        "order_count": len(order_rows),
        "evaluated_positions_count": len(baseline_shares),
        "baseline_source": "portfolio_run_position" if use_run_snapshot else "portfolio_position",
    }
    return overall, summary, checks


def evaluate_run_risk(
    session: Session,
    *,
    run_id: uuid.UUID,
    evaluated_by: str | None = None,
    force: bool = False,
) -> PortfolioRunRiskReport:
    """Compute and persist `portfolio_run_risk_report` (+ checks) for a run.

    For `BROKER_REBALANCE` runs, this evaluates policy constraints and stores a structured
    PASS/WARN/FAIL report used as an approval gate.
    """
    run = session.get(PortfolioRun, run_id)
    if run is None:
        raise ValueError("run_id not found")

    now_dt = datetime.now(UTC)

    existing = session.get(PortfolioRunRiskReport, run_id)
    if existing is not None and not force:
        cutoff = _risk_freshness_cutoff(session, run=run)
        if existing.evaluated_at >= cutoff:
            return existing

    policy = _resolve_policy_for_run(session, run=run)

    status = "PASS"
    summary: dict[str, Any] = {"note": "No checks evaluated"}
    checks: list[dict[str, Any]] = []
    if str(run.run_kind).upper() == "BROKER_REBALANCE":
        status, summary, checks = _evaluate_broker_run_risk(session, run=run, policy=policy)
    else:
        summary = {
            "run_id": str(run.run_id),
            "run_kind": str(run.run_kind),
            "note": "No checks for run_kind",
        }

    session.execute(delete(PortfolioRunRiskCheck).where(PortfolioRunRiskCheck.run_id == run_id))

    session.execute(
        insert(PortfolioRunRiskReport)
        .values(
            run_id=run_id,
            evaluated_at=now_dt,
            status=str(status).upper(),
            summary=cast(summary, JSONB),
        )
        .on_conflict_do_update(
            index_elements=[PortfolioRunRiskReport.run_id],
            set_={
                "evaluated_at": now_dt,
                "status": str(status).upper(),
                "summary": cast(summary, JSONB),
            },
        )
    )

    for chk in checks:
        session.execute(
            insert(PortfolioRunRiskCheck)
            .values(
                run_id=run_id,
                check_code=str(chk["check_code"]),
                severity=str(chk["severity"]).upper(),
                status=str(chk["status"]).upper(),
                metric_value=chk.get("metric_value"),
                threshold_value=chk.get("threshold_value"),
                details=cast(chk.get("details") or {}, JSONB),
            )
            .on_conflict_do_update(
                index_elements=[PortfolioRunRiskCheck.run_id, PortfolioRunRiskCheck.check_code],
                set_={
                    "severity": str(chk["severity"]).upper(),
                    "status": str(chk["status"]).upper(),
                    "metric_value": chk.get("metric_value"),
                    "threshold_value": chk.get("threshold_value"),
                    "details": cast(chk.get("details") or {}, JSONB),
                },
            )
        )

    # Library code must not commit; callers own transaction boundaries.
    session.flush()
    updated = session.get(PortfolioRunRiskReport, run_id)
    if updated is None:
        raise RuntimeError("Failed to persist risk report")
    return updated


def _resolve_source_key_by_name(session: Session, *, source_name: str) -> int:
    # DimSource.version is a string; prefer numeric ordering when the field is numeric
    # to avoid lexicographic hazards (e.g. "9" > "10" lexicographically).
    version_num = case(
        (DimSource.version.op("~")("^[0-9]+$"), cast(DimSource.version, Integer)),
        else_=None,
    )
    key = session.scalar(
        select(DimSource.source_key)
        .where(DimSource.source_name == source_name)
        .order_by(version_num.desc().nullslast(), DimSource.version.desc())
        .limit(1)
    )
    if key is None:
        raise ValueError(f"Unknown source_name: {source_name}")
    return int(key)


def _recommendation_strength(rec: FactTradeRecommendation) -> float:
    for field in ("risk_budget_bps", "size_percent", "size_shares"):
        raw = getattr(rec, field, None)
        if raw is None:
            continue
        try:
            v = float(raw)
        except Exception:
            continue
        if v > 0:
            return v
    return 1.0


def _get_active_signal_subscriptions(
    session: Session,
    *,
    broker_portfolio_id: uuid.UUID,
    as_of_date: date,
) -> list[PortfolioSignalSubscription]:
    return list(
        session.scalars(
            select(PortfolioSignalSubscription)
            .where(PortfolioSignalSubscription.broker_portfolio_id == broker_portfolio_id)
            .where(PortfolioSignalSubscription.approval_status == "APPROVED")
            .where(PortfolioSignalSubscription.enabled.is_(True))
            .where(PortfolioSignalSubscription.effective_from <= as_of_date)
            .where(
                or_(
                    PortfolioSignalSubscription.effective_to.is_(None),
                    PortfolioSignalSubscription.effective_to > as_of_date,
                )
            )
            .order_by(PortfolioSignalSubscription.effective_from.desc())
        ).all()
    )


def _load_signal_recommendations(
    session: Session,
    *,
    subscriptions: Sequence[PortfolioSignalSubscription],
    as_of_date_key: int,
) -> list[tuple[PortfolioSignalSubscription, FactTradeRecommendation]]:
    """Load recommendations for approved subscriptions on `as_of_date_key`."""
    out: list[tuple[PortfolioSignalSubscription, FactTradeRecommendation]] = []
    for sub in subscriptions:
        q = (
            select(FactTradeRecommendation)
            .where(FactTradeRecommendation.date_key == int(as_of_date_key))
            .where(FactTradeRecommendation.source_key == int(sub.source_key))
        )
        strat = str(getattr(sub, "strategy_name", "") or "").strip()
        if strat:
            q = q.where(FactTradeRecommendation.strategy_name == strat)
        recs = list(session.scalars(q).all())
        for rec in recs:
            out.append((sub, rec))
    return out


def _trailing_vol_by_stock(
    session: Session,
    *,
    stock_keys: Sequence[int],
    as_of_date: date,
    window_days: int = 20,
) -> dict[int, float]:
    """Compute trailing daily return volatility (stdev) from close prices.

    Notes:
    - Uses local-currency close prices; this is a sizing heuristic for relative risk scaling.
    - Requires at least 2 return observations to produce a volatility estimate.
    """
    keys = [int(k) for k in stock_keys if k is not None]
    if not keys:
        return {}
    w = max(int(window_days), 1)

    subq = (
        select(
            FactSecurityPrice.stock_key.label("stock_key"),
            FactSecurityPrice.close_px.label("close_px"),
            func.row_number()
            .over(
                partition_by=FactSecurityPrice.stock_key,
                order_by=FactSecurityPrice.date_key.desc(),
            )
            .label("rn"),
        )
        .join(DimDate, DimDate.date_key == FactSecurityPrice.date_key)
        .where(DimDate.full_date <= as_of_date)
        .where(DimDate.is_trading_day.is_(True))
        .where(FactSecurityPrice.stock_key.in_(keys))
        .subquery()
    )
    rows = session.execute(
        select(subq.c.stock_key, subq.c.close_px, subq.c.rn).where(subq.c.rn <= (w + 1))
    ).all()

    closes_by_stock: dict[int, list[tuple[int, float]]] = {}
    for stock_key, close_px, rn in rows:
        try:
            px = float(close_px or 0)
        except Exception:
            continue
        if px <= 0:
            continue
        closes_by_stock.setdefault(int(stock_key), []).append((int(rn), px))

    out: dict[int, float] = {}
    for stock_key, pairs in closes_by_stock.items():
        # rn=1 is most-recent. Sort ascending by rn to get chronological reverse order.
        pairs.sort(key=lambda x: x[0])
        closes = [px for _rn, px in pairs]
        if len(closes) < 3:
            continue
        rets: list[float] = []
        for i in range(len(closes) - 1):
            p0 = closes[i]
            p1 = closes[i + 1]
            if p0 <= 0 or p1 <= 0:
                continue
            rets.append((p0 / p1) - 1.0)
        if len(rets) < 2:
            continue
        try:
            out[int(stock_key)] = float(statistics.stdev(rets))
        except Exception:
            continue

    return out


def _compute_model_target_weights(
    session: Session,
    *,
    model_portfolio_id: uuid.UUID,
    as_of_date: date,
) -> tuple[dict[int, Decimal], dict[str, Any], set[uuid.UUID], list[dict[str, Any]]]:
    """Compute per-stock target weights (signed; gross risk-budget) for a model portfolio/day.

    This is a close-based, daily approximation:
    - Pulls `fact_trade_recommendation` for the configured (source, strategy) streams on `as_of_date`.
    - Treats BUY/COVER as positive exposure and SELL/SHORT as negative exposure.
    - Allocates each strategy's budget across its symbols in proportion to signal "strength"
      (risk_budget_bps > size_percent > size_shares > 1.0).
    """
    cfg = _get_active_model_config(
        session, model_portfolio_id=model_portfolio_id, as_of_date=as_of_date
    )
    blend_items = _parse_model_strategy_blend(getattr(cfg, "config", {}) or {})

    as_of_date_key = _resolve_date_key(session, full_date=as_of_date)

    weights: dict[int, Decimal] = {}
    included: set[uuid.UUID] = set()
    strategy_summaries: list[dict[str, Any]] = []
    strategy_breakdown: list[dict[str, Any]] = []

    for item in blend_items:
        if not bool(item.get("enabled", True)):
            continue
        weight_pct = float(item.get("weight_pct") or 0.0)
        if weight_pct <= 0:
            continue
        source_name = str(item["source_name"])
        strategy_name = str(item["strategy_name"])

        source_key = _resolve_source_key_by_name(session, source_name=source_name)
        recs = list(
            session.scalars(
                select(FactTradeRecommendation)
                .where(FactTradeRecommendation.date_key == as_of_date_key)
                .where(FactTradeRecommendation.source_key == int(source_key))
                .where(FactTradeRecommendation.strategy_name == strategy_name)
            ).all()
        )

        scores: dict[int, float] = {}
        for rec in recs:
            action = str(getattr(rec, "action", "") or "").upper()
            if action in {"BUY", "COVER"}:
                sign = 1.0
            elif action in {"SELL", "SHORT"}:
                sign = -1.0
            else:
                continue

            strength = _recommendation_strength(rec)
            scores[int(rec.stock_key)] = scores.get(int(rec.stock_key), 0.0) + (sign * strength)
            included.add(uuid.UUID(str(rec.recommendation_id)))

        total_abs = sum(abs(v) for v in scores.values() if v)
        if total_abs <= 0:
            strategy_summaries.append(
                {
                    "source_key": int(source_key),
                    "source_name": source_name,
                    "strategy_name": strategy_name,
                    "weight_pct": weight_pct,
                    "signals_count": len(recs),
                    "symbols_count": 0,
                    "gross_used_pct": 0.0,
                }
            )
            strategy_breakdown.append(
                {
                    "source_key": int(source_key),
                    "source_name": source_name,
                    "strategy_name": strategy_name,
                    "alloc_weight_pct": weight_pct,
                    "gross_abs_weight_pct": 0.0,
                    "positions": [],
                }
            )
            continue

        gross_budget = Decimal(weight_pct) / Decimal("100")
        gross_abs_used = Decimal("0")
        positions: list[dict[str, Any]] = []
        symbols_used = 0
        for stock_key, score in scores.items():
            if score == 0:
                continue
            symbols_used += 1
            w = (Decimal(abs(score)) / Decimal(total_abs)) * gross_budget
            if score < 0:
                w = -w
            weights[int(stock_key)] = weights.get(int(stock_key), Decimal("0")) + w
            gross_abs_used += abs(w)
            positions.append({"stock_key": int(stock_key), "weight_pct": float(w * Decimal("100"))})

        strategy_summaries.append(
            {
                "source_key": int(source_key),
                "source_name": source_name,
                "strategy_name": strategy_name,
                "weight_pct": weight_pct,
                "signals_count": len(recs),
                "symbols_count": symbols_used,
                "gross_used_pct": float(gross_budget * Decimal("100")),
            }
        )
        positions.sort(key=lambda x: abs(float(x["weight_pct"])), reverse=True)
        strategy_breakdown.append(
            {
                "source_key": int(source_key),
                "source_name": source_name,
                "strategy_name": strategy_name,
                "alloc_weight_pct": weight_pct,
                "gross_abs_weight_pct": float(gross_abs_used * Decimal("100")),
                "positions": positions,
            }
        )

    summary = {
        "model_portfolio_id": str(model_portfolio_id),
        "as_of_date": str(as_of_date),
        "config_id": int(cfg.config_id),
        "strategies": strategy_summaries,
        "symbols_count": len(weights),
        "gross_abs_weight_pct": float(sum(abs(w) for w in weights.values()) * Decimal("100")),
    }
    return weights, summary, included, strategy_breakdown


def _compute_model_target_weights_from_grades(
    session: Session,
    *,
    model_portfolio_id: uuid.UUID,
    as_of_date: date,
) -> tuple[dict[int, Decimal], dict[str, Any], set[uuid.UUID], list[dict[str, Any]]]:
    """Compute model target weights from RankAlpha grades (mv_latest_grades).

    This is intentionally simple: select top-N symbols and assign weights based on the config.
    """
    cfg_row = _get_active_model_config(
        session, model_portfolio_id=model_portfolio_id, as_of_date=as_of_date
    )
    cfg = typing_cast(dict[str, Any], getattr(cfg_row, "config", {}) or {})

    selection = _get_dict(cfg, "selection")
    weighting = _get_dict(cfg, "weighting")

    top_n = max(int(_get_int(selection, "top_n", 50) or 50), 0)
    min_grade = _get_float(selection, "min_grade", None)
    rank_field = str(selection.get("rank_field") or "avg_score").strip()
    if rank_field not in {"avg_score", "grade_order"}:
        raise ValueError("selection.rank_field must be one of: avg_score, grade_order")

    method = str(weighting.get("method") or "EQUAL").strip().upper()
    if method not in {"EQUAL", "SCORE"}:
        raise ValueError("weighting.method must be one of: EQUAL, SCORE")

    # Pull top candidates from mv_latest_grades (latest snapshot).
    # NOTE: mv_latest_grades is 'latest' by definition; this is not a full PIT model.
    base_sql = """
        SELECT symbol, avg_score, grade_order
        FROM rankalpha.mv_latest_grades
        WHERE avg_score IS NOT NULL
    """
    if min_grade is not None:
        base_sql += " AND avg_score >= :min_grade"
    base_sql += f" ORDER BY {rank_field} DESC NULLS LAST, symbol ASC"
    if top_n > 0:
        base_sql += " LIMIT :top_n"

    params: dict[str, Any] = {}
    if min_grade is not None:
        params["min_grade"] = float(min_grade)
    if top_n > 0:
        params["top_n"] = int(top_n)

    grade_rows = session.execute(text(base_sql), params).all()
    symbols = [str(sym).upper() for sym, _avg, _go in grade_rows if sym]
    if not symbols:
        summary = {
            "engine": "RANKALPHA_GRADES",
            "model_portfolio_id": str(model_portfolio_id),
            "as_of_date": str(as_of_date),
            "config_id": int(cfg_row.config_id),
            "symbols_count": 0,
            "selection": {"top_n": top_n, "min_grade": min_grade, "rank_field": rank_field},
            "weighting": {"method": method},
            "note": "No eligible symbols from mv_latest_grades",
        }
        return {}, summary, set(), []

    stock_rows = session.execute(
        select(DimStock.stock_key, DimStock.symbol).where(DimStock.symbol.in_(symbols))
    ).all()
    stock_key_by_symbol = {str(sym).upper(): int(k) for k, sym in stock_rows}

    # Keep ordering from mv_latest_grades selection.
    items: list[tuple[int, float]] = []
    for sym, avg_score, grade_order in grade_rows:
        s = str(sym).upper()
        stock_key = stock_key_by_symbol.get(s)
        if stock_key is None:
            continue
        score = avg_score if rank_field == "avg_score" else grade_order
        try:
            score_f = float(score or 0)
        except Exception:
            score_f = 0.0
        items.append((int(stock_key), score_f))

    if not items:
        summary = {
            "engine": "RANKALPHA_GRADES",
            "model_portfolio_id": str(model_portfolio_id),
            "as_of_date": str(as_of_date),
            "config_id": int(cfg_row.config_id),
            "symbols_count": 0,
            "selection": {"top_n": top_n, "min_grade": min_grade, "rank_field": rank_field},
            "weighting": {"method": method},
            "note": "Selected symbols not found in dim_stock",
        }
        return {}, summary, set(), []

    weights: dict[int, Decimal] = {}
    if method == "EQUAL":
        w = Decimal("1") / Decimal(len(items))
        for stock_key, _score in items:
            weights[int(stock_key)] = w
    else:
        denom = sum(max(0.0, score) for _k, score in items)
        if denom <= 0:
            w = Decimal("1") / Decimal(len(items))
            for stock_key, _score in items:
                weights[int(stock_key)] = w
        else:
            for stock_key, score in items:
                weights[int(stock_key)] = Decimal(str(max(0.0, score))) / Decimal(str(denom))

    summary = {
        "engine": "RANKALPHA_GRADES",
        "model_portfolio_id": str(model_portfolio_id),
        "as_of_date": str(as_of_date),
        "config_id": int(cfg_row.config_id),
        "symbols_count": len(weights),
        "selection": {"top_n": top_n, "min_grade": min_grade, "rank_field": rank_field},
        "weighting": {"method": method},
    }
    return weights, summary, set(), []


def _approve_model_run(
    session: Session,
    *,
    run: PortfolioRun,
    approved_by: str | None,
) -> None:
    now_dt = datetime.now(UTC)
    session.execute(
        update(PortfolioRun)
        .where(PortfolioRun.portfolio_id == run.portfolio_id)
        .where(PortfolioRun.run_kind == run.run_kind)
        .where(PortfolioRun.as_of_date == run.as_of_date)
        .where(PortfolioRun.status == "APPROVED")
        .where(PortfolioRun.run_id != run.run_id)
        .values(status="SUPERSEDED", updated_at=now_dt)
    )
    session.execute(
        update(PortfolioRun)
        .where(PortfolioRun.run_id == run.run_id)
        .values(
            status="APPROVED",
            approved_at=now_dt,
            approved_by=approved_by,
            updated_at=now_dt,
        )
    )


def generate_model_construction_run(
    session: Session,
    *,
    run_id: uuid.UUID,
    generated_by: str | None = None,
) -> dict[str, Any]:
    """Populate a MODEL_CONSTRUCTION run with TARGET weights using the active model config."""
    run = session.get(PortfolioRun, run_id)
    if run is None:
        raise ValueError("run_id not found")
    if str(run.run_kind).upper() != "MODEL_CONSTRUCTION":
        raise ValueError("run_kind must be MODEL_CONSTRUCTION")

    portfolio = session.get(Portfolio, run.portfolio_id)
    if portfolio is None:
        raise ValueError("run.portfolio_id not found")
    if str(getattr(portfolio, "portfolio_kind", "")).upper() != "MODEL":
        raise ValueError("MODEL_CONSTRUCTION runs must belong to a MODEL portfolio")

    cfg_row = _get_active_model_config(
        session,
        model_portfolio_id=uuid.UUID(str(run.portfolio_id)),
        as_of_date=typing_cast(date, run.as_of_date),
    )
    cfg = typing_cast(dict[str, Any], getattr(cfg_row, "config", {}) or {})
    engine = str(cfg.get("engine") or "STRATEGY_BLEND").upper()

    if engine == "RANKALPHA_GRADES":
        weights, summary, included, strategy_breakdown = _compute_model_target_weights_from_grades(
            session,
            model_portfolio_id=uuid.UUID(str(run.portfolio_id)),
            as_of_date=typing_cast(date, run.as_of_date),
        )
    else:
        weights, summary, included, strategy_breakdown = _compute_model_target_weights(
            session,
            model_portfolio_id=uuid.UUID(str(run.portfolio_id)),
            as_of_date=typing_cast(date, run.as_of_date),
        )
    as_of_date_key = _resolve_date_key(session, full_date=typing_cast(date, run.as_of_date))

    # Price snapshot (best-effort).
    close_by_stock: dict[int, Decimal] = {}
    if weights:
        px_rows = session.execute(
            select(FactSecurityPrice.stock_key, FactSecurityPrice.close_px)
            .where(FactSecurityPrice.date_key == as_of_date_key)
            .where(FactSecurityPrice.stock_key.in_(list(weights.keys())))
        ).all()
        close_by_stock = {int(k): (px or Decimal("0")) for k, px in px_rows}

    now_dt = datetime.now(UTC)

    # Upsert TARGET positions (unique by (run_id, role, stock_key)).
    if weights:
        session.execute(
            delete(PortfolioRunPosition)
            .where(PortfolioRunPosition.run_id == run.run_id)
            .where(PortfolioRunPosition.position_role == "TARGET")
        )
        for stock_key, w in weights.items():
            session.execute(
                insert(PortfolioRunPosition).values(
                    run_id=run.run_id,
                    position_role="TARGET",
                    instrument_type="EQUITY",
                    stock_key=int(stock_key),
                    currency_code=None,
                    quantity=Decimal("0"),
                    price_close_local=close_by_stock.get(int(stock_key)),
                    market_value_local=None,
                    market_value_base=None,
                    weight_pct=float(w * Decimal("100")),
                    updated_at=now_dt,
                )
            )
    else:
        session.execute(
            delete(PortfolioRunPosition)
            .where(PortfolioRunPosition.run_id == run.run_id)
            .where(PortfolioRunPosition.position_role == "TARGET")
        )

    # Signal lineage (best-effort): record all included recommendations.
    session.execute(
        delete(PortfolioRunSignalInput).where(PortfolioRunSignalInput.run_id == run.run_id)
    )
    for rec_id in sorted(included):
        session.execute(
            insert(PortfolioRunSignalInput)
            .values(
                run_id=run.run_id,
                recommendation_id=rec_id,
                subscription_id=None,
                sized_notional_base=None,
                sized_qty_shares=None,
                included=True,
                reason=None,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    PortfolioRunSignalInput.run_id,
                    PortfolioRunSignalInput.recommendation_id,
                ]
            )
        )

    # Artifacts: config + engine summary.
    session.execute(
        insert(PortfolioRunArtifact)
        .values(
            run_id=run.run_id,
            artifact_type="model_engine_summary",
            payload=typing_cast(dict[str, Any], summary),
            updated_at=now_dt,
        )
        .on_conflict_do_update(
            index_elements=[PortfolioRunArtifact.run_id, PortfolioRunArtifact.artifact_type],
            set_={"payload": cast(summary, JSONB), "updated_at": now_dt},
        )
    )

    strat_payload = {
        "model_portfolio_id": str(run.portfolio_id),
        "as_of_date": str(run.as_of_date),
        "config_id": int(summary.get("config_id") or 0),
        "strategies": strategy_breakdown,
    }
    session.execute(
        insert(PortfolioRunArtifact)
        .values(
            run_id=run.run_id,
            artifact_type="model_strategy_weights",
            payload=typing_cast(dict[str, Any], strat_payload),
            updated_at=now_dt,
        )
        .on_conflict_do_update(
            index_elements=[PortfolioRunArtifact.run_id, PortfolioRunArtifact.artifact_type],
            set_={
                "payload": cast(strat_payload, JSONB),
                "updated_at": now_dt,
            },
        )
    )

    # Model runs are auto-approved (they do not place broker orders).
    _approve_model_run(session, run=run, approved_by=generated_by)
    # Library code must not commit; callers own transaction boundaries.
    session.flush()
    return summary


def ensure_model_construction_run(
    session: Session,
    *,
    model_portfolio_id: uuid.UUID,
    as_of_date: date,
    created_by: str | None = None,
) -> uuid.UUID:
    """Idempotently ensure an approved MODEL_CONSTRUCTION run exists for (model, as_of_date)."""
    existing = session.scalar(
        select(PortfolioRun)
        .where(PortfolioRun.portfolio_id == model_portfolio_id)
        .where(PortfolioRun.run_kind == "MODEL_CONSTRUCTION")
        .where(PortfolioRun.as_of_date == as_of_date)
        .where(PortfolioRun.status == "APPROVED")
        .order_by(PortfolioRun.run_seq.desc())
        .limit(1)
    )
    if existing is not None:
        return uuid.UUID(str(existing.run_id))

    run = create_portfolio_run(
        session,
        portfolio_id=model_portfolio_id,
        run_kind="MODEL_CONSTRUCTION",
        as_of_date=as_of_date,
        policy_id=None,
        created_by=created_by,
    )
    generate_model_construction_run(
        session, run_id=uuid.UUID(str(run.run_id)), generated_by=created_by
    )
    return uuid.UUID(str(run.run_id))


def generate_broker_rebalance_run(
    session: Session,
    *,
    run_id: uuid.UUID,
    generated_by: str | None = None,
) -> dict[str, Any]:
    """Populate a BROKER_REBALANCE run from deployed model targets + broker policy overrides."""
    run = session.get(PortfolioRun, run_id)
    if run is None:
        raise ValueError("run_id not found")
    if str(run.run_kind).upper() != "BROKER_REBALANCE":
        raise ValueError("run_kind must be BROKER_REBALANCE")

    broker = session.get(Portfolio, run.portfolio_id)
    if broker is None:
        raise ValueError("run.portfolio_id not found")
    if str(getattr(broker, "portfolio_kind", "")).upper() != "BROKER":
        raise ValueError("BROKER_REBALANCE runs must belong to a BROKER portfolio")

    policy = _resolve_policy_for_run(session, run=run)
    constraints = dict(getattr(policy, "constraints", {}) or {}) if policy is not None else {}
    nav_cfg = _get_dict(constraints, "nav")
    exposure = _get_dict(constraints, "exposure")
    composition = _get_dict(constraints, "composition")
    overrides = _get_dict(constraints, "overrides")
    position_limits = _get_dict(constraints, "position_limits")
    fx_cfg = _get_dict(constraints, "fx")

    long_only = bool(exposure.get("long_only", True))
    allow_margin = bool(exposure.get("allow_margin", False))
    max_gross_exposure_pct = _get_float(exposure, "max_gross_exposure_pct", None)
    if max_gross_exposure_pct is None:
        max_gross_exposure_pct = _get_float(exposure, "max_allocatable_exposure_pct", None)
    if max_gross_exposure_pct is None:
        max_leverage = _get_float(exposure, "max_leverage", None)
        if max_leverage is None:
            max_leverage = _get_float(exposure, "max_gross_exposure", None)
        if max_leverage is not None:
            max_gross_exposure_pct = float(max_leverage) * 100.0
    min_cash_buffer_pct = _get_float(nav_cfg, "min_cash_buffer_pct", 1.0) or 0.0
    if min_cash_buffer_pct < 0:
        min_cash_buffer_pct = 0.0
    if min_cash_buffer_pct >= 100:
        raise ValueError("constraints.nav.min_cash_buffer_pct must be < 100")

    tolerate_untracked = bool(composition.get("tolerate_untracked_positions", True))
    fallback_fx = bool(fx_cfg.get("fallback_to_last_available", True))
    max_lookback_days = max(int(_get_int(fx_cfg, "max_lookback_days", 30) or 30), 0)
    pivot_ccy = str(fx_cfg.get("pivot_ccy") or "USD").upper()
    fx_cache: dict[tuple[int, str, str, str, int, bool], Decimal | None] = {}

    # Manual floors (long-only): symbol -> min_shares
    raw_floors = overrides.get("long_min_shares") or overrides.get("min_shares") or {}
    if raw_floors is None:
        raw_floors = {}
    if not isinstance(raw_floors, dict):
        raise ValueError("constraints.overrides.long_min_shares must be an object")

    base_ccy = str(getattr(broker, "currency_code", "USD") or "USD").upper()

    as_of_date = typing_cast(date, run.as_of_date)
    as_of_date_key = _resolve_date_key(session, full_date=as_of_date)

    # ---- deployments + model runs ----
    deps = list(
        session.scalars(
            select(PortfolioDeployment)
            .where(PortfolioDeployment.broker_portfolio_id == broker.portfolio_id)
            .where(PortfolioDeployment.is_active.is_(True))
            .where(PortfolioDeployment.effective_from <= as_of_date)
            .where(
                or_(
                    PortfolioDeployment.effective_to.is_(None),
                    PortfolioDeployment.effective_to > as_of_date,
                )
            )
            .order_by(PortfolioDeployment.effective_from.desc())
        ).all()
    )
    if not deps:
        raise ValueError("No active deployments for broker portfolio on as_of_date")

    model_runs: list[dict[str, Any]] = []
    for dep in deps:
        model_run_id = ensure_model_construction_run(
            session,
            model_portfolio_id=uuid.UUID(str(dep.model_portfolio_id)),
            as_of_date=as_of_date,
            created_by=generated_by,
        )
        model_runs.append(
            {
                "deployment_id": uuid.UUID(str(dep.deployment_id)),
                "model_portfolio_id": uuid.UUID(str(dep.model_portfolio_id)),
                "model_run_id": model_run_id,
                "allocation_pct": float(dep.allocation_pct),
                "sleeve_portfolio_id": uuid.UUID(str(dep.sleeve_portfolio_id)),
            }
        )
    total_allocation_pct = sum(float(mr["allocation_pct"]) for mr in model_runs)
    if total_allocation_pct < 0:
        raise ValueError("Total deployment allocation_pct must be non-negative")
    if not allow_margin and total_allocation_pct > 100.0 + 1e-6:
        raise ValueError(
            "Total deployment allocation_pct exceeds 100; enable constraints.exposure.allow_margin "
            "or lower allocations"
        )
    if allow_margin and max_gross_exposure_pct is not None:
        if max_gross_exposure_pct <= 0:
            raise ValueError("constraints.exposure.max_gross_exposure_pct must be > 0")
        if total_allocation_pct > float(max_gross_exposure_pct) + 1e-6:
            raise ValueError(
                "Total deployment allocation_pct exceeds constraints.exposure.max_gross_exposure_pct"
            )

    # Persist run inputs (audit)
    session.execute(delete(PortfolioRunInput).where(PortfolioRunInput.broker_run_id == run.run_id))
    for mr in model_runs:
        session.execute(
            insert(PortfolioRunInput)
            .values(
                broker_run_id=run.run_id,
                deployment_id=mr["deployment_id"],
                model_run_id=mr["model_run_id"],
                allocation_pct_snapshot=mr["allocation_pct"],
            )
            .on_conflict_do_update(
                index_elements=[PortfolioRunInput.broker_run_id, PortfolioRunInput.deployment_id],
                set_={
                    "model_run_id": mr["model_run_id"],
                    "allocation_pct_snapshot": mr["allocation_pct"],
                },
            )
        )

    # Load model weights from their run TARGETs (weight_pct stored as percent; convert to fraction).
    weights_by_model_run: dict[uuid.UUID, dict[int, Decimal]] = {}
    for mr in model_runs:
        rid = uuid.UUID(str(mr["model_run_id"]))
        rows = session.execute(
            select(PortfolioRunPosition.stock_key, PortfolioRunPosition.weight_pct)
            .where(PortfolioRunPosition.run_id == rid)
            .where(PortfolioRunPosition.position_role == "TARGET")
            .where(PortfolioRunPosition.instrument_type == "EQUITY")
        ).all()
        weights_by_model_run[rid] = {
            int(k): (Decimal(w or 0) / Decimal("100")) for k, w in rows if k is not None
        }

    floor_by_stock: dict[int, int] = {}
    floor_symbol_by_stock: dict[int, str] = {}
    requested_floors: dict[str, int] = {}
    for sym, raw_qty in raw_floors.items():
        symbol = str(sym or "").strip().upper()
        if not symbol:
            continue
        qty = int(raw_qty or 0)
        if qty <= 0:
            continue
        requested_floors[symbol] = qty
    if requested_floors:
        floor_rows = session.execute(
            select(DimStock.symbol, DimStock.stock_key).where(
                DimStock.symbol.in_(list(requested_floors.keys()))
            )
        ).all()
        found: set[str] = set()
        for symbol, stock_key in floor_rows:
            sym_u = str(symbol or "").upper()
            if not sym_u or stock_key is None:
                continue
            found.add(sym_u)
            floor_by_stock[int(stock_key)] = int(requested_floors[sym_u])
            floor_symbol_by_stock[int(stock_key)] = sym_u
        missing_symbols = sorted(set(requested_floors.keys()) - found)
        if missing_symbols:
            raise ValueError(f"Unknown symbol for long_min_shares: {', '.join(missing_symbols)}")

    managed_stock_keys: set[int] = set(floor_by_stock.keys())
    for w in weights_by_model_run.values():
        managed_stock_keys |= set(w.keys())

    # External delta-trade subscriptions (auditable overlay term in netting).
    signal_subs = _get_active_signal_subscriptions(
        session, broker_portfolio_id=uuid.UUID(str(broker.portfolio_id)), as_of_date=as_of_date
    )
    signal_recs = _load_signal_recommendations(
        session, subscriptions=signal_subs, as_of_date_key=int(as_of_date_key)
    )
    signal_stock_keys: set[int] = {
        int(rec.stock_key) for _sub, rec in signal_recs if rec.stock_key is not None
    }
    managed_stock_keys |= signal_stock_keys

    # ---- broker baseline snapshot (current tables) ----
    pos_rows = session.execute(
        select(PortfolioPosition, DimStock.symbol, DimStock.currency_code)
        .select_from(PortfolioPosition)
        .join(DimStock, DimStock.stock_key == PortfolioPosition.stock_key)
        .where(PortfolioPosition.portfolio_id == broker.portfolio_id)
    ).all()
    cash_rows = list(
        session.scalars(
            select(PortfolioCashPosition).where(
                PortfolioCashPosition.portfolio_id == broker.portfolio_id
            )
        ).all()
    )

    baseline_shares: dict[int, Decimal] = {}
    baseline_symbols: dict[int, str] = {}
    stock_ccy_by_key: dict[int, str] = {}
    for pos, symbol, ccy in pos_rows:
        baseline_shares[int(pos.stock_key)] = Decimal(pos.quantity or 0)
        baseline_symbols[int(pos.stock_key)] = str(symbol)
        stock_ccy_by_key[int(pos.stock_key)] = str(ccy or "").upper() or base_ccy

    cash_by_ccy: dict[str, Decimal] = {}
    for c in cash_rows:
        ccy = str(getattr(c, "currency_code", "") or "").upper() or base_ccy
        cash_by_ccy[ccy] = cash_by_ccy.get(ccy, Decimal("0")) + Decimal(
            getattr(c, "cash_amount", 0) or 0
        )

    # ---- close prices needed for sizing/reserve ----
    sizing_keys = set(baseline_shares.keys()) | managed_stock_keys
    px_rows = session.execute(
        select(FactSecurityPrice.stock_key, FactSecurityPrice.close_px)
        .where(FactSecurityPrice.date_key == as_of_date_key)
        .where(FactSecurityPrice.stock_key.in_(list(sizing_keys)))
    ).all()
    close_by_stock: dict[int, Decimal] = {int(k): (px or Decimal("0")) for k, px in px_rows}

    missing = [k for k in sizing_keys if close_by_stock.get(int(k), Decimal("0")) <= 0]
    if missing:
        missing_syms = [baseline_symbols.get(int(k)) or str(k) for k in missing]
        raise ValueError(f"Missing close prices for sizing: {missing_syms}")

    # Ensure we have currency codes for all sizing stocks (for FX conversion).
    missing_ccy_keys = [k for k in sizing_keys if int(k) not in stock_ccy_by_key]
    if missing_ccy_keys:
        rows = session.execute(
            select(DimStock.stock_key, DimStock.currency_code).where(
                DimStock.stock_key.in_(list(missing_ccy_keys))
            )
        ).all()
        for k, ccy in rows:
            stock_ccy_by_key[int(k)] = str(ccy or "").upper() or base_ccy

    # Resolve FX for all required currencies (stocks + cash).
    required_ccys = set(cash_by_ccy.keys()) | {
        stock_ccy_by_key.get(int(k), base_ccy) for k in sizing_keys
    }
    required_ccys.add(base_ccy)
    fx_to_base: dict[str, Decimal] = {base_ccy: Decimal("1")}
    missing_fx: list[dict[str, Any]] = []
    for ccy in sorted({c for c in required_ccys if c and c != base_ccy}):
        fx = _fx_mid_px(
            session,
            date_key=as_of_date_key,
            from_ccy=ccy,
            to_ccy=base_ccy,
            fallback_to_last_available=fallback_fx,
            max_lookback_days=max_lookback_days,
            pivot_ccy=pivot_ccy,
            cache=fx_cache,
        )
        if fx is None:
            missing_fx.append({"from_ccy": ccy, "to_ccy": base_ccy})
            continue
        fx_to_base[ccy] = fx
    if missing_fx:
        raise ValueError(f"Missing FX rates required for sizing: {missing_fx}")

    close_base_by_stock: dict[int, Decimal] = {}
    for k in sizing_keys:
        local_ccy = stock_ccy_by_key.get(int(k), base_ccy) or base_ccy
        fx = fx_to_base.get(local_ccy)
        if fx is None:
            raise ValueError(f"Missing FX for {local_ccy}->{base_ccy}")
        close_base_by_stock[int(k)] = close_by_stock[int(k)] * fx

    baseline_equity_base = sum(
        (qty * close_base_by_stock[int(k)]) for k, qty in baseline_shares.items()
    )
    baseline_cash_base = sum(
        (amt * fx_to_base.get(ccy, Decimal("0"))) for ccy, amt in cash_by_ccy.items()
    )
    baseline_reconstructed_nlv = baseline_equity_base + baseline_cash_base

    # Prefer broker NLV for sizing when available (execution day D = next trading day after as_of_date).
    execution_date = _next_trading_day(session, after_date=as_of_date)
    exec_date_key = _resolve_date_key(session, full_date=execution_date)
    broker_nlv_raw = session.scalar(
        select(FactPortfolioBrokerNlv.nlv_base_ccy)
        .where(FactPortfolioBrokerNlv.portfolio_id == broker.portfolio_id)
        .where(FactPortfolioBrokerNlv.date_key == int(exec_date_key))
        .limit(1)
    )
    nav_anchor = (
        Decimal(str(broker_nlv_raw)) if broker_nlv_raw is not None else baseline_reconstructed_nlv
    )
    nav_anchor_source = "BROKER_NLV" if broker_nlv_raw is not None else "RECONSTRUCTED"

    # ---- reserved / allocatable NLV ----
    untracked_stock_keys = set()
    if tolerate_untracked:
        untracked_stock_keys = set(baseline_shares.keys()) - managed_stock_keys

    reserved_untracked = sum(
        abs(baseline_shares[int(k)]) * close_base_by_stock[int(k)] for k in untracked_stock_keys
    )
    reserved_floors = sum(
        Decimal(qty) * close_base_by_stock[int(k)] for k, qty in floor_by_stock.items()
    )
    reserved_total = reserved_untracked + reserved_floors

    cash_buffer_frac = (
        (Decimal(str(min_cash_buffer_pct)) / Decimal("100"))
        if min_cash_buffer_pct
        else Decimal("0")
    )
    investable_nav = nav_anchor * (Decimal("1") - cash_buffer_frac)

    allocatable_nlv = investable_nav - reserved_total
    if allocatable_nlv < 0:
        allocatable_nlv = Decimal("0")

    # ---- aggregate model target shares (allocatable overlay only) ----
    overlay_shares: dict[int, Decimal] = {}
    for mr in model_runs:
        model_run_id = uuid.UUID(str(mr["model_run_id"]))
        allocation_pct = Decimal(str(mr["allocation_pct"] or 0))
        model_budget = (allocation_pct / Decimal("100")) * allocatable_nlv

        w = weights_by_model_run.get(model_run_id, {})
        for stock_key, weight in w.items():
            if weight == 0:
                continue
            px_base = close_base_by_stock.get(int(stock_key))
            if px_base is None or px_base <= 0:
                continue
            notional = model_budget * weight
            overlay_shares[int(stock_key)] = overlay_shares.get(int(stock_key), Decimal("0")) + (
                notional / px_base
            )

    # ---- build target shares (apply floors + freeze untracked) ----
    target_desired: dict[int, Decimal] = {}
    for stock_key, qty in overlay_shares.items():
        target_desired[int(stock_key)] = Decimal(qty)

    # Apply floors: locked base slice + non-negative overlay
    for stock_key, min_qty in floor_by_stock.items():
        extra = target_desired.get(int(stock_key), Decimal("0"))
        if extra < 0:
            extra = Decimal("0")
        target_desired[int(stock_key)] = Decimal(min_qty) + extra

    if tolerate_untracked:
        for stock_key in untracked_stock_keys:
            target_desired[int(stock_key)] = baseline_shares.get(int(stock_key), Decimal("0"))

    # ---- external delta-trade overlay (subscriptions) ----
    signal_overlay_shares: dict[int, Decimal] = {}
    signal_rows: list[dict[str, Any]] = []
    if signal_recs:
        inv_vol_groups: dict[
            int, tuple[PortfolioSignalSubscription, list[FactTradeRecommendation]]
        ] = {}

        def _record_signal(
            *,
            rec: FactTradeRecommendation,
            sub: PortfolioSignalSubscription,
            included: bool,
            reason: str | None,
            sized_notional_base: Decimal | None,
            sized_qty_shares: Decimal | None,
        ) -> None:
            qty_int: int | None = None
            if sized_qty_shares is not None:
                try:
                    qty_int = int(abs(sized_qty_shares).quantize(Decimal("1"), rounding=ROUND_DOWN))
                except Exception:
                    qty_int = None
            signal_rows.append(
                {
                    "recommendation_id": uuid.UUID(str(rec.recommendation_id)),
                    "subscription_id": int(sub.subscription_id),
                    "sized_notional_base": sized_notional_base,
                    "sized_qty_shares": qty_int,
                    "included": bool(included),
                    "reason": reason,
                }
            )

        for sub, rec in signal_recs:
            method = str(getattr(sub, "sizing_method", "") or "").upper()
            if method == "RISK_BUDGET_BPS_INV_VOL":
                inv_vol_groups.setdefault(int(sub.subscription_id), (sub, []))[1].append(rec)
                continue

            action = str(getattr(rec, "action", "") or "").upper()
            if action not in {"BUY", "SELL"}:
                _record_signal(
                    rec=rec,
                    sub=sub,
                    included=False,
                    reason=f"unsupported_action_{action or 'UNKNOWN'}",
                    sized_notional_base=None,
                    sized_qty_shares=None,
                )
                continue

            stock_key = int(rec.stock_key)
            px_base = close_base_by_stock.get(stock_key, Decimal("0"))
            if px_base <= 0:
                _record_signal(
                    rec=rec,
                    sub=sub,
                    included=False,
                    reason="missing_close_px",
                    sized_notional_base=None,
                    sized_qty_shares=None,
                )
                continue

            qty_mag: Decimal | None = None
            notional_base: Decimal | None = None

            if method == "USE_SIGNAL_SIZE":
                if rec.size_shares is not None:
                    qty_mag = Decimal(int(rec.size_shares))
                    notional_base = qty_mag * px_base
                elif rec.size_percent is not None:
                    notional_base = (Decimal(str(rec.size_percent)) / Decimal("100")) * nav_anchor
                    qty_mag = notional_base / px_base
                elif rec.risk_budget_bps is not None:
                    notional_base = (
                        Decimal(str(rec.risk_budget_bps)) / Decimal("10000")
                    ) * nav_anchor
                    qty_mag = notional_base / px_base
                else:
                    # Subscription-level defaults.
                    if getattr(sub, "default_notional_pct_nav", None) is not None:
                        notional_base = (
                            Decimal(str(sub.default_notional_pct_nav)) / Decimal("100")
                        ) * nav_anchor
                        qty_mag = notional_base / px_base
                    elif getattr(sub, "default_risk_budget_bps", None) is not None:
                        notional_base = (
                            Decimal(str(sub.default_risk_budget_bps)) / Decimal("10000")
                        ) * nav_anchor
                        qty_mag = notional_base / px_base
            elif method == "NOTIONAL_PCT_NAV":
                pct = (
                    rec.size_percent
                    if rec.size_percent is not None
                    else getattr(sub, "default_notional_pct_nav", None)
                )
                if pct is not None:
                    notional_base = (Decimal(str(pct)) / Decimal("100")) * nav_anchor
                    qty_mag = notional_base / px_base
            elif method == "RISK_BUDGET_BPS_FIXED":
                bps = (
                    rec.risk_budget_bps
                    if rec.risk_budget_bps is not None
                    else getattr(sub, "default_risk_budget_bps", None)
                )
                if bps is not None:
                    notional_base = (Decimal(str(bps)) / Decimal("10000")) * nav_anchor
                    qty_mag = notional_base / px_base
            else:
                _record_signal(
                    rec=rec,
                    sub=sub,
                    included=False,
                    reason=f"unsupported_sizing_method_{method or 'UNKNOWN'}",
                    sized_notional_base=None,
                    sized_qty_shares=None,
                )
                continue

            if qty_mag is None or qty_mag <= 0:
                _record_signal(
                    rec=rec,
                    sub=sub,
                    included=False,
                    reason="missing_or_zero_size",
                    sized_notional_base=notional_base,
                    sized_qty_shares=qty_mag,
                )
                continue

            # Long-only MVP: SELL is reduce-only against *baseline*.
            if action == "SELL":
                base_qty = baseline_shares.get(stock_key, Decimal("0"))
                if base_qty <= 0:
                    _record_signal(
                        rec=rec,
                        sub=sub,
                        included=False,
                        reason="reduce_only_no_position",
                        sized_notional_base=notional_base,
                        sized_qty_shares=qty_mag,
                    )
                    continue
                if qty_mag > base_qty:
                    qty_mag = base_qty
                    notional_base = qty_mag * px_base

            signed_qty = qty_mag if action == "BUY" else -qty_mag
            signal_overlay_shares[stock_key] = (
                signal_overlay_shares.get(stock_key, Decimal("0")) + signed_qty
            )
            _record_signal(
                rec=rec,
                sub=sub,
                included=True,
                reason=None,
                sized_notional_base=notional_base,
                sized_qty_shares=qty_mag,
            )

        # RISK_BUDGET_BPS_INV_VOL: allocate a subscription-level risk budget across its signals by inverse vol.
        for _sub_id, (sub, recs) in inv_vol_groups.items():
            if not recs:
                continue
            bps_total = getattr(sub, "default_risk_budget_bps", None)
            if bps_total is None:
                # Fall back to the sum of signal bps if provided.
                s = Decimal("0")
                for r in recs:
                    if r.risk_budget_bps is not None:
                        try:
                            s += Decimal(str(r.risk_budget_bps))
                        except Exception:
                            continue
                bps_total = s if s > 0 else None
            if bps_total is None:
                for r in recs:
                    _record_signal(
                        rec=r,
                        sub=sub,
                        included=False,
                        reason="missing_risk_budget_bps",
                        sized_notional_base=None,
                        sized_qty_shares=None,
                    )
                continue

            total_notional = (Decimal(str(bps_total)) / Decimal("10000")) * nav_anchor
            keys = [int(r.stock_key) for r in recs if r.stock_key is not None]
            vol_by_stock = _trailing_vol_by_stock(
                session, stock_keys=keys, as_of_date=as_of_date, window_days=20
            )
            inv: dict[int, Decimal] = {}
            for k in keys:
                v = vol_by_stock.get(int(k))
                if v is None or v <= 0:
                    continue
                inv[int(k)] = Decimal("1") / Decimal(str(v))
            denom = sum(inv.values()) if inv else Decimal("0")
            if denom <= 0:
                for r in recs:
                    _record_signal(
                        rec=r,
                        sub=sub,
                        included=False,
                        reason="missing_volatility",
                        sized_notional_base=None,
                        sized_qty_shares=None,
                    )
                continue

            for r in recs:
                action = str(getattr(r, "action", "") or "").upper()
                if action not in {"BUY", "SELL"}:
                    _record_signal(
                        rec=r,
                        sub=sub,
                        included=False,
                        reason=f"unsupported_action_{action or 'UNKNOWN'}",
                        sized_notional_base=None,
                        sized_qty_shares=None,
                    )
                    continue
                stock_key = int(r.stock_key)
                inv_w = inv.get(stock_key)
                px_base = close_base_by_stock.get(stock_key, Decimal("0"))
                if inv_w is None or px_base <= 0:
                    _record_signal(
                        rec=r,
                        sub=sub,
                        included=False,
                        reason="missing_close_or_vol",
                        sized_notional_base=None,
                        sized_qty_shares=None,
                    )
                    continue
                notional_i = total_notional * (inv_w / denom)
                qty_mag = notional_i / px_base
                if qty_mag <= 0:
                    _record_signal(
                        rec=r,
                        sub=sub,
                        included=False,
                        reason="zero_size",
                        sized_notional_base=notional_i,
                        sized_qty_shares=qty_mag,
                    )
                    continue

                if action == "SELL":
                    base_qty = baseline_shares.get(stock_key, Decimal("0"))
                    if base_qty <= 0:
                        _record_signal(
                            rec=r,
                            sub=sub,
                            included=False,
                            reason="reduce_only_no_position",
                            sized_notional_base=notional_i,
                            sized_qty_shares=qty_mag,
                        )
                        continue
                    if qty_mag > base_qty:
                        qty_mag = base_qty
                        notional_i = qty_mag * px_base

                signed_qty = qty_mag if action == "BUY" else -qty_mag
                signal_overlay_shares[stock_key] = (
                    signal_overlay_shares.get(stock_key, Decimal("0")) + signed_qty
                )
                _record_signal(
                    rec=r,
                    sub=sub,
                    included=True,
                    reason=None,
                    sized_notional_base=notional_i,
                    sized_qty_shares=qty_mag,
                )

    # Apply overlay deltas into target_desired (netting term).
    for stock_key, d_qty in signal_overlay_shares.items():
        if d_qty == 0:
            continue
        target_desired[int(stock_key)] = target_desired.get(int(stock_key), Decimal("0")) + d_qty

    clamped_negative_stock_keys: list[int] = []
    if long_only:
        for k, q in list(target_desired.items()):
            if q < 0:
                clamped_negative_stock_keys.append(int(k))
                target_desired[int(k)] = Decimal("0")

    # ---- compute rounded orders + final target ----
    round_lot_size = max(int(_get_int(position_limits, "round_lot_size", 1) or 1), 1)
    allow_fractional = bool(position_limits.get("allow_fractional_shares", False))
    if allow_fractional:
        raise ValueError(
            "constraints.position_limits.allow_fractional_shares=true is not supported for "
            "broker export (size_shares must be integer)"
        )

    line_no = 1
    orders: list[dict[str, Any]] = []
    final_target: dict[int, Decimal] = {}
    order_notional = Decimal("0")

    all_keys = set(baseline_shares.keys()) | set(target_desired.keys())
    for stock_key in sorted(all_keys):
        base_qty = baseline_shares.get(int(stock_key), Decimal("0"))
        desired_qty = target_desired.get(int(stock_key), Decimal("0"))
        if desired_qty == base_qty:
            if base_qty != 0:
                final_target[int(stock_key)] = base_qty
            continue

        def _round_qty(q: Decimal) -> Decimal:
            if q <= 0:
                return Decimal("0")
            if allow_fractional:
                return q
            qi = int(q)
            if round_lot_size > 1:
                qi = qi - (qi % round_lot_size)
            return Decimal(qi)

        def _emit(action: str, qty_trade: Decimal) -> Decimal:
            nonlocal line_no, order_notional
            qty_trade = _round_qty(qty_trade)
            if qty_trade <= 0:
                return Decimal("0")
            px_base = close_base_by_stock[int(stock_key)]
            order_notional += qty_trade * px_base
            orders.append(
                {
                    "line_no": line_no,
                    "stock_key": int(stock_key),
                    "action": action,
                    "qty_shares": float(qty_trade) if allow_fractional else int(qty_trade),
                    "order_type": "MARKET",
                    "time_in_force": "DAY",
                }
            )
            line_no += 1
            return qty_trade

        # Potentially split if we flip sign (long -> short, or short -> long).
        cur = base_qty
        tgt = desired_qty
        if cur > 0 and tgt < 0:
            sold = _emit("SELL", cur)
            cur -= sold
            short_qty = abs(tgt)
            shorted = _emit("SHORT", short_qty)
            cur -= shorted
        elif cur < 0 and tgt > 0:
            covered = _emit("COVER", abs(cur))
            cur += covered
            bought = _emit("BUY", tgt)
            cur += bought
        else:
            delta = tgt - cur
            if delta > 0:
                action = "COVER" if cur < 0 else "BUY"
                traded = _emit(action, delta)
                cur += traded
            else:
                action = "SHORT" if cur <= 0 else "SELL"
                traded = _emit(action, abs(delta))
                cur -= traded

        if cur != 0:
            final_target[int(stock_key)] = cur

    if long_only:
        residual_shorts = []
        for stock_key, qty in final_target.items():
            if qty < 0:
                residual_shorts.append(
                    {
                        "symbol": baseline_symbols.get(int(stock_key)) or str(stock_key),
                        "quantity": float(qty),
                    }
                )
        if residual_shorts:
            raise ValueError(
                "Long-only broker run produced residual short positions after round-lot sizing: "
                f"{residual_shorts}"
            )

    # Estimate target cash after orders, by currency (close-based, local currency).
    est_cash_by_ccy: dict[str, Decimal] = dict(cash_by_ccy)
    for o in orders:
        stock_key = int(o["stock_key"])
        px_local = close_by_stock[int(stock_key)]
        ccy = stock_ccy_by_key.get(int(stock_key), base_ccy) or base_ccy
        qty = Decimal(str(o["qty_shares"]))
        notional_local = qty * px_local
        action = str(o["action"]).upper()
        if action in {"BUY", "COVER"}:
            est_cash_by_ccy[ccy] = est_cash_by_ccy.get(ccy, Decimal("0")) - notional_local
        else:
            est_cash_by_ccy[ccy] = est_cash_by_ccy.get(ccy, Decimal("0")) + notional_local

    est_cash_base = sum(
        (amt * fx_to_base.get(ccy, Decimal("0"))) for ccy, amt in est_cash_by_ccy.items()
    )

    # ---- persist baseline/target run positions + orders ----
    now_dt = datetime.now(UTC)

    # Persist signal lineage for the broker run (external delta trades).
    session.execute(
        delete(PortfolioRunSignalInput).where(PortfolioRunSignalInput.run_id == run.run_id)
    )
    for row in signal_rows:
        session.execute(
            insert(PortfolioRunSignalInput)
            .values(
                run_id=run.run_id,
                recommendation_id=row["recommendation_id"],
                subscription_id=row.get("subscription_id"),
                sized_notional_base=row.get("sized_notional_base"),
                sized_qty_shares=row.get("sized_qty_shares"),
                included=bool(row.get("included", True)),
                reason=row.get("reason"),
            )
            .on_conflict_do_update(
                index_elements=[
                    PortfolioRunSignalInput.run_id,
                    PortfolioRunSignalInput.recommendation_id,
                ],
                set_={
                    "subscription_id": row.get("subscription_id"),
                    "sized_notional_base": row.get("sized_notional_base"),
                    "sized_qty_shares": row.get("sized_qty_shares"),
                    "included": bool(row.get("included", True)),
                    "reason": row.get("reason"),
                },
            )
        )

    session.execute(delete(PortfolioRunPosition).where(PortfolioRunPosition.run_id == run.run_id))

    # baseline equities
    for stock_key, qty in baseline_shares.items():
        px_local = close_by_stock.get(int(stock_key))
        mv_local = qty * (px_local or Decimal("0"))
        mv_base = qty * close_base_by_stock.get(int(stock_key), Decimal("0"))
        session.execute(
            insert(PortfolioRunPosition).values(
                run_id=run.run_id,
                position_role="BASELINE",
                instrument_type="EQUITY",
                stock_key=int(stock_key),
                currency_code=None,
                quantity=qty,
                price_close_local=px_local,
                market_value_local=mv_local,
                market_value_base=mv_base,
                weight_pct=None,
                updated_at=now_dt,
            )
        )

    # baseline cash (multi-ccy)
    for ccy, amt in cash_by_ccy.items():
        fx = fx_to_base.get(ccy, Decimal("0"))
        session.execute(
            insert(PortfolioRunPosition).values(
                run_id=run.run_id,
                position_role="BASELINE",
                instrument_type="CASH",
                stock_key=None,
                currency_code=ccy,
                quantity=amt,
                price_close_local=None,
                market_value_local=amt,
                market_value_base=amt * fx,
                weight_pct=None,
                updated_at=now_dt,
            )
        )

    # target equities
    target_equity_base = sum((qty * close_base_by_stock[int(k)]) for k, qty in final_target.items())
    target_nlv = target_equity_base + est_cash_base
    for stock_key, qty in final_target.items():
        px_local = close_by_stock.get(int(stock_key))
        mv_local = qty * (px_local or Decimal("0"))
        mv_base = qty * close_base_by_stock.get(int(stock_key), Decimal("0"))
        wt = None
        if target_nlv != 0:
            wt = float((mv_base / target_nlv) * Decimal("100"))
        session.execute(
            insert(PortfolioRunPosition).values(
                run_id=run.run_id,
                position_role="TARGET",
                instrument_type="EQUITY",
                stock_key=int(stock_key),
                currency_code=None,
                quantity=qty,
                price_close_local=px_local,
                market_value_local=mv_local,
                market_value_base=mv_base,
                weight_pct=wt,
                updated_at=now_dt,
            )
        )

    # target cash (multi-ccy; close-based estimate)
    for ccy, amt in est_cash_by_ccy.items():
        fx = fx_to_base.get(ccy, Decimal("0"))
        session.execute(
            insert(PortfolioRunPosition).values(
                run_id=run.run_id,
                position_role="TARGET",
                instrument_type="CASH",
                stock_key=None,
                currency_code=ccy,
                quantity=amt,
                price_close_local=None,
                market_value_local=amt,
                market_value_base=amt * fx,
                weight_pct=None,
                updated_at=now_dt,
            )
        )

    # Replace order intents for the run
    session.execute(delete(PortfolioOrderIntent).where(PortfolioOrderIntent.run_id == run.run_id))
    order_ids = upsert_order_intents(session, run_id=uuid.UUID(str(run.run_id)), orders=orders)

    engine_summary = {
        "run_id": str(run.run_id),
        "broker_portfolio_id": str(broker.portfolio_id),
        "as_of_date": str(as_of_date),
        "policy_id": int(policy.policy_id) if policy is not None else None,
        "base_currency": base_ccy,
        "nav_anchor_source": nav_anchor_source,
        "nav_anchor_base": float(nav_anchor),
        "min_cash_buffer_pct": float(min_cash_buffer_pct),
        "investable_nav": float(investable_nav),
        "reconstructed_nav_base": float(baseline_reconstructed_nlv),
        "nav_anchor_discrepancy_base": float(nav_anchor - baseline_reconstructed_nlv),
        "reserved_untracked": float(reserved_untracked),
        "reserved_floors": float(reserved_floors),
        "allocatable_nlv": float(allocatable_nlv),
        "deployments": model_runs,
        "signal_subscriptions_count": len(signal_subs),
        "signal_recommendations_count": len(signal_recs),
        "signal_included_count": sum(1 for r in signal_rows if bool(r.get("included"))),
        "signal_overlay_stock_count": len([k for k, v in signal_overlay_shares.items() if v != 0]),
        "tolerate_untracked_positions": tolerate_untracked,
        "long_only": bool(long_only),
        "clamped_negative_target_stock_keys": sorted(clamped_negative_stock_keys),
        "untracked_symbols": [
            baseline_symbols.get(int(k)) or str(k) for k in sorted(untracked_stock_keys)
        ],
        "floors": [
            {
                "symbol": floor_symbol_by_stock.get(int(k))
                or baseline_symbols.get(int(k))
                or str(k),
                "min_shares": v,
            }
            for k, v in floor_by_stock.items()
        ],
        "orders_count": len(order_ids),
        "orders_notional_usd": float(order_notional),
        "target_nlv": float(target_nlv),
        "target_cash": float(est_cash_base),
        "constraints_used": {
            "max_leverage": _get_float(exposure, "max_leverage", None),
            "allow_margin": bool(allow_margin),
            "max_gross_exposure_pct": (
                float(max_gross_exposure_pct) if max_gross_exposure_pct is not None else None
            ),
            "total_deployment_allocation_pct": float(total_allocation_pct),
            "min_cash_buffer_pct": float(min_cash_buffer_pct),
            "round_lot_size": int(round_lot_size),
            "allow_fractional_shares": bool(allow_fractional),
            "fx_fallback_to_last_available": bool(fallback_fx),
        },
    }

    session.execute(
        insert(PortfolioRunArtifact)
        .values(
            run_id=run.run_id,
            artifact_type="broker_engine_summary",
            payload=typing_cast(dict[str, Any], engine_summary),
            updated_at=now_dt,
        )
        .on_conflict_do_update(
            index_elements=[PortfolioRunArtifact.run_id, PortfolioRunArtifact.artifact_type],
            set_={"payload": cast(engine_summary, JSONB), "updated_at": now_dt},
        )
    )
    session.execute(
        update(PortfolioRun).where(PortfolioRun.run_id == run.run_id).values(updated_at=now_dt)
    )
    # Library code must not commit; callers own transaction boundaries.
    session.flush()
    return engine_summary


def _get_or_create_source_key(session: Session, *, source_name: str, version: str = "1") -> int:
    stmt = (
        insert(DimSource)
        .values(source_name=source_name, version=version)
        .on_conflict_do_nothing(index_elements=[DimSource.source_name, DimSource.version])
        .returning(DimSource.source_key)
    )
    key = session.execute(stmt).scalar_one_or_none()
    if key is not None:
        return int(key)
    fallback = session.scalar(
        select(DimSource.source_key)
        .where(DimSource.source_name == source_name)
        .where(DimSource.version == version)
    )
    if fallback is None:
        raise RuntimeError(f"Failed to ensure DimSource for {source_name}@{version}")
    return int(fallback)


def _export_broker_run_to_trade_recommendations(
    session: Session,
    *,
    run: PortfolioRun,
    execution_date: date,
    exported_by: str | None,
) -> int:
    """Export approved broker run orders into executable broker::<ACCOUNT> trade recommendations.

    This keeps the broker runner unchanged: it continues to poll `fact_trade_recommendation`
    filtered by `source_name = broker::<ACCOUNT>`.
    """
    portfolio = session.get(Portfolio, run.portfolio_id)
    if portfolio is None:
        raise ValueError("run.portfolio_id not found")
    if str(getattr(portfolio, "portfolio_kind", "")).upper() != "BROKER":
        return 0
    if str(run.run_kind).upper() != "BROKER_REBALANCE":
        return 0

    account_id = (
        getattr(portfolio, "broker_account_id", None) or portfolio.portfolio_name or ""
    ).strip()
    if not account_id:
        raise ValueError("Broker portfolio is missing broker_account_id/portfolio_name")
    source_name = _broker_source_name(account_id)
    source_key = _get_or_create_source_key(session, source_name=source_name, version="1")

    exec_date_key = session.scalar(
        select(DimDate.date_key).where(DimDate.full_date == execution_date)
    )
    if exec_date_key is None:
        raise ValueError(f"Date {execution_date} not found in dim_date")
    as_of_date_key = session.scalar(
        select(DimDate.date_key).where(DimDate.full_date == run.as_of_date)
    )
    if as_of_date_key is None:
        raise ValueError(f"Date {run.as_of_date} not found in dim_date")

    orders = list(
        session.scalars(
            select(PortfolioOrderIntent)
            .where(PortfolioOrderIntent.run_id == run.run_id)
            .order_by(PortfolioOrderIntent.line_no.asc())
        ).all()
    )

    # Only export non-zero equity orders; enforce one net (symbol, action) per run.
    seen: set[tuple[int, str]] = set()
    exportable: list[tuple[PortfolioOrderIntent, int]] = []
    stock_keys: set[int] = set()
    for o in orders:
        # Parse via str() to avoid float->Decimal surprises.
        qty_dec = Decimal(str(o.qty_shares or "0"))
        if qty_dec == 0:
            continue
        # Allow negative quantities; interpret as absolute magnitude (direction is encoded by action).
        if qty_dec < 0:
            qty_dec = abs(qty_dec)

        qty_int = int(qty_dec)
        if qty_dec != Decimal(qty_int):
            raise ValueError(
                f"Order line {o.line_no} qty_shares must be an integer for broker export (got {qty_dec})"
            )
        if qty_int <= 0:
            continue

        key = (int(o.stock_key), str(o.action).upper())
        if key in seen:
            raise ValueError("Broker export requires at most one order per symbol/action in a run")
        seen.add(key)
        exportable.append((o, qty_int))
        stock_keys.add(int(o.stock_key))

    if not exportable:
        return 0

    now_dt = datetime.now(UTC)
    # Avoid pre-market execution: gate eligibility until 09:00 ET on execution day.
    try:
        tz_et = ZoneInfo("America/New_York")
    except Exception:
        tz_et = UTC
    min_valid_from = datetime.combine(execution_date, time(9, 0), tzinfo=tz_et).astimezone(UTC)
    valid_from_ts = max(now_dt, min_valid_from)
    expiry_ts = _default_broker_expiry_ts(execution_date)

    # Safety: do not mutate/overwrite already-claimed rows for the same day/account/symbol/action.
    live_pairs = list(seen)
    live_exists = session.scalar(
        select(func.count())
        .select_from(FactTradeRecommendation)
        .where(FactTradeRecommendation.date_key == int(exec_date_key))
        .where(FactTradeRecommendation.source_key == int(source_key))
        .where(
            or_(
                FactTradeRecommendation.strategy_name == "BROKER_RUN",
                FactTradeRecommendation.strategy_name.is_(None),  # legacy exports
            )
        )
        .where(
            tuple_(FactTradeRecommendation.stock_key, FactTradeRecommendation.action).in_(
                live_pairs
            )
        )
        .where(FactTradeRecommendation.is_live.is_(True))
    )
    if live_exists and int(live_exists) > 0:
        raise ValueError(
            "Cannot export broker run: matching broker recommendations already claimed/live"
        )

    # Safety: refuse to overwrite non-broker strategies.
    # Treat NULL strategy_name as broker-owned only when tied to a portfolio run (model_run_id).
    foreign_exists = session.scalar(
        select(func.count())
        .select_from(FactTradeRecommendation)
        .where(FactTradeRecommendation.date_key == int(exec_date_key))
        .where(FactTradeRecommendation.source_key == int(source_key))
        .where(
            tuple_(FactTradeRecommendation.stock_key, FactTradeRecommendation.action).in_(
                live_pairs
            )
        )
        .where(
            or_(
                and_(
                    FactTradeRecommendation.strategy_name.is_not(None),
                    FactTradeRecommendation.strategy_name != "BROKER_RUN",
                ),
                and_(
                    FactTradeRecommendation.strategy_name.is_(None),
                    FactTradeRecommendation.model_run_id.is_(None),
                ),
            )
        )
    )
    if foreign_exists and int(foreign_exists) > 0:
        raise ValueError(
            "Cannot export broker run: existing non-broker recommendations with same key"
        )

    # Cancel any pending broker recommendations for this account/date (e.g., superseded drafts).
    session.execute(
        update(FactTradeRecommendation)
        .where(FactTradeRecommendation.date_key == int(exec_date_key))
        .where(FactTradeRecommendation.source_key == int(source_key))
        .where(
            or_(
                FactTradeRecommendation.strategy_name == "BROKER_RUN",
                FactTradeRecommendation.strategy_name.is_(None),  # legacy exports
            )
        )
        .where(
            or_(
                FactTradeRecommendation.is_live.is_(False),
                FactTradeRecommendation.is_live.is_(None),
            )
        )
        .where(
            or_(
                FactTradeRecommendation.expiry_ts.is_(None),
                FactTradeRecommendation.expiry_ts > now_dt,
            )
        )
        .values(expiry_ts=now_dt, update_ts=now_dt)
    )

    close_rows = session.execute(
        select(FactSecurityPrice.stock_key, FactSecurityPrice.close_px)
        .where(FactSecurityPrice.date_key == int(as_of_date_key))
        .where(FactSecurityPrice.stock_key.in_(stock_keys))
    ).all()
    close_by_stock: dict[int, Decimal] = {int(k): (px or Decimal("0")) for k, px in close_rows}

    exported = 0
    for order, qty_int in exportable:
        close_px = close_by_stock.get(int(order.stock_key))
        rec_px = Decimal("0")
        if close_px and Decimal(close_px) > 0:
            rec_px = Decimal(close_px)
        else:
            limit_px = typing_cast(Decimal | None, order.limit_price)
            stop_px = typing_cast(Decimal | None, order.stop_trigger_price)
            if limit_px is not None:
                rec_px = Decimal(limit_px)
            elif stop_px is not None:
                rec_px = Decimal(stop_px)

        preconditions: dict[str, Any] = {
            "execution": {
                "origin": "portfolio_run",
                "run_id": str(run.run_id),
                "order_id": str(order.order_id),
                "line_no": int(order.line_no),
                "portfolio_id": str(run.portfolio_id),
            }
        }
        if order.target_weight_after is not None:
            try:
                preconditions["execution"]["target_weight_after"] = float(order.target_weight_after)
            except Exception:
                pass

        stmt = (
            insert(FactTradeRecommendation)
            .values(
                date_key=int(exec_date_key),
                stock_key=int(order.stock_key),
                source_key=int(source_key),
                action=str(order.action).upper(),
                strategy_name="BROKER_RUN",
                recommended_price=rec_px,
                order_type=str(order.order_type or "MARKET").upper(),
                time_in_force=str(order.time_in_force or "DAY").upper(),
                valid_from_ts=valid_from_ts,
                expiry_ts=expiry_ts,
                limit_price=order.limit_price,
                stop_trigger_price=order.stop_trigger_price,
                size_shares=int(qty_int),
                size_percent=None,
                portfolio_id=run.portfolio_id,
                routing_hint="IBKR",
                model_run_id=run.run_id,
                preconditions=preconditions,
            )
            .on_conflict_do_update(
                constraint="uq_trade_rec",
                set_={
                    "recommended_price": rec_px,
                    "order_type": str(order.order_type or "MARKET").upper(),
                    "time_in_force": str(order.time_in_force or "DAY").upper(),
                    "valid_from_ts": valid_from_ts,
                    "expiry_ts": expiry_ts,
                    "limit_price": order.limit_price,
                    "stop_trigger_price": order.stop_trigger_price,
                    "size_shares": int(qty_int),
                    "portfolio_id": run.portfolio_id,
                    "routing_hint": "IBKR",
                    "model_run_id": run.run_id,
                    "strategy_name": "BROKER_RUN",
                    "preconditions": FactTradeRecommendation.preconditions.op("||")(
                        cast(preconditions, JSONB)
                    ),
                    "update_ts": now_dt,
                },
            )
            .returning(FactTradeRecommendation.recommendation_id)
        )
        rec_id = session.execute(stmt).scalar_one_or_none()
        if rec_id is not None:
            # Record export mapping for monitoring (order intent -> broker queue row).
            session.execute(
                insert(PortfolioOrderExport)
                .values(
                    order_id=order.order_id,
                    run_id=run.run_id,
                    recommendation_id=rec_id,
                    exported_at=now_dt,
                    exported_by=exported_by,
                )
                .on_conflict_do_update(
                    index_elements=[PortfolioOrderExport.order_id],
                    set_={
                        "run_id": run.run_id,
                        "recommendation_id": rec_id,
                        "exported_at": now_dt,
                        "exported_by": exported_by,
                    },
                )
            )
            exported += 1

    return exported


def get_or_create_portfolio(
    session: Session,
    *,
    portfolio_name: str,
    portfolio_kind: str,
    currency_code: str = "USD",
    broker_name: str | None = None,
    broker_account_id: str | None = None,
    is_public: bool | None = None,
    is_visible: bool | None = None,
    portfolio_owner_id: int | None = None,
    description: str | None = None,
) -> uuid.UUID:
    """Ensure a portfolio exists (idempotent on name). Returns portfolio_id."""
    name = (portfolio_name or "").strip()
    if not name:
        raise ValueError("portfolio_name is required")
    kind = str(portfolio_kind).upper()
    is_public_val = is_public
    is_visible_val = is_visible
    owner_id_val = portfolio_owner_id

    if is_visible_val is True and is_public_val is None:
        is_public_val = True

    if is_public_val is True and kind != "MODEL":
        raise ValueError("is_public portfolios must have portfolio_kind=MODEL")
    if is_visible_val is True and is_public_val is False:
        raise ValueError("is_visible requires is_public=true")
    if is_public_val is True:
        owner_id_val = None

    values: dict[str, Any] = {
        "portfolio_name": name,
        "portfolio_kind": kind,
        "currency_code": (currency_code or "USD").upper(),
        "broker_name": (broker_name or None),
        "broker_account_id": (broker_account_id or None),
        "description": description,
    }
    if is_public_val is not None:
        values["is_public"] = bool(is_public_val)
    if is_visible_val is not None:
        values["is_visible"] = bool(is_visible_val)
    if owner_id_val is not None:
        values["portfolio_owner_id"] = int(owner_id_val)

    stmt = (
        insert(Portfolio)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[Portfolio.portfolio_name])
        .returning(Portfolio.portfolio_id)
    )
    pid = session.execute(stmt).scalar_one_or_none()
    if pid is None:
        pid = session.scalar(select(Portfolio.portfolio_id).where(Portfolio.portfolio_name == name))
    if pid is None:
        raise RuntimeError(f"Failed to resolve portfolio_id for {name}")

    # Best-effort: ensure kind/metadata are not blank.
    updates: dict[str, Any] = {}
    if portfolio_kind:
        updates["portfolio_kind"] = kind
    if broker_name is not None:
        updates["broker_name"] = broker_name
    if broker_account_id is not None:
        updates["broker_account_id"] = broker_account_id
    if description is not None:
        updates["description"] = description
    if currency_code:
        updates["currency_code"] = currency_code.upper()
    if is_public_val is not None:
        updates["is_public"] = bool(is_public_val)
        if bool(is_public_val):
            updates["portfolio_owner_id"] = None
    if is_visible_val is not None:
        updates["is_visible"] = bool(is_visible_val)
    if owner_id_val is not None and not bool(is_public_val):
        updates["portfolio_owner_id"] = int(owner_id_val)

    if updates:
        current = session.get(Portfolio, pid)
        if current is None:
            raise RuntimeError(f"Failed to load portfolio for {name}")
        next_public = bool(current.is_public)
        next_visible = bool(current.is_visible)
        next_kind = str(getattr(current, "portfolio_kind", "")).upper()

        if "portfolio_kind" in updates:
            next_kind = str(updates["portfolio_kind"]).upper()
        if "is_public" in updates:
            next_public = bool(updates["is_public"])
        if "is_visible" in updates:
            next_visible = bool(updates["is_visible"])

        if next_visible and not next_public:
            raise ValueError("is_visible requires is_public=true")
        if next_public and next_kind != "MODEL":
            raise ValueError("is_public portfolios must have portfolio_kind=MODEL")
        if next_public:
            updates["portfolio_owner_id"] = None

    if updates:
        session.execute(update(Portfolio).where(Portfolio.portfolio_id == pid).values(**updates))
    # Library code must not commit; callers own transaction boundaries.
    session.flush()
    return uuid.UUID(str(pid))


def get_or_create_deployment(
    session: Session,
    *,
    broker_portfolio_id: uuid.UUID,
    model_portfolio_id: uuid.UUID,
    allocation_pct: float,
    effective_from: date | None = None,
    created_by: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create or update an active broker<->model deployment.

    Returns (deployment_id, sleeve_portfolio_id).
    """
    if allocation_pct < 0:
        raise ValueError("allocation_pct must be >= 0")
    if allocation_pct > 9999.99:
        raise ValueError("allocation_pct must be <= 9999.99")

    broker = session.get(Portfolio, broker_portfolio_id)
    model = session.get(Portfolio, model_portfolio_id)
    if broker is None:
        raise ValueError("broker_portfolio_id not found")
    if model is None:
        raise ValueError("model_portfolio_id not found")

    eff = effective_from or date.today()

    # Prefer updating an existing active deployment (stable sleeve book per broker+model).
    existing = session.scalar(
        select(PortfolioDeployment)
        .where(PortfolioDeployment.broker_portfolio_id == broker_portfolio_id)
        .where(PortfolioDeployment.model_portfolio_id == model_portfolio_id)
        .where(PortfolioDeployment.effective_to.is_(None))
        .where(PortfolioDeployment.is_active.is_(True))
        .order_by(PortfolioDeployment.effective_from.desc())
        .limit(1)
    )
    if existing is not None:
        session.execute(
            update(PortfolioDeployment)
            .where(PortfolioDeployment.deployment_id == existing.deployment_id)
            .values(
                allocation_pct=float(allocation_pct),
                effective_from=eff,
                created_by=created_by,
                is_active=True,
            )
        )
        # Library code must not commit; callers own transaction boundaries.
        session.flush()
        return uuid.UUID(str(existing.deployment_id)), uuid.UUID(str(existing.sleeve_portfolio_id))

    sleeve_name = _slug_sleeve_name(str(broker.portfolio_name), str(model.portfolio_name))
    sleeve_id = get_or_create_portfolio(
        session,
        portfolio_name=sleeve_name,
        portfolio_kind="SLEEVE",
        currency_code=str(broker.currency_code or "USD"),
        description=f"Sleeve for {model.portfolio_name} deployed into {broker.portfolio_name}",
    )

    stmt = (
        insert(PortfolioDeployment)
        .values(
            broker_portfolio_id=broker_portfolio_id,
            model_portfolio_id=model_portfolio_id,
            sleeve_portfolio_id=sleeve_id,
            allocation_pct=float(allocation_pct),
            effective_from=eff,
            is_active=True,
            created_by=created_by,
        )
        .returning(PortfolioDeployment.deployment_id)
    )
    dep_id = session.execute(stmt).scalar_one()
    # Library code must not commit; callers own transaction boundaries.
    session.flush()
    return uuid.UUID(str(dep_id)), sleeve_id


def create_portfolio_run(
    session: Session,
    *,
    portfolio_id: uuid.UUID,
    run_kind: str,
    as_of_date: date,
    policy_id: int | None = None,
    created_by: str | None = None,
) -> PortfolioRun:
    """Create a new draft run for a portfolio/day (auto-increments run_seq)."""
    max_seq = session.scalar(
        select(func.max(PortfolioRun.run_seq))
        .where(PortfolioRun.portfolio_id == portfolio_id)
        .where(PortfolioRun.run_kind == str(run_kind).upper())
        .where(PortfolioRun.as_of_date == as_of_date)
    )
    next_seq = int(max_seq or 0) + 1
    run = PortfolioRun(
        portfolio_id=portfolio_id,
        run_kind=str(run_kind).upper(),
        as_of_date=as_of_date,
        run_seq=next_seq,
        status="DRAFT",
        policy_id=policy_id,
        created_by=created_by,
    )
    session.add(run)
    session.flush()
    return run


def upsert_order_intents(
    session: Session,
    *,
    run_id: uuid.UUID,
    orders: Sequence[dict[str, Any]],
) -> list[uuid.UUID]:
    """Upsert order intents by (run_id, line_no).

    Any update resets approval to PENDING (requires re-approval).
    Returns the list of order_ids (best-effort; order preserved by input).
    """
    out: list[uuid.UUID] = []
    now_dt = datetime.now(UTC)
    for raw in orders:
        line_no = int(raw["line_no"])
        symbol = (raw.get("symbol") or "").strip().upper() or None
        stock_key = raw.get("stock_key")
        if stock_key is None:
            if not symbol:
                raise ValueError("order requires stock_key or symbol")
            stock_key = session.scalar(select(DimStock.stock_key).where(DimStock.symbol == symbol))
        if stock_key is None:
            raise ValueError(f"Unknown symbol for order: {symbol}")

        action = str(raw["action"]).upper()
        if action not in trade_action_enum.enums:
            raise ValueError(f"Invalid action: {action}")

        stmt = (
            insert(PortfolioOrderIntent)
            .values(
                run_id=run_id,
                line_no=line_no,
                stock_key=int(stock_key),
                action=action,
                order_type=str(raw.get("order_type") or "MARKET").upper(),
                time_in_force=str(raw.get("time_in_force") or "DAY").upper(),
                limit_price=raw.get("limit_price"),
                stop_trigger_price=raw.get("stop_trigger_price"),
                qty_shares=raw["qty_shares"],
                target_weight_after=raw.get("target_weight_after"),
                approval_status="PENDING",
                approved_at=None,
                approved_by=None,
                notes=raw.get("notes"),
                updated_at=now_dt,
            )
            .on_conflict_do_update(
                constraint="uq_order_line",
                set_={
                    "stock_key": int(stock_key),
                    "action": action,
                    "order_type": str(raw.get("order_type") or "MARKET").upper(),
                    "time_in_force": str(raw.get("time_in_force") or "DAY").upper(),
                    "limit_price": raw.get("limit_price"),
                    "stop_trigger_price": raw.get("stop_trigger_price"),
                    "qty_shares": raw["qty_shares"],
                    "target_weight_after": raw.get("target_weight_after"),
                    "approval_status": "PENDING",
                    "approved_at": None,
                    "approved_by": None,
                    "notes": raw.get("notes"),
                    "updated_at": now_dt,
                },
            )
            .returning(PortfolioOrderIntent.order_id)
        )
        oid = session.execute(stmt).scalar_one()
        out.append(uuid.UUID(str(oid)))
    # Library code must not commit; callers own transaction boundaries.
    session.flush()
    return out


def set_order_approval(
    session: Session,
    *,
    order_id: uuid.UUID,
    status: str,
    approved_by: str | None = None,
) -> None:
    """Set per-line approval status."""
    s = str(status).upper()
    if s not in {"APPROVED", "REJECTED"}:
        raise ValueError("status must be APPROVED or REJECTED")
    now_dt = datetime.now(UTC)
    session.execute(
        update(PortfolioOrderIntent)
        .where(PortfolioOrderIntent.order_id == order_id)
        .values(
            approval_status=s,
            approved_at=now_dt,
            approved_by=approved_by,
            updated_at=now_dt,
        )
    )
    # Library code must not commit; callers own transaction boundaries.
    session.flush()


def approve_run(
    session: Session,
    *,
    run_id: uuid.UUID,
    approved_by: str | None = None,
) -> None:
    """Approve a run, enforcing that all order intents are approved."""
    run = session.get(PortfolioRun, run_id)
    if run is None:
        raise ValueError("run_id not found")
    if str(run.status).upper() == "APPROVED":
        return

    execution_date: date | None = None
    if str(run.run_kind).upper() == "BROKER_REBALANCE":
        execution_date = _require_broker_run_execution_day(session, run=run)
        report = evaluate_run_risk(session, run_id=run_id, evaluated_by=approved_by)
        if str(report.status).upper() == "FAIL":
            raise ValueError("Cannot approve broker run: risk status FAIL")
        _require_fresh_risk_report(session, run=run)

    total = session.scalar(
        select(func.count())
        .select_from(PortfolioOrderIntent)
        .where(PortfolioOrderIntent.run_id == run_id)
    )
    pending = session.scalar(
        select(func.count())
        .select_from(PortfolioOrderIntent)
        .where(PortfolioOrderIntent.run_id == run_id)
        .where(PortfolioOrderIntent.approval_status != "APPROVED")
    )
    # A broker rebalance can legitimately generate zero orders (already aligned). Allow approval
    # so the run can be marked APPROVED/SUPERSEDED and audited.
    if not total or int(total) == 0:
        pending = 0
    if pending and int(pending) > 0:
        raise ValueError(f"Run has {int(pending)} unapproved order(s)")

    # Supersede any previously-approved run for the same portfolio/kind/day.
    session.execute(
        update(PortfolioRun)
        .where(PortfolioRun.portfolio_id == run.portfolio_id)
        .where(PortfolioRun.run_kind == run.run_kind)
        .where(PortfolioRun.as_of_date == run.as_of_date)
        .where(PortfolioRun.status == "APPROVED")
        .where(PortfolioRun.run_id != run_id)
        .values(status="SUPERSEDED", updated_at=datetime.now(UTC))
    )

    session.execute(
        update(PortfolioRun)
        .where(PortfolioRun.run_id == run_id)
        .values(
            status="APPROVED",
            approved_at=datetime.now(UTC),
            approved_by=approved_by,
            updated_at=datetime.now(UTC),
        )
    )

    # If this is a broker rebalance run, export approved order intents into executable trade recs.
    if execution_date is not None:
        _export_broker_run_to_trade_recommendations(
            session, run=run, execution_date=execution_date, exported_by=approved_by
        )
    # Library code must not commit; callers own transaction boundaries.
    session.flush()
