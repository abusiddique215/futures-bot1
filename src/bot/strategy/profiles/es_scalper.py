"""ES Scalper — MeanReversionStrategy defaults (tighter than Gold Bot).

Mirrors the strategy_params section of `config/bots/es_scalper.yml`.
Importing this module gives test code + future Python-side BotSpec
builders a single source of truth for the ES Scalper tuning.

Sibling of `bot.strategy.profiles.gold_bot`. The class
(`MeanReversionStrategy`) is reused across both bots — the parameter
tightening (shorter BB, smaller TP via `reward_ratio`, higher daily
trade cap) is what gives ES Scalper its faster turnaround vs Gold Bot.
"""
from __future__ import annotations

from typing import Any, Final

ES_SCALPER_DEFAULTS: Final[dict[str, Any]] = {
    "bb_period": 10,        # shorter than Gold's 20 — faster signals
    "bb_stddev": 1.5,       # tighter than 2.0 — more entries
    "rsi_period": 9,        # shorter — more sensitive
    "rsi_oversold": 35.0,   # tighter thresholds
    "rsi_overbought": 65.0,
    "reward_ratio": 0.75,   # smaller TP — scalper ethos
    "max_trades_per_day": 10,
    "symbol": "MES",
    "quantity": 1,
}
