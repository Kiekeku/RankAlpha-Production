import logging

from tradeexec.utils.logging_setup import setup_logging


def test_setup_logging_respects_env_level(monkeypatch):
    root = logging.getLogger()
    # Reset handlers to allow setup to configure
    existing = list(root.handlers)
    for h in existing:
        root.removeHandler(h)
    try:
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        setup_logging(simple=True)
        assert root.level == logging.DEBUG
    finally:
        # Clean up handlers for other tests
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in existing:
            root.addHandler(h)


def test_setup_logging_idempotent():
    root = logging.getLogger()
    # Install a dummy handler and level to simulate pre-configured logging
    handler = logging.NullHandler()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)

    setup_logging(level="ERROR")
    # Should not change existing configuration when handlers already present
    assert root.level == logging.WARNING
    assert handler in root.handlers
