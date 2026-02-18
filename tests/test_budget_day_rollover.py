import time as _time
from apps.common.src.ai.budget import BudgetLedger, Budget


def test_day_rollover_reservation_vs_commit():
    # Controlled clock to simulate day change between reserve and commit
    t = [1728600000.0]  # some UTC timestamp (Sat Oct 11, 2024 00:00:00 GMT-ish)

    def now():
        return t[0]

    led = BudgetLedger(service="rollover", budget=Budget(max_requests_per_min=1000, max_tokens_per_day=10_000, max_cost_usd_per_day=1000.0), now=now)

    # Begin call near midnight UTC on day D
    est_tokens = 100
    est_cost = 1.0
    r = led.begin_call(tokens_estimate=est_tokens, cost_estimate_usd=est_cost)

    # Advance clock to next day
    t[0] = t[0] + 24 * 3600 + 10

    # Commit actuals next day; should not subtract the previous day's estimate
    led.commit(tokens_in=80, tokens_out=20, actual_cost_usd=1.5, reservation=r)

    # Today's bucket should contain full actuals (100 tokens, $1.5) as delta
    today_key_tokens = f"rollover:tokens:{_time.strftime('%Y%m%d', _time.gmtime(t[0]))}"
    today_key_cost = f"rollover:cost:{_time.strftime('%Y%m%d', _time.gmtime(t[0]))}"
    assert int(led.counter.get(today_key_tokens)) == 100
    assert float(led.counter.get(today_key_cost)) == 1.5

