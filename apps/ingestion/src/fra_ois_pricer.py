#!/usr/bin/env python3

"""
fra_ois_pricer.py
-----------------

A pragmatic Python 3.12+ script that:
  1) Pulls SOFR and historical USD 3M LIBOR from FRED (API key optional; CSV fallback).
  2) Builds a minimal OIS discount curve from user-supplied par OIS quotes (annual fixed leg).
  3) Computes FRA forward rate for an arbitrary "XxY" period and its PV vs a strike.
  4) Computes OIS par rate and PV for a chosen tenor and fixed rate.

This is intentionally lightweight (no QuantLib). It’s good for research,
sanity checks, and demos. For production, you’ll want vendor curves, robust
convention handling, and day-count/business-day calendars aligned to your CSA.

Usage examples
--------------
# Demo with placeholder OIS quotes (annual fixed leg). Quotes are decimals.
python fra_ois_pricer.py --fra 3x6 --ois "1Y=0.0475,2Y=0.0440,3Y=0.0425,5Y=0.0410"

# Same, with a specific FRA strike and notional
python fra_ois_pricer.py --fra 3x6 --strike 0.045 --notional 5000000 --ois "1Y=0.0475,2Y=0.0440,3Y=0.0425,5Y=0.0410"

# Compute an OIS PV for a custom fixed rate
python fra_ois_pricer.py --ois "1Y=0.0475,2Y=0.0440,3Y=0.0425,5Y=0.0410" --ois-price 2Y --fixed 0.0460 --notional 10000000

# Pull SOFR and LIBOR since 2018-01-01 (prints latest values)
python fra_ois_pricer.py --start 2018-01-01

Notes
-----
- Defaults assume USD/ACT-360 and annual fixed leg for OIS. That matches the
  common market convention for SOFR OIS swaps (annual fixed). If your market
  uses different fixed-leg frequencies, adjust --fixed-freq.
- Par OIS quotes you pass in are used to bootstrap discount factors at the
  quoted maturities; zeros are interpolated log-linearly for in-between times.
- FRA PV uses standard start-of-period settlement formula with forward replacing realized.
- FRED series IDs used:
    SOFR          = "SOFR" (Secured Overnight Financing Rate)
    3M USD LIBOR  = "USD3MTD156N" (historical; ceased for new settings)

Dependencies
------------
pip install pandas numpy requests python-dateutil

Environment
-----------
Optionally set FRED_API_KEY for authenticated JSON API; otherwise the script
attempts a CSV fallback download (no key required).

DISCLAIMER: For illustration only. Quotes here are placeholders; use real vendor data
for trading. Conventions matter (day count, calendars, compounding, payment freq).
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

from apps.common.src.logging import get_logger

# Best-effort: load env/<ENV>/*.env so FRED_API_KEY etc. are available in local runs
try:
    from dotenv import load_dotenv  # type: ignore

    ROOT = Path(__file__).resolve().parents[3]
    ENV = os.getenv("RANKALPHA_ENV", "local")
    ENV_DIR = ROOT / "env" / ENV
    for _env_file in ("ingestion.env", "api.env", "sentiment.env", "scorer.env"):
        _p = ENV_DIR / _env_file
        if _p.exists():
            load_dotenv(_p, override=False)
except Exception:
    # Safe to ignore if dotenv is unavailable or path layout differs
    pass

# Shared settings + DB store
from apps.ingestion.src.rates_store import (
    SofrFutureRow,
    upsert_fra_ois,
    upsert_sofr_futures,
)
from apps.ingestion.src.settings import Settings

logger = get_logger(__name__)

# -----------------------------
# Broker SOFR futures helpers
# -----------------------------


def _imm_quarter_month(d: date) -> int:
    """Return the IMM quarter month (3,6,9,12) on/after date d."""
    m = d.month
    if m <= 3:
        return 3
    if m <= 6:
        return 6
    if m <= 9:
        return 9
    return 12


def _choose_sr3_contract(items: List[dict], start: date) -> Optional[dict]:
    """Pick the SR3 contract whose contract month equals the IMM month on/after 'start'."""
    target_m = _imm_quarter_month(start)
    target_y = start.year if target_m >= start.month else start.year + 1
    best: Optional[dict] = None
    for it in items:
        y = int(it.get("year")) if it.get("year") is not None else None
        m = int(it.get("month")) if it.get("month") is not None else None
        if not y or not m:
            continue
        if y == target_y and m == target_m:
            best = it
            break
    # fallback: first item with date >= start
    if best is None:
        for it in items:
            y = int(it.get("year")) if it.get("year") is not None else None
            m = int(it.get("month")) if it.get("month") is not None else None
            if not y or not m:
                continue
            cand = date(y, m, 15)
            if cand >= date(start.year, start.month, 1):
                best = it
                break
    return best


def _rate_from_price(px: Optional[float]) -> Optional[float]:
    if px is None:
        return None
    try:
        return (100.0 - float(px)) / 100.0
    except Exception:
        return None


def fetch_fra_from_broker(
    broker_base: str,
    as_of: date,
    start_m: int,
    end_m: int,
    *,
    root: str = "SR3",
    token: Optional[str] = None,
) -> Optional[float]:
    """Call broker endpoint to get SOFR futures and derive an FRA rate.

    For SR3 (3M SOFR futures), supports FRA windows exactly 3 months long.
    For other windows, returns None.
    """
    url = broker_base.rstrip("/") + "/rates/sofr-futures"
    headers = {"X-RA-Service-Token": token.strip()} if token and token.strip() else None
    try:
        resp = requests.get(
            url,
            params={"root": root.upper(), "limit": 16},
            timeout=120,
            headers=headers,
        )
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Broker request failed: {e}")
    payload = resp.json() or {}
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        return None

    if root.upper() == "SR3":
        # Require a 3-month FRA period
        if end_m - start_m != 3:
            return None
        start_date = add_months(as_of, start_m)
        pick = _choose_sr3_contract(items, start_date)
        if not pick:
            return None
        rate = _rate_from_price(pick.get("last")) or _rate_from_price(pick.get("settle"))
        return rate
    elif root.upper() == "SR1":
        # Simple average of three consecutive 1M contracts spanning [start,end)
        months = end_m - start_m
        if months <= 0:
            return None
        # Build list of year/month for each month in window
        start_date = add_months(as_of, start_m)
        ym_list: List[tuple[int, int]] = []
        cur = date(start_date.year, start_date.month, 1)
        for _ in range(months):
            ym_list.append((cur.year, cur.month))
            cur = add_months(cur, 1)
        # Map futures items to dict by (y,m)
        by_ym: Dict[tuple[int, int], dict] = {}
        for it in items:
            y = it.get("year")
            m = it.get("month")
            if y is None or m is None:
                continue
            by_ym[(int(y), int(m))] = it
        rates: List[float] = []
        for ym in ym_list:
            it = by_ym.get(ym)
            if not it:
                continue
            r = _rate_from_price(it.get("last")) or _rate_from_price(it.get("settle"))
            if r is not None:
                rates.append(r)
        if not rates:
            return None
        # Approximate simple average of monthly compounded rates
        return float(np.mean(rates))
    else:
        return None


def fetch_broker_sofr_list(
    broker_base: str,
    root: str = "SR1",
    *,
    limit: int = 24,
    token: Optional[str] = None,
) -> List[Dict]:
    """Fetch SOFR futures list from the Broker endpoint.

    Returns a list of dicts with keys: year, month, last, settle, local_symbol, conid, expiry.
    """
    url = broker_base.rstrip("/") + "/rates/sofr-futures"
    headers = {"X-RA-Service-Token": token.strip()} if token and token.strip() else None
    resp = requests.get(
        url,
        params={"root": root.upper(), "limit": int(limit)},
        timeout=120,
        headers=headers,
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    items = payload.get("items") or []
    if not isinstance(items, list):
        return []
    return items


def build_ois_curve_from_sofr_futures(
    as_of: date, items: List[Dict], *, root: str = "SR1"
) -> DiscountCurve:
    """Approximate an OIS discount curve from SOFR futures.

    - SR1: chain of monthly contracts; builds monthly pillars.
    - SR3: chain of quarterly contracts; builds quarterly pillars.
    Uses ACT/360 accrual and piecewise-constant forward approximation.
    """
    if not items:
        raise ValueError("No SOFR futures items provided to build OIS curve.")

    # Normalize and sort by (year, month)
    norm: List[Dict] = []
    for it in items:
        try:
            y = int(it.get("year")) if it.get("year") is not None else None
            m = int(it.get("month")) if it.get("month") is not None else None
        except Exception:
            y, m = None, None
        if not y or not m:
            continue
        last = it.get("last")
        settle = it.get("settle")
        r = _rate_from_price(last) or _rate_from_price(settle)
        if r is None:
            continue
        norm.append({"year": y, "month": m, "rate": float(r)})
    norm.sort(key=lambda x: (x["year"], x["month"]))
    if not norm:
        raise ValueError("No usable SOFR futures prices to infer rates.")

    times: List[float] = [0.0]
    dfs: List[float] = [1.0]

    if root.upper() == "SR1":
        # Monthly pillars from end of each futures month
        for it in norm:
            y, m, r = it["year"], it["month"], it["rate"]
            month_start = date(y, m, 1)
            month_end = add_months(month_start, 1)
            start = max(as_of, month_start)
            if start >= month_end:
                continue
            tau = yearfrac_act_360(start, month_end)
            D_prev = dfs[-1]
            D_next = D_prev * float(np.exp(-r * tau))
            t_next = yearfrac_act_360(as_of, month_end)
            times.append(t_next)
            dfs.append(D_next)
    else:  # SR3 quarterly (approximate accrual window [contract_month, contract_month+3))
        for it in norm:
            y, m, r = it["year"], it["month"], it["rate"]
            # CME SR3 settles on compounded SOFR over the three months starting
            # on the IMM date in the contract month. Approximate using full months
            # starting at the contract month boundary and ending three months later.
            q_start = date(y, m, 1)
            q_end = add_months(q_start, 3)
            start = max(as_of, q_start)
            if start >= q_end:
                continue
            tau = yearfrac_act_360(start, q_end)
            D_prev = dfs[-1]
            D_next = D_prev * float(np.exp(-r * tau))
            t_next = yearfrac_act_360(as_of, q_end)
            times.append(t_next)
            dfs.append(D_next)

    return DiscountCurve(times, dfs)


# -----------------------------
# Helpers: dates & day counts
# -----------------------------


def to_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def yearfrac_act_360(d1: date, d2: date) -> float:
    return (d2 - d1).days / 360.0


def add_months(d: date, months: int) -> date:
    return d + relativedelta(months=+months)


def tenor_to_months(tenor: str) -> int:
    """Parse tenor like '3M','6M','1Y','2Y','18M' -> months (int)."""
    t = tenor.strip().upper()
    if t.endswith("M"):
        return int(t[:-1])
    if t.endswith("Y"):
        return int(float(t[:-1]) * 12)
    raise ValueError(f"Unsupported tenor: {tenor}")


def parse_fra_tenor(fra: str) -> Tuple[int, int]:
    """Parse FRA tenor 'XxY' where X,Y in months. Ex: '3x6' -> (3,6)."""
    f = fra.lower().replace(" ", "")
    if "x" not in f:
        raise ValueError("FRA tenor must look like '3x6', '1x4', etc.")
    a, b = f.split("x")
    return int(a), int(b)


# ----------------------------------
# FRED fetch (JSON API + CSV fallback)
# ----------------------------------


def fetch_fred_series(
    series_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    api_key: Optional[str] = None,
) -> pd.Series:
    """
    Return a pandas Series indexed by datetime with float values.
    Tries JSON API (requires API key) then CSV fallback (no key).
    """
    if api_key is None:
        api_key = os.getenv("FRED_API_KEY", None)

    if api_key:
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {"series_id": series_id, "api_key": api_key, "file_type": "json"}
        if start:
            params["observation_start"] = start
        if end:
            params["observation_end"] = end
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()["observations"]
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            # Values come as strings; coerce to float, '.' -> NaN
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            s = df.set_index("date")["value"].dropna()
            s.index = s.index.tz_localize(None)
            return s
        except Exception as e:
            logger.warning("FRED JSON API failed (%s); trying CSV fallback...", e)

    # CSV fallback
    csv_url = f"https://fred.stlouisfed.org/series/{series_id}/downloaddata/{series_id}.csv"
    try:
        df = pd.read_csv(csv_url)
        df["DATE"] = pd.to_datetime(df["DATE"])
        df["VALUE"] = pd.to_numeric(df["VALUE"], errors="coerce")
        s = df.set_index("DATE")["VALUE"].dropna()
        s.index = s.index.tz_localize(None)
        if start:
            s = s[s.index >= pd.to_datetime(start)]
        if end:
            s = s[s.index <= pd.to_datetime(end)]
        return s
    except Exception as e:
        raise RuntimeError(f"Unable to fetch FRED series {series_id}: {e}")


# ----------------------------------
# Discount curve (log-linear zeros)
# ----------------------------------


@dataclass
class DiscountCurve:
    pillars_years: List[float]  # times in years
    dfs: List[float]  # discount factors at pillars

    def __post_init__(self):
        # ensure sorted ascending and unique by time
        pairs = sorted(zip(self.pillars_years, self.dfs), key=lambda x: x[0])
        # deduplicate by time (keep last)
        dedup = {}
        for t, d in pairs:
            dedup[t] = d
        self.pillars_years = list(dedup.keys())
        self.dfs = [dedup[t] for t in self.pillars_years]

    def df(self, t: float) -> float:
        """Discount factor at time t (years) via log-linear zero interpolation."""
        if t < 0:
            raise ValueError("t must be >= 0")
        if t == 0:
            return 1.0
        times = np.array(self.pillars_years, dtype=float)
        dfs = np.array(self.dfs, dtype=float)

        # If the curve only has D(0), we cannot evaluate for t>0 without at least
        # one positive-time pillar. Guard to avoid divide-by-zero during extrapolation.
        if len(times) == 1 and times[0] == 0.0:
            raise ValueError(
                "DiscountCurve has only t=0 pillar (D(0)=1). Add a positive-time pillar before querying t>0."
            )

        if t <= times[0]:
            # flat zero extrapolation from first pillar
            z0 = -np.log(dfs[0]) / times[0] if times[0] > 0 else 0.0
            return float(np.exp(-z0 * t))

        if t >= times[-1]:
            # flat zero extrapolation from last pillar
            zT = -np.log(dfs[-1]) / times[-1]
            return float(np.exp(-zT * t))

        # find bracketing indices
        idx = np.searchsorted(times, t) - 1
        t1, t2 = times[idx], times[idx + 1]
        d1, d2 = dfs[idx], dfs[idx + 1]
        # Guard against division by zero when the left bracket is t1 == 0
        if t1 == 0.0:
            # Use the first positive pillar's zero rate for the whole [0, t2] segment
            z1 = -np.log(d2) / t2
        else:
            z1 = -np.log(d1) / t1
        z2 = -np.log(d2) / t2
        w = (t - t1) / (t2 - t1)
        zt = z1 * (1 - w) + z2 * w
        return float(np.exp(-zt * t))

    def zero_rate(self, t: float) -> float:
        """Continuously-compounded zero rate at time t (years)."""
        if t <= 0:
            return 0.0
        d = self.df(t)
        return -np.log(d) / t

    def add_pillar(self, t: float, df: float) -> None:
        self.pillars_years.append(float(t))
        self.dfs.append(float(df))
        self.__post_init__()


# ----------------------------------
# OIS bootstrap (annual fixed leg)
# ----------------------------------


def build_ois_curve_from_par(
    as_of: date, par_quotes: Dict[str, float], fixed_leg_freq_months: int = 12
) -> DiscountCurve:
    """
    Bootstrap discount factors at each quoted OIS maturity using par OIS rates.
    Assumes annual fixed leg (or as provided) with ACT/360 accrual between actual dates.
    Floating leg assumption implies PV_float = 1 - D(T) when the first reset is in arrears from 'as_of'.
    """
    # Sort quotes by maturity (months)
    items = sorted(((tenor_to_months(k), v) for k, v in par_quotes.items()), key=lambda x: x[0])
    if not items:
        raise ValueError("No OIS quotes provided.")
    # Initialize curve with D(0)=1
    curve = DiscountCurve([0.0], [1.0])

    for months, par in items:
        maturity = add_months(as_of, months)
        # generate fixed-leg payment dates from as_of to maturity, stepping by fixed_leg_freq_months
        pay_dates = []
        d = add_months(as_of, fixed_leg_freq_months)
        while d < maturity or d == maturity:
            pay_dates.append(d)
            d = add_months(d, fixed_leg_freq_months)
        if not pay_dates or pay_dates[-1] != maturity:
            # ensure the last payment is at maturity (bullet)
            if pay_dates and pay_dates[-1] < maturity:
                pay_dates.append(maturity)
            elif not pay_dates:
                pay_dates = [maturity]

        # If this is the very first quote and the schedule has earlier pay dates
        # before maturity, we need their discount factors which do not exist yet.
        # Raise a clear error instead of attempting to extrapolate from only D(0).
        if len(curve.pillars_years) == 1 and curve.pillars_years[0] == 0.0 and len(pay_dates) > 1:
            first_intermediate = pay_dates[0]
            raise ValueError(
                (
                    "Cannot bootstrap first OIS pillar at {months}M with fixed-leg frequency {freq}M: "
                    "schedule includes earlier payment date {first_date} requiring prior discount factors. "
                    "Provide an earlier OIS quote (e.g., {freq}M/ {twice}M) or choose a fixed-leg frequency that aligns with the first tenor."
                ).format(
                    months=months,
                    freq=fixed_leg_freq_months,
                    first_date=first_intermediate.isoformat(),
                    twice=fixed_leg_freq_months * 2,
                )
            )

        # Build the sum of alpha_i * D(t_i) for known earlier pillars, then solve for D(T)
        sum_alpha_D = 0.0
        last = as_of
        for pay_date in pay_dates[:-1]:
            alpha = yearfrac_act_360(last, pay_date)
            t = yearfrac_act_360(as_of, pay_date)
            sum_alpha_D += alpha * curve.df(t)
            last = pay_date
        # final accrual to maturity
        alpha_N = yearfrac_act_360(last, maturity)
        T_years = yearfrac_act_360(as_of, maturity)
        # Par swap equation: PV_fixed = PV_float => par * sum(alpha_i D(t_i)) = 1 - D(T)
        # Solve for D(T): D(T) = (1 - par * sum_{i=1..N-1}(alpha_i D(t_i))) / (1 + par * alpha_N)
        numerator = 1.0 - par * sum_alpha_D
        denominator = 1.0 + par * alpha_N
        D_T = numerator / denominator
        curve.add_pillar(T_years, D_T)

    return curve


# ----------------------------------
# FRA calculations
# ----------------------------------


def fra_forward_rate(curve: DiscountCurve, t1: float, t2: float) -> float:
    """
    Forward simple annualized rate for period [t1, t2] using ACT/360 year fractions in 't' units.
    Formula: F = (D(t1)/D(t2) - 1) / (t2 - t1)
    """
    if t2 <= t1:
        raise ValueError("t2 must be > t1")
    D1 = curve.df(t1)
    D2 = curve.df(t2)
    tau = t2 - t1  # since t are already in years ACT/360
    return (D1 / D2 - 1.0) / tau


def fra_pv_at_time0(
    curve: DiscountCurve, notional: float, t1: float, t2: float, strike: float
) -> float:
    """
    PV at time 0 of a FRA (receive floating, pay strike), using forward F as expectation.
    Settlement at t1 with payoff N * (R - K) * tau / (1 + R * tau).
    Replace R with forward F for PV: PV0 ≈ N * D(t1) * (F - K) * tau / (1 + F * tau)
    """
    F = fra_forward_rate(curve, t1, t2)
    tau = t2 - t1
    disc = curve.df(t1)
    return notional * disc * (F - strike) * tau / (1.0 + F * tau)


# ----------------------------------
# OIS swap pricing (receiver fixed)
# ----------------------------------


def ois_par_rate(
    curve: DiscountCurve, as_of: date, tenor_months: int, fixed_leg_freq_months: int = 12
) -> float:
    """Compute par fixed rate S* = (1 - D(T)) / sum(alpha_i * D(t_i))."""
    maturity = add_months(as_of, tenor_months)
    # schedules
    pay_dates = []
    d = add_months(as_of, fixed_leg_freq_months)
    while d < maturity or d == maturity:
        pay_dates.append(d)
        d = add_months(d, fixed_leg_freq_months)
    if not pay_dates or pay_dates[-1] != maturity:
        if pay_dates and pay_dates[-1] < maturity:
            pay_dates.append(maturity)
        elif not pay_dates:
            pay_dates = [maturity]

    last = as_of
    denom = 0.0
    for pay_date in pay_dates:
        alpha = yearfrac_act_360(last, pay_date)
        t = yearfrac_act_360(as_of, pay_date)
        denom += alpha * curve.df(t)
        last = pay_date
    T_years = yearfrac_act_360(as_of, maturity)
    return (1.0 - curve.df(T_years)) / denom


def ois_pv_receiver_fixed(
    curve: DiscountCurve,
    as_of: date,
    tenor_months: int,
    fixed_rate: float,
    notional: float,
    fixed_leg_freq_months: int = 12,
) -> float:
    """PV of receiver-fixed OIS (receive fixed, pay float)."""
    maturity = add_months(as_of, tenor_months)
    # Fixed leg PV
    pay_dates = []
    d = add_months(as_of, fixed_leg_freq_months)
    while d < maturity or d == maturity:
        pay_dates.append(d)
        d = add_months(d, fixed_leg_freq_months)
    if not pay_dates or pay_dates[-1] != maturity:
        if pay_dates and pay_dates[-1] < maturity:
            pay_dates.append(maturity)
        elif not pay_dates:
            pay_dates = [maturity]

    last = as_of
    pv_fixed = 0.0
    for pay_date in pay_dates:
        alpha = yearfrac_act_360(last, pay_date)
        t = yearfrac_act_360(as_of, pay_date)
        pv_fixed += fixed_rate * alpha * curve.df(t)
        last = pay_date

    # Floating leg PV (standard swap assumption): PV_float = 1 - D(T)
    T_years = yearfrac_act_360(as_of, maturity)
    pv_float = 1.0 - curve.df(T_years)

    return notional * (pv_fixed - pv_float)


# ----------------------------------
# CLI & main
# ----------------------------------


def parse_ois_quotes(s: str) -> Dict[str, float]:
    """
    Parse OIS quotes from a string like "1Y=0.0475,2Y=0.044,3Y=0.0425,5Y=0.041".
    """
    out: Dict[str, float] = {}
    if not s:
        return out
    for part in s.split(","):
        if not part.strip():
            continue
        k, v = part.split("=")
        out[k.strip()] = float(v.strip())
    return out


def main():
    parser = argparse.ArgumentParser(description="FRA/OIS quick pricer + FRED fetch")
    parser.add_argument(
        "--start", type=str, default=None, help="FRED observation_start (YYYY-MM-DD)"
    )
    parser.add_argument("--end", type=str, default=None, help="FRED observation_end (YYYY-MM-DD)")
    parser.add_argument(
        "--fra", type=str, default=None, help="FRA tenor like 3x6 (months x months)"
    )
    parser.add_argument(
        "--strike", type=float, default=None, help="FRA strike (decimal). Default = par (forward)"
    )
    parser.add_argument(
        "--fra-quote",
        dest="strike",
        type=float,
        help="Alias for --strike (market FRA quote, decimal)",
    )
    parser.add_argument("--notional", type=float, default=1_000_000, help="Notional for PVs")
    parser.add_argument(
        "--as-of", type=str, default=None, help="Valuation date (YYYY-MM-DD). Default = today"
    )
    parser.add_argument(
        "--ois",
        type=str,
        default="",
        help='Par OIS quotes, e.g. "1Y=0.0475,2Y=0.0440,3Y=0.0425,5Y=0.0410"',
    )
    parser.add_argument(
        "--fixed-freq",
        type=int,
        default=12,
        help="Fixed-leg frequency in months (default annual=12)",
    )
    parser.add_argument(
        "--ois-price", type=str, default=None, help='Price an OIS (e.g., "2Y") with --fixed.'
    )
    parser.add_argument("--fixed", type=float, default=None, help="OIS fixed rate for PV (decimal)")
    # IBKR/Broker options to derive FRA from SOFR futures
    parser.add_argument(
        "--use-ibkr-fra",
        action="store_true",
        default=True,
        help="Derive FRA from IBKR SOFR futures via Broker endpoint (default on)",
    )
    parser.add_argument(
        "--no-ibkr",
        action="store_true",
        help="Disable IBKR integration and only use supplied --ois quotes",
    )
    parser.add_argument(
        "--fra-source",
        type=str,
        default="SR3",
        choices=["SR3", "SR1", "sr3", "sr1"],
        help="SOFR futures root to use for FRA (SR3=3M, SR1=1M)",
    )
    parser.add_argument(
        "--broker-url",
        type=str,
        default=None,
        help="Broker service base URL (default from BROKER_SERVICE_URL)",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        default=True,
        help="Persist IBKR SOFR futures and derived FRA/OIS to DB (default on)",
    )
    parser.add_argument("--no-persist", action="store_true", help="Disable DB persistence")
    args = parser.parse_args()

    as_of = to_date(args.as_of) if args.as_of else date.today()

    # 1) Fetch SOFR and 3M USD LIBOR (historical series) from FRED
    try:
        sofr = fetch_fred_series("SOFR", start=args.start, end=args.end)
        if not sofr.empty:
            logger.info(
                "SOFR: latest %s = %.6f",
                sofr.index[-1].date(),
                sofr.iloc[-1],
            )
        else:
            logger.warning("SOFR: no data returned (check dates)")
    except Exception as e:
        logger.warning("Could not fetch SOFR: %s", e)

    try:
        libor3m = fetch_fred_series("USD3MTD156N", start=args.start, end=args.end)
        if not libor3m.empty:
            logger.info(
                "3M USD LIBOR (historical): last %s = %.6f",
                libor3m.index[-1].date(),
                libor3m.iloc[-1],
            )
        else:
            logger.warning("3M USD LIBOR: no data returned (check dates)")
    except Exception as e:
        logger.warning("Could not fetch 3M USD LIBOR: %s", e)

    # 2) Build OIS discount curve: prefer IBKR SOFR futures if available, else par quotes
    par_quotes = parse_ois_quotes(args.ois)
    curve: Optional[DiscountCurve] = None
    use_ibkr = args.use_ibkr_fra and not args.no_ibkr
    broker_base = args.broker_url or os.getenv("BROKER_SERVICE_URL")
    settings = Settings()
    broker_token = getattr(settings, "broker_service_token", None)

    if use_ibkr and broker_base:
        # Try SR1 monthly first; if unavailable, fall back to SR3 quarterly
        try:
            items = fetch_broker_sofr_list(broker_base, root="SR1", limit=36, token=broker_token)
            if items:
                curve = build_ois_curve_from_sofr_futures(as_of, items, root="SR1")
                logger.info("Built OIS discount curve from IBKR SR1 monthly SOFR futures")
                if args.persist and not args.no_persist:
                    rows = [
                        SofrFutureRow(
                            as_of_date=as_of,
                            root="SR1",
                            year=int(it.get("year")),
                            month=int(it.get("month")),
                            local_symbol=str(it.get("local_symbol")),
                            conid=(int(it.get("conid")) if it.get("conid") is not None else None),
                            last_px=(float(it.get("last")) if it.get("last") is not None else None),
                            settle_px=(
                                float(it.get("settle")) if it.get("settle") is not None else None
                            ),
                        )
                        for it in items
                        if it.get("year") and it.get("month") and it.get("local_symbol")
                    ]
                    try:
                        cnt = upsert_sofr_futures(settings, rows)
                        logger.info("Persisted %s SR1 futures rows to DB for %s", cnt, as_of)
                    except Exception as e:
                        logger.warning("Failed to persist SR1 futures: %s", e)
            else:
                items_q = fetch_broker_sofr_list(
                    broker_base, root="SR3", limit=20, token=broker_token
                )
                if items_q:
                    curve = build_ois_curve_from_sofr_futures(as_of, items_q, root="SR3")
                    logger.info("Built OIS discount curve from IBKR SR3 quarterly SOFR futures")
                    if args.persist and not args.no_persist:
                        rows = [
                            SofrFutureRow(
                                as_of_date=as_of,
                                root="SR3",
                                year=int(it.get("year")),
                                month=int(it.get("month")),
                                local_symbol=str(it.get("local_symbol")),
                                conid=(
                                    int(it.get("conid")) if it.get("conid") is not None else None
                                ),
                                last_px=(
                                    float(it.get("last")) if it.get("last") is not None else None
                                ),
                                settle_px=(
                                    float(it.get("settle"))
                                    if it.get("settle") is not None
                                    else None
                                ),
                            )
                            for it in items_q
                            if it.get("year") and it.get("month") and it.get("local_symbol")
                        ]
                        try:
                            cnt = upsert_sofr_futures(settings, rows)
                            logger.info("Persisted %s SR3 futures rows to DB for %s", cnt, as_of)
                        except Exception as e:
                            logger.warning("Failed to persist SR3 futures: %s", e)
        except Exception as e:
            logger.warning("Could not build OIS curve from IBKR SOFR futures: %s", e)

    if curve is None and par_quotes:
        try:
            curve = build_ois_curve_from_par(
                as_of, par_quotes, fixed_leg_freq_months=args.fixed_freq
            )
            logger.info("Built OIS discount curve from par OIS quotes")
        except ValueError as e:
            raise SystemExit(str(e))

    # Pretty print curve pillars if we have a curve
    if curve is not None:
        logger.info("OIS discount curve pillars (years, DF, zero%%):")
        for t, d in zip(curve.pillars_years, curve.dfs):
            z = curve.zero_rate(t) * 100.0
            logger.info("  t=%6.3fy  DF=%1.8f  zc=%6.3f%%", t, d, z)

    # 3) FRA computation (if requested)
    if args.fra:
        start_m, end_m = parse_fra_tenor(args.fra)
        if curve is None:
            # If no curve yet and IBKR allowed, try to build from SR1/SR3 now based on horizon
            if use_ibkr and broker_base:
                try:
                    horizon_m = end_m
                    # Request enough months/contracts to cover the horizon
                    items = fetch_broker_sofr_list(
                        broker_base,
                        root="SR1",
                        limit=max(12, horizon_m + 3),
                        token=broker_token,
                    )
                    if items:
                        curve = build_ois_curve_from_sofr_futures(as_of, items, root="SR1")
                        logger.info("Built OIS discount curve from IBKR SR1 monthly SOFR futures")
                except Exception as e:
                    logger.warning("Could not build OIS curve from IBKR SOFR futures: %s", e)
            if curve is None:
                raise SystemExit(
                    "FRA requested but no OIS curve available. Provide --ois quotes or configure BROKER_SERVICE_URL for IBKR integration."
                )
        # Align FRA times to the curve's date/ACT-360 basis
        start_date = add_months(as_of, start_m)
        end_date = add_months(as_of, end_m)
        t1 = yearfrac_act_360(as_of, start_date)
        t2 = yearfrac_act_360(as_of, end_date)
        tau = yearfrac_act_360(start_date, end_date)
        F = fra_forward_rate(curve, t1, t2)
        logger.info("FRA %s: OIS-implied forward=%.4f%%  (tau=%.6fy)", args.fra, F * 100, tau)
        K = args.strike if args.strike is not None else F
        pv = fra_pv_at_time0(curve, args.notional, t1, t2, K)
        logger.info(
            "  Strike K=%.4f%%  Notional=%s  PV@0=%.2f",
            K * 100,
            f"{args.notional:,.0f}",
            pv,
        )
        if args.strike is not None:
            spread_bp = (K - F) * 1e4
            logger.info("  FRA–OIS spread (K − F) = %.2f bp", spread_bp)

        # Optionally derive FRA from IBKR SOFR futures via Broker
        if args.use_ibkr_fra:
            broker_base = args.broker_url or os.getenv("BROKER_SERVICE_URL")
            if not broker_base:
                logger.warning(
                    "--use-ibkr-fra set but BROKER_SERVICE_URL/--broker-url not configured; skipping IBKR FRA"
                )
            else:
                try:
                    fra_src = args.fra_source.upper()
                    market_fra = fetch_fra_from_broker(
                        broker_base,
                        as_of,
                        start_m,
                        end_m,
                        root=fra_src,
                        token=broker_token,
                    )
                    if market_fra is not None:
                        logger.info(
                            "  IBKR-derived FRA(%s,%s) = %.4f%%",
                            args.fra,
                            fra_src,
                            market_fra * 100,
                        )
                        spread_bp2 = (market_fra - F) * 1e4
                        logger.info("  FRA(IBKR) – OIS forward = %.2f bp", spread_bp2)
                        if args.persist and not args.no_persist:
                            try:
                                upsert_fra_ois(
                                    settings,
                                    as_of,
                                    start_months=start_m,
                                    end_months=end_m,
                                    fra_source=fra_src,
                                    fra_rate=float(market_fra),
                                    ois_forward=float(F),
                                    spread_bp=float(spread_bp2),
                                    fra_ois_z=None,
                                )
                                logger.info("  Persisted FRA–OIS row to DB")
                            except Exception as e:
                                logger.warning("  Failed to persist FRA–OIS row: %s", e)
                    else:
                        logger.warning(
                            "  Broker returned no usable SOFR futures for FRA derivation"
                        )
                except Exception as e:
                    logger.warning("Failed to derive FRA from IBKR SOFR futures: %s", e)

    # 4) OIS pricing (if requested)
    if args.ois_price:
        if curve is None:
            raise SystemExit(
                "OIS pricing requested but no OIS curve built. Pass --ois quotes to build a curve."
            )
        tenor_m = tenor_to_months(args.ois_price)
        par = ois_par_rate(curve, as_of, tenor_m, fixed_leg_freq_months=args.fixed_freq)
        logger.info("OIS par(%s) = %.4f%%", args.ois_price, par * 100)
        if args.fixed is not None:
            pv = ois_pv_receiver_fixed(
                curve,
                as_of,
                tenor_m,
                args.fixed,
                args.notional,
                fixed_leg_freq_months=args.fixed_freq,
            )
            logger.info(
                "  Receiver-fixed PV (fixed=%.4f%%, N=%s) = %.2f",
                args.fixed * 100,
                f"{args.notional:,.0f}",
                pv,
            )

    if not args.fra and not args.ois_price:
        logger.info(
            "No FRA or OIS pricing requested. Pass --fra and/or --ois-price along with --ois quotes. Use -h for help."
        )


if __name__ == "__main__":
    main()
