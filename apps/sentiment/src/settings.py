from __future__ import annotations

from typing import Dict, Optional

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from apps.common.src.settings_base import ENV, ENV_DIR, ROOT, BaseAppSettings


class Settings(BaseAppSettings):
    """Sentiment service settings (multi-agent analysis, consensus, cache)."""

    sentiment_use_lean_report: bool = False
    sentiment_symbol: Optional[str] = None
    sentiment_force: bool = False
    sentiment_openai_debug: bool = False
    sentiment_single_symbol_only: bool = False
    sentiment_log_prompts: bool = False
    sentiment_log_file: Optional[str] = None

    # Paths for sentiment app (helpful for local runs)
    sentiment_data_dir: Optional[str] = None
    sentiment_output_dir: Optional[str] = None
    sentiment_schedule_file: Optional[str] = None

    # Sentiment worker output sizing (GPT-5 Responses)
    sentiment_analyst_max_tokens: Optional[int] = None
    sentiment_writer_max_tokens: Optional[int] = None

    # Sentiment tool behavior
    sentiment_fetch_max_length: Optional[int] = None
    sentiment_tool_cache: bool = True
    sentiment_tool_cache_ttl_seconds: Optional[int] = None
    sentiment_tool_cache_ttl_overrides: Optional[Dict[str, int]] = None
    # Optional: enrich prompts with human analyst price targets (via Serper HTTP API)
    sentiment_use_serper_analyst_targets: bool = False
    sentiment_serper_analyst_targets_limit: Optional[int] = None
    # Preferred base URL for internal API access from the sentiment app (used by Fetch MCP URL rewriting)
    sentiment_api_base: Optional[str] = None
    # Read timeout (seconds) for anchor price fetches from the RankAlpha API.
    sentiment_anchor_api_timeout_seconds: Optional[float] = None
    # Preferred base URL for broker service (used for live/snapshot price prefetch)
    sentiment_broker_base: Optional[str] = None
    # Planner/orchestrator tuning
    sentiment_orchestrator_timeout_seconds: Optional[int] = None
    # PDF extraction size cap for EDGAR/generic fetches (characters)
    sentiment_pdf_extract_max_chars: Optional[int] = None
    # Cap the number of analyses performed in a single scheduled run (testing safeguard)
    sentiment_max_analyses: Optional[int] = None

    # Consensus screener (optional sentiment integration)
    sentiment_use_consensus: bool = False
    sentiment_consensus_min_appearances: Optional[int] = None
    sentiment_consensus_min_styles: Optional[int] = None
    sentiment_consensus_limit: Optional[int] = None
    sentiment_consensus_batch_only: bool = False
    # Skip re-analysis if there is a recent analysis within N days (default 1 = same-day only)
    sentiment_skip_if_within_days: int = 1
    # Main loop sleep cadence (seconds) between scheduled checks
    sentiment_loop_sleep_seconds: Optional[int] = None

    # SEC EDGAR MCP configuration
    sec_edgar_user_agent: Optional[str] = None
    # Search MCP provider (Serper) configuration
    serper_api_key: Optional[str] = None
    fred_api_key: Optional[str] = Field(default=None, alias="FRED_API_KEY")

    # AI analysis cache (shared with API admin warmers)
    ai_analysis_cache_ttl_seconds: Optional[int] = None
    ai_analysis_cache_refresh_chunk_size: Optional[int] = None
    ai_analysis_cache_url: Optional[str] = None
    ai_analysis_cache_token: Optional[str] = None
    ai_analysis_cache_timeout_seconds: Optional[int] = None

    model_config = SettingsConfigDict(
        env_file=[ENV_DIR / "shared.env", ENV_DIR / "sentiment.env"],
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


__all__ = ["Settings", "ENV", "ENV_DIR", "ROOT"]
