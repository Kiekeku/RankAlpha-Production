from __future__ import annotations

from datetime import date

import pytest
from apps.api.src.utils.date_range import parse_iso_date_range, parse_optional_iso_date
from fastapi import HTTPException


def test_parse_optional_iso_date_accepts_none():
    assert parse_optional_iso_date(None, field_name="date_from") is None


@pytest.mark.parametrize("value", ["", "   "])
def test_parse_optional_iso_date_treats_blank_as_missing(value: str):
    assert parse_optional_iso_date(value, field_name="date_from") is None


def test_parse_iso_date_range_parses_valid_values():
    date_from, date_to = parse_iso_date_range("2025-01-01", "2025-01-31")
    assert date_from == date(2025, 1, 1)
    assert date_to == date(2025, 1, 31)


def test_parse_iso_date_range_accepts_non_zero_padded_dates():
    date_from, date_to = parse_iso_date_range("2025-1-1", "2025-1-31")
    assert date_from == date(2025, 1, 1)
    assert date_to == date(2025, 1, 31)


@pytest.mark.parametrize(
    ("field_name", "value", "expected_detail"),
    [
        ("date_from", "2025/01/01", "Invalid date_from format. Use YYYY-MM-DD"),
        ("date_to", "2025-99-01", "Invalid date_to format. Use YYYY-MM-DD"),
    ],
)
def test_parse_optional_iso_date_rejects_invalid_values(
    field_name: str, value: str, expected_detail: str
):
    with pytest.raises(HTTPException) as exc_info:
        parse_optional_iso_date(value, field_name=field_name)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == expected_detail


def test_parse_iso_date_range_rejects_inverted_range():
    with pytest.raises(HTTPException) as exc_info:
        parse_iso_date_range("2025-02-01", "2025-01-31")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "date_from must be <= date_to"
