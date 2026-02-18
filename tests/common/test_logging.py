import logging
from logging.handlers import QueueHandler

from apps.common.src.logging import get_logger, setup_logging, shutdown_async_logging


def test_get_logger_reuse():
    logger1 = get_logger("rankalpha-test")
    assert isinstance(logger1, logging.Logger)
    logger2 = get_logger("rankalpha-test")
    assert logger1 is logger2


def test_setup_logging_int_level_honors_async_queue():
    root = logging.getLogger()
    shutdown_async_logging()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    setup_logging(logging.INFO, use_async=True, async_queue_maxsize=10)

    assert any(isinstance(handler, QueueHandler) for handler in root.handlers)

    shutdown_async_logging()
    for handler in list(root.handlers):
        root.removeHandler(handler)
