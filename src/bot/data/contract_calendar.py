# src/bot/data/contract_calendar.py
"""CME quarterly contract calendar for NQ/MNQ.

H=Mar, M=Jun, U=Sep, Z=Dec. Roll on third Friday of contract month.
Spec: 01-data-pipeline.md §3.2.
"""
from __future__ import annotations

from datetime import date
from typing import Final

CONTRACT_MONTHS: Final[dict[str, int]] = {"H": 3, "M": 6, "U": 9, "Z": 12}
_MONTH_TO_CODE: Final[dict[int, str]] = {v: k for k, v in CONTRACT_MONTHS.items()}


def third_friday(year: int, month: int) -> date:
    """Return the third Friday of the given month.

    Algorithm: Find the first Friday, add 14 days. Friday is weekday() == 4.
    """
    first_of_month = date(year, month, 1)
    first_friday_offset = (4 - first_of_month.weekday()) % 7
    return date(year, month, 1 + first_friday_offset + 14)


def roll_calendar(start_year: int, end_year: int) -> list[date]:
    """All quarterly roll dates between [start_year, end_year], inclusive."""
    dates: list[date] = []
    for year in range(start_year, end_year + 1):
        for month in (3, 6, 9, 12):
            dates.append(third_friday(year, month))
    return dates


def parse_contract_code(code: str) -> tuple[int, int]:
    """Parse a FirstRateData contract suffix like "2023Z" → (2023, 12).

    Raises ValueError on malformed input.
    """
    if len(code) != 5:
        raise ValueError(f"Contract code must be 5 chars (YYYY+M), got {code!r}")
    year_str, month_code = code[:4], code[4]
    try:
        year = int(year_str)
    except ValueError as e:
        raise ValueError(f"Year part of {code!r} not an integer") from e
    if month_code not in CONTRACT_MONTHS:
        raise ValueError(f"Month code {month_code!r} not in {sorted(CONTRACT_MONTHS)}")
    return (year, CONTRACT_MONTHS[month_code])


def format_contract_code(year: int, month: int) -> str:
    """Inverse of parse_contract_code: (2023, 12) → "2023Z"."""
    if month not in _MONTH_TO_CODE:
        raise ValueError(f"Month {month} not a quarterly contract month")
    return f"{year}{_MONTH_TO_CODE[month]}"
