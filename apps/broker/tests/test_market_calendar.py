from datetime import date, datetime, time

from tradeexec.utils.market_calendar import (
    is_early_close_day,
    is_market_open_now,
    is_trading_day,
    is_us_equity_holiday,
)


def test_us_equity_holiday_fixed_and_good_friday():
    # New Year's Day 2025
    assert is_us_equity_holiday(date(2025, 1, 1))
    # Observed New Year's Day for 2022 (Jan 1, 2022 was Saturday)
    assert is_us_equity_holiday(date(2021, 12, 31))
    # Good Friday 2024-03-29
    assert is_us_equity_holiday(date(2024, 3, 29))
    # Juneteenth observed (2022-06-20, Jun 19 was Sunday)
    assert is_us_equity_holiday(date(2022, 6, 20))
    # A regular weekday that's not a holiday
    assert not is_us_equity_holiday(date(2024, 3, 28))


def test_is_trading_day_weekends():
    # Saturday
    assert not is_trading_day(date(2024, 3, 30))
    # Monday
    assert is_trading_day(date(2024, 4, 1))


def test_is_market_open_window():
    # Construct a datetime within hours on a trading day
    dt = datetime(2024, 3, 28, 9, 45)
    assert is_market_open_now(now=dt, open_time=time(9, 30), close_time=time(16, 0))
    # Before open
    dt2 = datetime(2024, 3, 28, 8, 0)
    assert not is_market_open_now(now=dt2, open_time=time(9, 30), close_time=time(16, 0))
    # Holiday regardless of time
    dt3 = datetime(2024, 3, 29, 10, 0)
    assert not is_market_open_now(now=dt3, open_time=time(9, 30), close_time=time(16, 0))


def test_early_close_days_and_times():
    # Black Friday 2024-11-29
    d = date(2024, 11, 29)
    assert is_early_close_day(d)
    # Before early close
    assert is_market_open_now(
        now=datetime(2024, 11, 29, 12, 0), open_time=time(9, 30), close_time=time(16, 0)
    )
    # After early close (13:00 implied)
    assert not is_market_open_now(
        now=datetime(2024, 11, 29, 14, 0), open_time=time(9, 30), close_time=time(16, 0)
    )
    # Christmas Eve trading day (e.g., 2024-12-24 is Tuesday)
    assert is_early_close_day(date(2024, 12, 24))
    # Day before July 4 observed holiday (July 4, 2022 was Monday -> early close on July 1)
    assert is_early_close_day(date(2022, 7, 1))
    # Day before observed Christmas (Christmas 2022 observed on Dec 26 -> early close Dec 23)
    assert is_early_close_day(date(2022, 12, 23))
