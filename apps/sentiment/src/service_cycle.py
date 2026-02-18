from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime, timedelta

from mcp_agent.app import MCPApp

from apps.common.src.logging import get_logger
from apps.sentiment.src.settings import Settings as Settings

try:
    from . import paths as sentiment_paths
    from .analysis_workflow import ai_analysis
    from .metrics import run_queue_metrics_poller, update_queue_depth_metrics
except ImportError:  # pragma: no cover - direct execution fallback
    import paths as sentiment_paths
    from analysis_workflow import ai_analysis

    try:
        from metrics import run_queue_metrics_poller, update_queue_depth_metrics  # type: ignore
    except Exception:
        run_queue_metrics_poller = None  # type: ignore
        update_queue_depth_metrics = None  # type: ignore

try:
    from .consensus_runner import run_consensus_batch
    from .on_demand import handle_on_demand
    from .schedule_manager import clean_schedule
    from .scheduler import run_scheduled_analyses
except ImportError:  # pragma: no cover - direct execution fallback
    from consensus_runner import run_consensus_batch
    from on_demand import handle_on_demand
    from schedule_manager import clean_schedule
    from scheduler import run_scheduled_analyses


_RECENT_ANALYSIS_BY_STOCK: dict[int, int] = {}


def _today_key() -> int:
    return int(datetime.now().strftime("%Y%m%d"))


def _already_completed_today(stock_key: int) -> bool:
    try:
        return _RECENT_ANALYSIS_BY_STOCK.get(stock_key) == _today_key()
    except Exception:
        return False


def _mark_completed_today(stock_key: int) -> None:
    try:
        _RECENT_ANALYSIS_BY_STOCK[stock_key] = _today_key()
    except Exception:
        pass


async def _run_sentiment_service_cycle(
    settings: Settings,
    *,
    symbol: str | None,
    force: bool,
    connection_factory,
) -> bool:
    """Run a single MCP-backed sentiment service cycle.

    Returns
    -------
    bool
        False when the cycle intentionally completed (e.g., on-demand symbol or
        consensus-only run) and the process should exit. True when the MCP app
        exited unexpectedly and the caller should restart the cycle.
    """
    logger = get_logger(__name__)
    app = MCPApp(name="unified_stock_analyzer", human_input_callback=None)
    queue_metrics_task = None

    try:
        try:
            logger.info(f"CWD: {os.getcwd()}")
            cfg_path = os.path.join(os.getcwd(), "mcp_agent.config.yaml")
            logger.info(f"Config exists at CWD? {os.path.exists(cfg_path)}")
        except Exception:
            pass

        async with app.run() as analyzer_app:
            try:
                interval_raw = os.getenv("SENTIMENT_QUEUE_METRICS_INTERVAL_SECONDS") or os.getenv(
                    "SENTIMENT_QUEUE_METRICS_INTERVAL_SEC"
                )
                interval = int(interval_raw) if interval_raw else 300
            except Exception:
                interval = 300
            if run_queue_metrics_poller is not None and interval > 0:
                try:
                    if update_queue_depth_metrics is not None:
                        update_queue_depth_metrics(connection_factory)
                    queue_metrics_task = asyncio.create_task(
                        run_queue_metrics_poller(
                            connection_factory=connection_factory,
                            interval_seconds=interval,
                        )
                    )
                except Exception:
                    queue_metrics_task = None

            # Configure MCP servers (filesystem roots, EDGAR UA, Serper key)
            try:
                cfg = analyzer_app.context.config
                if getattr(cfg, "mcp", None) and getattr(cfg.mcp, "servers", None):
                    servers = cfg.mcp.servers
                    # Ensure filesystem has OUTPUT_DIR and CWD roots
                    try:
                        fs = (
                            servers.get("filesystem")
                            if isinstance(servers, dict)
                            else getattr(servers, "filesystem", None)
                        )
                        allowed_roots = [sentiment_paths.OUTPUT_DIR, os.getcwd()]
                        valid_roots: list[str] = []
                        for path_candidate in allowed_roots:
                            try:
                                ap = os.path.abspath(path_candidate)
                                if os.path.isdir(ap):
                                    valid_roots.append(ap)
                            except Exception:
                                continue
                        if fs is None:
                            servers["filesystem"] = {  # type: ignore[index]
                                "command": "npx",
                                "args": [
                                    "-y",
                                    "@modelcontextprotocol/server-filesystem",
                                    *valid_roots,
                                ],
                            }
                        else:
                            try:
                                if isinstance(fs, dict):
                                    args = list(fs.get("args") or [])
                                else:
                                    args = list(getattr(fs, "args", []) or [])
                                for root in valid_roots:
                                    if root not in args:
                                        args.append(root)
                                if isinstance(fs, dict):
                                    fs["args"] = args
                                else:
                                    setattr(fs, "args", args)
                            except Exception:
                                pass
                    except Exception as exc:
                        logger.warning(f"Filesystem server configuration failed: {exc}")

                    # EDGAR UA bridging
                    try:
                        ua = str(
                            settings.sec_edgar_user_agent or os.getenv("SEC_EDGAR_USER_AGENT") or ""
                        ).strip()
                        if "edgar" in servers:
                            if not ua:
                                servers.pop("edgar", None)
                                logger.warning("EDGAR MCP disabled: SEC_EDGAR_USER_AGENT not set.")
                            else:
                                srv = servers.get("edgar")
                                if srv is not None:
                                    if isinstance(srv, dict):
                                        env_map = srv.get("env") or {}
                                        env_map["SEC_EDGAR_USER_AGENT"] = ua
                                        srv["env"] = env_map
                                    else:
                                        env_map = getattr(srv, "env", None) or {}
                                        env_map["SEC_EDGAR_USER_AGENT"] = ua
                                        setattr(srv, "env", env_map)
                                    logger.info(
                                        "EDGAR MCP: injected SEC_EDGAR_USER_AGENT into server env"
                                    )
                    except Exception as exc:
                        logger.warning(f"Could not configure EDGAR MCP: {exc}")

                    # Serper API key bridging
                    try:
                        if "serper" in servers:
                            api_key = str(
                                getattr(settings, "serper_api_key", None)
                                or os.getenv("SERPER_API_KEY")
                                or ""
                            ).strip()
                            if not api_key:
                                logger.warning(
                                    "Serper MCP configured but SERPER_API_KEY not set; search may fail"
                                )
                            else:
                                srv = servers["serper"]
                                if isinstance(srv, dict):
                                    env_map = srv.get("env") or {}
                                    env_map["SERPER_API_KEY"] = api_key
                                    srv["env"] = env_map
                                else:
                                    env_map = getattr(srv, "env", None) or {}
                                    env_map["SERPER_API_KEY"] = api_key
                                    setattr(srv, "env", env_map)
                                logger.info("Serper MCP: injected SERPER_API_KEY into server env")
                                try:
                                    logger.info(
                                        "Serper MCP: key present=%s length=%d",
                                        "yes" if len(api_key) > 0 else "no",
                                        len(api_key),
                                    )
                                except Exception:
                                    pass
                    except Exception as exc:
                        logger.warning(f"Could not configure Serper MCP: {exc}")

                    # Startup banner for search selection
                    try:
                        has_serper = "serper" in servers
                        has_gsearch = "g-search" in servers
                        chosen = "serper" if has_serper else ("g-search" if has_gsearch else None)
                        logger.info(
                            "Startup: Search MCP discovery → serper=%s, g-search=%s; selected=%s",
                            "yes" if has_serper else "no",
                            "yes" if has_gsearch else "no",
                            chosen or "(none)",
                        )
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning(f"Post-initialize MCP configuration failed: {exc}")

            # Optional: run a one-off consensus batch and optionally exit
            async def _run_consensus_once() -> None:
                try:
                    await run_consensus_batch(
                        analyzer_app,
                        ai_analysis,
                        settings=settings,
                        already_completed_today=_already_completed_today,
                        mark_completed_today=_mark_completed_today,
                        schedule_file=sentiment_paths.SCHEDULE_FILE,
                        connection_factory=connection_factory,
                    )
                except Exception as exc:
                    logger.error(f"Consensus batch failed: {exc}")

            if bool(getattr(settings, "sentiment_use_consensus", False)) and bool(
                getattr(settings, "sentiment_consensus_batch_only", False)
            ):
                logger.info("Consensus batch-only mode active: running once and exiting")
                await _run_consensus_once()
                return False

            if symbol:
                await handle_on_demand(
                    analyzer_app,
                    settings=settings,
                    connection_factory=connection_factory,
                    symbol=symbol,
                    force=force,
                    schedule_file=sentiment_paths.SCHEDULE_FILE,
                    ai_analysis=ai_analysis,
                    already_completed_today=_already_completed_today,
                    mark_completed_today=_mark_completed_today,
                )
                return False

            if (
                bool(getattr(settings, "sentiment_use_consensus", False))
                and int(getattr(settings, "sentiment_consensus_limit", 0) or 0) > 0
            ):
                logger.info("Running consensus batch before scheduled checks")
                await _run_consensus_once()

            try:
                raw_sleep = getattr(settings, "sentiment_loop_sleep_seconds", None)
                if raw_sleep is None:
                    env_override = os.getenv("SENTIMENT_LOOP_SLEEP_SEC") or os.getenv(
                        "SENTIMENT_LOOP_SLEEP_SECONDS"
                    )
                    raw_sleep = int(env_override) if env_override else None
                loop_sleep_seconds = int(raw_sleep) if raw_sleep is not None else 86400
            except Exception:
                loop_sleep_seconds = 86400
            loop_sleep_seconds = max(1, loop_sleep_seconds)
            logger.info(f"Scheduled loop sleep interval: {loop_sleep_seconds} seconds")

            await run_scheduled_analyses(
                analyzer_app,
                settings=settings,
                connection_factory=connection_factory,
                ai_analysis=ai_analysis,
                schedule_file=sentiment_paths.SCHEDULE_FILE,
                already_completed_today=_already_completed_today,
                mark_completed_today=_mark_completed_today,
            )

            while True:
                try:
                    next_run = datetime.now() + timedelta(seconds=loop_sleep_seconds)
                    logger.info(
                        "Idle: sleeping for %ss (next check at %s)",
                        loop_sleep_seconds,
                        next_run.isoformat(timespec="seconds"),
                    )
                except Exception:
                    logger.info("Idle: sleeping for %ss", loop_sleep_seconds)
                await asyncio.sleep(loop_sleep_seconds)

                logger.info(f"Running daily check at {datetime.now()}")
                try:
                    if (
                        bool(getattr(settings, "sentiment_use_consensus", False))
                        and int(getattr(settings, "sentiment_consensus_limit", 0) or 0) > 0
                    ):
                        logger.info("Running daily consensus batch")
                        await _run_consensus_once()
                    clean_schedule(sentiment_paths.SCHEDULE_FILE)
                    await run_scheduled_analyses(
                        analyzer_app,
                        settings=settings,
                        connection_factory=connection_factory,
                        ai_analysis=ai_analysis,
                        schedule_file=sentiment_paths.SCHEDULE_FILE,
                        already_completed_today=_already_completed_today,
                        mark_completed_today=_mark_completed_today,
                    )
                except Exception as exc:
                    logger.error(f"Error in daily check: {exc}")

        logger.info("MCP app run loop exited unexpectedly; signalling restart")
        return True
    finally:
        if queue_metrics_task is not None:
            with contextlib.suppress(Exception):
                queue_metrics_task.cancel()
            with contextlib.suppress(Exception):
                await queue_metrics_task
        shutdown = getattr(app, "shutdown", None)
        if callable(shutdown):
            with contextlib.suppress(Exception):
                result = shutdown()
                if asyncio.iscoroutine(result):
                    await result


async def run_sentiment_service_cycle(
    settings: Settings,
    *,
    symbol: str | None,
    force: bool,
    connection_factory,
) -> bool:
    return await _run_sentiment_service_cycle(
        settings,
        symbol=symbol,
        force=force,
        connection_factory=connection_factory,
    )


__all__ = ["run_sentiment_service_cycle", "_run_sentiment_service_cycle"]
