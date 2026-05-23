"""Configuration for TopstepRiskGate. See spec 04 §3.7."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Env = Literal["backtest", "paper", "live"]
ConsistencyMode = Literal["soft", "hard"]


class RiskConfig(BaseModel):
    """Per-spec 04 §3.7."""
    model_config = ConfigDict(validate_default=True)

    env: Env
    accounts_managed: int = Field(default=1, ge=1, le=1)  # v1 single-account
    consistency_mode: ConsistencyMode = "soft"
    hft_cancel_to_fill_threshold: float = Field(default=5.0, gt=0)
    safety_buffer_ticks: int = Field(default=5, ge=0)
    tick_cadence_seconds: float = Field(default=1.0, gt=0)
    news_calendar_path: str | None = None
