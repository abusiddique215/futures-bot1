# src/bot/data/contract_calendar.py
"""CME / COMEX contract calendar.

Equity-index futures (NQ/MNQ/ES/MES) settle on the third Friday of the
contract month (H=Mar, M=Jun, U=Sep, Z=Dec).

Gold futures (GC/MGC) settle on the third-to-last business day of the month
*preceding* the delivery month (months G=Feb, J=Apr, M=Jun, Q=Aug, V=Oct,
Z=Dec). See `docs/superpowers/research/2026-05-23-cme-comex-contract-specs.md`
for citations.

Spec: 01-data-pipeline.md §3.2.
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # avoid circular import at runtime
    from bot.markets.spec import MarketSpec, RollDayRule

# Union of CME month codes used by every market in the Plan-14 registry.
# Equity-index quarterly: H(3), M(6), U(9), Z(12).
# Gold even-months:        G(2), J(4), M(6), Q(8), V(10), Z(12).
CONTRACT_MONTHS: Final[dict[str, int]] = {
    "G": 2, "H": 3, "J": 4, "M": 6, "Q": 8, "U": 9, "V": 10, "Z": 12,
}
_MONTH_TO_CODE: Final[dict[int, str]] = {v: k for k, v in CONTRACT_MONTHS.items()}


def third_friday(year: int, month: int) -> date:
    """Return the third Friday of the given month.

    Algorithm: Find the first Friday, add 14 days. Friday is weekday() == 4.
    """
    first_of_month = date(year, month, 1)
    first_friday_offset = (4 - first_of_month.weekday()) % 7
    return date(year, month, 1 + first_friday_offset + 14)


def _last_day_of_month(year: int, month: int) -> int:
    """Day number of the last day of the given month (calendar)."""
    if month == 12:
        return 31
    next_first = date(year, month + 1, 1)
    return (next_first - date(year, month, 1)).days


def third_last_business_day(year: int, month: int) -> date:
    """Return the third-to-last weekday (Mon-Fri) of the given month.

    Used by COMEX Gold / Micro Gold for last-trading-day calculation; the
    delivery month for a GC `<YYYY><month>` contract terminates on the
    third-to-last business day of the *preceding* calendar month — so callers
    typically invoke this with `month` already decremented.

    "Business day" here means Mon-Fri only; US bank holidays are NOT excluded.
    Downstream broker adapters apply holiday-aware adjustments if needed; this
    function is the registry-driven roll heuristic used for synthetic
    continuous-roll series. See research doc for rationale.
    """
    last_day = _last_day_of_month(year, month)
    business_days: list[date] = []
    for day in range(last_day, 0, -1):
        d = date(year, month, day)
        if d.weekday() < 5:  # 0=Mon .. 4=Fri
            business_days.append(d)
            if len(business_days) == 3:
                return d
    # 31-day month with at least 3 weekdays — unreachable in any real calendar.
    raise AssertionError(f"Fewer than 3 business days in {year}-{month:02d}")


def last_trading_day(
    year: int, contract_month: int, rule: RollDayRule,
) -> date:
    """Dispatch to the rule-appropriate last-trading-day function.

    `contract_month` is the integer month of the contract's delivery (e.g.,
    GCM26 -> month=6 for June 2026). The function applies the rule to compute
    when trading terminates in that contract.

    See `bot.markets.spec.RollDayRule` for the supported rule names.
    """
    if rule == "third_friday_of_contract_month":
        return third_friday(year, contract_month)
    if rule == "third_last_business_day_of_prev_month":
        # Decrement to the preceding calendar month.
        prev_year = year if contract_month > 1 else year - 1
        prev_month = contract_month - 1 if contract_month > 1 else 12
        return third_last_business_day(prev_year, prev_month)
    # mypy treats this as unreachable thanks to the Literal type — keep the
    # guard for runtime safety against typo'd registry entries.
    raise ValueError(f"Unknown roll_day_rule: {rule!r}")


def roll_calendar(start_year: int, end_year: int) -> list[date]:
    """All quarterly H/M/U/Z roll dates in [start_year, end_year] (NQ/ES style).

    Kept unchanged for back-compat with pre-Plan-14 callers (NQ-only tests +
    any tooling that doesn't yet pass a MarketSpec). Multi-market callers
    should prefer `market_roll_calendar`.
    """
    dates: list[date] = []
    for year in range(start_year, end_year + 1):
        for month in (3, 6, 9, 12):
            dates.append(third_friday(year, month))
    return dates


def market_roll_calendar(
    market: MarketSpec, start_year: int, end_year: int,
) -> list[date]:
    """Roll dates for `market` over [start_year, end_year], chronologically.

    For each year in range, emits one date per code in `market.contract_months`,
    applying `market.roll_day_rule` to compute the last trading day.
    """
    dates: list[date] = []
    for year in range(start_year, end_year + 1):
        for code in market.contract_months:
            month = CONTRACT_MONTHS[code]
            dates.append(last_trading_day(year, month, market.roll_day_rule))
    return dates


def parse_contract_code(code: str) -> tuple[int, int]:
    """Parse a FirstRateData contract suffix like "2023Z" -> (2023, 12).

    Raises ValueError on malformed input or unknown month code.
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
    """Inverse of parse_contract_code: (2023, 12) -> "2023Z"."""
    if month not in _MONTH_TO_CODE:
        raise ValueError(f"Month {month} not a recognized contract month")
    return f"{year}{_MONTH_TO_CODE[month]}"
