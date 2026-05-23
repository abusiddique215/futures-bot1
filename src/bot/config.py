"""Pydantic v2 configuration models for the futures bot.

Spec: 07-config-and-deploy.md §3.1.

Two cross-field validators (broker_matches_env, force_after_warning) live on
BotConfig — they're added in the next task so this file can be split into
small bite-sized test passes.
"""
from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---- Sub-configs ------------------------------------------------------------

class DataConfig(BaseModel):
    """Data pipeline settings. See spec 01 + 07 §3.1."""
    historical_root: Path                           # parquet store
    historical_vendor: Literal["firstratedata"]
    live_source: Literal["ib", "topstepx"]
    symbol_primary: Literal["MNQ", "NQ"] = "MNQ"
    bar_seconds: int = Field(default=60, ge=1)      # 1-min bars by default


class TelegramConfig(BaseModel):
    """Telegram alerts. Actual token / chat_id live in env vars; these fields
    name the env vars, they are NOT secrets themselves.

    NB: severity strings match 06-observability.md §3.2 / §3.6 (WARN, not WARNING).
    """
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    min_severity: Literal["INFO", "WARN", "CRITICAL"] = "WARN"


# ---- Root config ------------------------------------------------------------

Env = Literal["dev", "paper", "live"]
Broker = Literal["sim", "ib_paper", "topstepx"]
RiskPolicyTag = Literal[
    "combine_50k",
    "efa_standard_50k",
    "efa_consistency_50k",
]


class BotConfig(BaseModel):
    """Root configuration loaded from bot/config/bot.yml.

    Cross-field validators (broker_matches_env, force_after_warning) are
    attached in the next task. validate_default=True ensures those validators
    run against default values too — so a YAML that omits flat_by_force_ct
    can't silently bypass force_after_warning.
    """
    model_config = ConfigDict(validate_default=True)

    env: Env
    broker: Broker
    account_id: str                                 # IB account or TopstepX accountId
    strategy: Literal["orb"]
    strategy_profile: Path                          # path to surge.yml or maintenance.yml
    risk_policy: RiskPolicyTag
    data: DataConfig
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    news_calendar: Path
    flat_by_warning_ct: time = time(14, 0)          # soft warn — 04-risk-engine
    flat_by_force_ct:   time = time(15, 10)         # hard flatten — 04-risk-engine
    halt_on_journal_desync: bool = True
