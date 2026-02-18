# Money Flow (Functional Spec)

This document describes RankAlpha’s **Money Flow** signal from a *functional/quant* perspective: what it measures, which data series it depends on, and how the derived indicators are constructed and used (including the Nowcast “Money Flow” pillar).

## 1) What “Money Flow” means in RankAlpha

RankAlpha’s Money Flow is a **daily cross‑sectional** signal intended to capture **buying vs selling pressure** at the stock level, and **risk appetite** at the sector level.

It has two layers:

1. **Per‑stock Money Flow Score** (`money flow score`): a 1–100 percentile score computed daily across the eligible universe.
2. **Sector “risk appetite”** (`Cyclical − Defensive`): derived from sector averages of that per‑stock score, and used as the Nowcast “flows” pillar input.

## 2) Data inputs and universe

### Core price/volume series (required)
For each eligible equity, the calculation uses daily OHLCV:
- High
- Low
- Close (using an adjusted-close equivalent; see below)
- Volume

The canonical source of truth is the database price fact table (and its “adjusted close” semantics via `total_return_factor`), not Parquet.

### Stock metadata (required)
- **Sector** (must be present and not “Unknown”)
- **Asset type** (equity; non-equities are excluded)
- **Active flag** (`is_active = true`)

### Market cap (optional; improves robustness)
If fundamentals market cap is available, it is used only to build **cross‑sectional weights** (see §3.3). If market cap is missing, the system falls back to an unweighted (or lightly weighted) computation.

### Universe summary
Operationally, Money Flow is computed for **active equities with valid sector classification**, and is intended to align with the “eligible universe” policy used across the stack.

## 3) Per‑stock Money Flow Score (1–100)

### 3.1 Components (per stock, per day)
Each stock gets a set of component signals computed on daily data:

1. **Chaikin Money Flow (CMF)** on a short window (5 trading days)
2. **Chaikin Money Flow (CMF)** on a medium window (20 trading days)
3. **Volume surprise** on a 60‑day baseline  
   - log(Volume / rolling median Volume over 60 days)
4. **20‑day return**  
   - percent change over 20 trading days (using the adjusted-close equivalent)

Coverage rules apply on rolling windows: each component requires a minimum fraction of valid observations (default **80%** of the window) or it is treated as unavailable for that stock/day.

### 3.2 CMF definition (intuitive)
CMF is computed from High/Low/Close/Volume using the standard “money flow multiplier” idea:
- close near the day’s high → positive money flow contribution
- close near the day’s low → negative money flow contribution
- scaled by volume

CMF over a window is the ratio of “money flow volume” to total volume.

### 3.3 Cross‑sectional normalization (daily)
Raw components are not comparable across stocks without normalization. For each trading day, RankAlpha standardizes each component **across the universe**:

- Compute a **weighted z‑score** per component across stocks on that day.
- Weights are a monotone transform of market cap (log-like) to reduce microcap noise while preventing megacaps from dominating.
- Z‑scores are **winsorized** (clipped) to limit outlier impact (default ±3).

### 3.4 Composite “money flow raw” signal (daily)
For each stock/day, the standardized components are combined into a single raw score:

`mf_raw = w20*z(CMF20) + w5*z(CMF5) + wv*z(VolSurp60) + wr*z(Ret20)`

Default weights:
- CMF20: 0.4
- CMF5: 0.2
- Volume surprise: 0.3
- 20‑day return: 0.1

If a component is unavailable for a given stock/day, it contributes neutrally (treated as 0 in the standardized space) rather than forcing the entire composite to null.

### 3.5 Percentile mapping to 1–100 (“score”)
The final published per‑stock output is a **weighted percentile rank** of `mf_raw` across the universe on that day:

- Percentile ∈ [0, 1] is computed with weights (same weighting family as above).
- The percentile is mapped to a **1..100** score:
  - `score = 1 + 99 * percentile`

Interpretation:
- **Higher Money Flow Score** → stock is in the upper tail of (volume‑weighted) positive money flow / buying pressure for that day.
- **Lower Money Flow Score** → lower tail.

## 4) Sector layer: “Cyclical − Defensive” appetite

### 4.1 Sector aggregation
For each day, compute sector averages of the per‑stock Money Flow Score:
- group by sector (or a mapped sector ETF label)
- take the mean score per sector

### 4.2 Cyclical vs defensive baskets
Sectors are mapped into two baskets (SPDR‑style labels):

**Cyclical:**
- XLY, XLI, XLF, XLK, XLE, XLB, XLC

**Defensive:**
- XLP, XLV, XLU, XLRE

### 4.3 Appetite definition
Define daily risk appetite as:

`appetite = mean(score_cyclical) − mean(score_defensive)`

Interpretation:
- **Positive appetite** → cyclicals lead defensives (risk‑on tilt).
- **Negative appetite** → defensives lead cyclicals (risk‑off tilt).

This appetite series is what the UI often labels as “Cyclical − Defensive”.

## 5) Nowcast integration (“flows” pillar)

The Nowcast “Money Flow” pillar uses the **appetite** series as an input and converts it into a daily **0–100 risk‑off score** so it is comparable with the other Nowcast pillars.

Canonical references (consolidated)
- Audit + lineage (persisted Nowcast artifacts): `docs/DATA_CATALOG.md` (see “2.16 Risk Nowcast”)
- Exact pillar formulas + thresholds: `docs/NOWCAST_QUANT_CHECKLIST.md`
- DB implementation (source of truth):
  - `docker/database/sql/migrations/V121__nowcast_snapshots.sql`
  - `docker/database/sql/migrations/V122__nowcast_money_flow_sector_coverage.sql` (adds sector coverage validity constraints for the Money Flow pillar)

## 6) Operational / data-quality notes

### Why the Nowcast “Money Flow” score can be blank
The Nowcast pillar requires a minimum history length to compute z‑scores. If the system has not yet accumulated enough historical `money flow score` records (or if appetite cannot be formed due to sector coverage), the pillar’s risk‑off score will remain unavailable even if some per‑day appetite values exist.

### Backfill expectation
If you have sufficient price history but only recently started persisting `money flow score`, a one‑off backfill can populate historical daily scores and immediately enable the Nowcast pillar to compute.

### What the signal is (and isn’t)
- It is **cross‑sectional** (relative to the day’s universe), not an absolute “flow in dollars”.
- It is intended as a **risk‑appetite/rotation proxy**, not a standalone alpha guarantee.
- It can be sensitive to:
  - sector classification quality
  - volume anomalies
  - survivorship/eligibility changes (mitigated by eligibility policy)
