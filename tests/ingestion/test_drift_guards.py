from __future__ import annotations

from datetime import date

from apps.ingestion.src.ingestion_runner import evaluate_symbol_coverage


def test_evaluate_symbol_coverage_accounts_for_expected_missing():
    symbols = ["AAPL", "MSFT", "TSLA", "GOOG"]
    last_dates = {"AAPL": date(2026, 2, 6), "MSFT": date(2026, 2, 6)}
    expected_missing = {"TSLA"}

    total, with_price, expected_count, covered, coverage_ratio, drift_ratio, uncovered = (
        evaluate_symbol_coverage(symbols, last_dates, expected_missing)
    )

    assert total == 4
    assert with_price == 2
    assert expected_count == 1
    assert covered == 3
    assert coverage_ratio == 0.75
    assert drift_ratio == 0.25
    assert uncovered == ["GOOG"]


def test_evaluate_symbol_coverage_is_case_insensitive():
    symbols = ["aapl", "MsFt"]
    last_dates = {"AAPL": date(2026, 2, 6)}
    expected_missing = {"msft"}

    total, with_price, expected_count, covered, coverage_ratio, drift_ratio, uncovered = (
        evaluate_symbol_coverage(symbols, last_dates, expected_missing)
    )

    assert total == 2
    assert with_price == 1
    assert expected_count == 1
    assert covered == 2
    assert coverage_ratio == 1.0
    assert drift_ratio == 0.0
    assert uncovered == []
