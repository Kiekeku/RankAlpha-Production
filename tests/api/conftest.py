import pytest

pytest.importorskip("starlette")

from starlette.background import BackgroundTasks


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _disable_background_tasks(monkeypatch):
    def _noop_add_task(self, func, *args, **kwargs):
        return None

    monkeypatch.setattr(BackgroundTasks, "add_task", _noop_add_task)
