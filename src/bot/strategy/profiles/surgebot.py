"""SurgeBot defaults — Voodoo-shaped parameters for the NQ daily-exit bot.

SurgeBot is a `BotSpec` (Plan 12) wiring three pieces:
  * OpeningRangeBreakoutStrategy as the signal generator (placeholder for
    the VSL's undisclosed entry logic — see plan 15 for the disclosure)
  * TieredSizingDecorator with the [1, 2, 4, 5] tier ladder
  * CombineIntradayDrawdown as the risk policy (Combine-aggressive)

This module exposes the parameter dictionaries the registry's
"orb_5m_tiered" factory consumes. The structure mirrors what
`config/bots/surgebot_nq.yml` passes via `strategy_params`.

Tier breakpoints are MY DESIGN under the visible [1,2,4,5] tier list — the
VSL doesn't reveal exact dollar thresholds. The YAML keeps these
overridable.
"""
from __future__ import annotations

from typing import Any, Final

SURGEBOT_DEFAULTS: Final[dict[str, Any]] = {
    "strategy": {
        # OpeningRangeBreakoutStrategy / ORBProfile fields. Real field names
        # are `atr_mult` + `tp_r_multiple` (NOT `atr_multiplier` /
        # `reward_ratio` — see src/bot/strategy/orb.py).
        "symbol": "MNQ",
        "range_minutes": 5,
        "atr_mult": 1.0,
        "tp_r_multiple": 2.0,
        "max_trades_per_day": 2,
    },
    "tiered": {
        "tier_breakpoints": [
            (0.0, 1),
            (500.0, 2),
            (1_500.0, 4),
            (2_500.0, 5),
        ],
        "symbol": "MNQ",
    },
}
