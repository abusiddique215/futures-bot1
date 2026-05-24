"""SimAccount — frozen dataclass + pure stage / fill / mark-to-market transitions.

Mirrors the real Topstep account state machine (Combine → EFA → Funded) but
holds only what the simulator needs: balance, equity, realized/unrealized,
open positions, and a stage label. The risk policies (`CombineIntradayDrawdown`
et al.) consume `AccountState` from `bot.types`; the engine in
`bot.execution.topstepx_sim.engine` translates `SimAccount` → `AccountState`
on demand so the same policies grade sim and live identically.

Point value formula matches `bot.backtest.tracker._POINT_VALUE`:
TICK_VALUES[sym] / MIN_TICK[sym] → MNQ=$2/pt, NQ=$20/pt.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Final, Literal

from bot.constants import MIN_TICK, TICK_VALUES

Stage = Literal[
    "combine_active",
    "combine_passed",
    "combine_failed",
    "efa_active",
    "efa_payout",
    "efa_failed",
    "funded",
]

_POINT_VALUE: Final[dict[str, float]] = {
    sym: TICK_VALUES[sym] / MIN_TICK[sym] for sym in TICK_VALUES
}

# Legal stage transitions. Anything not listed raises ValueError.
_LEGAL_TRANSITIONS: Final[dict[Stage, frozenset[Stage]]] = {
    "combine_active": frozenset({"combine_passed", "combine_failed"}),
    "combine_passed": frozenset({"efa_active"}),
    "combine_failed": frozenset(),
    "efa_active": frozenset({"efa_payout", "efa_failed"}),
    "efa_payout": frozenset({"funded", "efa_active"}),
    "efa_failed": frozenset(),
    "funded": frozenset(),
}


@dataclass(frozen=True, slots=True)
class SimFill:
    """A completed fill produced by the sim engine."""
    symbol: str
    signed_qty: int           # +long, -short
    fill_price: float
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class SimAccount:
    """Snapshot of the simulated Topstep account at one instant."""
    balance: float
    equity: float
    high_water_equity: float
    realized_pnl: float
    unrealized_pnl: float
    # symbol -> (signed_qty, avg_entry_price)
    open_positions: dict[str, tuple[int, float]] = field(default_factory=dict)
    last_mark: dict[str, float] = field(default_factory=dict)
    stage: Stage = "combine_active"
    start_balance: float = 50_000.0
    mll_amount: float = 2_000.0

    @classmethod
    def new(
        cls,
        *,
        start_balance: float,
        mll_amount: float,
        stage: Stage = "combine_active",
    ) -> SimAccount:
        return cls(
            balance=start_balance,
            equity=start_balance,
            high_water_equity=start_balance,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            open_positions={},
            last_mark={},
            stage=stage,
            start_balance=start_balance,
            mll_amount=mll_amount,
        )


def apply_fill(account: SimAccount, fill: SimFill) -> SimAccount:
    """Apply a fill to the account, realizing P&L on close / flip."""
    positions = dict(account.open_positions)
    realized = account.realized_pnl
    current = positions.get(fill.symbol)

    if current is None:
        positions[fill.symbol] = (fill.signed_qty, fill.fill_price)
    else:
        cur_qty, cur_avg = current
        new_qty = cur_qty + fill.signed_qty
        same_sign = cur_qty * new_qty > 0 and abs(new_qty) > abs(cur_qty)
        if new_qty == 0 or (cur_qty * new_qty < 0):
            # Closing or flipping; realize on the closed portion.
            closed_signed_qty = (
                min(abs(cur_qty), abs(fill.signed_qty)) * (1 if cur_qty > 0 else -1)
            )
            pnl = (
                (fill.fill_price - cur_avg)
                * closed_signed_qty
                * _POINT_VALUE[fill.symbol]
            )
            realized += pnl
            if new_qty == 0:
                del positions[fill.symbol]
            else:
                positions[fill.symbol] = (new_qty, fill.fill_price)
        elif same_sign:
            # Adding to existing same-side position — weighted avg entry.
            new_avg = (
                (cur_avg * abs(cur_qty) + fill.fill_price * abs(fill.signed_qty))
                / abs(new_qty)
            )
            positions[fill.symbol] = (new_qty, new_avg)
        else:
            # Should not happen: same-side reducer would have hit close branch.
            positions[fill.symbol] = (new_qty, cur_avg)

    new_balance = account.start_balance + realized
    unrealized = _compute_unrealized(positions, account.last_mark)
    new_equity = new_balance + unrealized
    new_hw = max(account.high_water_equity, new_equity)
    return replace(
        account,
        balance=new_balance,
        equity=new_equity,
        high_water_equity=new_hw,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        open_positions=positions,
    )


def mark_to_market(
    account: SimAccount, *, mid_price: float, symbol: str,
) -> SimAccount:
    """Update unrealized P&L for `symbol` from the latest mid; refresh equity."""
    last_mark = dict(account.last_mark)
    last_mark[symbol] = mid_price
    unrealized = _compute_unrealized(account.open_positions, last_mark)
    new_equity = account.balance + unrealized
    new_hw = max(account.high_water_equity, new_equity)
    return replace(
        account,
        unrealized_pnl=unrealized,
        equity=new_equity,
        high_water_equity=new_hw,
        last_mark=last_mark,
    )


def advance_stage(account: SimAccount, target: Stage) -> SimAccount:
    """Move the account to `target`; raise on illegal transition."""
    if target not in _LEGAL_TRANSITIONS[account.stage]:
        raise ValueError(
            f"illegal transition: {account.stage!r} -> {target!r}",
        )
    return replace(account, stage=target)


def _compute_unrealized(
    positions: dict[str, tuple[int, float]],
    last_mark: dict[str, float],
) -> float:
    total = 0.0
    for sym, (qty, avg) in positions.items():
        mark = last_mark.get(sym)
        if mark is None:
            continue
        total += (mark - avg) * qty * _POINT_VALUE[sym]
    return total
