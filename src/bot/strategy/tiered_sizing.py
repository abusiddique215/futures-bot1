"""TieredSizingDecorator — wrap any Strategy with equity-based position scaling.

The Voodoo lineup (SurgeBot, PropBot, etc.) sizes positions by realised
profit: 1 contract at start, 2 at +$500, 4 at +$1_500, 5 at +$2_500. This
decorator implements that scaling on top of an *unchanged* inner strategy.

Key constraints (see tests for the failure modes):

* `OrderIntent` is frozen — we return a `dataclasses.replace`d copy.
* Open and close intents on the same position must use the **same** quantity.
  ORB emits a BRACKET on open and a MARKET on close (both at qty=1 in the
  profile). If the equity tier changes between open and close, sizing the
  close at the new tier would flip the position. The decorator remembers
  the qty it sized each open at (per symbol) and re-uses it for the close.
* Tier breakpoints arrive as YAML lists-of-lists; we normalise to
  (profit, qty) tuples and sort ascending by profit so the highest matching
  threshold wins.
* Micro contracts (e.g. MNQ, MES, MGC) scale the per-tier qty by 10. The
  symbol arg is used as the gating key — when the symbol is a known micro
  in `bot.markets.registry.MARKETS`, the micro multiplier applies.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace

from bot.backtest.strategy import Strategy
from bot.markets.registry import MARKETS
from bot.types import AccountState, Bar, OrderIntent

_DEFAULT_BREAKPOINTS: tuple[tuple[float, int], ...] = (
    (0.0, 1),
    (500.0, 2),
    (1_500.0, 4),
    (2_500.0, 5),
)

_MICRO_MULTIPLIER = 10


def _normalise(
    breakpoints: Sequence[Sequence[float | int]] | Sequence[tuple[float, int]],
) -> list[tuple[float, int]]:
    """Coerce list-of-lists / list-of-tuples to sorted list of (profit, qty) tuples."""
    out: list[tuple[float, int]] = []
    for entry in breakpoints:
        profit, qty = entry[0], entry[1]
        out.append((float(profit), int(qty)))
    out.sort(key=lambda p: p[0])
    return out


def _is_micro_symbol(symbol: str) -> bool:
    """True iff the symbol root is a registered micro contract.

    A micro is a MARKETS entry whose `micro_root` is None AND that is itself
    targeted by some other MARKETS entry's `micro_root`. Equivalent shortcut:
    the symbol appears as some entry's `micro_root` value.
    """
    return symbol in {spec.micro_root for spec in MARKETS.values() if spec.micro_root}


class TieredSizingDecorator:
    """Wrap a `Strategy`, overriding each emitted intent's qty by equity tier.

    Implements `bot.backtest.strategy.Strategy` so it composes with the same
    engine + live loop as the inner strategy.
    """

    def __init__(
        self,
        inner: Strategy,
        tier_breakpoints: Sequence[Sequence[float | int]]
            | Sequence[tuple[float, int]]
            | None = None,
        symbol: str = "MNQ",
    ) -> None:
        self._inner = inner
        self._breakpoints = (
            _normalise(tier_breakpoints)
            if tier_breakpoints is not None
            else list(_DEFAULT_BREAKPOINTS)
        )
        if not self._breakpoints:
            raise ValueError("tier_breakpoints must contain at least one entry")
        self._symbol = symbol
        self._micro_multiplier = (
            _MICRO_MULTIPLIER if _is_micro_symbol(symbol) else 1
        )
        # Per-symbol qty applied to the currently-open leg; cleared on close.
        self._open_qty: dict[str, int] = {}

    # ---- Strategy protocol ----------------------------------------------------

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        profit = state.equity - state.start_balance
        current_tier_qty = self._tier_for(profit) * self._micro_multiplier
        out: list[OrderIntent] = []
        for intent in self._inner.on_bar(bar, state):
            out.append(self._resize(intent, current_tier_qty))
        return out

    # ---- Internals ------------------------------------------------------------

    def _tier_for(self, profit: float) -> int:
        """Linear scan: pick the qty for the highest breakpoint <= profit."""
        qty = self._breakpoints[0][1]
        for threshold, tier_qty in self._breakpoints:
            if profit >= threshold:
                qty = tier_qty
            else:
                break
        return qty

    def _resize(self, intent: OrderIntent, current_tier_qty: int) -> OrderIntent:
        """Pick the qty for this intent based on whether it opens or closes a position.

        BRACKET = open: use current tier qty, remember it for the matching close.
        Other order types are treated as closes for symbols we tracked an open
        for; otherwise they get the current tier qty too (a defensive default
        for strategies that emit non-bracket opens).
        """
        symbol = intent.symbol
        if intent.order_type == "BRACKET":
            self._open_qty[symbol] = current_tier_qty
            return replace(intent, quantity=current_tier_qty)

        remembered = self._open_qty.pop(symbol, None)
        if remembered is not None:
            return replace(intent, quantity=remembered)
        return replace(intent, quantity=current_tier_qty)
