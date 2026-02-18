import sys
from pathlib import Path


def pytest_configure() -> None:
    # Allow broker tests to import shared code like `apps.common.*`.
    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root))
    # Ensure `tradeexec` is importable even when running pytest from repo root.
    sys.path.insert(0, str(repo_root / "apps" / "broker"))
