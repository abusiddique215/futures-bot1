"""MarketSpec — frozen dataclass describing one futures market.

One entry in the registry (`bot.markets.registry.MARKETS`) per supported
market. Owns tick size/value, multiplier, micro counterpart, contract-month
codes, roll-day rule, and IB contract construction fields.

Frozen + slots: instances are immutable and have no `__dict__`; all
attributes are exposed via slots. Mutation raises FrozenInstanceError.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Roll-day rule names. Dispatched by `bot.data.contract_calendar.last_trading_day`.
#
# "third_friday_of_contract_month": NQ, MNQ, ES, MES — settles on the third
#   Friday of the contract month itself (e.g., NQH26 last-trades 2026-03-20).
# "third_last_business_day_of_prev_month": GC, MGC — settles on the third-last
#   business day of the month preceding the delivery month (e.g., GCM26 / Jun-2026
#   last-trades on the third-last business day of May 2026).
RollDayRule = Literal[
    "third_friday_of_contract_month",
    "third_last_business_day_of_prev_month",
]


@dataclass(frozen=True, slots=True)
class MarketSpec:
    """Per-market specification.

    Fields:
      root:                   CME root symbol ("NQ", "MNQ", "GC", "MGC", "ES", "MES").
      name:                   Human-readable product name.
      exchange:               Listing venue ("CME", "COMEX").
      tick_size:              Minimum price increment in points.
      tick_value:             Dollar value of one tick (= tick_size * multiplier).
      multiplier:             $/point.
      micro_root:             Root of the micro counterpart, or None.
      micro_to_full_ratio:    How many micros equal one full contract for
                              position-cap purposes (10 for NQ/MNQ/GC/MGC/ES/MES).
      contract_months:        Tuple of CME month codes for the liquid quarterly
                              cycle this market trades on.
      roll_day_rule:          Which roll-day function applies — see RollDayRule.
      ib_sec_type:            ib_async Contract secType (always "FUT" for us).
      ib_currency:            ib_async Contract currency ("USD").
    """
    root: str
    name: str
    exchange: str
    tick_size: float
    tick_value: float
    multiplier: float
    micro_root: str | None
    micro_to_full_ratio: int
    contract_months: tuple[str, ...]
    roll_day_rule: RollDayRule
    ib_sec_type: str
    ib_currency: str
