"""Gold Bot — MeanReversionStrategy defaults.

Mirrors the strategy_params section of `config/bots/gold_bot.yml`. Importing
this module gives test code + future Python-side BotSpec builders a single
source of truth for the Gold Bot tuning.

The constants here are also the reference values for Plans 18 (ES Scalper)
and 20 (NQ Maintenance) when they author their own MeanReversionStrategy
profiles — change a knob here without grepping the YAML.
"""
from __future__ import annotations

from typing import Any, Final

GOLD_BOT_DEFAULTS: Final[dict[str, Any]] = {
    "bb_period": 20,
    "bb_stddev": 2.0,
    "rsi_period": 14,
    "rsi_oversold": 30.0,
    "rsi_overbought": 70.0,
    "reward_ratio": 1.0,
    "max_trades_per_day": 3,
    "symbol": "MGCH26",
    "quantity": 1,
}
