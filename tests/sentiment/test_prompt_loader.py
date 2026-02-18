from __future__ import annotations

import pytest

from apps.sentiment.src.llm.prompt_loader import load_prompt


def test_load_prompt_reads_file_and_applies_replacements():
    text = load_prompt(
        "report_writer_lean",
        replacements={
            "COMPANY_NAME": "Acme Corp",
            "TICKER": "ACME",
            "ANCHOR_PRICE": "123.45",
            "ANCHOR_TIMESTAMP_UTC": "2025-01-02T00:00:00Z",
            "ANCHOR_SOURCE": "unit_test",
            "OUTPUT_PATH": "/tmp/out.json",
        },
    )
    assert "Acme Corp" in text
    assert "ACME" in text
    assert "123.45" in text
    assert "2025-01-02T00:00:00Z" in text
    assert "unit_test" in text
    assert "/tmp/out.json" in text
    assert "{{COMPANY_NAME}}" not in text


def test_load_prompt_applies_new_analyst_target_tokens():
    text = load_prompt(
        "search_finder_lean",
        replacements={
            "COMPANY_NAME": "Acme Corp",
            "TICKER": "ACME",
            "ANCHOR_PRICE": "123.45",
            "ANCHOR_TIMESTAMP_UTC": "2025-01-02T00:00:00Z",
            "ANCHOR_SOURCE": "unit_test",
            "ANALYST_TARGETS_ORGANIC": "[]",
            "ANALYST_TARGETS_SUMMARY_JSON": '{"count":5,"low_usd":100,"median_usd":120,"high_usd":140,"mean_usd":121}',
            "ANALYST_TARGET_COUNT": "5",
            "ANALYST_TARGET_LOW_USD": "100",
            "ANALYST_TARGET_MEDIAN_USD": "120",
            "ANALYST_TARGET_HIGH_USD": "140",
        },
    )
    assert "{{ANALYST_TARGETS_SUMMARY_JSON}}" not in text
    assert "{{ANALYST_TARGET_LOW_USD}}" not in text
    assert "{{ANALYST_TARGET_MEDIAN_USD}}" not in text
    assert "{{ANALYST_TARGET_HIGH_USD}}" not in text
    assert "{{ANALYST_TARGET_COUNT}}" not in text
    assert "analyst_targets_summary_json" in text
    assert "analyst_target_median_usd: 120" in text


def test_load_prompt_raises_for_missing_file():
    with pytest.raises(FileNotFoundError):
        load_prompt("does_not_exist_12345")
