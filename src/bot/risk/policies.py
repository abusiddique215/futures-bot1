"""DrawdownPolicy port (Protocol).

Three concrete policies live in Plan 3 (Risk Engine):
  - CombineIntradayDrawdown    : real-time on unrealized; locks at start_balance
  - EFAStandardEoDDrawdown     : EoD-trailing; profit-gated scaling plan
  - EFAConsistencyDrawdown     : EoD-trailing + payout-window 40% cap

This file ships the Protocol shell only. Concrete implementations + the
phantom-MLL state machine + force-flatten triggers come in Plan 3.

Spec: 04-risk-engine.md §3.3 lines 215-225.
"""
from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from bot.types import AccountState


@runtime_checkable
class DrawdownPolicy(Protocol):
    """Selects the Combine vs EFA drawdown semantics for TopstepRiskGate.

    All methods are pure functions on AccountState. State updates return a new
    AccountState; never mutate. See spec 04 §3.4 transition diagram.
    """

    # Plan 22 T1: whether this policy enforces the Topstep Combine 15:10 CT
    # hard-flat. Combine accounts MUST flatten by 15:10; EFA / funded accounts
    # have no daily hard-flat (only EoD-trailing MLL). Declared `ClassVar` so
    # implementers can satisfy it as a class-level attribute.
    enforces_hard_flat: ClassVar[bool]

    def phantom_mll(self, state: AccountState) -> float:
        """Equity floor below which the account is dead. Used by rule 3."""
        ...

    def is_locked(self, state: AccountState) -> bool:
        """True once the trailing drawdown has reached its lock point."""
        ...

    def max_position(self, symbol: str, state: AccountState) -> int:
        """Per-symbol size cap. Used by rule 4.

        For Combine: fixed. For EFA: profit-gated scaling plan keyed off
        accumulated profit (= equity - start_balance), NOT absolute equity.
        See spec 04 §3.2 rule 4 note.
        """
        ...

    def update_on_tick(self, state: AccountState) -> AccountState:
        """Return a new AccountState with high_water_equity / is_locked /
        lock_point updated per the policy's tick-cadence rules.

        Combine: ratchets high-water on every tick; locks at start_balance
        once high_water >= start_balance + MLL.
        EFA: tick is a no-op (EoD-trailing).
        """
        ...

    def update_on_eod(self, state: AccountState) -> AccountState:
        """End-of-day update.

        Combine: no-op.
        EFA: ratchets high_water_equity at session close.
        """
        ...
