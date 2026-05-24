# tests/test_data_contract_calendar.py
"""contract_calendar: roll dates for NQ/MNQ. Spec 01 §3.2."""
from __future__ import annotations

from datetime import date

import pytest


def test_third_friday_known_dates() -> None:
    from bot.data.contract_calendar import third_friday
    # Known historical roll dates
    assert third_friday(2023, 12) == date(2023, 12, 15)
    assert third_friday(2024, 3)  == date(2024, 3, 15)
    assert third_friday(2024, 6)  == date(2024, 6, 21)
    assert third_friday(2024, 9)  == date(2024, 9, 20)
    assert third_friday(2026, 3)  == date(2026, 3, 20)


def test_third_friday_when_month_starts_on_friday() -> None:
    """November 2024 starts on a Friday; third Friday is the 15th."""
    from bot.data.contract_calendar import third_friday
    assert third_friday(2024, 11) == date(2024, 11, 15)


def test_contract_code_to_month() -> None:
    """CONTRACT_MONTHS covers every code used by any registered market.

    Plan 14: extended from the NQ/ES quarterly set (H/M/U/Z) to the union
    that also covers Gold's even-month cycle (G/J/M/Q/V/Z). See
    `tests/markets/test_contract_calendar_markets.py` for the multi-market
    parametrize coverage.
    """
    from bot.data.contract_calendar import CONTRACT_MONTHS
    # Original NQ/ES quarterly codes still mapped correctly.
    assert CONTRACT_MONTHS["H"] == 3
    assert CONTRACT_MONTHS["M"] == 6
    assert CONTRACT_MONTHS["U"] == 9
    assert CONTRACT_MONTHS["Z"] == 12
    # Plan 14 additions for Gold (G/J/Q/V).
    assert CONTRACT_MONTHS["G"] == 2
    assert CONTRACT_MONTHS["J"] == 4
    assert CONTRACT_MONTHS["Q"] == 8
    assert CONTRACT_MONTHS["V"] == 10


def test_roll_calendar_quarterly() -> None:
    from bot.data.contract_calendar import roll_calendar
    dates = roll_calendar(start_year=2023, end_year=2024)
    # 8 quarterly dates: 2023 H/M/U/Z + 2024 H/M/U/Z
    assert len(dates) == 8
    assert dates[0] == date(2023, 3, 17)   # 2023H
    assert dates[-1] == date(2024, 12, 20)  # 2024Z


def test_parse_contract_code() -> None:
    from bot.data.contract_calendar import parse_contract_code
    assert parse_contract_code("2023Z") == (2023, 12)
    assert parse_contract_code("2024H") == (2024, 3)
    assert parse_contract_code("2025U") == (2025, 9)


def test_parse_contract_code_rejects_bad_input() -> None:
    from bot.data.contract_calendar import parse_contract_code

    with pytest.raises(ValueError, match="not in"):
        parse_contract_code("2023X")  # X is not a valid CME month code
    with pytest.raises(ValueError, match="must be 5 chars"):
        parse_contract_code("23Z")  # year must be 4 digits
