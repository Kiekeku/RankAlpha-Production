#!/usr/bin/env python3
"""
One-off FRA/OIS backfill using IBKR SOFR futures history served by the Broker.

Usage (example):
  cd apps/ingestion
  uv run python src/fra_ois_backfill.py --start-date 2023-01-01 --end-date 2025-12-01 \
    --fra-window 3x6 --fra-window 6x9 --fra-window 9x12 --include-sofr-futures

The script is idempotent: upserts into fact_sofr_futures (optional) and
fact_fra_ois keyed by (date_key, start_months, end_months, fra_source).
Re-running will update rows for the same dates/windows.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests

from apps.common.src.logging import get_logger
from apps.ingestion.src.fra_ois_pricer import (
    _choose_sr3_contract,
    _rate_from_price,
    add_months,
    build_ois_curve_from_sofr_futures,
    fra_forward_rate,
    parse_fra_tenor,
    yearfrac_act_360,
)
from apps.ingestion.src.rates_store import (
    SofrFutureRow,
    compute_fra_ois_z,
    fetch_fra_ois_history,
    upsert_fra_ois,
    upsert_sofr_futures,
)
from apps.ingestion.src.settings import Settings

logger = get_logger(__name__)


def _parse_date(val: Optional[str], default: Optional[date] = None) -> date:
    if not val:
        if default is None:
            raise ValueError("Date is required")
        return default
    return datetime.strptime(val, "%Y-%m-%d").date()


def _fetch_sofr_history_from_broker(
    base: str,
    root: str,
    years: int,
    limit: int,
    *,
    token: Optional[str] = None,
) -> Dict:
    url = base.rstrip("/") + "/rates/sofr-futures/history"
    headers = {"X-RA-Service-Token": token.strip()} if token and token.strip() else None
    resp = requests.get(
        url,
        params={"root": root, "years": years, "limit": limit},
        timeout=180,
        headers=headers,
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    return payload


def _build_history_maps(
    payload: Dict,
) -> Tuple[Dict[Tuple[str, int, int], Dict[date, float]], Dict[Tuple[str, int, int], Dict]]:
    """Return mapping (root, year, month) -> {date -> settle} and meta."""
    prices: Dict[Tuple[str, int, int], Dict[date, float]] = {}
    meta: Dict[Tuple[str, int, int], Dict] = {}
    items = payload.get("items") or []
    for it in items:
        root = str(it.get("root") or payload.get("root") or "").upper()
        year = it.get("year")
        month = it.get("month")
        if not root or not year or not month:
            continue
        meta[(root, int(year), int(month))] = {
            "local_symbol": it.get("local_symbol"),
            "conid": it.get("conid"),
            "expiry": it.get("expiry"),
        }
        bars = it.get("bars") or []
        daily: Dict[date, float] = {}
        for b in bars:
            try:
                d = _parse_date(str(b.get("as_of_date")))
            except Exception:
                continue
            close = b.get("close")
            if close is None:
                continue
            try:
                daily[d] = float(close)
            except Exception:
                continue
        if daily:
            prices[(root, int(year), int(month))] = daily
    return prices, meta


def _collect_available_dates(history: Dict[Tuple[str, int, int], Dict[date, float]]) -> List[date]:
    dates: set[date] = set()
    for daily in history.values():
        dates.update(daily.keys())
    return sorted(dates)


def _make_items_for_date(
    root: str,
    as_of: date,
    history: Dict[Tuple[str, int, int], Dict[date, float]],
    meta: Dict[Tuple[str, int, int], Dict],
) -> List[Dict]:
    """Build a futures chain (list of dicts) for a specific date using settle=close."""
    items: List[Dict] = []
    for (r, year, month), daily in history.items():
        if r != root:
            continue
        px = daily.get(as_of)
        if px is None:
            continue
        m = meta.get((r, year, month), {})
        items.append(
            {
                "root": root,
                "year": year,
                "month": month,
                "local_symbol": m.get("local_symbol"),
                "conid": m.get("conid"),
                "expiry": m.get("expiry"),
                "last": None,
                "settle": float(px),
            }
        )
    items.sort(key=lambda x: (x["year"], x["month"]))
    return items


def _fra_from_history_sr3(
    as_of: date, start_m: int, end_m: int, items: List[Dict]
) -> Optional[float]:
    if end_m - start_m != 3:
        return None
    start_date = add_months(as_of, start_m)
    pick = _choose_sr3_contract(items, start_date)
    if not pick:
        return None
    return _rate_from_price(pick.get("settle")) or _rate_from_price(pick.get("last"))


def _fra_from_history_sr1(
    as_of: date, start_m: int, end_m: int, items: List[Dict]
) -> Optional[float]:
    months = end_m - start_m
    if months <= 0:
        return None
    # Map (y,m) -> rate
    rate_by_ym: Dict[Tuple[int, int], float] = {}
    for it in items:
        y = it.get("year")
        m = it.get("month")
        if y is None or m is None:
            continue
        r = _rate_from_price(it.get("settle")) or _rate_from_price(it.get("last"))
        if r is not None:
            rate_by_ym[(int(y), int(m))] = r

    start_date = add_months(as_of, start_m)
    cur = date(start_date.year, start_date.month, 1)
    rates: List[float] = []
    for _ in range(months):
        key = (cur.year, cur.month)
        if key in rate_by_ym:
            rates.append(rate_by_ym[key])
        cur = add_months(cur, 1)
    if not rates:
        return None
    return float(sum(rates) / len(rates))


def _safe_float(val: object) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill FRA/OIS using IBKR SOFR futures history via Broker."
    )
    parser.add_argument(
        "--start-date", type=str, default=None, help="YYYY-MM-DD; default = today - 2y"
    )
    parser.add_argument("--end-date", type=str, default=None, help="YYYY-MM-DD; default = today")
    parser.add_argument(
        "--fra-window", action="append", default=None, help="FRA tenor like 3x6. Repeatable."
    )
    parser.add_argument(
        "--broker-url", type=str, default=None, help="Broker base URL; default BROKER_SERVICE_URL"
    )
    parser.add_argument(
        "--years", type=int, default=2, help="Lookback in years for broker history (clamped 1..2)"
    )
    parser.add_argument(
        "--limit", type=int, default=16, help="Front contracts to pull from broker (per root)"
    )
    parser.add_argument(
        "--include-sofr-futures",
        action="store_true",
        default=False,
        help="Also backfill fact_sofr_futures",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False, help="Log only; no DB writes"
    )
    args = parser.parse_args()

    settings = Settings()
    broker_base = args.broker_url or settings.broker_service_url
    if not broker_base:
        raise SystemExit("BROKER_SERVICE_URL not configured; cannot backfill.")
    token = getattr(settings, "broker_service_token", None)

    years = max(1, min(int(args.years or 2), 2))
    today = date.today()
    start_default = today - timedelta(days=365 * years)
    start_date = _parse_date(args.start_date, start_default)
    end_date = _parse_date(args.end_date, today)
    if start_date > end_date:
        raise SystemExit("start-date must be <= end-date")

    fra_windows = args.fra_window or ["3x6", "6x9", "9x12"]
    parsed_windows: List[Tuple[int, int]] = [parse_fra_tenor(f) for f in fra_windows]

    logger.info(
        "Backfill FRA/OIS from %s to %s (years=%s, limit=%s, include_sofr_futures=%s, dry_run=%s)",
        start_date,
        end_date,
        years,
        args.limit,
        args.include_sofr_futures,
        args.dry_run,
    )

    # Fetch history for both SR1 and SR3 (best effort)
    history_maps: Dict[str, Dict[Tuple[str, int, int], Dict[date, float]]] = {}
    meta_maps: Dict[str, Dict[Tuple[str, int, int], Dict]] = {}
    for root in ("SR1", "SR3"):
        try:
            payload = _fetch_sofr_history_from_broker(
                broker_base,
                root,
                years,
                args.limit,
                token=token,
            )
            prices, meta = _build_history_maps(payload)
            history_maps[root] = prices
            meta_maps[root] = meta
            logger.info(
                "Fetched history for %s: %d contracts, %d dates",
                root,
                len(history_maps[root]),
                len(_collect_available_dates(history_maps[root])),
            )
        except Exception as exc:
            logger.warning("Failed to fetch history for %s: %s", root, exc)
            history_maps[root] = {}
            meta_maps[root] = {}

    if not any(history_maps.values()):
        raise SystemExit("No SOFR history returned; aborting.")

    # Available dates (union) within requested window
    all_dates: set[date] = set()
    for hm in history_maps.values():
        all_dates.update([d for d in _collect_available_dates(hm) if start_date <= d <= end_date])
    backfill_dates = sorted(all_dates)
    if not backfill_dates:
        raise SystemExit("No dates available in requested range.")

    # z-score history caches per FRA key
    fra_history_cache: Dict[Tuple[int, int, str], List[Tuple[date, Optional[float]]]] = {}

    for as_of in backfill_dates:
        sr1_items = _make_items_for_date(
            "SR1", as_of, history_maps.get("SR1", {}), meta_maps.get("SR1", {})
        )
        sr3_items = _make_items_for_date(
            "SR3", as_of, history_maps.get("SR3", {}), meta_maps.get("SR3", {})
        )

        # Optional: persist fact_sofr_futures for this date
        if args.include_sofr_futures and not args.dry_run:
            rows: List[SofrFutureRow] = []
            for root, items in (("SR1", sr1_items), ("SR3", sr3_items)):
                for it in items:
                    if not it.get("local_symbol"):
                        continue
                    last_px = _safe_float(it.get("last"))
                    settle_px = _safe_float(it.get("settle"))
                    rows.append(
                        SofrFutureRow(
                            as_of_date=as_of,
                            root=root,
                            year=int(it["year"]),
                            month=int(it["month"]),
                            local_symbol=str(it.get("local_symbol") or ""),
                            conid=(int(it.get("conid")) if it.get("conid") is not None else None),
                            last_px=last_px,
                            settle_px=settle_px,
                        )
                    )
            if rows:
                upsert_sofr_futures(settings, rows)

        # Build OIS curve (prefer SR1 if available)
        curve = None
        curve_root = None
        try:
            if sr1_items:
                curve = build_ois_curve_from_sofr_futures(as_of, sr1_items, root="SR1")
                curve_root = "SR1"
            elif sr3_items:
                curve = build_ois_curve_from_sofr_futures(as_of, sr3_items, root="SR3")
                curve_root = "SR3"
        except Exception as exc:
            logger.warning("Curve build failed for %s: %s", as_of, exc)
            curve = None

        if curve is None:
            logger.info("No curve for %s; skipping FRA/OIS", as_of)
            continue

        for start_m, end_m in parsed_windows:
            fra_root = "SR3" if (end_m - start_m) == 3 else "SR1"
            items_for_root = sr3_items if fra_root == "SR3" else sr1_items
            if not items_for_root:
                continue

            fra_rate = (
                _fra_from_history_sr3(as_of, start_m, end_m, items_for_root)
                if fra_root == "SR3"
                else _fra_from_history_sr1(as_of, start_m, end_m, items_for_root)
            )
            t1 = yearfrac_act_360(as_of, add_months(as_of, start_m))
            t2 = yearfrac_act_360(as_of, add_months(as_of, end_m))
            ois_forward = fra_forward_rate(curve, t1, t2) if curve is not None else None

            if fra_rate is None or ois_forward is None:
                continue
            spread_bp = (fra_rate - ois_forward) * 1e4

            # z-score (optional)
            key = (start_m, end_m, fra_root)
            if key not in fra_history_cache:
                fra_history_cache[key] = fetch_fra_ois_history(
                    settings, start_m, end_m, fra_root, limit=800
                )
            history_list = fra_history_cache[key]
            fra_ois_z = compute_fra_ois_z(history_list, new_point=(as_of, spread_bp))
            history_list.append((as_of, spread_bp))

            if args.dry_run:
                logger.info(
                    "[dry-run] %s FRA %sx%s %s fra=%.6f ois=%.6f spread=%.2f bp z=%s curve=%s",
                    as_of,
                    start_m,
                    end_m,
                    fra_root,
                    fra_rate,
                    ois_forward,
                    spread_bp,
                    f"{fra_ois_z:.4f}" if fra_ois_z is not None else "null",
                    curve_root,
                )
                continue

            upsert_fra_ois(
                settings,
                as_of,
                start_months=start_m,
                end_months=end_m,
                fra_source=fra_root,
                fra_rate=float(fra_rate),
                ois_forward=float(ois_forward),
                spread_bp=float(spread_bp),
                fra_ois_z=fra_ois_z,
            )
            logger.info(
                "Upserted FRA/OIS %s %sx%s %s fra=%.6f ois=%.6f spread=%.2f bp z=%s curve=%s",
                as_of,
                start_m,
                end_m,
                fra_root,
                fra_rate,
                ois_forward,
                spread_bp,
                f"{fra_ois_z:.4f}" if fra_ois_z is not None else "null",
                curve_root,
            )


if __name__ == "__main__":
    main()
