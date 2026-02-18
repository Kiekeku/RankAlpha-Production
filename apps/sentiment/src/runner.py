from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from apps.common.src.logging import add_rotating_file_handler, get_logger
from apps.sentiment.src.settings import Settings as Settings

try:
    from . import paths as sentiment_paths
    from .service_cycle import run_sentiment_service_cycle
except ImportError:  # pragma: no cover - direct execution fallback
    import paths as sentiment_paths
    from service_cycle import run_sentiment_service_cycle

try:
    from .db_utils import get_connection
except ImportError:  # pragma: no cover - direct execution fallback
    from db_utils import get_connection

try:
    from .schedule_manager import clean_schedule
except ImportError:  # pragma: no cover - direct execution fallback
    from schedule_manager import clean_schedule


async def async_main(symbol: str | None = None, force: bool = False):
    logger = get_logger(__name__)

    # Load settings and configure data paths based on env files
    settings = Settings()
    data_dir = sentiment_paths.configure_paths(settings)

    # Ensure primary data directories exist before any server startup
    try:
        os.makedirs(sentiment_paths.OUTPUT_DIR, exist_ok=True, mode=0o777)
    except Exception as exc:
        logger.warning(
            "Could not create OUTPUT_DIR '%s': %s",
            sentiment_paths.OUTPUT_DIR,
            exc,
        )
    try:
        os.makedirs(sentiment_paths.SCHEDULE_FILE.parent, exist_ok=True, mode=0o777)
    except Exception as exc:
        logger.warning(
            "Could not create schedule dir '%s': %s",
            sentiment_paths.SCHEDULE_FILE.parent,
            exc,
        )

    # Configure optional file logging for OpenAI/MCP traces under DATA_DIR/logs
    try:
        logs_dir = os.path.join(data_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(logs_dir, f"sentiment_oai_{run_ts}.log")
        # Always attach file handler in debug mode or when full prompt logging is requested
        if bool(settings.sentiment_openai_debug) or bool(settings.sentiment_log_prompts):
            add_rotating_file_handler(path=log_file, level=logging.DEBUG)
        else:
            add_rotating_file_handler(path=log_file, level=logging.INFO)
        # Expose the log file path so downstream modules (e.g., GPT‑5 wrappers)
        # can attach their own file handlers without relying on root level.
        os.environ["SENTIMENT_LOG_FILE"] = log_file
        logger.info("File logging enabled: %s", log_file)
        logger.info(
            "Logging toggles -> openai_debug=%s, log_prompts=%s, file=%s",
            bool(settings.sentiment_openai_debug),
            bool(settings.sentiment_log_prompts),
            log_file,
        )
    except Exception as exc:
        logger.warning("Could not initialize file logging: %s", exc)

    logger.info("Starting scheduled stock analysis system...")
    logger.info("Schedule file location: %s", sentiment_paths.SCHEDULE_FILE)
    # One-liner: resolved API base for price fetch (Fetch MCP)
    try:
        api_base = (
            getattr(settings, "sentiment_api_base", None)
            or os.getenv("SENTIMENT_API_BASE")
            or "(unset)"
        )
        logger.info("Resolved API base for prices (SENTIMENT_API_BASE): %s", api_base)
    except Exception:
        pass

    # Ensure SEC_EDGAR_USER_AGENT is exported for MCP subprocesses
    try:
        if getattr(settings, "sec_edgar_user_agent", None) and not os.getenv(
            "SEC_EDGAR_USER_AGENT"
        ):
            os.environ["SEC_EDGAR_USER_AGENT"] = str(settings.sec_edgar_user_agent)
            logger.info("Exported SEC_EDGAR_USER_AGENT from Settings for EDGAR MCP server")
    except Exception:
        pass

    # Optional OpenAI SDK debug logging to inspect actual request payloads
    if settings.sentiment_log_prompts:
        os.environ["SENTIMENT_LOG_PROMPTS"] = "true"

    if bool(settings.sentiment_openai_debug):
        os.environ["OPENAI_LOG"] = "debug"
        os.environ["OPENAI_DEBUG"] = "true"
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.DEBUG,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            )
        else:
            logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)
        logging.getLogger("httpx").setLevel(logging.DEBUG)
        logging.getLogger("mcp_agent").setLevel(logging.DEBUG)
        logger.info("OpenAI debug logging enabled (OPENAI_LOG=debug, OPENAI_DEBUG=true)")

    # Connection factory shared across helpers
    def connection_factory():
        return get_connection(settings)

    # Clean up any existing schedule to ensure no duplicates
    if sentiment_paths.SCHEDULE_FILE.exists():
        logger.info("Cleaning existing schedule to ensure no duplicate dates...")
        clean_schedule(sentiment_paths.SCHEDULE_FILE)

    try:
        restart_delay = int(os.getenv("SENTIMENT_MCP_RESTART_DELAY_SEC") or 15)
    except Exception:
        restart_delay = 15
    restart_delay = max(1, restart_delay)

    while True:
        try:
            restart_needed = await run_sentiment_service_cycle(
                settings,
                symbol=symbol,
                force=force,
                connection_factory=connection_factory,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            restart_needed = True
            logger.error(
                "Sentiment service cycle crashed: %s",
                exc,
                exc_info=True,
            )

        if not restart_needed:
            logger.info("Sentiment cycle completed; exiting main loop")
            break

        logger.warning(
            "Sentiment MCP app exited unexpectedly; restarting in %s seconds",
            restart_delay,
        )
        await asyncio.sleep(restart_delay)


__all__ = ["async_main"]
