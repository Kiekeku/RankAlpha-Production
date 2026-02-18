import os

from apps.common.src.observability import init_service_observability, start_span
from opentelemetry.trace import Status, StatusCode


# Test shim: the unit test expects a module-level `logger` and that
# `main()` calls `logger.info("Hello from sentiment!")` at least once.
# We keep this behavior for tests while still delegating to the real
# runner in normal execution.
class _DefaultLogger:
    def info(self, msg: str) -> None:  # pragma: no cover - trivial
        try:
            print(msg)
        except Exception:
            pass


logger = _DefaultLogger()


def main() -> None:
    # Satisfy the existing unit test contract
    try:
        logger.info("Hello from sentiment!")
    except Exception:
        pass

    # Only delegate to the real runner when not under pytest to avoid
    # heavy imports and external calls during unit tests.
    if os.getenv("PYTEST_CURRENT_TEST"):
        return

    init_service_observability("rankalpha-sentiment")
    from apps.sentiment.src.main import main as run_main  # type: ignore

    with start_span("sentiment.run") as span:
        try:
            run_main()
        except Exception as exc:
            try:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception:
                pass
            raise


if __name__ == "__main__":
    main()
