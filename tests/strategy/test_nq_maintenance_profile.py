"""NQ_MAINTENANCE_DEFAULTS — schema + low-frequency sanity check.

Plan 20 T3. The maintenance profile is a wide-BB / relaxed-RSI tuning of
`MeanReversionStrategy` — verifies the defaults match the strategy's kwarg
schema (so the registry can pass them through unchanged) and that a year
of deterministic sinusoidal bars rarely pierces the wide bands.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from bot.strategy.mean_reversion import MeanReversionStrategy
from bot.strategy.profiles.nq_maintenance import NQ_MAINTENANCE_DEFAULTS
from bot.types import AccountState, Bar


def test_defaults_have_expected_keys() -> None:
    expected = {
        "bb_period", "bb_stddev", "rsi_period",
        "rsi_oversold", "rsi_overbought", "reward_ratio",
        "max_trades_per_day", "symbol",
    }
    assert expected.issubset(set(NQ_MAINTENANCE_DEFAULTS.keys()))


def test_defaults_are_wide_and_low_frequency() -> None:
    d = NQ_MAINTENANCE_DEFAULTS
    # Wider than Gold Bot's 20/2.0 — the maintenance ethos.
    assert d["bb_period"] >= 50
    assert d["bb_stddev"] >= 3.0
    # Extreme RSI gates only.
    assert d["rsi_oversold"] <= 25.0
    assert d["rsi_overbought"] >= 75.0
    # Low-frequency cap.
    assert d["max_trades_per_day"] <= 2


def test_defaults_target_mnq() -> None:
    """NQ Maintenance trades the Nasdaq micro contract (MNQ)."""
    assert NQ_MAINTENANCE_DEFAULTS["symbol"].startswith("MNQ")


def test_profile_constructs_mean_reversion_strategy() -> None:
    """Defaults must satisfy MeanReversionStrategy.__init__'s schema as-is."""
    strat = MeanReversionStrategy(**NQ_MAINTENANCE_DEFAULTS)
    assert isinstance(strat, MeanReversionStrategy)
    assert strat.symbol == NQ_MAINTENANCE_DEFAULTS["symbol"]


def _sinusoidal_year_bars(symbol: str) -> list[Bar]:
    """One year of 5-min bars on a slow sinusoid + tiny micro-jitter.

    Amplitude 5 around 18000; the BB stddev settles near the amplitude / sqrt(2),
    so a 3-sigma band rarely pierces. Deterministic — no PRNG.
    """
    bars: list[Bar] = []
    start = datetime(2026, 1, 1, tzinfo=UTC)
    # 24h * 12 bars/hour * 252 trading days ≈ 72,576 bars; cap to keep the
    # test snappy. 252 trading days * 24h * 12 bars/hour = 72k is overkill —
    # use 252 calendar days at 12 bars/hour (288 bars/day) for ~72k bars.
    bars_per_day = 288  # 5-min bars across 24h
    n_days = 252
    n = bars_per_day * n_days
    period = 200  # bars; ~16h cycle
    for i in range(n):
        # Sinusoid + a slow drift so it's not perfectly periodic.
        price = 18000.0 + 5.0 * math.sin(2 * math.pi * i / period) + 0.001 * i
        bars.append(Bar(
            symbol=symbol, open=price, high=price + 0.25, low=price - 0.25,
            close=price, volume=10,
            timestamp=start + timedelta(minutes=5 * i),
            interval="5m",
        ))
    return bars


def test_year_of_sinusoidal_bars_is_low_frequency() -> None:
    """Sanity bound: deterministic sinusoid produces << 100 entries/year.

    A pure sinusoid never pierces a 3-sigma band (the band tracks the sine),
    so the count should be near zero. The bound is generous (< 100) to give
    room for the BB-warmup transient and the drift term.
    """
    strat = MeanReversionStrategy(**NQ_MAINTENANCE_DEFAULTS)
    state = AccountState(
        equity=50_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0,
        open_positions={}, pending_intent_count=0, high_water_equity=50_000.0,
        is_combine=False, timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )
    entries = 0
    for bar in _sinusoidal_year_bars(NQ_MAINTENANCE_DEFAULTS["symbol"]):
        for intent in strat.on_bar(bar, state):
            if intent.order_type == "BRACKET":
                entries += 1
    assert entries < 100, f"NQ Maintenance entries={entries}; expected << 100"
