from __future__ import annotations

import pandas as pd
import pytest

from apps.ingestion.src.repair_parquets import repair_one


def test_repair_one_upgrades_close_only_parquet(tmp_path):
    pytest.importorskip("pyarrow", reason="pyarrow required for parquet IO")
    path = tmp_path / "AAPL.parquet"
    df = pd.DataFrame(
        {"Close": [10.0, 11.0], "Date": ["2025-01-01", "2025-01-02"]},
    )
    df.to_parquet(path, engine="pyarrow")

    assert repair_one(str(path)) is True

    repaired = pd.read_parquet(path, engine="pyarrow")
    assert "Adj Close" in repaired.columns
    assert repaired["Adj Close"].tolist() == repaired["Close"].tolist()

