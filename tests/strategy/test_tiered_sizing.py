"""TieredSizingDecorator — equity-based position scaling on top of any Strategy.

Covers tier breakpoints (mini + micro), inner pass-through, open/close
qty pairing (close uses the qty the open was sized at, not the current
tier — crucial when equity crosses a breakpoint between entry and exit),
and breakpoint normalisation (YAML deserialises list-of-lists, not tuples).
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Final

from bot.strategy.tiered_sizing import TieredSizingDecorator
from bot.types import AccountState, Bar, Bracket, OrderIntent

_TS: Final[datetime] = datetime(2026, 5, 22, 14, 30, tzinfo=UTC)


def _state(equity: float, *, start_balance: float = 50_000.0) -> AccountState:
    return AccountState(
        equity=equity,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        open_positions={},
        pending_intent_count=0,
        high_water_equity=max(equity, start_balance),
        is_combine=True,
        timestamp=_TS,
        start_balance=start_balance,
    )


def _bar(symbol: str = "MNQ") -> Bar:
    return Bar(
        symbol=symbol, open=18_000, high=18_010, low=17_990, close=18_005,
        volume=100, timestamp=_TS, interval="1m",
    )


def _open(symbol: str = "MNQ", side: str = "BUY", coid: str = "open-1") -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=1,
        order_type="BRACKET",
        client_order_id=coid,
        timestamp=_TS,
        bracket=Bracket(stop_loss_ticks=4, take_profit_ticks=8),
    )


def _close(symbol: str = "MNQ", side: str = "SELL", coid: str = "close-1") -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=1,
        order_type="MARKET",
        client_order_id=coid,
        timestamp=_TS,
    )


class _ScriptedStrategy:
    """Strategy stub: emits the queued intents on each successive on_bar call."""

    def __init__(self, scripts: list[list[OrderIntent]]) -> None:
        self._scripts = scripts
        self._call = 0

    def on_bar(self, bar: Bar, state: AccountState) -> Iterable[OrderIntent]:
        if self._call >= len(self._scripts):
            return []
        out = self._scripts[self._call]
        self._call += 1
        return out


# ---- Tier breakpoint selection ----------------------------------------------

def test_profit_below_first_breakpoint_uses_tier_one_micro() -> None:
    inner = _ScriptedStrategy([[_open()]])
    dec = TieredSizingDecorator(inner=inner, symbol="MNQ")
    out = list(dec.on_bar(_bar(), _state(equity=50_000.0)))
    assert len(out) == 1
    # MNQ is micro → tier 1 * 10 = 10 contracts.
    assert out[0].quantity == 10


def test_profit_above_500_uses_tier_two_micro() -> None:
    inner = _ScriptedStrategy([[_open()]])
    dec = TieredSizingDecorator(inner=inner, symbol="MNQ")
    out = list(dec.on_bar(_bar(), _state(equity=51_000.0)))
    assert len(out) == 1
    assert out[0].quantity == 20  # tier 2 micro = 20.


def test_profit_above_2500_uses_top_tier_micro() -> None:
    inner = _ScriptedStrategy([[_open()]])
    dec = TieredSizingDecorator(inner=inner, symbol="MNQ")
    out = list(dec.on_bar(_bar(), _state(equity=53_000.0)))
    assert len(out) == 1
    assert out[0].quantity == 50  # tier 5 micro = 50.


def test_mini_symbol_does_not_multiply() -> None:
    inner = _ScriptedStrategy([[_open(symbol="NQ")]])
    dec = TieredSizingDecorator(inner=inner, symbol="NQ")
    out = list(dec.on_bar(_bar("NQ"), _state(equity=51_000.0)))
    assert len(out) == 1
    assert out[0].quantity == 2  # tier 2 mini = 2.


# ---- Inner pass-through ------------------------------------------------------

def test_empty_inner_output_yields_empty() -> None:
    inner = _ScriptedStrategy([[]])
    dec = TieredSizingDecorator(inner=inner, symbol="MNQ")
    assert list(dec.on_bar(_bar(), _state(equity=50_000.0))) == []


def test_bracket_preserved_on_open() -> None:
    inner = _ScriptedStrategy([[_open()]])
    dec = TieredSizingDecorator(inner=inner, symbol="MNQ")
    out = list(dec.on_bar(_bar(), _state(equity=50_000.0)))
    assert out[0].bracket is not None
    assert out[0].bracket.stop_loss_ticks == 4
    assert out[0].bracket.take_profit_ticks == 8


def test_preserves_other_intent_fields() -> None:
    inner = _ScriptedStrategy([[_open(coid="alpha")]])
    dec = TieredSizingDecorator(inner=inner, symbol="MNQ")
    out = list(dec.on_bar(_bar(), _state(equity=50_000.0)))
    assert out[0].client_order_id == "alpha"
    assert out[0].side == "BUY"
    assert out[0].order_type == "BRACKET"


# ---- Open/close pairing ------------------------------------------------------

def test_close_uses_open_qty_when_tier_changes_between() -> None:
    """Open at tier 1 (10 micros), equity climbs into tier 2, close still 10.

    Otherwise we'd flip the position: open 10 long → close 20 → 10 short.
    """
    inner = _ScriptedStrategy([[_open()], [_close()]])
    dec = TieredSizingDecorator(inner=inner, symbol="MNQ")
    open_out = list(dec.on_bar(_bar(), _state(equity=50_000.0)))
    assert open_out[0].quantity == 10
    close_out = list(dec.on_bar(_bar(), _state(equity=52_000.0)))
    assert len(close_out) == 1
    assert close_out[0].quantity == 10  # mirrors the open, not the current tier.


def test_second_open_after_close_uses_current_tier() -> None:
    """Close clears the remembered open qty so the next open sizes fresh."""
    inner = _ScriptedStrategy([
        [_open(coid="o1")],
        [_close(coid="c1")],
        [_open(coid="o2")],
    ])
    dec = TieredSizingDecorator(inner=inner, symbol="MNQ")
    list(dec.on_bar(_bar(), _state(equity=50_000.0)))  # tier 1 open
    list(dec.on_bar(_bar(), _state(equity=52_000.0)))  # close at tier 1 qty
    second_open = list(dec.on_bar(_bar(), _state(equity=52_000.0)))
    assert second_open[0].quantity == 40  # tier 4 micro on re-entry.


# ---- Configuration -----------------------------------------------------------

def test_list_of_lists_breakpoints_normalised() -> None:
    """YAML-loaded `[[0,1],[500,2]]` must work alongside list-of-tuples."""
    inner = _ScriptedStrategy([[_open()]])
    dec = TieredSizingDecorator(
        inner=inner,
        tier_breakpoints=[[0, 1], [500, 2]],  # type: ignore[list-item]
        symbol="MNQ",
    )
    out = list(dec.on_bar(_bar(), _state(equity=50_600.0)))
    assert out[0].quantity == 20  # tier 2 micro.


def test_unsorted_breakpoints_sorted_internally() -> None:
    inner = _ScriptedStrategy([[_open()]])
    dec = TieredSizingDecorator(
        inner=inner,
        tier_breakpoints=[(2500, 5), (0, 1), (500, 2), (1500, 4)],
        symbol="MNQ",
    )
    out = list(dec.on_bar(_bar(), _state(equity=51_600.0)))  # +$1_600 → tier 4.
    assert out[0].quantity == 40


def test_breakpoint_inclusive_boundary() -> None:
    """Profit exactly at a breakpoint takes the higher tier."""
    inner = _ScriptedStrategy([[_open()]])
    dec = TieredSizingDecorator(inner=inner, symbol="MNQ")
    out = list(dec.on_bar(_bar(), _state(equity=50_500.0)))
    assert out[0].quantity == 20  # +$500 exactly → tier 2.
