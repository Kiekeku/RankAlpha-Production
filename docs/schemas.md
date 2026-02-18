# RankAlpha Database Schema (Postgres)

## 1. Overview

RankAlpha uses a Postgres schema named `rankalpha` with a star/constellation layout:

- Dimensions (`dim_*`): reference data (dates, securities, factors, etc.).
- Facts (`fact_*`): time-series or event data.
- Helper/operational tables: queues, auth, flags, portfolios.
- Views (`v_*` / `vw_*`): query-friendly projections.

Migrations live in `docker/database/sql/migrations` and are the source of truth.
See `docs/schema_mermaid.md` for a high-level ERD of the core tables.

### Naming conventions

```
<schema>.<prefix>_<noun>    -- e.g. dim_stock, fact_security_price
*_key / *_id                -- surrogate keys
*_pk / *_fk                 -- constraint names
pk_ / fk_ / idx_            -- index names
```

Notes:
- Most dimension tables use surrogate serial keys, but `dim_date` is keyed by `date_key` (YYYYMMDD int).
- Fact table primary keys vary by domain; do not assume `date_key` + surrogate key everywhere.

---

## 2. Dimension tables

| Table | Purpose | Notes |
| --- | --- | --- |
| `dim_date` | Calendar and trading calendar. | `date_key` (YYYYMMDD int), `full_date`, `is_trading_day`. |
| `dim_stock` | Instruments master. | Symbol, company, exchange, sector; includes `currency_code` (authoritative listing/local currency; do not derive from `exchange`). |
| `dim_source` | Data provenance. | Vendor + version. |
| `dim_style` | Style buckets. | Value/Growth/Quality, etc. |
| `dim_score_type` | Score taxonomy. | Used by score history. |
| `dim_asset_type` | Equity/ETF/ADR, etc. | Used by trades and AI analysis. |
| `dim_rating` | Rating labels. | Used by AI analysis. |
| `dim_confidence` | Low/Med/High certainty. | AI analysis and trade recs. |
| `dim_timeframe` | Horizon tags. | 1d/1w/1m, etc. |
| `dim_trend_category` | Trend buckets. | Up/flat/down. |
| `dim_benchmark` | Benchmark indices. | S&P 500, etc. |
| `dim_factor` | Factor definitions. | Model + factor name. |
| `dim_fin_metric` | Fundamentals metric dictionary. | Statement field map. |
| `dim_corr_method` | Correlation method catalog. | Pearson/Spearman/Kendall. |
| `dim_corr_window` | Correlation windows. | 30D/90D/252D, etc. |
| `dim_tenor` | Term structure buckets. | 1D-30Y. |
| `dim_var_method` | VaR/ES methods. | Historical/Parametric, etc. |
| `dim_stress_scenario` | Stress scenarios. | Historical/hypo scenarios. |
| `dim_macro_series` | Macro series dictionary. | Used by macro facts. |
| `dim_news_cluster` | News clustering dictionary. | Newswire pipeline. |
| `dim_style_regime_map` | Style to regime mapping. | Regime scoring. |
| `dim_model_weight` | Current model weights. | Composite weighting. |
| `dim_model_weight_version` | Versioned model weight header. | Weight versioning. |
| `dim_model_weight_item` | Versioned model weight items. | Per-factor weights. |

---

## 3. Fact tables (by domain)

### 3.1 Market and reference data

- `fact_security_price`: daily OHLCV + total_return_factor.
- `fact_benchmark_price`: benchmark daily bars.
- `fact_factor_return`: daily factor returns.
- `fact_fx_rate`: daily FX mid rates (PK includes `date_key`).
- `fact_risk_free_rate`: daily risk-free curve by tenor.
- `fact_stock_borrow_rate`: daily borrow rates.
- `fact_iv_surface`: implied vol surface by tenor.
- `fact_vix_term_structure`: VIX term structure.
- `fact_spx_vix_vrp`: SPX/VIX/VRP snapshot.
- `fact_sofr_futures`: SOFR futures series.
- `fact_fra_ois`: FRA/OIS series.
- `fact_macro_series`: macro time series values.
- `fact_hy_stress`: high-yield stress metrics.
- `fact_nowcast_snapshot`: nightly Risk Nowcast composite snapshot (overall + tiers + deltas via views).
- `fact_nowcast_pillar_snapshot`: nightly Risk Nowcast pillar snapshot (per pillar score + details).
- `fact_stock_next_earnings`: earnings calendar.
- `fact_corporate_action`: splits/dividends/spinoffs.

### 3.2 Fundamentals

- `fact_fin_fundamentals`: as-reported and TTM metrics, partitioned by `date_key`.

### 3.3 Technicals

- `fact_technical_indicator`: daily technical indicators.

### 3.4 Scoring and screening

- `fact_score_history`: score time series by score type (partitioned).
- `fact_stock_scores`: per-style scores.
- `fact_stock_score_types`: per-score-type scores.
- `fact_screener_rank`: per-run ranks (partitioned).
- `fact_screener_rank_change`: delta events.
- `fact_screener_presence`: screener presence.
- `fact_screener_presence_side`: screener side details.
- `fact_stock_correlation`: pairwise correlations (partitioned).
- `fact_style_z_us`: style intensity z-scores.
- `fact_regime_series`: regime series facts.
- `fact_regime_market_structure`: market structure regime.
- `fact_regime_effective_weight`: effective weights by regime.
- `fact_regime_rules`: regime rule outputs.

### 3.5 AI analysis

- `fact_ai_stock_analysis`: core AI thesis per stock/day (partitioned).
- `fact_ai_factor_score`: AI factor scores.
- `fact_ai_peer_comparison`: peer snapshot.
- `fact_ai_valuation_metrics`: valuation metrics.
- `fact_ai_catalyst`: catalysts list.
- `fact_ai_price_scenario`: price scenarios.
- `fact_ai_macro_risk`: macro risks.
- `fact_ai_headline_risk`: headline risks.
- `fact_ai_data_gap`: data gaps.
- `fact_ai_analyst_summary`: analyst summaries.
- `fact_ai_event`: AI events.
- `fact_ai_risk`: AI risk rows.
- `fact_ai_news`: AI news links.
- `fact_ai_scenario_proximity`: scenario proximity.
- `fact_ai_benchmarking`: benchmarking facts.
- `fact_ai_summary_metrics`: summary metrics.
- `fact_ai_overall_summary`: rollup summary.
- `fact_ai_alternative_data`: alt-data signals.

### 3.6 News and sentiment

- `fact_news_articles`: raw articles (partitioned by `article_date`).
- `fact_news_sentiment`: one-to-one with `fact_news_articles` (PK = `article_id`).
- `fact_news_raw`: raw newswire ingestion.
- `fact_news_event`: material events.
- `fact_news_impact`: event impacts.

### 3.7 Portfolio and trading

- `fact_portfolio_trade`: executed trades.
- `fact_portfolio_position_hist`: historical positions.
- `fact_portfolio_nav`: NAV history.
- `fact_portfolio_pnl`: PnL breakdown.
- `fact_portfolio_risk`: risk metrics.
- `fact_portfolio_factor_exposure`: factor exposures.
- `fact_portfolio_var`: VaR/ES by method.
- `fact_portfolio_scenario_pnl`: stress PnL.
- `fact_trade_recommendation`: trade recommendations (with execution metadata).
- `portfolio_cash_position`: current cash balances by currency (supports negative cash for margin).
- `portfolio_policy_version`: versioned policy (risk tolerance) by portfolio over time.
- `portfolio_deployment`: deploy a model portfolio into a broker account via a sleeve.
- `portfolio_run`: daily runs (drafts → approvals) for model/broker/sleeve books.
- `portfolio_run_input`: broker run inputs (which deployments + model runs were used).
- `portfolio_run_position`: baseline/target snapshots (equity + cash) per run.
- `portfolio_order_intent`: per-line approved order list per run.
- `portfolio_order_intent_source`: link order intents to trade recommendations (idea lineage).
- `portfolio_order_intent_alloc`: allocate order intents to deployments/sleeves (qty/weight components).
- `portfolio_trade_link`: link actual trades to order intents (if originated from a run).
- `portfolio_trade_alloc`: allocate actual fills to deployments/sleeves for attribution.
- `fact_internal_cross`: explicit internal crosses between sleeves (priced at as-of close).

---

## 4. Helper and operational tables

- `portfolio`: portfolio master.
- `portfolio_position`: current positions.
- `portfolio_cash_position`: current cash balances by currency.
- `admin_flag`: one-shot admin toggles.
- `auth_role`, `auth_user`, `auth_user_role`: role-based access tables.
- `universe_policy`: universe inclusion policy.
- `regime_rules_config`: regime rule configuration.
- `news_cursor`: newswire cursor tracking.
- `news_suggestion`: external news suggestions.
- `news_ingest_queue`: newswire ingestion queue.
- `sentiment_analysis_queue`: sentiment pipeline queue.

---

## 5. Views

### Screening and scoring

- `v_latest_screener`
- `v_latest_screener_values`
- `v_latest_screener_consensus`
- `vw_screener_rank`
- `vw_score_history`
- `vw_stock_style_scores`

### Prices, rates, and macro

- `vw_stock_price_history`
- `vw_latest_adj_close`
- `vw_latest_technicals`
- `vw_benchmark_price`
- `vw_stock_borrow_rate`
- `vw_risk_free_rate`
- `vw_iv_surface`
- `vw_vix_term_structure_latest`
- `vw_spx_vix_vrp_latest`
- `vw_sofr_futures_latest`
- `vw_fra_ois_latest`
- `vw_macro_series`
- `vw_hy_stress`
- `vw_hy_stress_latest`

### Fundamentals

- `vw_fin_fundamentals`

### AI analysis

- `vw_ai_analysis_full`
- `vw_ai_analysis_latest`
- `vw_ai_stock_analysis_summary`
- `vw_ai_valuation_metrics`
- `vw_ai_factor_scores`
- `vw_ai_peer_comparison`
- `vw_ai_catalysts`
- `vw_ai_price_scenarios`
- `vw_ai_risks`
- `vw_ai_scenario_proximity`

### News

- `vw_news_sentiment`
- `vw_news_by_symbol`

### Portfolio and risk

- `vw_portfolio_position`
- `vw_portfolio_snapshot`
- `vw_portfolio_performance`
- `vw_portfolio_turnover`
- `vw_portfolio_top_contrib`
- `vw_portfolio_factor_exposure`
- `vw_portfolio_var`
- `vw_portfolio_scenario_pnl`
- `vw_risk_dashboard`

### Regime and breadth

- `vw_regime_series`
- `vw_regime_market_structure`
- `vw_breadth_signals`
- `vw_dxy_signals`

### Trading and auth

- `vw_trade_recommendation`
- `vw_auth_user_roles`

---

## 6. Partitioning and indexing notes

Large time-series tables are partitioned to keep queries fast. Current partitioned tables include:

- `fact_screener_rank` (by `date_key`)
- `fact_score_history` (by `date_key`)
- `fact_fin_fundamentals` (by `date_key`)
- `fact_news_articles` (by `article_date`)
- `fact_ai_stock_analysis` (by `date_key`)
- `fact_stock_correlation` (by `date_key`)

Partition tables are created by year (and sometimes a `_default` partition).

---

## 7. Keeping this doc current

If you add or change schema objects, update this file and the relevant migration.
For the full, canonical definition, always consult `docker/database/sql/migrations`.
