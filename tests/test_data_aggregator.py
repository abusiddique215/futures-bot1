"""BarAggregator: aggregate sub-bars into 1m/5m. Spec 01 §3.4."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bot.types import Tick


def _tick(t: datetime, price: float, size: int = 1) -> Tick:
    return Tick(symbol="MNQ", price=price, size=size, timestamp=t)


@pytest.fixture
def t0() -> datetime:
    return datetime(2026, 5, 22, 14, 30, 0, tzinfo=UTC)


def test_first_tick_starts_bar_no_emit(t0) -> None:
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    out = agg.feed(_tick(t0, 100.0))
    assert out is None


def test_tick_within_bar_no_emit(t0) -> None:
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    agg.feed(_tick(t0, 100.0))
    out = agg.feed(_tick(t0 + timedelta(seconds=30), 101.0))
    assert out is None


def test_tick_crossing_boundary_emits_closed_bar(t0) -> None:
    """Tick at t0+60s closes the [t0, t0+60s) bar."""
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    agg.feed(_tick(t0, 100.0))
    agg.feed(_tick(t0 + timedelta(seconds=30), 102.0))
    agg.feed(_tick(t0 + timedelta(seconds=45), 99.5))
    closed = agg.feed(_tick(t0 + timedelta(seconds=60), 101.0))
    assert closed is not None
    assert closed.timestamp == t0
    assert closed.open == 100.0
    assert closed.high == 102.0
    assert closed.low == 99.5
    assert closed.close == 99.5  # last in-window close
    assert closed.interval == "1m"


def test_volume_accumulates(t0) -> None:
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    agg.feed(_tick(t0, 100.0, size=2))
    agg.feed(_tick(t0 + timedelta(seconds=30), 101.0, size=3))
    closed = agg.feed(_tick(t0 + timedelta(seconds=60), 102.0, size=1))
    assert closed is not None
    assert closed.volume == 5  # 2+3, NOT including the boundary-crossing tick


def test_flush_emits_partial_bar(t0) -> None:
    """flush() drains the current in-progress bar (used at end-of-data)."""
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    agg.feed(_tick(t0, 100.0))
    agg.feed(_tick(t0 + timedelta(seconds=15), 101.0))
    out = agg.flush()
    assert out is not None
    assert out.open == 100.0
    assert out.close == 101.0
    assert agg.flush() is None


def test_aggregator_rejects_out_of_order_tick(t0) -> None:
    from bot.data.aggregator import BarAggregator
    agg = BarAggregator(interval="1m", symbol="MNQ")
    agg.feed(_tick(t0 + timedelta(seconds=30), 100.0))
    with pytest.raises(ValueError, match="out of order"):
        agg.feed(_tick(t0, 99.0))
