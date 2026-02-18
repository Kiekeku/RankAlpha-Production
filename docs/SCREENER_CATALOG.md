# RankAlpha Screener Catalog (Functional)

Last updated: 2026-01-19

This document inventories RankAlpha’s **screener system** from a functional perspective:

- **Styles** (families like Momentum, Pullback, Value, Short)
- **Screener sources** (named presets like `RA-Momo-50DayBreakout`)
- **What each screener is trying to capture** (goal + representative criteria)

For a lineage view of where screener data sits in the broader platform, see `docs/DATA_CATALOG.md`.

## Where screener data lives (DB)

The database stores screener membership as “hits”:

- Fact: `rankalpha.fact_screener_rank` (one row per `(date_key, stock_key, source_key, style_key)` hit)
- Dictionaries:
  - `rankalpha.dim_style` (style family + side + style weight)
  - `rankalpha.dim_source` (screener/source name + per-source weight + “exclude from screener” flag)
- Latest projections:
  - `rankalpha.v_latest_screener_values` (today’s hits with weights)
  - `rankalpha.v_latest_screener_consensus` (daily enriched composite used by the API/UI)

Inventory exports (generated from Postgres in this repo):

- **All observed screener sources by style** (includes vendor/legacy, with last-seen coverage): `docs/screener_style_source_inventory_fact.csv`
- **RankAlpha internal preset sources (`RA-*`) including those with zero hits**: `docs/screener_style_source_inventory.csv`

## Style inventory (today)

Styles are configured in `rankalpha.dim_style` (each one has a `position_side` and `screener_weight`).

Current styles:

- `Breakout` (long)
- `BuyAndHold` (long)
- `Defensive` (long)
- `Earnings` (long)
- `EarningsPost` (long)
- `EarningsPre` (long)
- `Growth` (long)
- `HighVolume` (long)
- `IPO` (long)
- `MeanReversion` (long)
- `Momentum` (long)
- `Pullback` (long)
- `Short` (short)
- `ShortSqueeze` (long)
- `Value` (long)

## RankAlpha internal presets (RA-*) by style

The human descriptions below are the same copy used by the frontend About page:
`apps/frontend/src/content/screener-methodology.ts`.

### Momentum (Breakouts & continuations)

- `RA-Momo-50DayBreakout`
  - Goal: Names making new highs with participation (continuation candidates).
  - Representative criteria: New 52-week highs, price above 50/200-DMA, relative volume >= ~1.3-1.5, price >= $10, average volume >= 1M.
- `RA-Momo-NearHighContinuation`
  - Goal: Leaders within ~10% of 52-week highs, trend stack (20>50>200).
  - Representative criteria: Within 0-10% of 52-week high, price above 20/50/200-DMA, one-week performance positive.
- `RA-Momo-Fresh52wBreakout`
  - Goal: Earlier breakouts that haven’t printed 52-week highs yet.
  - Representative criteria: New 50-day highs, price above 50/200-DMA, modest relative-volume gate.

### Pullback (Pullback in uptrend)

- `RA-Pullback-Under50Over200`
  - Goal: Shallow pullbacks in primary uptrends, poised to resume.
  - Representative criteria: Price above 200-DMA and below 50-DMA, price > 20-DMA (or reclaim), RSI not overbought, one-week performance down.
- `RA-Pullback-ChannelUpWeeklyDown`
  - Goal: Touches of lower channel within rising trends.
  - Representative criteria: Pattern = channel up, one-week performance down, price > 200-DMA, RSI roughly 40-55.

### MeanReversion (Oversold bounces)

- `RA-MeanReversion-OversoldPop`
  - Goal: RSI washout plus relative-volume spike -> bounce candidates.
  - Representative criteria: RSI <= 30, relative volume >= 2, green on the day, price >= $5, average volume >= 1M.
- `RA-MeanReversion-OversoldUptrend`
  - Goal: Oversold within long-term uptrend; less knife-catching.
  - Representative criteria: RSI <= 30, price > 200-DMA, moderate relative volume.

### Growth (Quality growth)

- `RA-QualityGrowth-EPS`
  - Goal: Real top/bottom-line growth with profitability, not just story.
  - Representative criteria: EPS YoY & next-year growth, sales QoQ growth, ROE > 15%, debt/equity < 1, price > 200-DMA.
- `RA-QualityGrowth-Trend`
  - Goal: Revenue torque with healthy margins and trend alignment.
  - Representative criteria: Sales QoQ > ~20%, gross margin > ~20%, ROE > 15%, price > 50/200-DMA, RSI >= 50.

### Value (Value / GARP / dividend)

- `RA-Value-Quality`
  - Goal: Cheaper but healthy balance sheet/business.
  - Representative criteria: P/E <= ~15, PEG low (~<=1), debt/equity < 1, ROE > 12%, price > 200-DMA, mid-cap or larger.
- `RA-Value-Dividend`
  - Goal: Growth-at-reasonable-price among dividend payers.
  - Representative criteria: Dividend > 0, payout ratio < ~60%, P/E <= 20, PEG low, price > 200-DMA, large-cap or larger.
- `RA-Value-IncomeQuality`
  - Goal: Defensible dividend franchises.
  - Representative criteria: Dividend > 0, payout < ~60%, debt/equity < 1, ROE > 10%, institutional ownership high, price > 200-DMA.

### ShortSqueeze (Short-squeeze candidates)

- `RA-ShortSqueeze-OnTheMove`
  - Goal: Crowded shorts where momentum ignition is happening.
  - Representative criteria: Short float high, relative volume >= 1.5, today’s volume >= ~1-2M, often a 50-day breakout.
- `RA-ShortSqueeze-NearHigh`
  - Goal: Structurally strong, near highs with crowding.
  - Representative criteria: Short float >= ~15%, within 0-10% of 52-week high, liquidity floor enforced.

### Earnings (Earnings plays)

Note: the DB currently tracks Earnings in multiple related style families (`Earnings`, `EarningsPre`, `EarningsPost`).

- `RA-Earnings-PreSqueeze`
  - Goal: “Buy the rumor” flows ahead of prints.
  - Representative criteria: Earnings this week, gap up >= ~2%, relative volume >= 1.5, price > 50/200-DMA.
- `RA-Earnings-PostMomo`
  - Goal: After a strong print, ride continuation leaders.
  - Representative criteria: Day/weekly performance up, price > 50/200-DMA.

### IPO (IPO momentum)

- `RA-IPO-Momo`
  - Goal: Recent IPOs with real sales torque making highs.
  - Representative criteria: IPO <= 3 years, sales QoQ > ~30%, new 52-week high, relative volume >= 2.

### Defensive (Defensive quality / low-vol)

- `RA-Quality-LowBeta`
  - Goal: Ballast: steady return of capital/returns on capital.
  - Representative criteria: Large-cap or larger, beta < ~0.9, debt/equity < 1, ROE > 12%, price > 200-DMA.

### Short (Short / sell-bias)

- `RA-Short-MomoBreakdown`
  - Goal: Structural downtrends with fresh weakness.
  - Representative criteria: Price < 50-DMA and < 200-DMA, new 20-day lows, relative volume >= 1.5.
- `RA-Short-Resistance`
  - Goal: Stretched rallies into nearby supply.
  - Representative criteria: RSI >= 70, within 0-5% below 20-day high, down on the day.

## Vendor / legacy sources (FV-*)

The database contains historical screener hits for a set of `FV-*` sources (likely vendor presets).

- These sources are present in `rankalpha.fact_screener_rank` (see `docs/screener_style_source_inventory_fact.csv`).
- In the current DB, they are flagged `exclude_from_screener = true` in `rankalpha.dim_source`.
- No dedicated functional descriptions for `FV-*` were found in the frontend methodology copy (the About page documents `RA-*` presets).

If you want, I can add short “what it means” blurbs for each `FV-*` entry (explicitly labeled as inferred from the preset name unless we locate a vendor definition table/source-of-truth).

## Naming and mapping notes

- The DB key is `rankalpha.dim_source.source_name` (max 50 chars). UI labels may include additional descriptive text after ` - `.
- `docs/screener_style_source_inventory.csv` includes a couple of `RA-PullBack-*` variants (capitalization) that exist in `dim_source` but have no observed hits; the canonical keys used by the current frontend copy are `RA-Pullback-*`.
