"""EFA drawdown policies. Spec 04 §3.3 + §4.4.

Both EFA Standard and EFA Consistency:
- Floor ratchets EoD only (NOT intraday).
- BUT: equity-touch check (`state.equity <= phantom_mll(state)`) still runs
  every tick in TopstepRiskGate.on_tick. The DIFFERENCE between Combine and
  EFA is when the floor itself moves (every tick vs once per day), not what
  triggers liquidation (always real-time unrealized).

Scaling tiers verified 2026-05-22 per pre-Plan-1 research:
  profit < $1,500          -> 2 mini-equiv
  $1,500 <= profit < $2,000 -> 3 mini-equiv
  profit >= $2,000         -> 5 mini-equiv

TopstepX-quirk: 10 micros = 1 mini for scaling purposes. We use that.
Tier upgrade takes effect NEXT session after Trade Report posts — not enforced
in the policy itself (the policy just reports the cap given current state);
the driver is responsible for snapshotting AccountState at session boundary.
"""
from __future__ import annotations

from dataclasses import replace
from typing import ClassVar

from bot.markets.registry import get_market, is_micro
from bot.types import AccountState


class EFAStandardEoDDrawdown:
    """EFA Standard: EoD-trailing floor; profit-gated scaling plan."""

    # Plan 22 T1: EFA / funded accounts do NOT have a daily hard-flat — only
    # the EoD-trailing MLL. 24/7 bots (NQ Maintenance) need to trade through
    # the 15:10-17:00 CT window that Combine accounts must close. The risk
    # gate skips HARD_FLAT_CLOCK / HARD_FLAT_PREEMPT when this is False.
    enforces_hard_flat: ClassVar[bool] = False

    def __init__(self, mll_amount: float) -> None:
        self._mll_amount = mll_amount

    def update_on_tick(self, state: AccountState) -> AccountState:
        return state  # EFA floor ratchets EoD only

    def update_on_eod(self, state: AccountState) -> AccountState:
        new_hw = max(state.high_water_equity, state.equity)
        return replace(state, high_water_equity=new_hw)

    def phantom_mll(self, state: AccountState) -> float:
        """Absolute equity floor for EFA Standard.

        Floor = start_balance + min(max(0, profit_hw) - MLL, 0), where
        profit_hw = state.high_water_equity - state.start_balance.

        Floor starts at start_balance - MLL and ratchets up toward start_balance
        as profit_hw rises. Once profit_hw >= MLL, the floor LOCKS at start_balance
        (= 0 profit). It never moves above start_balance — that's the spec's "locks
        at 0 [profit]" rule.
        """
        profit_hw = state.high_water_equity - state.start_balance
        floor_profit = max(0.0, profit_hw) - self._mll_amount
        floor_capped = min(floor_profit, 0.0)
        return state.start_balance + floor_capped

    def is_locked(self, state: AccountState) -> bool:
        """True once profit_hw >= MLL (the floor has reached start_balance)."""
        return (state.high_water_equity - state.start_balance) >= self._mll_amount

    def max_position(self, symbol: str, state: AccountState) -> int:
        # Profit-gated tiers (VERIFIED 2026-05-22). Keyed off accumulated profit.
        profit = state.equity - state.start_balance
        if profit < 1500:
            cap_mini = 2
        elif profit < 2000:
            cap_mini = 3
        else:
            cap_mini = 5
        # Plan 14: replace symbol startswith chain with registry lookup so any
        # market in `bot.markets.MARKETS` (NQ/MNQ/GC/MGC/ES/MES today) gets the
        # right cap with no per-symbol branching here.
        try:
            market = get_market(symbol)
        except KeyError as e:
            raise ValueError(f"Unsupported symbol for Topstep: {symbol}") from e
        if is_micro(symbol):
            return cap_mini * market.micro_to_full_ratio
        return cap_mini


class EFAConsistencyDrawdown(EFAStandardEoDDrawdown):
    """EFA Consistency: same per-trade rules + payout-window 40% cap."""

    # Plan 22 T1: same as the parent — EFA accounts (Standard or Consistency)
    # never enforce the 15:10 CT hard-flat. Restated here explicitly so a
    # future maintainer can read this class in isolation.
    enforces_hard_flat: ClassVar[bool] = False

    CONSISTENCY_THRESHOLD: float = 0.40

    def gate_payout(self, best_day: float, net_profit: float) -> bool:
        """True iff payout request is allowed (best_day / net_profit <= 40%).

        Called at request_payout() time, NOT per-trade.
        """
        if net_profit <= 0:
            return False
        return (best_day / net_profit) <= self.CONSISTENCY_THRESHOLD
