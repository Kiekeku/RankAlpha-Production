from __future__ import annotations

from datetime import date, datetime, time, timedelta


def _observed(dt: date) -> date:
    if dt.weekday() == 5:  # Saturday -> observed Friday
        return dt - timedelta(days=1)
    if dt.weekday() == 6:  # Sunday -> observed Monday
        return dt + timedelta(days=1)
    return dt


def _good_friday(year: int) -> date:
    # Meeus/Jones/Butcher algorithm for Easter Sunday, then minus 2 days
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    easter = date(year, month, day)
    return easter - timedelta(days=2)


def is_us_equity_holiday(d: date) -> bool:
    """Approximate NYSE/Nasdaq holiday schedule (regular trading days).

    Covers common full-day holidays with observed rules:
    - New Year's Day, MLK Day, Presidents' Day, Good Friday,
      Memorial Day, Juneteenth (2022+), Independence Day, Labor Day,
      Thanksgiving Day, Christmas Day.
    This is a pragmatic subset sufficient for gatekeeping daily automation.
    """
    y = d.year
    # Fixed/observed
    if d == _observed(date(y, 1, 1)) or d == _observed(date(y + 1, 1, 1)):
        return True  # New Year (including observed Dec 31 of prior year)
    if y >= 2022 and d == _observed(date(y, 6, 19)):
        return True  # Juneteenth (observed starting 2022)
    if d == _observed(date(y, 7, 4)):
        return True  # Independence Day
    if d == _observed(date(y, 12, 25)):
        return True  # Christmas

    # Mondays
    # MLK: third Monday in Jan
    if d.month == 1 and d.weekday() == 0 and 15 <= d.day <= 21:
        return True
    # Presidents: third Monday in Feb
    if d.month == 2 and d.weekday() == 0 and 15 <= d.day <= 21:
        return True
    # Memorial: last Monday in May
    if d.month == 5 and d.weekday() == 0 and d.day + 7 > 31:
        return True
    # Labor: first Monday in Sep
    if d.month == 9 and d.weekday() == 0 and 1 <= d.day <= 7:
        return True

    # Good Friday
    if d == _good_friday(y):
        return True

    # Thanksgiving: fourth Thursday in Nov
    if d.month == 11 and d.weekday() == 3 and 22 <= d.day <= 28:
        return True

    return False


def is_trading_day(d: date) -> bool:
    """Return True if weekday and not a US equity holiday."""
    return d.weekday() < 5 and not is_us_equity_holiday(d)


def is_market_open_now(
    *,
    now: datetime | None = None,
    open_time: time = time(9, 30),
    close_time: time = time(16, 0),
) -> bool:
    """Check if current time window applies on a trading day.

    Caller supplies naive `open_time`/`close_time` as UTC times. For other zones,
    pre-convert to UTC before calling.
    """
    now = now or datetime.now()
    if not is_trading_day(now.date()):
        return False
    # Early close handling (approximate): US equities usually close 1:00 PM ET
    # on certain days (e.g., Black Friday, Christmas Eve, July 3 when not a full holiday).
    session_close = _effective_close_time(now.date(), open_time, close_time)
    return open_time <= now.time() <= session_close


# -------------------------- Early close helpers -------------------------------

_EARLY_CLOSE_OFFSET = timedelta(hours=3, minutes=30)  # 9:30 -> 13:00 in ET


def _thanksgiving(y: int) -> date:
    # Fourth Thursday in November (day 22..28)
    for day in range(22, 29):
        if date(y, 11, day).weekday() == 3:
            return date(y, 11, day)
    # Fallback
    return date(y, 11, 22)


def is_early_close_day(d: date) -> bool:
    """Return True if US equities typically have an early close.

    Pragmatic approximation covering common cases:
    - Day after Thanksgiving (Black Friday)
    - Christmas Eve (Dec 24) when it’s a trading day
    - July 3 when it’s a trading day (and not a full holiday)
    """
    if d.weekday() >= 5:
        return False
    # Black Friday
    if d == _thanksgiving(d.year) + timedelta(days=1):
        return True
    # Trading day immediately before observed Christmas holiday
    if d == _previous_trading_day(_observed(date(d.year, 12, 25))):
        return True
    # Trading day immediately before observed Independence Day holiday
    if d == _previous_trading_day(_observed(date(d.year, 7, 4))):
        return True
    return False


def _effective_close_time(d: date, open_time: time, close_time: time) -> time:
    if not is_early_close_day(d):
        return close_time
    # Compute early close relative to the configured open_time to avoid TZ issues.
    dt_open = datetime.combine(d, open_time)
    dt_close = dt_open + _EARLY_CLOSE_OFFSET
    return dt_close.time()


def _previous_trading_day(d: date) -> date:
    candidate = d
    while True:
        candidate = candidate - timedelta(days=1)
        if is_trading_day(candidate):
            return candidate
