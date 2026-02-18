from __future__ import annotations

from typing import Optional

from pydantic_settings import SettingsConfigDict

from apps.common.src.settings_base import ENV, ENV_DIR, ROOT, BaseAppSettings


class Settings(BaseAppSettings):
    """Scorer service settings (momentum/value factors, regimes, weights)."""

    scoring_momentum_window_weights: Optional[str] = None  # e.g. "200=1.0,90=1.0,50=1.0,30=1.0"
    scoring_momentum_min_valid_frac: Optional[float] = 0.8
    scoring_momentum_tstat_cap: Optional[float] = 3.0
    scoring_mf_component_weights: Optional[str] = None
    scoring_mf_min_valid_frac: Optional[float] = 0.8
    scoring_asof_min_coverage: Optional[float] = 0.5
    scoring_asof_grace_trading_days: Optional[int] = 1
    scoring_momentum_composite_mode: Optional[str] = "blend"  # residual | raw | blend
    scoring_momentum_residual_weight: Optional[float] = 0.7
    scoring_momentum_raw_weight: Optional[float] = 0.3
    scoring_momentum_min_group_size: Optional[int] = 5
    scoring_valuation_sector_weight: Optional[float] = 0.7
    scoring_valuation_market_weight: Optional[float] = 0.3
    scoring_valuation_min_sector_size: Optional[int] = 5
    # Scoring weights (hybrid IC + RP)
    scoring_weight_lambda_rp: Optional[float] = None
    scoring_weight_window_days: Optional[int] = None
    scoring_weight_horizon_days: Optional[int] = None
    scoring_weight_force: Optional[bool] = False

    # Data-quality alerting
    # Alert when required score coverage (Momentum + Value) is missing for > X fraction of the universe.
    scoring_missing_required_ratio_alert_threshold: Optional[float] = 0.05
    # Hard-fail run when too few eligible symbols pass the as-of freshness gate.
    scoring_asof_pass_min_ratio: Optional[float] = 0.5
    # Hard-fail run when too few as-of-passing symbols produce valid momentum windows.
    scoring_momentum_valid_min_ratio: Optional[float] = 0.5

    # Market Structure (CVD) regime knobs
    scoring_market_structure_lookback_days: Optional[int] = 320
    scoring_market_structure_trend_window: Optional[int] = 50
    scoring_market_structure_rv_window: Optional[int] = 20
    scoring_market_structure_corr_window: Optional[int] = 20
    scoring_market_structure_z_window: Optional[int] = 252
    scoring_market_structure_trend_up_z: Optional[float] = 0.5
    scoring_market_structure_trend_down_z: Optional[float] = -0.5
    scoring_market_structure_vol_threshold: Optional[float] = 0.0
    scoring_market_structure_corr_threshold: Optional[float] = 0.0
    scoring_market_structure_disp_threshold: Optional[float] = 0.0

    # VIX term structure / regime
    scoring_vix_window_days: Optional[int] = 750
    scoring_vix_calm_pct: Optional[float] = 0.30
    scoring_vix_stress_pct: Optional[float] = 0.70
    scoring_vix_panic_pct: Optional[float] = 0.90
    scoring_vix_ffill_limit: Optional[int] = 2

    # VRP (SPX vs VIX) regime
    scoring_vrp_trading_days: Optional[int] = 21
    scoring_vrp_lookback_days: Optional[int] = 720
    scoring_vrp_vrp_low_pct: Optional[float] = 0.20
    scoring_vrp_vrp_high_pct: Optional[float] = 0.80
    scoring_vrp_vix_low_pct: Optional[float] = 0.33
    scoring_vrp_vix_high_pct: Optional[float] = 0.66

    model_config = SettingsConfigDict(
        env_file=[ENV_DIR / "shared.env", ENV_DIR / "scorer.env"],
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


__all__ = ["Settings", "ENV", "ENV_DIR", "ROOT"]
