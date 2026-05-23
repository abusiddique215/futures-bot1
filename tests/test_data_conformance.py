"""§3.6 conformance contract: backtest and live emit byte-identical Bar streams.

Both paths feed the SAME fixture data through:
- "Backtest path": one synthetic 1-min Bar built directly from the OHLCV of the
  ticks (mimicking what FirstRateData would have produced).
- "Live path": ticks fed one-by-one through BarAggregator.

Assert: closed Bar from the live path equals the historical bar field-by-field.
"""
from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from bot.data.aggregator import BarAggregator
from bot.types import Bar, Tick

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_ticks() -> list[Tick]:
    ticks: list[Tick] = []
    with (_FIXTURES / "conformance_5sec_ticks.csv").open() as f:
        for row in csv.DictReader(f):
            ts_naive = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            ts = ts_naive.replace(tzinfo=UTC)
            ticks.append(Tick(symbol="MNQ", price=float(row["price"]),
                              size=int(row["size"]), timestamp=ts))
    return ticks


def _backtest_path() -> Bar:
    """What FirstRateData-style 1-min OHLCV looks like from the same ticks."""
    ticks = _load_ticks()
    # Bar covers [14:30:00, 14:31:00); the 14:31:00 tick is EXCLUDED.
    in_bar = [t for t in ticks if t.timestamp < datetime(
        2026, 5, 22, 14, 31, tzinfo=UTC)]
    return Bar(
        symbol="MNQ",
        open=in_bar[0].price,
        high=max(t.price for t in in_bar),
        low=min(t.price for t in in_bar),
        close=in_bar[-1].price,
        volume=sum(t.size for t in in_bar),
        timestamp=datetime(2026, 5, 22, 14, 30, tzinfo=UTC),
        interval="1m",
    )


def _live_path() -> Bar:
    """Live aggregation: feed each tick to BarAggregator; the boundary-crossing
    tick (14:31:00) closes the [14:30, 14:31) bar."""
    ticks = _load_ticks()
    agg = BarAggregator(interval="1m", symbol="MNQ")
    closed: Bar | None = None
    for t in ticks:
        result = agg.feed(t)
        if result is not None:
            closed = result
            break
    assert closed is not None, "expected a closed bar after the boundary tick"
    return closed


def test_conformance_backtest_live_identical_bars() -> None:
    bt = _backtest_path()
    live = _live_path()
    assert bt.symbol == live.symbol
    assert bt.open == live.open
    assert bt.high == live.high
    assert bt.low == live.low
    assert bt.close == live.close
    assert bt.volume == live.volume
    assert bt.timestamp == live.timestamp
    assert bt.interval == live.interval
