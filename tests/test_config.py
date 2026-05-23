"""Tests for Pydantic config models.

Spec: 07-config-and-deploy.md §3.1.
"""
from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest
from pydantic import ValidationError


def _valid_config_kwargs() -> dict[str, object]:
    """Minimal kwargs that produce a valid BotConfig. Tests mutate copies of this
    to verify specific validator paths."""
    return {
        "env": "dev",
        "broker": "sim",
        "account_id": "sim-0",
        "strategy": "orb",
        "strategy_profile": Path("config/profiles/surge.yml"),
        "risk_policy": "combine_50k",
        "data": {
            "historical_root": Path("data/parquet"),
            "historical_vendor": "firstratedata",
            "live_source": "ib",
        },
        "telegram": {},
        "news_calendar": Path("config/news_calendar.yml"),
    }


def test_data_config_defaults() -> None:
    from bot.config import DataConfig
    c = DataConfig(
        historical_root=Path("data/parquet"),
        historical_vendor="firstratedata",
        live_source="ib",
    )
    assert c.symbol_primary == "MNQ"
    assert c.bar_seconds == 60


def test_telegram_config_default_severity_is_WARN() -> None:
    """Severity is "WARN" (not "WARNING") to match 06-observability.md §3.2.
    See spec 07 §3.1."""
    from bot.config import TelegramConfig
    t = TelegramConfig()
    assert t.min_severity == "WARN"
    assert t.bot_token_env == "TELEGRAM_BOT_TOKEN"
    assert t.chat_id_env == "TELEGRAM_CHAT_ID"


def test_bot_config_minimal_valid() -> None:
    from bot.config import BotConfig
    c = BotConfig(**_valid_config_kwargs())
    assert c.env == "dev"
    assert c.broker == "sim"
    assert c.flat_by_force_ct == time(15, 10)
    assert c.flat_by_warning_ct == time(14, 0)
    assert c.halt_on_journal_desync is True


def test_bot_config_rejects_unknown_env() -> None:
    from bot.config import BotConfig
    kwargs = _valid_config_kwargs() | {"env": "production"}
    with pytest.raises(ValidationError):
        BotConfig(**kwargs)


def test_bot_config_rejects_unknown_risk_policy() -> None:
    from bot.config import BotConfig
    kwargs = _valid_config_kwargs() | {"risk_policy": "bogus_policy"}
    with pytest.raises(ValidationError):
        BotConfig(**kwargs)
