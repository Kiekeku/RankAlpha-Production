import asyncio
from datetime import date

import pytest

fastapi = pytest.importorskip("fastapi")
from httpx import ASGITransport, AsyncClient  # type: ignore  # noqa: E402

from apps.api.src.main import app
from apps.api.src.routers.hy_stress import DEFAULT_BENCHMARK
from apps.api.src.routers import hy_stress

class DummyRow:
    def __init__(self, as_of_date, benchmark_name, raw, ma, z):
        self.as_of_date = as_of_date
        self.benchmark_name = benchmark_name
        self.hy_stress_raw = raw
        self.hy_stress_ma = ma
        self.hy_stress_z = z


def test_hy_stress_defaults_to_ccchys(monkeypatch):
    captured = []
    rows = [
        DummyRow(date(2025, 1, 2), DEFAULT_BENCHMARK, 900.0, 905.0, -1.2),
        DummyRow(date(2025, 1, 3), DEFAULT_BENCHMARK, 910.0, 906.0, 1.6),
    ]
    latest_row = rows[-1]

    class FakeResult:
        def __init__(self, kind):
            self.kind = kind

        def scalars(self):
            return self

        def first(self):
            return latest_row

        def all(self):
            return rows

        def scalar_one(self):
            return len(rows)

    class FakeSession:
        def execute(self, q):
            captured.append(q)
            text = str(q).lower()
            if "count" in text:
                return FakeResult("count")
            return FakeResult("rows")

    def override_get_db():
        yield FakeSession()

    app.dependency_overrides[hy_stress.get_db] = override_get_db
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/hy-stress/latest")
            resp2 = await client.get("/api/v1/hy-stress/series")
            return resp, resp2

    resp, resp2 = asyncio.run(_run())
    assert resp.status_code == 200
    body = resp.json()
    assert body["benchmark_name"] == DEFAULT_BENCHMARK
    assert body["hy_stress_raw"] == latest_row.hy_stress_raw
    assert body["label"] == "risk_off"

    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["total_count"] == len(rows)
    assert all(item["benchmark_name"] == DEFAULT_BENCHMARK for item in body2["items"])
    assert body2["items"][0]["label"] == "risk_on"  # z < -1
    assert body2["items"][-1]["label"] == "risk_off"  # z > 1.5

    # Ensure queries carried a benchmark filter clause
    assert any("benchmark_name = :benchmark_name_1" in str(q) for q in captured)

    app.dependency_overrides.pop(hy_stress.get_db, None)
