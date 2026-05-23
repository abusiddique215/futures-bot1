"""Tests for the Bar and Tick dataclasses.

Spec: 01-data-pipeline.md §3.5 timezone-awareness invariant.
"""
from __future__ import annotations

from datetime import datetime

import pytest


def test_bar_rejects_naive_timestamp() -> None:
    from bot.types import Bar
    with pytest.raises(TypeError, match="timezone-aware"):
        Bar(
            symbol="MNQ",
            open=15000.0, high=15010.0, low=14990.0, close=15005.0,
            volume=100,
            timestamp=datetime(2026, 5, 22, 14, 30, 0),  # naive!
            interval="1m",
        )


def test_bar_accepts_utc_timestamp(utc_now) -> None:
    from bot.types import Bar
    b = Bar(symbol="MNQ", open=1.0, high=2.0, low=0.5, close=1.5,
            volume=10, timestamp=utc_now, interval="1m")
    assert b.symbol == "MNQ"
    assert b.timestamp.tzinfo is not None


def test_bar_is_frozen(utc_now) -> None:
    from dataclasses import FrozenInstanceError

    from bot.types import Bar
    b = Bar(symbol="MNQ", open=1.0, high=2.0, low=0.5, close=1.5,
            volume=10, timestamp=utc_now, interval="1m")
    with pytest.raises(FrozenInstanceError):
        b.symbol = "NQ"  # type: ignore[misc]


def test_tick_rejects_naive_timestamp() -> None:
    from bot.types import Tick
    with pytest.raises(TypeError, match="timezone-aware"):
        Tick(
            symbol="MNQ",
            price=15000.0, size=1,
            timestamp=datetime(2026, 5, 22, 14, 30, 0),
        )


def test_tick_accepts_non_utc_tz(utc_now) -> None:
    """Any tz-aware datetime is valid at construction; UTC conversion happens
    elsewhere (per spec 01 §3.5 storage is UTC, ingest converts ET→UTC)."""
    from zoneinfo import ZoneInfo

    from bot.types import Tick
    et_now = utc_now.astimezone(ZoneInfo("America/New_York"))
    t = Tick(symbol="MNQ", price=1.0, size=1, timestamp=et_now)
    assert t.timestamp.tzinfo is not None
