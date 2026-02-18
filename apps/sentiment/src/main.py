from __future__ import annotations

import argparse
import asyncio
import logging
import os

from apps.common.src.logging import get_logger, setup_logging  # noqa: E402
from apps.common.src.observability import init_service_observability  # noqa: E402
from apps.sentiment.src.settings import Settings  # noqa: E402

try:
    _settings_early = Settings()
except Exception:  # pragma: no cover - defensive
    _settings_early = None

if _settings_early and bool(_settings_early.sentiment_openai_debug):
    os.environ["OPENAI_LOG"] = "debug"
    os.environ["OPENAI_DEBUG"] = "true"
    setup_logging("DEBUG")
    logging.getLogger("openai").setLevel(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    logging.getLogger("mcp_agent").setLevel(logging.DEBUG)

if (
    _settings_early
    and getattr(_settings_early, "sec_edgar_user_agent", None)
    and not os.getenv("SEC_EDGAR_USER_AGENT")
):
    os.environ["SEC_EDGAR_USER_AGENT"] = str(_settings_early.sec_edgar_user_agent)

try:
    from .runner import async_main  # type: ignore[import]
except ImportError:  # pragma: no cover - direct execution fallback
    from runner import async_main  # type: ignore[import]


def main() -> None:
    parser = argparse.ArgumentParser(description="RankAlpha Sentiment Analyzer")
    parser.add_argument(
        "--symbol",
        help="Stock symbol to analyze immediately (bypasses schedule)",
        type=str,
    )
    parser.add_argument(
        "--force",
        help="Force reanalysis even if already run today",
        action="store_true",
        default=False,
    )
    args = parser.parse_args()

    try:
        settings = Settings()
    except Exception:
        settings = None

    desired_level = None
    if settings and settings.sentiment_openai_debug:
        desired_level = "DEBUG"
    elif settings and settings.log_level:
        desired_level = settings.log_level
    setup_logging(desired_level)
    init_service_observability("rankalpha-sentiment")

    logger = get_logger(__name__)

    if settings:
        if not args.symbol and settings.sentiment_symbol:
            args.symbol = settings.sentiment_symbol
        if not args.force and isinstance(settings.sentiment_force, bool):
            args.force = settings.sentiment_force
        if settings.sentiment_single_symbol_only:
            if not args.symbol:
                logger.error("SENTIMENT_SINGLE_SYMBOL_ONLY=1 set but no SENTIMENT_SYMBOL provided")
                return
            logger.info(
                "Single-symbol mode active: symbol=%s (SENTIMENT_SINGLE_SYMBOL_ONLY=1)",
                args.symbol,
            )

    if args.symbol:
        args.symbol = args.symbol.upper()

    model_log = settings.openai_model if settings and settings.openai_model else "(config default)"
    planner_model_log = (
        settings.openai_planner_model if settings and settings.openai_planner_model else "(same)"
    )
    debug_log = "on" if (settings and settings.sentiment_openai_debug) else "off"
    single_only_log = "on" if (settings and settings.sentiment_single_symbol_only) else "off"
    logger.info(
        "Startup config: symbol=%s, force=%s, OPENAI_MODEL=%s, OPENAI_PLANNER_MODEL=%s, DEBUG=%s, SINGLE_SYMBOL_ONLY=%s",
        args.symbol or "(none)",
        args.force,
        model_log,
        planner_model_log,
        debug_log,
        single_only_log,
    )
    if not args.symbol:
        logger.info("No on-demand symbol provided; running scheduled mode")

    try:
        asyncio.run(async_main(symbol=args.symbol, force=args.force))
    except KeyboardInterrupt:
        get_logger(__name__).info("Shutting down scheduled stock analysis system...")


if __name__ == "__main__":
    main()
