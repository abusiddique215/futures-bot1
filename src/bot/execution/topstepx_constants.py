"""TopstepX wire-protocol constants — DEFENSIVE, DO NOT CHANGE.

ProjectX / TopstepX inverts the conventional 0/1 side encoding:
  - 0 = Bid side = BUY (you are hitting the bid to buy)
  - 1 = Ask side = SELL (you are hitting the ask to sell)

The intuitive (and wrong) reading is 0=SELL, 1=BUY. A junior dev
refactoring this file will get it backwards. Every silent loss in the
TopstepX community forum starts here.

If you "simplify" these constants you WILL lose real money. The required
unit test in tests/test_topstepx_side_encoding.py exists to catch any PR
that breaks this contract.

Source: gateway.docs.projectx.com/docs/api-reference/order/order-place/
Spec: 02-execution-clients.md §3.4.

Search terms (for future git-log archaeology): SIDE_BUY=0 footgun.
"""
from __future__ import annotations

from typing import Final, Literal

# TopstepX wire protocol — DO NOT REORDER, DO NOT CHANGE.
# These constants are loud on purpose. If you "simplify" them you will lose money.
SIDE_BUY: Final[int] = 0   # Bid
SIDE_SELL: Final[int] = 1  # Ask

_SIDE_MAP: Final[dict[Literal["BUY", "SELL"], int]] = {
    "BUY": SIDE_BUY,
    "SELL": SIDE_SELL,
}


def topstepx_side(side: Literal["BUY", "SELL"]) -> int:
    """Map a broker-agnostic side string to the TopstepX wire integer.

    Raises KeyError on unknown side — defensive against silent fall-through
    to a default that would mean BUY.
    """
    return _SIDE_MAP[side]
