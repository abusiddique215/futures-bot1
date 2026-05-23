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
