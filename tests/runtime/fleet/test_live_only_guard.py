"""LiveOnlyGuard — refuses 24/7 schedule on combine accounts.

Plan 20 T1. A `BotSpec` with `schedule_type=always` + `risk_policy=combine_intraday`
is silently dangerous: Topstep Combine forces a hard-flat at 15:10 CT, which the
AlwaysOn schedule will keep re-entering against. The guard surfaces this at
boot time with a clear error.
"""
from __future__ import annotations

import pytest

from bot.runtime.fleet.live_only_guard import (
    IncompatibleBotSpecError,
    validate_schedule_x_policy,
)


def test_always_plus_combine_intraday_raises() -> None:
    with pytest.raises(IncompatibleBotSpecError) as exc_info:
        validate_schedule_x_policy("always", "combine_intraday")
    # Exact message — registry test + caller-facing error string.
    msg = str(exc_info.value)
    assert "24/7 schedule (always) is incompatible with combine_intraday" in msg
    assert "15:10 CT" in msg
    assert "efa_standard" in msg


def test_always_plus_efa_standard_ok() -> None:
    # Returns None on the live-only happy path.
    assert validate_schedule_x_policy("always", "efa_standard") is None


def test_always_plus_efa_consistency_ok() -> None:
    assert validate_schedule_x_policy("always", "efa_consistency") is None


def test_market_hours_plus_combine_intraday_ok() -> None:
    # SurgeBot's exact combination — must not trip the guard.
    assert validate_schedule_x_policy("market_hours", "combine_intraday") is None


def test_market_hours_plus_efa_standard_ok() -> None:
    assert validate_schedule_x_policy("market_hours", "efa_standard") is None


def test_custom_windows_plus_combine_intraday_ok() -> None:
    assert validate_schedule_x_policy("custom_windows", "combine_intraday") is None


def test_custom_windows_plus_efa_standard_ok() -> None:
    # Gold Bot's exact combination.
    assert validate_schedule_x_policy("custom_windows", "efa_standard") is None


def test_incompatible_error_is_value_error_subclass() -> None:
    """ConfigError convention in spec.py — guard errors are also ValueErrors."""
    assert issubclass(IncompatibleBotSpecError, ValueError)
