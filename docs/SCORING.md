# RankAlpha Scoring Methodology

This document explains how Value, Momentum, and the Final Grade are computed, the data sources involved, and the configuration knobs available to tune behavior.

Canonical references (consolidated)
- Audit + lineage (what datasets exist, who produces them, where stored): `docs/DATA_CATALOG.md`
- Exact scoring + grading methodology (this document): `docs/SCORING.md`
- Implementation notes / operational tunables: `apps/scorer/README.md` and the DB grade MV migration referenced below

## Overview
- Value Score (0–100): Fundamentals‑based relative valuation, sector‑aware.
- Momentum Score (0–100): R²‑weighted trend blend across multiple windows, blended 70/30 (residual/raw), ranked cross‑sectionally.
- Final Grade (A–F): Weighted composite of Value, Momentum, and Sentiment, converted to a percentile (0–100) and mapped to letter bands.

## Data Sources
- Fundamentals: `rankalpha.fact_fin_fundamentals` joined with `rankalpha.dim_fin_metric`, `rankalpha.dim_stock`, `rankalpha.dim_date`.
- Scores table: `rankalpha.fact_score_history` for storing and reading computed scores.
- Latest Grades MV: `rankalpha.mv_latest_grades` (materialized view) for fast API queries.

## Valuation Score (Fundamentals)
- Metric set (lower is cheaper):
  - P/FCF per share (TTM): `ttmprfcfps`, fallback FY `aprfcfps` (weight 35%)
  - P/CF per share (TTM): `ttmprcfps` (25%)
  - P/S (TTM): `ttmpr2rev`, fallback FY `apr2rev` (20%)
  - P/B (FY): `aprice2bk`, fallback P/Tangible Book `apr2tanbk` (20%)
- For each metric m:
  - Sector percentile: rank ascending within sector; cheapness = (1 − rank_pct) × 100
  - Market percentile: rank ascending across market; cheapness = (1 − rank_pct) × 100
  - Blend: sector_vs_market = 0.7 × sector + 0.3 × market (defaults; configurable)
  - If sector sample < 5, use market only
- Combine metrics: weighted average using the weights above with dynamic reweighting when some metrics are missing (weights renormalize to 1 for metrics present)
- Clamp final Value Score to [0,100]
- Storage: written to `fact_score_history` with score_type = `value score`
- Implementation: `apps/scorer/src/main.py:compute_valuation_scores()`

## Momentum Score (Blended 70/30)
- Windows: 200, 90, 50, 30 trading days
- Per window w:
  - Linear regression of Close vs time over the last w days → slope_w and R²_w
  - Effective weight = base_window_weight_w × R²_w (base weights configurable via env)
- Blend: blended_slope = sum(slope_w × effective_weight_w) / sum(effective_weight_w)
- Residual leg: demean blended_slope by sector median (per day); raw leg uses unadjusted blended_slope
- Cross‑section percentile: rank sector‑neutralized values across the universe; map to Momentum Score in [1..100] via (pct × 99 + 1)
- Storage: written to `fact_score_history` with score_type = `momentum score`
- Implementation: `apps/scorer/src/main.py` (R² fit `linreg_slope_r2`, blending + neutralization logic in `main()`)

## Sentiment Score (used in Final Grade)
- **Preferred source (current):** `rankalpha.mv_sentiment_proxy.sentiment_proxy_score` (0–100)
  - Built from the latest AI analysis scenario targets (`fact_ai_price_scenario`) vs the latest close (`fact_security_price`).
  - The proxy computes an expected return from bull/base/bear targets and maps it to 0–100 via robust 5th–95th percentile scaling (see `docs/AI_SENTIMENT_DATA.md`).
- **If missing:** sentiment is excluded from the composite (no penalty; weights renormalize over available pillars).

## Final Composite and Grades (MV)
- Source of truth:
  - MV: `rankalpha.mv_latest_grades`
  - Point-in-time function: `rankalpha.fn_grades_as_of(date)`
  - Current implementation: `docker/database/sql/migrations/V118__fix_grades_percentiles_and_sentiment_proxy.sql`
- Inputs per symbol:
  - Momentum: prefer new `momentum score` from `fact_score_history`; fallback to legacy LR200 cross‑section scaling on the latest day
  - Value: prefer fundamentals `value score` from `fact_score_history`; fallback to AI value score
  - Sentiment: `mv_sentiment_proxy.sentiment_proxy_score` (scenario-based 0–100 proxy)
- Composite weights (configurable only in code/MV for now):
  - Momentum 40%, Value 40%, Sentiment 20%
  - Dynamic reweighting: exclude NULL components and renormalize the remaining weights to sum to 1
- Requirement gate: Momentum and Value must both be present; Sentiment is optional.
- Cross‑section percentile → `avg_score` in [1..100]: `(cume_dist × 99) + 1`
  - Percentiles are computed over **non-NULL composites** (symbols without a composite are excluded from the ranking pool).
- Grade bands:
  - A: ≥ 90
  - B: ≥ 70
  - C: ≥ 45
  - D: ≥ 20
  - F: < 20 (N/A if all components NULL)
  - `grade_order`: A=5, B=4, C=3, D=2, F=1, N/A=0

## Environment Variables (Scorer)
Read from `env/<ENV>/scorer.env` via `apps.scorer.src.settings.Settings`.
- `SCORING_MOMENTUM_WINDOW_WEIGHTS` (default: `200=1.0,90=1.0,50=1.0,30=1.0`)
  - Comma‑separated `window=weight` pairs; effective per‑window weight = base_weight × R²
- `SCORING_VALUATION_SECTOR_WEIGHT` (default: `0.7`)
  - Blend weight for sector cheapness
- `SCORING_VALUATION_MARKET_WEIGHT` (default: `0.3`)
  - Blend weight for market cheapness
- `SCORING_VALUATION_MIN_SECTOR_SIZE` (default: `5`)
  - Minimum sector sample to apply sector percentile; else market only

Example file: `env/example/scorer.env.example` (copy to your active profile, e.g., `env/local/scorer.env`).

## Operational Notes
- Scorer writes momentum, value, and (optional) sentiment scores to `fact_score_history`.
- Grades are computed in the DB (`mv_latest_grades`) and are typically refreshed by the pipeline via API refresh endpoints after scorer completes.
- The MV reads the latest per‑symbol momentum and value from `fact_score_history` using deterministic tie‑breakers (date_key, load_ts, fact_id) to avoid duplicates.
- API grades and UI rankings consume `mv_latest_grades` to keep behavior consistent.

## Calibration Recommendations
- Weights: The default 40/40/20 split is a reasonable starting point; adjust per sector or regime with backtests.
- Neutralization: Demeaning by sector is robust; consider z‑scoring within sector for tighter neutrality if needed.
- Thresholds: Grade bands are percentile‑based for stability; you can adjust cutoffs to match desired selectivity.
