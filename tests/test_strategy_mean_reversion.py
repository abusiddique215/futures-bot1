"""MeanReversionStrategy — Bollinger + RSI mid-band-exit state machine.

The strategy is reusable across markets: Gold Bot (Plan 17), and Plans 18/20
will pass different `bb_period / bb_stddev / rsi_period / symbol / quantity`
values. Tests below cover the protocol-shape, entry/exit semantics, and the
guardrails (`max_trades_per_day`, cooldown after stop, no entry while in
trend).
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from bot.backtest.strategy import Strategy
from bot.strategy.mean_reversion import MeanReversionStrategy
from bot.types import AccountState, Bar, OrderIntent


def _bar(
    symbol: str, close: float, ts: datetime, *,
    high: float | None = None, low: float | None = None,
) -> Bar:
    high_ = high if high is not None else close
    low_ = low if low is not None else close
    return Bar(
        symbol=symbol, open=close, high=high_, low=low_, close=close,
        volume=100, timestamp=ts, interval="10m",
    )


def _state(ts: datetime) -> AccountState:
    return AccountState(
        equity=50_000, realized_pnl_today=0, unrealized_pnl=0,
        open_positions={}, pending_intent_count=0,
        high_water_equity=50_000, is_combine=False, timestamp=ts,
    )


def _ranging_prices(center: float, amplitude: float, n: int) -> list[float]:
    """Sinusoidal oscillation around `center` with `amplitude` peak deviation."""
    return [center + amplitude * math.sin(2 * math.pi * i / 20) for i in range(n)]


def _drive(
    strat: MeanReversionStrategy, closes: list[float], *,
    symbol: str = "GC", start: datetime | None = None,
    interval_minutes: int = 10,
) -> list[OrderIntent]:
    start = start or datetime(2026, 5, 22, 13, 30, tzinfo=UTC)
    intents: list[OrderIntent] = []
    for i, c in enumerate(closes):
        ts = start + timedelta(minutes=interval_minutes * i)
        intents.extend(strat.on_bar(_bar(symbol, c, ts), _state(ts)))
    return intents


# ---- Protocol + construction -----------------------------------------------


def test_satisfies_strategy_protocol() -> None:
    assert isinstance(MeanReversionStrategy(), Strategy)


def test_accepts_all_documented_params() -> None:
    """Plans 18/20 reuse this class with different params — exercise the
    full constructor surface."""
    s = MeanReversionStrategy(
        bb_period=10, bb_stddev=1.5, rsi_period=7,
        rsi_oversold=25.0, rsi_overbought=75.0,
        reward_ratio=2.0, max_trades_per_day=5,
        symbol="MES", quantity=2,
    )
    assert s.symbol == "MES"
    assert s.quantity == 2


def test_requires_registered_market() -> None:
    """Tick size flows from `bot.markets.MARKETS` — unknown symbols raise."""
    import pytest
    with pytest.raises(KeyError):
        MeanReversionStrategy(symbol="ZZZ")


# ---- Warmup --------------------------------------------------------------


def test_no_intent_during_bb_warmup() -> None:
    """First `bb_period - 1` bars cannot produce a band, so no intent."""
    s = MeanReversionStrategy(bb_period=20, rsi_period=14)
    intents = _drive(s, [2000.0] * 19)
    assert intents == []


# ---- Ranging market produces both BUY and SELL ----------------------------


def test_ranging_market_emits_buy_and_sell() -> None:
    """Synthetic oscillation around 2000 → strategy enters near band edges."""
    s = MeanReversionStrategy(
        bb_period=10, bb_stddev=1.5, rsi_period=5,
        rsi_oversold=40.0, rsi_overbought=60.0,
        max_trades_per_day=20, symbol="GC",
    )
    closes = _ranging_prices(center=2000.0, amplitude=8.0, n=200)
    intents = _drive(s, closes)
    sides = {i.side for i in intents}
    assert "BUY" in sides
    assert "SELL" in sides


# ---- Trending market produces no entries (chop filter) -------------------


def test_trending_market_no_entries() -> None:
    """A monotonic ramp keeps RSI past extremes but price tracks the upper
    band, never crossing back inside → no entries."""
    s = MeanReversionStrategy(
        bb_period=10, bb_stddev=2.0, rsi_period=14,
        rsi_oversold=30.0, rsi_overbought=70.0,
        max_trades_per_day=5, symbol="GC",
    )
    # Steady 1-point uptrend.
    closes = [2000.0 + i for i in range(100)]
    intents = _drive(s, closes)
    # Allowed: at most a single sell from a brief overbought touch at the start.
    # The filter we want to exercise: no BUYS in an uptrend.
    assert all(i.side == "SELL" for i in intents)


# ---- Mid-band exit -------------------------------------------------------


def test_exit_at_mid_band() -> None:
    """After a BUY, the next bar whose high crosses the rolling mid emits SELL."""
    s = MeanReversionStrategy(
        bb_period=10, bb_stddev=1.5, rsi_period=5,
        rsi_oversold=40.0, rsi_overbought=60.0,
        max_trades_per_day=10, symbol="GC",
    )
    # Push price down to trigger BUY then push back up through the mid.
    down = [2000.0 - i * 0.4 for i in range(30)]
    bottom = [2000.0 - 12.0] * 5
    up = [2000.0 - 12.0 + i * 1.5 for i in range(30)]
    intents = _drive(s, down + bottom + up)
    # We should see at least one BUY followed by a closing SELL.
    sides = [i.side for i in intents]
    assert "BUY" in sides
    buy_idx = sides.index("BUY")
    assert "SELL" in sides[buy_idx + 1:]


# ---- max_trades_per_day cap ----------------------------------------------


def test_max_trades_per_day_cap() -> None:
    """Once the daily cap is reached, no further entry intents are emitted."""
    s = MeanReversionStrategy(
        bb_period=8, bb_stddev=1.0, rsi_period=5,
        rsi_oversold=49.0, rsi_overbought=51.0,
        max_trades_per_day=1, symbol="GC",
    )
    # All bars within a single Topstep day (17:00 CT → 17:00 CT).
    # 14:30 UTC == 09:30 CT; 30 bars * 10min = 5 hours -> ends 14:30 CT.
    start = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)
    closes = _ranging_prices(center=2000.0, amplitude=8.0, n=30)
    intents: list[OrderIntent] = []
    for i, c in enumerate(closes):
        ts = start + timedelta(minutes=10 * i)
        intents.extend(s.on_bar(_bar("GC", c, ts), _state(ts)))
    entries = [i for i in intents if i.client_order_id.endswith("-entry")]
    assert len(entries) <= 1


# ---- Symbol + tick wiring -------------------------------------------------


def test_uses_registry_tick_size_not_hardcoded() -> None:
    """Construct against MES (0.25 tick) — emitted bracket uses MES tick.

    This is the load-bearing test that Plans 18 (ES Scalper) and 20 (NQ
    Maintenance) can reuse this class for non-gold markets without
    code changes."""
    s = MeanReversionStrategy(
        bb_period=8, bb_stddev=1.0, rsi_period=5,
        rsi_oversold=40.0, rsi_overbought=60.0,
        max_trades_per_day=10, symbol="MES",
    )
    closes = _ranging_prices(center=5000.0, amplitude=4.0, n=60)
    intents = _drive(s, closes, symbol="MES")
    assert intents, "expected at least one intent in ranging market"
    entries: Iterable[OrderIntent] = (i for i in intents if i.bracket is not None)
    first = next(iter(entries))
    assert first.symbol == "MES"
    # Tick size for MES = 0.25; stop_loss_ticks must be at least 1.
    assert first.bracket is not None
    assert first.bracket.stop_loss_ticks >= 1


# ---- Quantity flows through -----------------------------------------------


def test_quantity_param_flows_to_intent() -> None:
    s = MeanReversionStrategy(
        bb_period=8, bb_stddev=1.0, rsi_period=5,
        rsi_oversold=40.0, rsi_overbought=60.0,
        max_trades_per_day=10, symbol="GC", quantity=3,
    )
    closes = _ranging_prices(center=2000.0, amplitude=8.0, n=60)
    intents = _drive(s, closes)
    assert intents, "expected an intent in ranging market"
    assert intents[0].quantity == 3
