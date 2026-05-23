"""Opening Range Breakout strategy + ORBProfile.

The Strategy emits BUY/SELL bracketed intents after the opening range completes
and price closes outside the range. Stop is `atr_mult x ATR`, take-profit is
`tp_r_multiple x stop_distance`. Session-time logic uses America/New_York.

Spec: Plan 5.
"""
from __future__ import annotations

from datetime import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bot.types import Bar


class ORBProfile(BaseModel):
    """Per-profile ORB tuning. Loaded from YAML by ``profile_loader.load_orb_profile``."""

    model_config = ConfigDict(validate_default=True)

    symbol: Literal["MNQ", "NQ"] = "MNQ"
    quantity: int = Field(default=1, ge=1)
    range_minutes: int = Field(default=5, ge=1, le=30)
    atr_period: int = Field(default=14, ge=1)
    atr_mult: float = Field(default=1.0, gt=0)
    tp_r_multiple: float = Field(default=2.0, gt=0)
    session_start_et: time = time(9, 30)
    cutoff_time_et: time | None = None
    max_trades_per_day: int = Field(default=1, ge=1)


def _compute_atr(bars: list[Bar], period: int) -> float | None:
    """ATR = simple average of the last ``period`` True Ranges.

    True Range = max(high-low, |high - prev_close|, |low - prev_close|).
    Requires ``period + 1`` bars (one prior close + ``period`` TRs). Returns
    ``None`` when fewer than ``period + 1`` bars are available.
    """
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        h = bars[i].high
        low = bars[i].low
        tr = max(h - low, abs(h - prev_close), abs(low - prev_close))
        trs.append(tr)
    last = trs[-period:]
    return sum(last) / period
