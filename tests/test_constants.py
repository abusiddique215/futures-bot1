"""Tests for the constants module.

Source: 00-architecture-overview.md §5 (rule constants table),
        04-risk-engine.md §3.2 rule 2 (tick values).
"""
from __future__ import annotations

import pytest


def test_tick_value_mnq_is_50_cents() -> None:
    """MNQ tick value = $0.50 (4 ticks/pt x $2/pt). See 04 §3.2 rule 2."""
    from bot.constants import TICK_VALUES
    assert TICK_VALUES["MNQ"] == pytest.approx(0.50)


def test_tick_value_nq_is_5_dollars() -> None:
    """NQ tick value = $5.00 (4 ticks/pt x $20/pt). See 04 §3.2 rule 2."""
    from bot.constants import TICK_VALUES
    assert TICK_VALUES["NQ"] == pytest.approx(5.00)


def test_min_tick_size() -> None:
    """Both MNQ and NQ tick at 0.25 points. See 02 §3.2 contract resolution."""
    from bot.constants import MIN_TICK
    assert MIN_TICK["MNQ"] == pytest.approx(0.25)
    assert MIN_TICK["NQ"] == pytest.approx(0.25)


def test_combine_50k_constants() -> None:
    """Topstep $50K Combine rule constants. See 00 §5."""
    from bot.constants import (
        COMBINE_50K_CONSISTENCY_PCT,
        COMBINE_50K_DLL,
        COMBINE_50K_MAX_MICRO,
        COMBINE_50K_MAX_MINI,
        COMBINE_50K_MLL,
        COMBINE_50K_PROFIT_TARGET,
        COMBINE_50K_START_BALANCE,
    )
    assert COMBINE_50K_START_BALANCE == 50_000
    assert COMBINE_50K_PROFIT_TARGET == 3_000
    assert COMBINE_50K_DLL == 1_000
    assert COMBINE_50K_MLL == 2_000
    assert COMBINE_50K_MAX_MINI == 5
    assert COMBINE_50K_MAX_MICRO == 50
    assert COMBINE_50K_CONSISTENCY_PCT == pytest.approx(0.50)


def test_hard_flat_time_is_15_10_chicago() -> None:
    """3:10 PM CT hard flat. See 00 §5 + §7 item 3."""
    from datetime import time
    from zoneinfo import ZoneInfo

    from bot.constants import HARD_FLAT_TIME_CT, HARD_FLAT_TZ
    assert HARD_FLAT_TIME_CT == time(15, 10)
    assert HARD_FLAT_TZ == ZoneInfo("America/Chicago")


def test_topstepx_side_constants_are_inverted_from_intuition() -> None:
    """TopstepX side encoding: 0=BUY (Bid), 1=SELL (Ask). The footgun.
    See 00 §7 item 1, 02 §3.4."""
    from bot.constants import TOPSTEPX_SIDE_BUY, TOPSTEPX_SIDE_SELL
    assert TOPSTEPX_SIDE_BUY == 0, "TopstepX 0 is BUY (Bid). Do not change."
    assert TOPSTEPX_SIDE_SELL == 1, "TopstepX 1 is SELL (Ask). Do not change."
