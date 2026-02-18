from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException


def parse_optional_iso_date(value: str | None, *, field_name: str) -> date | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        # Keep compatibility with legacy router behavior:
        # - Accept non-zero-padded month/day values (e.g., 2025-1-1)
        # - Treat empty string as "not provided" (handled above)
        return datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} format. Use YYYY-MM-DD",
        ) from exc


def parse_iso_date_range(
    date_from: str | None, date_to: str | None
) -> tuple[date | None, date | None]:
    parsed_from = parse_optional_iso_date(date_from, field_name="date_from")
    parsed_to = parse_optional_iso_date(date_to, field_name="date_to")
    if parsed_from and parsed_to and parsed_from > parsed_to:
        raise HTTPException(status_code=400, detail="date_from must be <= date_to")
    return parsed_from, parsed_to
