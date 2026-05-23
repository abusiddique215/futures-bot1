"""RiskConfig validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_risk_config_valid() -> None:
    from bot.risk.config import RiskConfig
    c = RiskConfig(
        env="backtest",
        accounts_managed=1,
        consistency_mode="soft",
        hft_cancel_to_fill_threshold=5.0,
        safety_buffer_ticks=5,
        tick_cadence_seconds=1.0,
    )
    assert c.env == "backtest"
    assert c.consistency_mode == "soft"


def test_risk_config_default_safety_buffer_is_5() -> None:
    from bot.risk.config import RiskConfig
    c = RiskConfig(env="backtest", accounts_managed=1)
    assert c.safety_buffer_ticks == 5
    assert c.consistency_mode == "soft"


def test_risk_config_rejects_multi_account() -> None:
    """v1: single-account only. Cross-account hedging is a Topstep ToS violation."""
    from bot.risk.config import RiskConfig
    with pytest.raises(ValidationError):
        RiskConfig(env="backtest", accounts_managed=2)
