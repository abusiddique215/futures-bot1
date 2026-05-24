"""Static constants — CME contract specs and Topstep $50K Combine rule values.

Source:
- CME contract specs: NQ / MNQ tick = 0.25 pt, NQ point = $20, MNQ point = $2.
- Topstep $50K Combine rules: 00-architecture-overview.md §5.
- TopstepX side encoding: 02-execution-clients.md §3.4 (the inversion footgun).

Constants are loud-named and `Final`-annotated. Do NOT add a level of indirection
(no `RULES["mll"]`) — a typo on a key fails silently, a typo on a constant name
fails at import time.
"""
from __future__ import annotations

from datetime import time
from typing import Final
from zoneinfo import ZoneInfo

from bot.markets.registry import MARKETS

# ---- CME / COMEX contract specs --------------------------------------------
#
# Plan 14: TICK_VALUES and MIN_TICK are now thin views over `bot.markets.MARKETS`
# (the single source of truth). The dict shape is preserved so callers in
# `bot.backtest.*`, `bot.execution.*`, `bot.strategy.*`, and `bot.risk.gate` keep
# their `TICK_VALUES[symbol]` access patterns unchanged. To add or modify a
# market, edit `bot.markets.registry.MARKETS` — never mutate these dicts.

TICK_VALUES: Final[dict[str, float]] = {
    root: spec.tick_value for root, spec in MARKETS.items()
}

MIN_TICK: Final[dict[str, float]] = {
    root: spec.tick_size for root, spec in MARKETS.items()
}


# ---- Topstep $50K Combine rule constants (00 §5) ----------------------------

COMBINE_50K_START_BALANCE:   Final[float] = 50_000.0
COMBINE_50K_PROFIT_TARGET:   Final[float] = 3_000.0    # Combine pass threshold
COMBINE_50K_DLL:             Final[float] = 1_000.0    # Daily Loss Limit
COMBINE_50K_MLL:             Final[float] = 2_000.0    # Max Loss Limit (trailing, intraday on unrealized)
COMBINE_50K_MAX_MINI:        Final[int]   = 5
COMBINE_50K_MAX_MICRO:       Final[int]   = 50
COMBINE_50K_CONSISTENCY_PCT: Final[float] = 0.50       # best-day-vs-target ≤ 50%

# Hard-flat time, timezone-aware (00 §5, §7 item 3).
HARD_FLAT_TIME_CT: Final[time]     = time(15, 10)
HARD_FLAT_TZ:      Final[ZoneInfo] = ZoneInfo("America/Chicago")
PREEMPT_FLAT_TIME_CT: Final[time]  = time(15, 0)       # soft-warn after this (04 §3.2 rule 1)


# ---- TopstepX wire protocol — DO NOT REORDER (00 §7 item 1, 02 §3.4) --------

# These constants are loud on purpose. If you "simplify" them, you will lose money.
TOPSTEPX_SIDE_BUY:  Final[int] = 0   # Bid
TOPSTEPX_SIDE_SELL: Final[int] = 1   # Ask
