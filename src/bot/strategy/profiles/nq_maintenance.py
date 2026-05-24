"""NQ Maintenance defaults — wide-BB, low-frequency MeanReversionStrategy.

Mirrors the strategy_params section of `config/bots/nq_maintenance.yml`. The
24/7 live-only maintenance bot trades far less often than Gold Bot:

  * bb_period 50 + bb_stddev 3.0 — only extreme moves pierce the band.
  * rsi_period 21 + 20/80 thresholds — only extreme oversold/overbought.
  * reward_ratio 0.5 — small TP, higher win rate, slow accumulation.
  * max_trades_per_day 2 — hard cap; the schedule is 24/7 but the bot
                            stays on the bench most of the time.

Symbol is `MNQH26` to match `config/bots/nq_maintenance.yml` so the
gate-bound symbol and the strategy-emitted symbol align (regression
coverage in `test_propbot_strategy_params_include_symbol_match`-style
assertions).
"""
from __future__ import annotations

from typing import Any, Final

NQ_MAINTENANCE_DEFAULTS: Final[dict[str, Any]] = {
    "bb_period": 50,
    "bb_stddev": 3.0,
    "rsi_period": 21,
    "rsi_oversold": 20.0,
    "rsi_overbought": 80.0,
    "reward_ratio": 0.5,
    "max_trades_per_day": 2,
    "symbol": "MNQH26",
    "quantity": 1,
}
