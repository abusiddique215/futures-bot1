"""Tests for the AccountState dataclass.

Spec: 04-risk-engine.md §4.1 lines 388-404.
"""
from __future__ import annotations

import pytest


def test_account_state_required_fields(utc_now) -> None:
    from bot.types import AccountState
    s = AccountState(
        equity=50_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=50_000.0,
        is_combine=True,
        timestamp=utc_now,
    )
    assert s.equity == 50_000.0
    assert s.is_combine is True


def test_account_state_defaults_for_locked_and_lock_point(utc_now) -> None:
    from bot.types import AccountState
    s = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    assert s.is_locked is False
    assert s.lock_point is None


def test_account_state_default_start_balance_is_50k(utc_now) -> None:
    from bot.types import AccountState
    s = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    assert s.start_balance == 50_000.0
    assert s.account_size == "50K"


def test_account_state_is_frozen(utc_now) -> None:
    from dataclasses import FrozenInstanceError

    from bot.types import AccountState
    s = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    with pytest.raises(FrozenInstanceError):
        s.equity = 99_999.0  # type: ignore[misc]


def test_account_state_position_dict_can_hold_short_and_long(utc_now) -> None:
    from bot.types import AccountState
    s = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={"MNQ": 3, "NQ": -1},
        pending_intent_count=0,
        high_water_equity=50_000.0, is_combine=True, timestamp=utc_now,
    )
    assert s.open_positions["MNQ"] == 3
    assert s.open_positions["NQ"] == -1
