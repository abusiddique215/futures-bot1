"""Tests for the DrawdownPolicy Protocol.

Spec: 04-risk-engine.md §3.3 lines 215-225.

The three concrete policies (CombineIntradayDrawdown, EFAStandardEoDDrawdown,
EFAConsistencyDrawdown) are implemented in Plan 3 (Risk Engine). This file
only nails down the Protocol shape so Plan 3 has a target to extend.
"""
from __future__ import annotations

import pytest


def test_drawdown_policy_protocol_importable() -> None:
    from bot.risk.policies import DrawdownPolicy
    assert DrawdownPolicy is not None


def test_drawdown_policy_protocol_has_expected_methods() -> None:
    from bot.risk.policies import DrawdownPolicy
    expected = {
        "phantom_mll", "is_locked", "max_position",
        "update_on_tick", "update_on_eod",
    }
    actual = {n for n in dir(DrawdownPolicy) if not n.startswith("_")}
    missing = expected - actual
    assert not missing, f"Protocol missing methods: {missing}"


def test_dummy_policy_satisfies_protocol(utc_now) -> None:
    """Trivial policy where the floor is fixed at start_balance - MLL.
    Validates the Protocol's shape; not real risk-engine logic."""
    from bot.risk.policies import DrawdownPolicy
    from bot.types import AccountState

    class _NoopPolicy:
        def phantom_mll(self, state: AccountState) -> float:
            return state.start_balance - 2_000.0
        def is_locked(self, state: AccountState) -> bool:
            return False
        def max_position(self, symbol: str, state: AccountState) -> int:
            return 0
        def update_on_tick(self, state: AccountState) -> AccountState:
            return state
        def update_on_eod(self, state: AccountState) -> AccountState:
            return state

    p: DrawdownPolicy = _NoopPolicy()
    state = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    assert p.phantom_mll(state) == pytest.approx(48_000.0)
    assert p.is_locked(state) is False
    assert p.update_on_tick(state) is state
