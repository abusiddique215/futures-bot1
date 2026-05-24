"""LiveOnlyGuard — refuses incompatible schedule x risk-policy pairings.

Plan 20 introduces NQ Maintenance, a 24/7 (`AlwaysOn`) bot. Combine accounts
require a hard-flat at 15:10 CT (see `CombineIntradayDrawdown`) — attaching
an `AlwaysOn` bot to a Combine policy means the schedule keeps re-entering
positions the risk gate is forced to close every afternoon. The guard
surfaces this misconfiguration at `BotRegistry.build()` time so the operator
sees the failure at boot, not after the bot starts firing into a closed
account.

Only the explicit pair `(schedule_type=always, risk_policy=combine_intraday)`
is refused. Other Combine variants do not exist today; if they're added in a
future plan, the registry's `_register_builtins` should add them to the
refusal set explicitly — see plan-20.md advisor notes for why a `combine_*`
prefix check would silently approve unknown variants.
"""
from __future__ import annotations

from typing import Final

_REFUSED_PAIRS: Final[frozenset[tuple[str, str]]] = frozenset({
    ("always", "combine_intraday"),
})


class IncompatibleBotSpecError(ValueError):
    """Raised when a BotSpec's schedule x risk_policy combination is unsafe."""


def validate_schedule_x_policy(schedule_type: str, risk_policy: str) -> None:
    """Raise `IncompatibleBotSpecError` for refused pairings.

    Pure function — no I/O, no spec lookup. Caller passes the literal
    `BotSpec.schedule_type` + `BotSpec.risk_policy` strings.
    """
    if (schedule_type, risk_policy) in _REFUSED_PAIRS:
        raise IncompatibleBotSpecError(
            "24/7 schedule (always) is incompatible with combine_intraday risk "
            "policy — Topstep Combine requires hard-flat at 15:10 CT. Use "
            "efa_standard for live/funded accounts."
        )
