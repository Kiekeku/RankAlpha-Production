# Trading Signal Ingestion (External Strategies → RankAlpha)

This document defines the **contract** an external trading system/strategy repo should follow to hand off **trade ideas** to RankAlpha.

RankAlpha supports execution via the broker’s recommendation pipeline, but **execution is gated by portfolio approvals**:

- External strategies submit **ideas** into `rankalpha.fact_trade_recommendation` (non-broker sources).
- RankAlpha portfolio construction produces **approved broker rebalance runs** and exports an **executable** trade list.
- The broker runner executes only those exported (approved) rows.

External systems must use the RankAlpha API ingestion route described below. Direct database writes are not supported for external integrations.

## Date + timing conventions (daily close-based)

RankAlpha is currently **daily / close-based** for most signals. To avoid look-ahead confusion:

- `as_of_date` (API field) should represent the **data as-of close date** (typically **D-1**, the last completed trading day).
- `valid_from_ts` should represent the **earliest execution eligibility time** on the **execution day D** (default convention: **09:00 ET**, queue/eligibility time; broker transmits orders with `outside_rth=false` so they should not execute outside RTH).
- `expiry_ts` should be set to **D EOD ET** (recommended) so stale ideas don’t linger.

This matches the portfolio construction schedule (ET):
- signals ready by ~06:00 ET (D) using D-1 data
- portfolio construction at ~06:30 ET (D)
- queue/export by ~09:00 ET (D), intended for RTH-only execution

### Recommended defaults (external runners)

If your external strategy runner knows the intended **execution day** `D` (a trading day, ET), use:

- `as_of_date`: previous trading day (**D-1**) (data as-of close date)
- `valid_from_ts`: `D 09:00:00 ET` (queue/eligibility time; orders are transmitted with `outside_rth=false`)
- `expiry_ts`: `D 20:00:00 ET` (simple “EOD” expiry; avoids stale ideas lingering overnight)

Python example (generate UTC timestamps):

```python
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

def valid_window_utc(execution_day_d: date) -> tuple[datetime, datetime]:
    valid_from_et = datetime.combine(execution_day_d, time(9, 0), tzinfo=ET)
    expiry_et = datetime.combine(execution_day_d, time(20, 0), tzinfo=ET)
    return valid_from_et.astimezone(UTC), expiry_et.astimezone(UTC)
```

Notes:
- If you need **MOO/MOC-specific** behavior, keep using `valid_from_ts`/`expiry_ts` for gating; order-type handling happens downstream.
- If you want to avoid *any* order submissions before the 09:30 ET open, set `valid_from_ts` to `D 09:30:00 ET` instead of 09:00.
- If `D` is not a trading day, choose the next trading day and set `as_of_date` to the prior trading day.

---

## Execution Model (How the Broker Consumes Signals)

The broker reads **pending executable** recommendations for a specific IB account by filtering on:

- `source_name = broker::<ACCOUNT_NUMBER>` (via `rankalpha.dim_source`) **(reserved; created by RankAlpha after approval)**
- `is_live = false` (or NULL) (not yet claimed)
- `valid_from_ts <= now()` (eligible now)
- `expiry_ts IS NULL OR expiry_ts > now()` (not expired)
- Optional allowlist: the runner may still whitelist external `strategy_name` values, but **portfolio-run exports are always allowed**.

Important:
- External systems must **not** submit `source_name` values starting with `broker::`. These are reserved for approved broker orders.
- See `docs/PORTFOLIO_CONSTRUCTION.md` for the approval + export workflow.

When a row is placed:

- The broker **atomically claims** it by setting `is_live = true` (prevents duplicates per account).
- An IB order is submitted.
- When fills are observed, the broker inserts an idempotent ledger row into **`rankalpha.fact_portfolio_trade`** and best-effort updates `filled_price` / `filled_date` on the matching recommendation.

---

## Recommended Ingestion Path (API)

If the RankAlpha API service is reachable, use:

- Endpoint: `POST /api/v1/trading/signals`
- Auth: `Authorization: Bearer <TRADING_BEARER_TOKEN>`

This endpoint performs all dimension lookups and uses an idempotent upsert into `rankalpha.fact_trade_recommendation`.
It is intended for **ideas**, not direct broker execution.

### Minimal request (API-required fields)

```json
{
  "symbol": "AAPL",
  "action": "BUY",
  "as_of_date": "2026-01-07",
  "recommended_price": 182.45,
  "source_name": "External-Strategy-01"
}
```

Notes:
- API-required fields are intentionally minimal so external systems can “publish ideas” early.
- For ideas to be actionable downstream, also provide sizing (`size_shares` or `size_percent`) and a validity window (`valid_from_ts`, `expiry_ts`).

### Recommended request (actionable idea)

```json
{
  "symbol": "AAPL",
  "action": "BUY",
  "as_of_date": "2026-01-07",
  "recommended_price": 182.45,
  "source_name": "External-Strategy-01",
  "strategy_name": "Breakout-Oct",
  "size_percent": 2.5,
  "valid_from_ts": "2026-01-08T14:00:00Z",
  "expiry_ts": "2026-01-09T01:00:00Z"
}
```

Notes:
- `2026-01-08T14:00:00Z` corresponds to **09:00 ET** on 2026-01-08 (queueing convention; see above).
- `2026-01-09T01:00:00Z` corresponds to **20:00 ET** on 2026-01-08 (simple “EOD” expiry convention).

---

## Field Reference (What to Populate)

## Current Broker Limitations (Important)

The broker’s current `fact_trade_recommendation` execution path is intentionally simple. These constraints matter for external strategy repos:

- `time_in_force` is currently **not applied** to IB orders (parent orders are submitted as `DAY`; bracket children use `GTC`).
- `STOP` / `STOP_LIMIT` / `TRAIL` are treated as **protective stop management**, not “stop-entry” orders:
  - If there is **no existing IB position**, these recommendations will be skipped.
- `COVER` is effectively a **generic “exit existing IB position”** action (it closes long or short), and the current implementation exits the **full** position size.
- For `SELL`/`BUY` exit-sizing: `size_percent` is based on **available cash**, not your current position size (so it is not suitable for “sell 25% of position” type exits).
- Trailing stops are supported as **cancel/replace** updates when trail parameters change (see “Trailing Stops” below).

### Practical requirements (for actionable entry orders)

These are the practical requirements to ensure the idea is actionable downstream (execution happens later via portfolio runs):

- `source_name`: must **not** start with `broker::` (reserved for approved broker exports)
- `action`: one of `BUY | SELL | SHORT | COVER` (see semantics below)
- `as_of_date`: the **data as-of close date** (typically **D-1**; must exist in `rankalpha.dim_date`)
- `recommended_price`: required by the ingestion API and used as a sizing/reference price
- `symbol` + `currency_code`: `dim_stock.symbol` is a **unique listing identifier** in RankAlpha. For dual-listed tickers, use an exchange-qualified symbol (e.g., `SHOP` vs `SHOP.TO`) and keep `currency_code` consistent. The API rejects attempts to upsert the same `symbol` with a different `currency_code`.
- Sizing: provide **one** of:
  - `size_shares` (preferred if you already know target shares), or
  - `size_percent` (percent of available cash; broker computes shares)

### Optional (execution behavior)

- `order_type`: default `MARKET`. Supported by the broker:
  - `MARKET` (or `MKT`)
  - `LIMIT` (or `LMT`) → requires `limit_price` (broker will fall back to `recommended_price`)
  - `STOP` (or `STP`) → requires `stop_trigger_price`
  - `STOP_LIMIT` / `STOPLIMIT` / `STP_LMT` → requires `stop_trigger_price` and `limit_price`
  - `TRAIL` / `TRAILING_STOP` / `TRAILINGSTOP` → **protective trailing stop** (requires existing position and `trail_percent`; see below)
  - `MOC` / `MARKET_ON_CLOSE`
  - `MOO` / `MARKET_ON_OPEN`
- `stop_loss_price` / `take_profit_price`: if set, the broker attempts to place a bracket (child stop/target orders) using absolute prices.
- `valid_from_ts`: when the recommendation becomes eligible (defaults to `now()`).
- `expiry_ts`: when it becomes stale (strongly recommended).
- `portfolio_id`: optional routing to a specific portfolio sleeve; if omitted, fills are attributed to a per-account portfolio named `<ACCOUNT_NUMBER>`.
- `preconditions` (JSON): optional execution constraints metadata (stored; not strictly enforced yet).
- `routing_hint`, `risk_budget_bps`, `signal_version`, `model_run_id`, `time_in_force`, `auto_hedge`: stored for downstream use/analysis (some are not enforced by the broker yet).

### Broker-managed (do not set from external strategies)

- `is_live`: set to `true` by the broker when it claims/places an order
- `filled_price`, `filled_date`: set by the broker when fills are observed
- `create_ts`, `update_ts`: managed by DB defaults/triggers

---

## Long-only integration rules (MVP; enforced by portfolio construction)

If your external strategy is feeding the **long-only portfolio construction** workflow:

- `SHORT` and `COVER` will be ignored/rejected for MVP.
- `SELL` is treated as **reduce-only**:
  - if baseline position is 0, the sell will be dropped (with a recorded reason code in run artifacts).
  - sell quantity must not exceed baseline shares (no sell-to-open).
- `BUY` may still be resized/blocked by portfolio-level constraints (e.g., max-name %, liquidity).

External strategies should treat their sizing fields (`size_shares` / `size_percent`) as a **proposal**; the portfolio manager may override sizing at the account level.

Note:
- The portfolio engine can be configured for non-long-only runs; the above constraints apply when the portfolio run is configured as `long_only`.

## Trailing Stops (Place + Adjust)

Trailing stops are implemented as **protective orders** (only after a position exists at IBKR).
Sizing fields (`size_shares` / `size_percent`) are ignored for trailing stops; the broker sizes to the current IB position.
For `order_type=TRAIL`, `stop_trigger_price` and `limit_price` are not used.

### Trail parameters

Provide:

- API: `trail_percent` (preferred; 0 < percent < 100)
- Under the hood: the broker submits an IBKR **Client Portal (Web) API** order with `orderType="TRAIL"`, `trailingType="%"`, and `trailingAmt=<trail_percent>`.

Example (API):

```json
{
  "symbol": "AAPL",
  "action": "SELL",
  "as_of_date": "2026-01-07",
  "recommended_price": 182.45,
  "order_type": "TRAIL",
  "trail_percent": 2.5,
  "source_name": "External-Strategy-01",
  "strategy_name": "Breakout-Oct",
  "valid_from_ts": "2026-01-08T14:00:00Z",
  "expiry_ts": "2026-01-09T01:00:00Z"
}
```

### Adjusting a live trailing stop

- Re-submit (upsert) the same recommendation row with the updated trailing percent.
- Keep `as_of_date`, `symbol`, `action`, and `source_name` unchanged so the upsert hits the existing `uq_trade_rec` row.
- The broker will cancel the existing trailing order and place a new one sized to the current IB position.

---

## Action Semantics (Long/Short)

`rankalpha.trade_action` supports:

- `BUY`: send a buy order (opens/increases long or covers a short depending on current position)
- `SELL`: send a sell order (closes/reduces long or opens/increases short depending on current position)
- `SHORT` / `COVER`: available for expressiveness, but some broker bookkeeping (e.g., fill matching) currently treats executions as `BUY`/`SELL`.

Recommendation:

- If you need **unambiguous broker-side bookkeeping**, use `BUY` and `SELL` as the actual order side.
- If you need “close whatever IB position exists” behavior without specifying quantity, use `COVER` (broker treats it as an “exit” instruction).

---

## Validity, Idempotence, and Updates

- A recommendation is unique per `(as_of_date, symbol, source_name, action)` because of `uq_trade_rec`.
- Re-posting the same recommendation should be done as an **upsert** (safe retries).
- To cancel a not-yet-placed order, set `expiry_ts = now()` (or earlier) while `is_live = false`.
- Once the broker has claimed a row (`is_live = true`), it will not be re-processed as a new entry; **live trailing-stop recommendations** can be updated (cancel/replace) by changing the trail parameters and upserting the same row.

---

## Verification Queries

Use the readable view:

```sql
SELECT *
FROM rankalpha.vw_trade_recommendation
WHERE source_name = 'External-Strategy-01'
ORDER BY recommendation_date DESC, create_ts DESC;
```
