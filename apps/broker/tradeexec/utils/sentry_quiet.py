from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

_EASTERN_TZ = ZoneInfo("America/New_York")


def is_broker_sentry_quiet_hours(now_et: datetime | None = None) -> bool:
    enabled = (os.getenv("BROKER_SENTRY_QUIET_HOURS_ENABLED") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if not enabled:
        return False

    quiet_weekends = (os.getenv("BROKER_SENTRY_QUIET_WEEKENDS_ET") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    try:
        start_hour = int((os.getenv("BROKER_SENTRY_QUIET_HOURS_START_ET") or "20").strip())
        end_hour = int((os.getenv("BROKER_SENTRY_QUIET_HOURS_END_ET") or "6").strip())
    except Exception:
        start_hour, end_hour = 20, 6

    if start_hour < 0 or start_hour > 23 or end_hour < 0 or end_hour > 23:
        start_hour, end_hour = 20, 6

    now = now_et or datetime.now(tz=_EASTERN_TZ)
    if quiet_weekends and now.weekday() >= 5:
        return True

    hour = int(now.hour)
    if start_hour == 0 and end_hour == 23:
        return True
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def is_ibkr_maintenance_error(exc: BaseException) -> bool:
    msg = (str(exc) or "").lower()
    if not msg:
        return False
    # Common during IBKR maintenance/bridge restarts.
    tokens = (
        "reached max retries",
        "max retries exceeded",
        "maxretryerror",
        "remote end closed connection without response",
        "remote end closed connection",
        "remotedisconnected",
        "connection aborted",
        "protocolerror",
        "connection reset by peer",
        "no bridge",
        "initialize_brokerage_session",
        "temporarily unavailable",
        "service unavailable",
        "gateway",
        "/v1/api/tickle",
        "410 client error",
        "/v1/api/iserver/auth/ssodh/init",
        "snapshot price request failed",
        "/v1/api/oauth/live_session_token",
        "failed to resolve",
        "nameresolutionerror",
    )
    if any(t in msg for t in tokens):
        return True
    rate_limit_tokens = ("too many requests", "rate limit", "pacing violation", "pacing")
    if "429" in msg and (any(t in msg for t in rate_limit_tokens) or "http 429" in msg):
        return True
    # Ledger endpoint is a frequent overnight offender.
    if "api.ibkr.com" in msg and "/portfolio/" in msg and "/ledger" in msg:
        return True
    return False
