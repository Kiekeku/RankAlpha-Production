"""Daily SOFR futures + FRA–OIS job (runs inside ingestion).

Steps:
  1) Read BROKER_SERVICE_URL from Settings; skip if unset.
  2) Fetch SOFR futures from Broker endpoint for SR1 (monthly) and/or SR3.
  3) Upsert rows into rankalpha.fact_sofr_futures for as_of date.
  4) Build a SOFR-based OIS curve (prefer SR1 monthly; fallback SR3 quarterly).
  5) For a set of FRA windows, derive market FRA from futures and compute
     OIS-implied forward; persist into rankalpha.fact_fra_ois.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional, Sequence, Tuple

# Reuse pricer utilities to avoid duplication
from apps.ingestion.src.fra_ois_pricer import (
    add_months,
    build_ois_curve_from_sofr_futures,
    fetch_broker_sofr_list,
    fetch_fra_from_broker,
    fra_forward_rate,
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

DEFAULT_FRA_WINDOWS: tuple[tuple[int, int], ...] = ((3, 6), (6, 9), (9, 12))


def run_sofr_rates_job(
    settings: Settings,
    logger,
    *,
    as_of: Optional[date] = None,
    fra_windows: Sequence[Tuple[int, int]] = DEFAULT_FRA_WINDOWS,
) -> None:
    as_of = as_of or date.today()
    # Feature toggle
    enabled = bool(getattr(settings, "ingestion_rates_enabled", True))
    if not enabled:
        logger.info("SOFR rates job disabled via INGESTION_RATES_ENABLED; skipping")
        return
    base = getattr(settings, "broker_service_url", None)
    if not base:
        logger.info("SOFR rates job skipped: BROKER_SERVICE_URL not configured")
        return
    token = getattr(settings, "broker_service_token", None)

    # 1) Fetch futures from Broker (SR1 preferred)
    sr1_items: List[dict] = []
    sr3_items: List[dict] = []
    try:
        sr1_items = fetch_broker_sofr_list(base, root="SR1", limit=36, token=token)
    except Exception as e:
        logger.warning("SOFR SR1 fetch failed: %s", e)
    try:
        sr3_items = fetch_broker_sofr_list(base, root="SR3", limit=20, token=token)
    except Exception as e:
        logger.warning("SOFR SR3 fetch failed: %s", e)

    if not sr1_items and not sr3_items:
        logger.warning("SOFR rates job: no items for SR1 or SR3; skipping")
        return

    # 2) Persist futures rows
    try:
        rows: list[SofrFutureRow] = []
        for root, items in ("SR1", sr1_items), ("SR3", sr3_items):
            for it in items:
                if not it.get("year") or not it.get("month") or not it.get("local_symbol"):
                    continue
                rows.append(
                    SofrFutureRow(
                        as_of_date=as_of,
                        root=root,
                        year=int(it.get("year")),
                        month=int(it.get("month")),
                        local_symbol=str(it.get("local_symbol")),
                        conid=(int(it.get("conid")) if it.get("conid") is not None else None),
                        last_px=(float(it.get("last")) if it.get("last") is not None else None),
                        settle_px=(
                            float(it.get("settle")) if it.get("settle") is not None else None
                        ),
                    )
                )
        if rows:
            cnt = upsert_sofr_futures(settings, rows)
            logger.info("SOFR rates job: persisted %d futures rows for %s", cnt, as_of)
    except Exception as e:
        logger.warning("SOFR futures upsert failed: %s", e)

    # 3) Build an OIS curve from futures
    curve = None
    try:
        if sr1_items:
            curve = build_ois_curve_from_sofr_futures(as_of, sr1_items, root="SR1")
        elif sr3_items:
            curve = build_ois_curve_from_sofr_futures(as_of, sr3_items, root="SR3")
    except Exception as e:
        logger.warning("SOFR curve build failed: %s", e)

    if curve is None:
        logger.warning("SOFR rates job: no curve built; skipping FRA derivation")
        return

    # 4) Derive FRA from Broker futures and store FRA–OIS
    for start_m, end_m in fra_windows:
        try:
            # OIS-implied forward
            t1 = yearfrac_act_360(as_of, add_months(as_of, start_m))
            t2 = yearfrac_act_360(as_of, add_months(as_of, end_m))
            F_ois = fra_forward_rate(curve, t1, t2)
            # Market FRA from futures
            root = "SR3" if (end_m - start_m) == 3 else "SR1"
            fra = fetch_fra_from_broker(base, as_of, start_m, end_m, root=root, token=token)
            if fra is None:
                logger.info(
                    "SOFR rates job: FRA(%sx%s) not available from %s", start_m, end_m, root
                )
                continue
            spread_bp = (fra - F_ois) * 1e4 if fra is not None and F_ois is not None else None

            # Compute z-score (5d MA → z over 750d window, require 500 pts, clip [-3,5])
            fra_ois_z = None
            try:
                history = fetch_fra_ois_history(settings, start_m, end_m, root, limit=800)
                if history:
                    logger.info(
                        "SOFR FRA–OIS history: %sx%s %s rows=%d range=%s..%s",
                        start_m,
                        end_m,
                        root,
                        len(history),
                        history[0][0],
                        history[-1][0],
                    )
                fra_ois_z = compute_fra_ois_z(
                    history,
                    new_point=(as_of, spread_bp),
                    ma_window=5,
                    z_window=750,
                    min_count=500,
                    clip_low=-3.0,
                    clip_high=5.0,
                )
            except Exception as e:
                logger.warning(
                    "SOFR rates job: FRA z-score compute failed for %sx%s %s: %s",
                    start_m,
                    end_m,
                    root,
                    e,
                )

            upsert_fra_ois(
                settings,
                as_of,
                start_months=start_m,
                end_months=end_m,
                fra_source=root,
                fra_rate=(float(fra) if fra is not None else None),
                ois_forward=(float(F_ois) if F_ois is not None else None),
                spread_bp=(float(spread_bp) if spread_bp is not None else None),
                fra_ois_z=fra_ois_z,
            )
            logger.info(
                "SOFR FRA–OIS upserted: %sx%s %s fra=%.6f ois=%.6f spread=%.2f bp z=%s",
                start_m,
                end_m,
                root,
                float(fra) if fra is not None else float("nan"),
                float(F_ois) if F_ois is not None else float("nan"),
                float(spread_bp) if spread_bp is not None else float("nan"),
                f"{fra_ois_z:.4f}" if fra_ois_z is not None else "null",
            )
        except Exception as e:
            logger.warning("SOFR FRA–OIS upsert failed for %sx%s: %s", start_m, end_m, e)
