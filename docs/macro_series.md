## → RankAlpha macro / rates ingestion

This document specifies how to map economic and rate series into the
RankAlpha warehouse tables:

- `rankalpha.dim_macro_series` / `rankalpha.fact_macro_series`
- `rankalpha.dim_benchmark` / `rankalpha.fact_benchmark_price`
- `rankalpha.dim_tenor` / `rankalpha.fact_risk_free_rate`

The goal is:

- Keep **macro prints and composite indicators** in a single generic macro fact.
- Keep **tradable / index‑style series and non‑curve rates** in the benchmark fact.
- Use the dedicated **risk‑free curve** tables for Treasury yields and Fed funds.

All series below should use `dim_source` to register (e.g. `source_name = 'DataVendor'`)
and store the resulting `source_key` in `fact_macro_series.source_key` where applicable.

---

## 1. Macro prints & composite indicators → dim_macro_series / fact_macro_series

These series go into:

- Dimension: `rankalpha.dim_macro_series`
- Fact: `rankalpha.fact_macro_series`

For each row:

- `series_code` – stable machine code (used by ingestion & downstream code).
- `series_name` – human‑readable label.
- `category` – coarse grouping (activity, labor, prices, housing, money, conditions).
- `frequency` – `'M'` (monthly), `'Q'` (quarterly), `'W'` (weekly), `'D'` (daily).
- `units` – free‑text (e.g. `"index"`, `"percent"`, `"thousands"`, `"billions_usd"`).
- `value` in `fact_macro_series` should be the raw vendor value; any scaling should be
  clearly reflected in `units`.

> Note: frequencies are based on typical FRED conventions; if differs, use the
> actual vendor frequency but keep `series_code` and `category` as below.

### 1.1 Real economy / activity

| series                                  | symbol | series_code                         | category  | frequency | units         | fact table                      | notes                                                   |
| ---------------------------------------------- | -------------- | ----------------------------------- | --------- | --------- | ------------- | -------------------------------- | ------------------------------------------------------- |
| Chicago Fed National Activity Index            | `#CFNAI`       | `US_CFNAI`                          | activity  | M         | index         | `rankalpha.fact_macro_series`   |                                                         |
| ISM Purchasing Managers Index                  | `#NAPMI`       | `US_ISM_PMI`                        | activity  | M         | index         | `rankalpha.fact_macro_series`   | Use `#NAPMI` as level; `#NAPMI2/3` are derived variants |
| US Durable Goods New Orders                    | `#DURSA`       | `US_DURABLE_GOODS_NEW_ORDERS`      | activity  | M         | billions_usd  | `rankalpha.fact_macro_series`   | Use `#DURSA` as level; `#DURSA1/2/3` are derived        |
| US Industrial Production Index                 | `#INDSA`       | `US_INDUSTRIAL_PRODUCTION_IDX`     | activity  | M         | index         | `rankalpha.fact_macro_series`   |                                                         |
| US Retail & Food Services Sales                | `#RETSA`       | `US_RETAIL_FOOD_SALES`             | activity  | M         | billions_usd  | `rankalpha.fact_macro_series`   | `#RETSA` = “US Retail & Food Service Sales”             |
| US Retail Sales                                | `#RETXSA`      | `US_RETAIL_SALES`                  | activity  | M         | billions_usd  | `rankalpha.fact_macro_series`   | `#RETXSA` = “US Retail Sales”                           |
| US Total Construction Spending                 | `#TCSSA`       | `US_CONSTRUCTION_SPENDING_TOTAL`   | activity  | M         | billions_usd  | `rankalpha.fact_macro_series`   |                                                         |

### 1.2 Housing / construction

| series                                  | symbol | series_code                         | category | frequency | units        | fact table                    | notes |
| ---------------------------------------------- | -------------- | ----------------------------------- | -------- | --------- | ------------ | ------------------------------ | ----- |
| US Housing Completions                         | `#HOCSA`       | `US_HOUSING_COMPLETIONS`           | housing  | M         | thousands    | `rankalpha.fact_macro_series` |       |
| US Housing Starts                              | `#HOSSA`       | `US_HOUSING_STARTS`                | housing  | M         | thousands    | `rankalpha.fact_macro_series` |       |
| S&P/Case Shiller Composite-20 Home Price Index | `#SPCS20`      | `US_CS_20_HOME_PRICE_IDX`         | housing  | M         | index        | `rankalpha.fact_macro_series` |       |
| US Existing Home Sales Median Price            | `#HOMPR`       | `US_EXISTING_HOME_MEDIAN_PRICE`    | housing  | M         | usd          | `rankalpha.fact_macro_series` |       |

### 1.3 Labor market

| series           | symbol | series_code              | category | frequency | units        | fact table                    | notes                      |
| ------------------------ | -------------- | ------------------------ | -------- | --------- | ------------ | ------------------------------ | -------------------------- |
| US Initial Jobless Claims| `#INJOB`       | `US_INITIAL_CLAIMS`      | labor    | W         | thousands    | `rankalpha.fact_macro_series` | Weekly claims              |
| US Non-Farm Payrolls     | `#NFPAY`       | `US_NFP`                 | labor    | M         | thousands    | `rankalpha.fact_macro_series` | Monthly change in payrolls |
| US Unemployment Rate     | `#UNEMP`       | `US_UNEMPLOYMENT_RATE`   | labor    | M         | percent      | `rankalpha.fact_macro_series` | Unemployment rate in %     |

### 1.4 Income, balances, GDP

| series                         | symbol | series_code                         | category | frequency | units           | fact table                    | notes                    |
| -------------------------------------- | -------------- | ----------------------------------- | -------- | --------- | --------------- | ------------------------------ | ------------------------ |
| US Corporate Before Tax Profits       | `#CO$SA`       | `US_CORP_PROFITS_PRETAX`           | income   | Q         | billions_usd    | `rankalpha.fact_macro_series` | National income accounts |
| US Current Account Balance            | `#CURSA`       | `US_CURRENT_ACCOUNT_BALANCE`       | external | Q         | billions_usd    | `rankalpha.fact_macro_series` |                          |
| US Gross Domestic Product             | `#GDPSA`       | `US_GDP`                           | activity | Q         | billions_usd    | `rankalpha.fact_macro_series` | Real or nominal per vendor |
| US Real Personal Consumption Spending | `#PCESA`       | `US_REAL_PCE`                      | income   | M         | index or billions_usd | `rankalpha.fact_macro_series` | Match vendor definition  |
| US Trade Balance of Payments          | `#BOPSA`       | `US_TRADE_BALANCE`                 | external | M         | billions_usd    | `rankalpha.fact_macro_series` | Negative = deficit       |

### 1.5 Prices & inflation

| series                      | symbol | series_code      | category | frequency | units   | fact table                    | notes                         |
| ----------------------------------- | -------------- | ---------------- | -------- | --------- | ------- | ------------------------------ | ----------------------------- |
| US Consumer Price Index             | `#CPISA`       | `US_CPI_ALL`     | prices   | M         | index   | `rankalpha.fact_macro_series` | All items                     |
| US Chained Consumer Price Index     | `#CPICH`       | `US_CPI_CHAINED` | prices   | M         | index   | `rankalpha.fact_macro_series` | Chained CPI                   |
| US Core Consumer Price Index        | `#CPIXSA`      | `US_CPI_CORE`    | prices   | M         | index   | `rankalpha.fact_macro_series` | Ex‑food & energy              |
| US Producer Price Index             | `#PPISA`       | `US_PPI_ALL`     | prices   | M         | index   | `rankalpha.fact_macro_series` | Headline PPI (core = `#PPIXSA`) |

### 1.6 Money & financial conditions

| series                                           | symbol | series_code                               | category    | frequency | units        | fact table                    | notes                       |
| -------------------------------------------------------- | -------------- | ----------------------------------------- | ----------- | --------- | ------------ | ------------------------------ | --------------------------- |
| US M1 Money Stock                                       | `#M1FED`       | `US_M1`                                   | money       | M         | billions_usd | `rankalpha.fact_macro_series` | Frequency per vendor (M/W)  |
| US M2 Money Stock                                       | `#M2FED`       | `US_M2`                                   | money       | M         | billions_usd | `rankalpha.fact_macro_series` |                             |
| Chicago Fed National Financial Conditions Index         | `#NFCI`        | `US_NFCI`                                 | conditions  | W         | index        | `rankalpha.fact_macro_series` |                             |
| Chicago Fed NFCI Credit SubIndex                        | `#NFCIC`       | `US_NFCI_CREDIT`                          | conditions  | W         | index        | `rankalpha.fact_macro_series` |                             |
| Chicago Fed NFCI Leverage SubIndex                      | `#NFCIL`       | `US_NFCI_LEVERAGE`                        | conditions  | W         | index        | `rankalpha.fact_macro_series` |                             |
| Chicago Fed NFCI Risk SubIndex                          | `#NFCIR`       | `US_NFCI_RISK`                            | conditions  | W         | index        | `rankalpha.fact_macro_series` |                             |

---

## 2. Yield curve & policy rates

We distinguish between:

- **Risk‑free curve** – stored in `fact_risk_free_rate` keyed by `dim_tenor`.
- **Non‑risk‑free rates** – stored as benchmark series in `fact_benchmark_price`.

### 2.1 Risk‑free curve → dim_tenor / fact_risk_free_rate

Use:

- `rankalpha.dim_tenor` (tenor calendar)
- `rankalpha.fact_risk_free_rate` (daily curve, `rate_pct` in percent p.a.)

Required `dim_tenor` rows (if not already present):

| tenor_label | tenor_days | notes                           |
| ----------- | ---------- | ------------------------------- |
| `O/N`       | 1          | Overnight (Fed funds effective) |
| `3M`        | 90         | Approximate 13‑week / 3‑month   |
| `1Y`        | 365        | 1‑year                          |
| `2Y`        | 730        | 2‑year                          |
| `5Y`        | 1825       | 5‑year                          |
| `10Y`       | 3650       | 10‑year                         |
| `30Y`       | 10950      | 30‑year                         |

Map series as follows:

| series                                  | symbol | tenor_label | fact table                         | notes                                           |
| ---------------------------------------------- | -------------- | ----------- | ----------------------------------- | ----------------------------------------------- |
| 30 Day Federal Funds Rate (Effective)          | `%FFYE`        | `O/N`       | `rankalpha.fact_risk_free_rate`    | Store rate in `rate_pct` (e.g. 5.3250)         |
| US 13-Week T. Bill Yield                       | `%IRX`         | `3M`        | `rankalpha.fact_risk_free_rate`    | Map as 3M tenor                                |
| US 3-Month Treasury Constant Maturity Yield    | `%3MTCM`       | `3M`        | `rankalpha.fact_risk_free_rate`    | Prefer this as canonical 3M if both exist      |
| US 1-Year Treasury Constant Maturity Yield     | `%1YTCM`       | `1Y`        | `rankalpha.fact_risk_free_rate`    |                                                 |
| US 2-Year Treasury Constant Maturity Yield     | `%2YTCM`       | `2Y`        | `rankalpha.fact_risk_free_rate`    |                                                 |
| US 5-Year Treasury Constant Maturity Yield     | `%5YTCM`       | `5Y`        | `rankalpha.fact_risk_free_rate`    |                                                 |
| US 10-Year Treasury Constant Maturity Yield    | `%10YTCM`      | `10Y`       | `rankalpha.fact_risk_free_rate`    |                                                 |
| US 30-Year Treasury Constant Maturity Yield    | `%30YTCM`      | `30Y`       | `rankalpha.fact_risk_free_rate`    |                                                 |

> If both “T. Note/Bond Yield” and “Treasury Constant Maturity” variants are present,
> prefer the constant‑maturity series and ignore the duplicates to keep
> `(date_key, tenor_key)` unique.

### 2.2 Other rates → dim_benchmark / fact_benchmark_price

These are important rates but not part of the risk‑free curve; store them as benchmark
time series:

| series                                  | symbol | benchmark_name                          | category  | frequency | units   | fact table                            | notes                    |
| ---------------------------------------------- | -------------- | ---------------------------------------- | --------- | --------- | ------- | -------------------------------------- | ------------------------ |
| US Bank Prime Loan Rate                        | `%USPRIME`     | `US Bank Prime Loan Rate`                | rates     | D         | percent | `rankalpha.fact_benchmark_price`      | Level, not change        |
| US 30-Year Fixed Rate Mortgage Average Rate    | `%30MTG`       | `US 30Y Fixed Mortgage Avg Rate`         | rates     | W or D    | percent | `rankalpha.fact_benchmark_price`      | Match vendor frequency   |
| Moody's Seasoned Corporate Bonds AAA Yield     | `%COAAA`       | `Moody's AAA Corporate Bond Yield`       | credit    | D         | percent | `rankalpha.fact_benchmark_price`      |                          |
| Moody's Seasoned Corporate Bonds BAA Yield     | `%COBAA`       | `Moody's BAA Corporate Bond Yield`       | credit    | D         | percent | `rankalpha.fact_benchmark_price`      |                          |

Implementation note:

- For these, create `dim_benchmark` rows with the `benchmark_name` above, then write
  daily values into `fact_benchmark_price.close_px` (rate in percent).

---

## 3. Credit, bond & volatility indices → dim_benchmark / fact_benchmark_price

These are naturally “benchmark indices” with levels or spreads.

Use:

- `rankalpha.dim_benchmark`
- `rankalpha.fact_benchmark_price`
- View: `rankalpha.vw_benchmark_price`

Recommended mappings:

| series                                           | symbol | benchmark_name                                      | category | frequency | units        | fact table                       | notes                                    |
| -------------------------------------------------------- | -------------- | --------------------------------------------------- | -------- | --------- | ------------ | --------------------------------- | ---------------------------------------- |
| Dow Jones Equal Weight US Corporate Bond Total Return Index | `$DJCBT`       | `DJ Eq Weight US Corp Bond TR`                    | credit   | D         | index_level  | `rankalpha.fact_benchmark_price` | Use TR level; `total_return_factor` optional |
| S&P 500 Investment Grade Corporate Bond Total Return Index | `$SP5IGBIT`    | `S&P 500 IG Corp Bond TR`                         | credit   | D         | index_level  | `rankalpha.fact_benchmark_price` |                                          |
| S&P US Aggregate Bond Total Return Index                | `$SPUSAGGT`    | `S&P US Aggregate Bond TR`                         | credit   | D         | index_level  | `rankalpha.fact_benchmark_price` |                                          |
| S&P US Treasury Bill/Bond Total Return series (13 indices) | `$SPBDU10T`, `$SPBDU20T`, `$SPBDUB3T`, `$SPBDUB6T`, `$SPBDUB9T`, `$SPBDUBIT`, `$SPBDUBYT`, `$SPBDUS1T`, `$SPBDUS3T`, `$SPBDUS5T`, `$SPBDUS7T`, `$SPBDUSBT`, `$SPBDUSLT` | `S&P US Treasury TR <tenor/code>`                 | rates    | D         | index_level  | `rankalpha.fact_benchmark_price` | One `dim_benchmark` row per index        |
| ICE BofA CCC & Lower US High Yield Index OAS            | `%CCCHYS`      | `ICE BofA CCC & Lower HY OAS`                      | credit   | D         | basis_points | `rankalpha.fact_benchmark_price` | Store OAS in `close_px` (bps)           |
| ICE BofAML MOVE Index                                   | `$MOVE`        | `ICE BofAML MOVE Index`                            | vol      | D         | index        | `rankalpha.fact_benchmark_price` | Treasury implied vol index               |

For the S&P Treasury TR series, use clear `benchmark_name` values such as:

- `S&P US Treasury Bill TR 0-3M`
- `S&P US Treasury Bond TR 1-3Y`
- `S&P US Treasury Bond TR 3-5Y`
- … (one per series / ticker).

---

## 4. Ingestion notes for the implementing agent

1. **Seed dimensions**
   - Insert a `dim_source` row for if one does not already exist.
   - Insert all `dim_macro_series` rows using the `series_code`/`series_name`/`category` above.
   - Insert or upsert required `dim_tenor` rows (`O/N`, `3M`, `1Y`, `2Y`, `5Y`, `10Y`, `30Y`).
   - Insert `dim_benchmark` rows for each benchmark series listed.

2. **Load facts**
   - For each series, map the vendor symbol to:
     - a `series_key` (via `dim_macro_series`) **or**
     - a `benchmark_key` (via `dim_benchmark`) **or**
     - a `tenor_key` (via `dim_tenor` for curve series).
   - Convert vendor dates to `date_key` (`YYYYMMDD` int) via `dim_date`.
   - Upsert facts:
     - `fact_macro_series(date_key, series_key, source_key, value, load_ts)`
     - `fact_benchmark_price(date_key, benchmark_key, close_px, total_return_factor)`
     - `fact_risk_free_rate(date_key, tenor_key, rate_pct)`

3. **Idempotency**
   - Use `INSERT … ON CONFLICT (date_key, series_key) DO UPDATE` for `fact_macro_series`.
   - Use `INSERT … ON CONFLICT (date_key, benchmark_key) DO UPDATE` for `fact_benchmark_price`.
   - Use `INSERT … ON CONFLICT (date_key, tenor_key) DO UPDATE` for `fact_risk_free_rate`.

4. **Validation**
   - Sanity‑check a sample of series against known public sources (FRED, etc.).
   - Confirm views:
     - `SELECT * FROM rankalpha.vw_macro_series LIMIT 100;`
     - `SELECT * FROM rankalpha.vw_benchmark_price LIMIT 100;`
     - `SELECT * FROM rankalpha.vw_risk_free_rate LIMIT 100;`

This mapping should be sufficient for an ingestion agent to wire data into
the appropriate RankAlpha dimension and fact tables with clear, stable identifiers.

---

## 5. Breadth, technical & volatility indicators (symbol patterns)

**US market “Extras”** breadth/technical/volatility symbols follow consistent
prefix/suffix patterns. This section explains how to route them without having to hard‑code
every symbol.

### 5.1 Prefixes – what universe the series refers to

All of these are **one number per date** and belong in either
`fact_macro_series` (breadth/technicals/sentiment) or `fact_benchmark_price`
(volatility indices).

- Exchange‑level breadth (go to `fact_macro_series`):
  - `#NYSE…` – NYSE exchange (new highs/lows, AD issues, TRIN, etc.).
  - `#NAS…` / `#NASDAQ…` – Nasdaq exchange breadth.
  - `#AMEX…` – NYSE American breadth.
- Index‑level breadth/technicals (go to `fact_macro_series`):
  - `#COMP…` – Nasdaq Composite.
  - `#DJI…` – Dow Jones Industrial Average.
  - `#NDX…` – Nasdaq 100.
  - `#SPX…` – S&P 500.
  - `#MID…` – S&P 400 MidCap.
  - `#SML…` – S&P 600 SmallCap.
  - `#SP1500…` – S&P Composite 1500.
  - `#NYA…` – NYSE Composite.
  - `#RUA…` – Russell 3000.
  - `#RUI…` – Russell 1000.
  - `#RUT…` – Russell 2000.
  - `#OEX…` – S&P 100 (OEX).
- Put/call ratios (go to `fact_macro_series` with `category='sentiment'`):
  - `#CBOEPC`, `#CBOEPCE`, `#CBOEPCI`, `#CBOEPCSPX`.
- Volatility indices (go to `fact_benchmark_price` as benchmarks, `category='vol'`):
  - All `$VIX*`, `$VVIX`, `$VOLI`, `$GVZ`, `$OVX`, `$RVX`, `$VXEEM`, `$VXEFA`,
    `$VXEWZ`, `$VXN`, `$VXTLT`, `$SDEX`, `$TDEX`, `$SKEW`.

### 5.2 Suffixes – what the metric is

Within each prefix group, the **suffix** determines the metric. Use this to set
`series_code`, `category`, and `units` in `dim_macro_series`.

**Breadth counts & ratios (issues/volume)**

- `AD` / `ADV` – advancing issues (count) or net advance/decline; treat as **breadth count**, `units='count'`.
- `DEC` – declining issues (count), `units='count'`.
- `UNC` – unchanged issues (count).
- `ADR` / `ADVR` – advance/decline ratio (issues or volume), `units='ratio'`.
- `TRIN` – Arms Index (TRIN), `units='ratio'`, `category='breadth'`.

**Highs / lows (new 4/13/26/52‑week extremes)**

- `4WHI`, `13WHI`, `26WHI`, `52WHI` – number of new highs in last 4/13/26/52 weeks.
- `4WHL`, `13WHL`, `26WHL`, `52WHL` – number of new lows.
- `4WLO`, `13WLO`, `26WLO`, `52WLO` – often “lows” or combined metrics; treat as **count**.
- All of the above: `category='breadth'`, `units='count'`.

**Percent above moving average**

- `%MA20`, `%MA50`, `%MA100`, `%MA150`, `%MA200` – percentage of constituents above
  their X‑day simple moving average.
  - `category='breadth'`, `units='percent'`.
  - Example series codes: `US_SPX_PCT_ABOVE_50D`, `US_NDX_PCT_ABOVE_200D`.

**Oscillators and composite technicals**

- `BB%B`, `AVGBB%B` – Bollinger Band %B and average %B.
  - `category='technical'`, `units='index'`.
- `W%R`, `AVGW%R` – Williams %R and its average.
  - `category='technical'`, `units='index'`.
- `COPP` – Coppock indicator.
  - `category='technical'`, `units='index'`.
- `ITBM`, `ITVM` – Intermediate‑Term Breadth/Volume Momentum Oscillator.
  - `category='technical'`, `units='index'`.
- `MCOSC`, `MCOSCV`, `MCSUM` – McClellan Oscillator, McClellan Volume Oscillator,
  McClellan Summation.
  - `category='breadth'` or `'technical'` (choose one consistently), `units='index'`.
- `SWTR` – Swenlin Trading Oscillator.
  - `category='technical'`, `units='index'`.
- `ZWBT` – Zweig Breadth Thrust.
  - `category='breadth'` or `'sentiment'`, `units='index'`.

### 5.3 Where they land in the schema

- **All `#...` breadth/technical/sentiment series** listed above:
  - Dimension row in `rankalpha.dim_macro_series` (with a `series_code` such as
    `US_SPX_MCCLELLAN_OSC`, `US_RUT_TRIN`, `US_NYSE_AD_ISSUES`).
  - Daily values in `rankalpha.fact_macro_series` with:
    - `category` ∈ {`'breadth'`, `'technical'`, `'sentiment'`}.
    - `units` ∈ {`'count'`, `'percent'`, `'ratio'`, `'index'`}.
- **All `$...` volatility indices**:
  - Dimension row in `rankalpha.dim_benchmark` (`benchmark_name` like
    `CBOE VIX Index`, `CBOE VVIX Index`, `CBOE SKEW Index`).
  - Daily levels in `rankalpha.fact_benchmark_price.close_px`
    (`category='vol'`, `units='index'` or `'basis_points'` as appropriate).

This pattern‑based mapping should be enough for an ingestion agent to:

- Determine the **target table** from the first character (`#` → macro/breadth; `$` → benchmark/vol).
- Derive a consistent `series_code` and `category` from the prefix (universe) and suffix (metric).
