"""PropBot defaults — kwargs for `TrendFollowingStrategy`.

These are the values shipped in `config/bots/propbot_nq.yml`. Exposed as a
Python dict so tests can pin them without re-parsing YAML, and so the
BotRegistry factory can default any param missing from the spec.

Session_end_ct mirrors the YAML's `schedule_params.close_ct` (14:30 CT) so
the bot is flat before EFA Standard's EoD ratchet — accepted duplication
called out in the plan.
"""
from __future__ import annotations

from datetime import time
from typing import Any, Final

PROPBOT_DEFAULTS: Final[dict[str, Any]] = {
    "fast_ema": 20,
    "slow_ema": 50,
    "pullback_atr_mult": 0.5,
    "reward_ratio": 1.5,
    "max_trades_per_day": 1,
    "session_end_ct": time(14, 30),
}
