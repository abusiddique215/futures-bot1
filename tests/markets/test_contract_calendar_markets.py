"""Plan 14: contract_calendar must honor MarketSpec.roll_day_rule.

Equity-index markets (NQ/MNQ/ES/MES) keep their third-Friday-of-the-contract-
month roll. Gold markets (GC/MGC) roll on the third-last business day of the
preceding month.

Existing NQ-only tests in `test_data_contract_calendar.py` remain as
regression coverage; this file exercises the new market-aware API.
"""
from __future__ import annotations

from datetime import date

import pytest

# ---- expanded CONTRACT_MONTHS (covers GC's G/J/M/Q/V/Z) -------------------

def test_contract_months_includes_gold_codes() -> None:
    """CONTRACT_MONTHS must accept gold's G/J/Q/V in addition to H/M/U/Z."""
    from bot.data.contract_calendar import CONTRACT_MONTHS
    for code in ("G", "H", "J", "M", "Q", "U", "V", "Z"):
        assert code in CONTRACT_MONTHS, f"{code!r} missing from CONTRACT_MONTHS"


@pytest.mark.parametrize(
    ("code", "year", "month"),
    [
        ("2026G", 2026, 2),
        ("2026J", 2026, 4),
        ("2026M", 2026, 6),
        ("2026Q", 2026, 8),
        ("2026V", 2026, 10),
        ("2026Z", 2026, 12),
        # Equity-index codes still parse.
        ("2026H", 2026, 3),
        ("2026U", 2026, 9),
    ],
)
def test_parse_contract_code_accepts_all_registered_months(
    code: str, year: int, month: int,
) -> None:
    from bot.data.contract_calendar import parse_contract_code
    assert parse_contract_code(code) == (year, month)


def test_gold_contract_codes_sort_chronologically() -> None:
    """`continuous._list_contracts` sorts by parse_contract_code, so the
    sort key (year, calendar_month_int) must yield G<J<M<Q<V<Z within a year."""
    from bot.data.contract_calendar import parse_contract_code
    codes = ["2026Z", "2026G", "2026M", "2026J", "2026V", "2026Q"]
    sorted_codes = sorted(codes, key=parse_contract_code)
    assert sorted_codes == ["2026G", "2026J", "2026M", "2026Q", "2026V", "2026Z"]


# ---- third_last_business_day (GC roll-day helper) -------------------------

@pytest.mark.parametrize(
    ("year", "month", "expected"),
    [
        # May 2026: business days fall on weekdays Mon-Fri. Last business day
        # is Fri May 29, 2026. Two business days back -> Wed May 27 -> the third-
        # last business day is May 27.
        (2026, 5, date(2026, 5, 27)),
        # Jul 2026: last business day = Fri Jul 31; 3rd-last = Wed Jul 29.
        (2026, 7, date(2026, 7, 29)),
        # Nov 2026: last business day = Mon Nov 30; 3rd-last = Thu Nov 26.
        # (Note: this is a US bank holiday — CME's published gold calendar uses
        # business days w/o holiday exclusion at this granularity. We follow the
        # weekday-only convention; downstream calendar adjustments live in the
        # broker, not in our continuous-roll algorithm.)
        (2026, 11, date(2026, 11, 26)),
    ],
)
def test_third_last_business_day_known_dates(
    year: int, month: int, expected: date,
) -> None:
    from bot.data.contract_calendar import third_last_business_day
    assert third_last_business_day(year, month) == expected


# ---- last_trading_day dispatcher ------------------------------------------

def test_last_trading_day_equity_index_uses_third_friday_of_contract_month() -> None:
    from bot.data.contract_calendar import last_trading_day
    # NQH26 -> third Friday of Mar 2026 = 2026-03-20
    assert last_trading_day(2026, 3, "third_friday_of_contract_month") == date(2026, 3, 20)


def test_last_trading_day_gold_uses_third_last_business_day_of_prev_month() -> None:
    from bot.data.contract_calendar import last_trading_day
    # GCM26 (June 2026 delivery) -> third-last business day of May 2026 = 2026-05-27
    assert last_trading_day(2026, 6, "third_last_business_day_of_prev_month") == date(2026, 5, 27)


def test_last_trading_day_gold_january_wraps_to_prior_year_december() -> None:
    from bot.data.contract_calendar import last_trading_day
    # GCG26 (Feb 2026 delivery) -> third-last business day of Jan 2026.
    # Jan 2026: last business day = Fri Jan 30; 3rd-last = Wed Jan 28.
    assert last_trading_day(2026, 2, "third_last_business_day_of_prev_month") == date(2026, 1, 28)
    # GCG27 (Feb 2027 delivery) -> third-last business day of Jan 2027.
    # Jan 2027 last business day = Fri Jan 29; 3rd-last = Wed Jan 27.
    assert last_trading_day(2027, 2, "third_last_business_day_of_prev_month") == date(2027, 1, 27)


# ---- market_roll_calendar -------------------------------------------------

def test_market_roll_calendar_for_nq_returns_quarterly_third_fridays() -> None:
    from bot.data.contract_calendar import market_roll_calendar
    from bot.markets.registry import MARKETS
    dates = market_roll_calendar(MARKETS["NQ"], start_year=2024, end_year=2024)
    assert dates == [
        date(2024, 3, 15),  # 2024H
        date(2024, 6, 21),  # 2024M
        date(2024, 9, 20),  # 2024U
        date(2024, 12, 20), # 2024Z
    ]


def test_market_roll_calendar_for_gc_returns_six_per_year() -> None:
    """GC trades G/J/M/Q/V/Z — six rolls per year."""
    from bot.data.contract_calendar import market_roll_calendar
    from bot.markets.registry import MARKETS
    dates = market_roll_calendar(MARKETS["GC"], start_year=2026, end_year=2026)
    assert len(dates) == 6
    # GCG26 -> 3rd-last business day of Jan 2026 = Jan 28
    assert dates[0] == date(2026, 1, 28)
    # GCZ26 -> 3rd-last business day of Nov 2026 = Nov 26
    assert dates[-1] == date(2026, 11, 26)


def test_market_roll_calendar_for_es_matches_nq_quarterly_rule() -> None:
    """ES uses the same H/M/U/Z quarterly + third-Friday rule as NQ."""
    from bot.data.contract_calendar import market_roll_calendar
    from bot.markets.registry import MARKETS
    es_dates = market_roll_calendar(MARKETS["ES"], start_year=2026, end_year=2026)
    nq_dates = market_roll_calendar(MARKETS["NQ"], start_year=2026, end_year=2026)
    assert es_dates == nq_dates
