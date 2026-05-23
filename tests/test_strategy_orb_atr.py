"""ATR (true range simple average) helper for ORB strategy."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bot.types import Bar


def _bar(o: float, h: float, lo: float, c: float, ts: datetime) -> Bar:
    return Bar(
        symbol="MNQ", open=o, high=h, low=lo, close=c,
        volume=100, timestamp=ts, interval="1m",
    )


def test_compute_atr_returns_none_when_insufficient_bars() -> None:
    from bot.strategy.orb import _compute_atr
    base = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    # period=2 requires period+1 = 3 bars; we provide 2.
    bars = [
        _bar(100, 105, 99, 102, base),
        _bar(102, 110, 101, 109, base + timedelta(minutes=1)),
    ]
    assert _compute_atr(bars, period=2) is None


def test_compute_atr_three_bars_period_two_simple_average() -> None:
    """Three bars, period=2: TR_1 = max(h1-l1, |h1-c0|, |l1-c0|); same for TR_2.
    ATR = (TR_1 + TR_2) / 2."""
    from bot.strategy.orb import _compute_atr
    base = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    # bar 0: close = 100
    # bar 1: h=110, l=98, c=105 -> TR = max(12, |110-100|=10, |98-100|=2) = 12
    # bar 2: h=108, l=102, c=107 -> TR = max(6, |108-105|=3, |102-105|=3) = 6
    bars = [
        _bar(100, 101, 99, 100, base),
        _bar(100, 110, 98, 105, base + timedelta(minutes=1)),
        _bar(105, 108, 102, 107, base + timedelta(minutes=2)),
    ]
    atr = _compute_atr(bars, period=2)
    assert atr is not None
    assert atr == (12.0 + 6.0) / 2.0


def test_compute_atr_uses_only_last_period_trs() -> None:
    """Extra warmup bars beyond period+1 should be ignored — only last `period` TRs."""
    from bot.strategy.orb import _compute_atr
    base = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    # 5 bars, period=2 -> last 2 TRs only.
    # bar 0 close=100
    # bar 1 h=200, l=50, c=100 -> TR enormous; should be ignored
    # bar 2 h=200, l=50, c=100 -> TR enormous; should be ignored
    # bar 3 h=105, l=95, c=100 -> TR = max(10, |105-100|=5, |95-100|=5) = 10
    # bar 4 h=102, l=98, c=100 -> TR = max(4, |102-100|=2, |98-100|=2) = 4
    bars = [
        _bar(100, 101, 99, 100, base),
        _bar(100, 200, 50, 100, base + timedelta(minutes=1)),
        _bar(100, 200, 50, 100, base + timedelta(minutes=2)),
        _bar(100, 105, 95, 100, base + timedelta(minutes=3)),
        _bar(100, 102, 98, 100, base + timedelta(minutes=4)),
    ]
    atr = _compute_atr(bars, period=2)
    assert atr is not None
    assert atr == (10.0 + 4.0) / 2.0
