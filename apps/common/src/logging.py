"""Logging utilities.

Ensures both module-level and root loggers have handlers so that
third-party libraries (e.g., OpenAI SDK, httpx) actually emit logs
when their log level is raised. This avoids the common pitfall where
the root logger has no handlers and debug logs are silently dropped.
"""

import atexit
import logging
import os
from logging import Logger
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from queue import Queue
from threading import Lock

_MANAGED_HANDLER_ATTR = "_rankalpha_managed_handler"
_ASYNC_QUEUE_HANDLER_ATTR = "_rankalpha_async_queue_handler"
_ASYNC_LOCK = Lock()
_ASYNC_LISTENER: QueueListener | None = None
_ASYNC_ATEXIT_REGISTERED = False


def _build_stream_handler() -> logging.StreamHandler:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    setattr(handler, _MANAGED_HANDLER_ATTR, True)
    return handler


def _is_async_logging_enabled(root: logging.Logger | None = None) -> bool:
    target = root or logging.getLogger()
    return any(getattr(h, _ASYNC_QUEUE_HANDLER_ATTR, False) for h in target.handlers)


def _shutdown_async_listener() -> None:
    global _ASYNC_LISTENER
    with _ASYNC_LOCK:
        if _ASYNC_LISTENER is None:
            return
        try:
            _ASYNC_LISTENER.stop()
        finally:
            _ASYNC_LISTENER = None


def shutdown_async_logging() -> None:
    """Stop the queue listener, if async logging is enabled."""
    _shutdown_async_listener()


def _promote_managed_loggers_to_root() -> None:
    manager = logging.root.manager
    for candidate in manager.loggerDict.values():
        if not isinstance(candidate, logging.Logger):
            continue
        removed = False
        for handler in list(candidate.handlers):
            if getattr(handler, _MANAGED_HANDLER_ATTR, False):
                candidate.removeHandler(handler)
                removed = True
        if removed and not candidate.handlers:
            candidate.propagate = True


def _enable_async_root_logging(queue_size: int = 0) -> None:
    global _ASYNC_LISTENER, _ASYNC_ATEXIT_REGISTERED
    root = logging.getLogger()
    with _ASYNC_LOCK:
        if _is_async_logging_enabled(root):
            return

        if not root.handlers:
            root.addHandler(_build_stream_handler())

        downstream_handlers = list(root.handlers)
        log_queue: Queue[logging.LogRecord] = Queue(maxsize=max(int(queue_size), 0))
        queue_handler = QueueHandler(log_queue)
        setattr(queue_handler, _ASYNC_QUEUE_HANDLER_ATTR, True)
        listener = QueueListener(log_queue, *downstream_handlers, respect_handler_level=True)
        listener.start()

        for handler in downstream_handlers:
            root.removeHandler(handler)
        root.addHandler(queue_handler)
        _ASYNC_LISTENER = listener
        _promote_managed_loggers_to_root()

        if not _ASYNC_ATEXIT_REGISTERED:
            atexit.register(_shutdown_async_listener)
            _ASYNC_ATEXIT_REGISTERED = True


def _ensure_root_handler() -> None:
    """Attach a basic StreamHandler to the root logger if missing.

    This is intentionally minimal and idempotent. It does not change
    the root level (callers can still adjust levels), it only ensures
    there is at least one handler so that logs from other libraries
    propagate and are visible.
    """
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(_build_stream_handler())


def get_logger(name: str, level: int = logging.INFO) -> Logger:
    """Create or retrieve a configured logger.

    Also ensures the root logger has a handler so that other library
    loggers (like 'openai' or 'httpx') can propagate and be seen when
    debug mode is enabled by the application.
    """
    _ensure_root_handler()
    logger = logging.getLogger(name)
    if _is_async_logging_enabled():
        for handler in list(logger.handlers):
            if getattr(handler, _MANAGED_HANDLER_ATTR, False):
                logger.removeHandler(handler)
        if not logger.handlers:
            logger.propagate = True
        if logger.level == logging.NOTSET:
            logger.setLevel(level)
        return logger

    if not logger.handlers:
        logger.addHandler(_build_stream_handler())
        logger.setLevel(level)
        # Prevent duplicate emission via root when root also has handlers
        logger.propagate = False
    return logger


def setup_logging(
    level: str | int | None = None,
    *,
    use_async: bool | None = None,
    async_queue_maxsize: int | None = None,
) -> None:
    """Configure the root logger once, with optional level override.

    If ``level`` is None, reads LOG_LEVEL from the environment (default INFO).
    Safe to call multiple times.
    """
    _ensure_root_handler()
    root = logging.getLogger()
    if isinstance(level, int):
        root.setLevel(level)
    elif isinstance(level, str):
        level_name = level.strip().upper()
        root.setLevel(getattr(logging, level_name, logging.INFO))
    else:
        level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
        root.setLevel(getattr(logging, level_name, logging.INFO))
    if use_async is None:
        use_async = (os.getenv("LOG_ASYNC") or "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if not use_async:
        return

    queue_size = async_queue_maxsize
    if queue_size is None:
        raw = (os.getenv("LOG_ASYNC_QUEUE_MAXSIZE") or "0").strip()
        try:
            queue_size = int(raw)
        except ValueError:
            queue_size = 0
    _enable_async_root_logging(max(int(queue_size), 0))


def add_rotating_file_handler(
    *,
    path: str,
    level: int = logging.DEBUG,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Attach a RotatingFileHandler to the root logger if not already attached.

    Safe to call multiple times; it will de-duplicate by filename.
    """
    _ensure_root_handler()
    root = logging.getLogger()
    # De-duplicate by absolute filename
    try:
        from os.path import abspath

        abs_target = abspath(path)
    except Exception:
        abs_target = path
    for h in root.handlers:
        try:
            if (
                isinstance(h, RotatingFileHandler)
                and getattr(h, "baseFilename", None) == abs_target
            ):
                # Already attached
                return
        except Exception:
            continue
    fh = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    root.addHandler(fh)
