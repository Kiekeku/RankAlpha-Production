import os
from datetime import datetime

import pandas as pd
import numpy as np
import types
import pytest

pytest.importorskip("pyarrow", reason="pyarrow required for parquet backfill test")


def test_backfill_dry_run_filters_universe_and_counts(tmp_path, monkeypatch, capsys):
    # Import module under test
    import apps.scorer.src.tools.backfill_momentum as bm
    from apps.scorer.src.services.prices import PriceReader
    from apps.scorer.src.services.momentum import MomentumCalculator

    # Create two eligible symbols with simple increasing series
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    last_dt = idx[-1]
    df = pd.DataFrame({"Adj Close": 100.0 + np.arange(len(idx))}, index=idx)
    symA = "AAAA"; symB = "BBBB"
    pA = tmp_path / f"{symA}.parquet"
    pB = tmp_path / f"{symB}.parquet"
    df.to_parquet(pA, engine="pyarrow")
    df.to_parquet(pB, engine="pyarrow")

    # Stub: candidate as-of dates (single date matching parquet last date)
    asof_key = int(last_dt.strftime("%Y%m%d"))
    asof_df = pd.DataFrame({
        "date_key": [asof_key],
        "full_date": [last_dt.normalize()],
        "have_px": [2],
        "coverage": [1.0],
    })
    monkeypatch.setattr(bm, "_candidate_asof_dates", lambda engine, min_cov, limit: asof_df)

    # Stub: eligible symbols
    monkeypatch.setattr(bm, "_eligible_symbols", lambda engine: {symA, symB})

    # Stub: sector map query
    def _fake_read_sql_query(sql, engine, parse_dates=None):
        if isinstance(sql, str) and "FROM rankalpha.dim_stock" in sql:
            return pd.DataFrame({"symbol": [symA, symB], "sector": ["Tech", "Tech"]})
        raise AssertionError("Unexpected query in test: %r" % (sql,))
    monkeypatch.setattr(bm.pd, "read_sql_query", _fake_read_sql_query)

    # Fake ScoreRepository to avoid real DB work
    class FakeConn:
        def cursor(self):
            class C:  # pragma: no cover - trivial stub
                def execute(self, *a, **k):
                    pass
                def fetchall(self):
                    return []
            return C()
        def close(self):
            pass

    class FakeRepo:
        def __init__(self, dsn, logger=None):
            self.engine = object()
        def connect(self):
            return FakeConn()
        def ensure_score_types(self, cursor):
            pass
        def fetch_score_type_keys(self, cursor):
            return {
                "momentum raw score": 1,
                "momentum residual score": 2,
                "momentum score": 3,
            }
        def fetch_stock_key(self, cursor, ticker):
            return 101 if ticker.upper() == symA else 102
        def insert_score_if_absent(self, *a, **k):  # pragma: no cover - not used in dry-run
            pass

    class FakeSettings:
        def __init__(self):
            # Minimal DB env (unused in test due to fakes)
            self.db_username = "u"; self.password = "p"; self.host = "h"; self.port = 5432; self.database_name = "d"
            # Momentum knobs
            self.scoring_momentum_window_weights = "200=1.0,90=1.0,50=1.0,30=1.0"
            self.scoring_momentum_min_valid_frac = 0.8
            self.scoring_momentum_tstat_cap = 3.0
            self.scoring_momentum_min_group_size = 5
            self.scoring_momentum_composite_mode = "blend"
            self.scoring_momentum_residual_weight = 0.7
            self.scoring_momentum_raw_weight = 0.3
            self.scoring_asof_min_coverage = 0.5

    monkeypatch.setattr(bm, "_import_modules", lambda: (PriceReader, MomentumCalculator, FakeRepo, FakeSettings))

    # Execute backfill in dry-run mode
    bm.backfill(days=1, min_cov=0.5, prices_dir=str(tmp_path), dry_run=True)

    out = capsys.readouterr().out
    assert "Backfilling as-of" in out
    # Expect two symbols counted for each of raw/residual/composite in dry-run
    assert "Inserted 2 raw, 2 residual, 2 composite" in out
