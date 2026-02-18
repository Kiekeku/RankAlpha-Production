import pandas as pd


def test_asof_selection_by_coverage(monkeypatch):
    import apps.scorer.src.main as scorer_main

    # Build fake coverage table: latest date below threshold, previous date above
    latest_date = pd.to_datetime("2025-01-31")
    prev_date = pd.to_datetime("2025-01-30")
    cov_df = pd.DataFrame(
        {
            "date_key": [20250131, 20250130],
            "full_date": [latest_date, prev_date],
            "have_px": [40, 80],  # eligible will be 100 via q_elig
        }
    )
    elig_df = pd.DataFrame({"n": [100]})

    def fake_read_sql_query(sql, engine, parse_dates=None):
        sql_s = str(sql) if not isinstance(sql, bytes) else sql.decode()
        if "COUNT(1) AS n" in sql_s:
            return elig_df
        if "FROM rankalpha.fact_security_price" in sql_s:
            # Ensure parse_dates is respected
            df = cov_df.copy()
            if parse_dates and "full_date" in parse_dates:
                df["full_date"] = pd.to_datetime(df["full_date"])  # idempotent
            return df
        raise AssertionError(f"Unexpected SQL in test: {sql}")

    monkeypatch.setattr(scorer_main.pd, "read_sql_query", fake_read_sql_query)

    class S:
        scoring_asof_min_coverage = 0.5

    class L:
        def info(self, *a, **k):
            pass
        def warning(self, *a, **k):
            pass

    asof_dt, asof_key, cov, have_px, n_elig = scorer_main._select_asof_date_with_coverage(
        engine=object(), settings=S(), logger=L(), active_symbols=None
    )
    # Should pick the previous date (coverage 0.8) not the latest (0.4)
    assert asof_key == 20250130
    assert str(asof_dt.date()) == "2025-01-30"
    assert abs(cov - 0.8) < 1e-9 and have_px == 80 and n_elig == 100

