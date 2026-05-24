"""CombineIntradayDrawdown — real-time on unrealized P&L; locks at start_balance.

Spec: 04 §3.4 transition diagram, §4.3 pseudocode.

The phantom MLL ratchets ONE WAY: high_water_equity only increases. When
high_water_equity >= start_balance + MLL_AMOUNT, the floor locks PERMANENTLY at
start_balance. After lock, the floor never moves regardless of equity.
"""
from __future__ import annotations

from dataclasses import replace

from bot.markets.registry import get_market, is_micro
from bot.types import AccountState


class CombineIntradayDrawdown:
    """$50K/$100K/$150K Combine drawdown policy (real-time on unrealized)."""

    def __init__(self, start_balance: float, mll_amount: float, max_mini: int) -> None:
        self._start_balance = start_balance
        self._mll_amount = mll_amount
        self._max_mini = max_mini

    def update_on_tick(self, state: AccountState) -> AccountState:
        new_hw = max(state.high_water_equity, state.equity)
        new_locked = state.is_locked
        new_lock_point = state.lock_point
        if not new_locked and new_hw >= self._start_balance + self._mll_amount:
            new_locked = True
            new_lock_point = self._start_balance
        return replace(
            state,
            high_water_equity=new_hw,
            is_locked=new_locked,
            lock_point=new_lock_point,
        )

    def update_on_eod(self, state: AccountState) -> AccountState:
        return state  # Combine intraday policy is tick-driven; EoD is no-op

    def phantom_mll(self, state: AccountState) -> float:
        if state.is_locked and state.lock_point is not None:
            return state.lock_point
        return state.high_water_equity - self._mll_amount

    def is_locked(self, state: AccountState) -> bool:
        return state.is_locked

    def max_position(self, symbol: str, state: AccountState) -> int:
        """Per-market position cap. Spec 04 §3.2 rule 4.

        Lookup goes through `bot.markets.registry` so adding a market in
        Plan 14 (GC/MGC, ES/MES, ...) requires no change here. Micros get the
        full market's `micro_to_full_ratio` extra contracts (10x for every
        registered market as of 2026-05-23). Unknown symbol -> KeyError from
        the registry, surfaced as ValueError so callers see the same exception
        type they did pre-Plan-14.
        """
        try:
            market = get_market(symbol)
        except KeyError as e:
            raise ValueError(f"Unsupported symbol for Topstep: {symbol}") from e
        if is_micro(symbol):
            return self._max_mini * market.micro_to_full_ratio
        return self._max_mini
