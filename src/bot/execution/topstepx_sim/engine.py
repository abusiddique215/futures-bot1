"""TopstepSimEngine — in-memory broker that mirrors Topstep's account rules.

The engine consumes broker-agnostic `OrderIntent`s and produces canonical
`OrderEvent`s (FILLED / REJECTED), maintaining a `SimAccount` snapshot
between calls. It reuses the same `CombineIntradayDrawdown` / EFA policies
the live `TopstepRiskGate` uses — that is the sim/live parity guarantee.

Scope (v1):
  - Immediate fills at mid ± slippage; no partial fills, no working orders.
  - Phantom-MLL liquidation flips `stage` to `combine_failed` / `efa_failed`.
  - Hard-flat clock blocks NEW open exposure after `hard_flat_time_ct`;
    closes / reducers always allowed.
  - Max-position cap from the drawdown policy.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from datetime import time as dtime
from typing import Final
from zoneinfo import ZoneInfo

from bot.constants import HARD_FLAT_TIME_CT, MIN_TICK
from bot.execution.topstepx_constants import topstepx_side
from bot.execution.topstepx_sim.account import (
    SimAccount,
    SimFill,
    advance_stage,
    apply_fill,
    mark_to_market,
)
from bot.risk.combine_drawdown import CombineIntradayDrawdown
from bot.risk.efa_drawdown import EFAStandardEoDDrawdown
from bot.types import AccountState, OrderEvent, OrderIntent

_CT: Final[ZoneInfo] = ZoneInfo("America/Chicago")


class TopstepSimEngine:
    """Sim broker enforcing Topstep-flavored rules on submitted intents."""

    def __init__(
        self,
        *,
        account: SimAccount,
        combine_policy: CombineIntradayDrawdown,
        efa_policy: EFAStandardEoDDrawdown | None,
        slippage_ticks: int = 0,
        hard_flat_time_ct: dtime = HARD_FLAT_TIME_CT,
        now: Callable[[], datetime],
    ) -> None:
        self._account = account
        self._combine_policy = combine_policy
        self._efa_policy = efa_policy
        self._slippage_ticks = slippage_ticks
        self.hard_flat_time_ct = hard_flat_time_ct
        self._now: Callable[[], datetime] = now
        self._broker_id_counter = 0
        # Symbol → most recent mid the engine saw (for AccountState mapping).
        self._latest_mid: dict[str, float] = {}

    # ---- account access ------------------------------------------------

    @property
    def account(self) -> SimAccount:
        return self._account

    def now(self) -> datetime:
        return self._now()

    def set_now(self, ts: datetime) -> None:
        """Replace the clock source with a fixed timestamp.

        Test convenience — production code should pass a callable to __init__.
        """
        self._now = lambda: ts

    # ---- order submission ----------------------------------------------

    def submit_order(self, intent: OrderIntent, mid_price: float) -> OrderEvent:
        """Validate + fill an OrderIntent immediately.

        Returns a FILLED OrderEvent on accept, REJECTED on rule violation.
        """
        self._latest_mid[intent.symbol] = mid_price
        # 1. Hard-flat clock: only block NEW exposure.
        if self._is_after_hard_flat() and self._is_open_increasing(intent):
            return self._reject(intent, "HARD_FLAT_CLOCK")

        # 2. Max-position cap via active policy.
        cap = self._active_policy().max_position(intent.symbol, self._as_state(intent.timestamp))
        current = self._signed_qty_of(intent.symbol)
        projected = current + intent.signed_qty()
        if abs(projected) > cap:
            return self._reject(intent, "MAX_POSITION")

        # 3. Fill at mid ± slippage.
        fill_price = self._apply_slippage(intent, mid_price)
        fill = SimFill(
            symbol=intent.symbol,
            signed_qty=intent.signed_qty(),
            fill_price=fill_price,
            timestamp=intent.timestamp,
        )
        self._account = apply_fill(self._account, fill)
        self._account = mark_to_market(
            self._account, mid_price=mid_price, symbol=intent.symbol,
        )
        self._broker_id_counter += 1
        return OrderEvent(
            client_order_id=intent.client_order_id,
            broker_order_id=f"sim-{self._broker_id_counter}",
            status="FILLED",
            filled_quantity=intent.quantity,
            avg_fill_price=fill_price,
            timestamp=intent.timestamp,
            metadata={"topstepx_side": topstepx_side(intent.side)},
        )

    def cancel_order(self, client_order_id: str) -> OrderEvent:
        """Sim fills are immediate, so every cancel is too late."""
        return OrderEvent(
            client_order_id=client_order_id,
            broker_order_id="",
            status="REJECTED",
            filled_quantity=0,
            avg_fill_price=None,
            timestamp=self._now(),
            metadata={"reason": "TOO_LATE"},
        )

    # ---- mark-to-market + EoD ------------------------------------------

    def tick(self, mid_price: float, symbol: str) -> SimAccount:
        """Mark-to-market; liquidate at MLL floor if equity touches it."""
        self._latest_mid[symbol] = mid_price
        self._account = mark_to_market(
            self._account, mid_price=mid_price, symbol=symbol,
        )
        state = self._as_state(self._now())
        policy = self._active_policy()
        state = policy.update_on_tick(state)
        phantom = policy.phantom_mll(state)
        if state.equity <= phantom:
            self._flatten_at(mid_price, symbol)
            self._account = self._mark_failed()
        return self._account

    def eod(self, mid_price: float, symbol: str) -> SimAccount:
        """End-of-day pass: flatten open positions past hard-flat; ratchet EFA EoD floor."""
        if self._is_after_hard_flat() and self._signed_qty_of(symbol) != 0:
            self._flatten_at(mid_price, symbol)
        if self._efa_policy is not None:
            state = self._as_state(self._now())
            new_state = self._efa_policy.update_on_eod(state)
            self._account = self._merge_state(new_state)
        return self._account

    # ---- AccountState bridge -------------------------------------------

    def as_account_state(self, timestamp: datetime | None = None) -> AccountState:
        """Project the SimAccount into the broker-agnostic AccountState shape.

        Used by the client adapter for `get_account()` and by tests asserting
        that risk-gate inputs match what the live adapter would report.
        """
        return self._as_state(timestamp or self._now())

    # ---- internals -----------------------------------------------------

    def _active_policy(self) -> CombineIntradayDrawdown | EFAStandardEoDDrawdown:
        if self._account.stage in ("efa_active", "efa_payout", "funded"):
            if self._efa_policy is None:
                return self._combine_policy
            return self._efa_policy
        return self._combine_policy

    def _is_after_hard_flat(self) -> bool:
        now_ct = self._now().astimezone(_CT)
        return now_ct.time() >= self.hard_flat_time_ct

    def _is_open_increasing(self, intent: OrderIntent) -> bool:
        current = self._signed_qty_of(intent.symbol)
        projected = current + intent.signed_qty()
        return abs(projected) > abs(current)

    def _signed_qty_of(self, symbol: str) -> int:
        pos = self._account.open_positions.get(symbol)
        return pos[0] if pos is not None else 0

    def _apply_slippage(self, intent: OrderIntent, mid_price: float) -> float:
        tick = MIN_TICK[intent.symbol]
        offset = self._slippage_ticks * tick
        return mid_price + offset if intent.side == "BUY" else mid_price - offset

    def _reject(self, intent: OrderIntent, reason: str) -> OrderEvent:
        return OrderEvent(
            client_order_id=intent.client_order_id,
            broker_order_id="",
            status="REJECTED",
            filled_quantity=0,
            avg_fill_price=None,
            timestamp=intent.timestamp,
            metadata={
                "reason": reason,
                "topstepx_side": topstepx_side(intent.side),
            },
        )

    def _flatten_at(self, mid_price: float, symbol: str) -> None:
        qty = self._signed_qty_of(symbol)
        if qty == 0:
            return
        fill = SimFill(
            symbol=symbol,
            signed_qty=-qty,
            fill_price=mid_price,
            timestamp=self._now(),
        )
        self._account = apply_fill(self._account, fill)
        self._account = mark_to_market(
            self._account, mid_price=mid_price, symbol=symbol,
        )

    def _mark_failed(self) -> SimAccount:
        if self._account.stage == "combine_active":
            return advance_stage(self._account, "combine_failed")
        if self._account.stage == "efa_active":
            return advance_stage(self._account, "efa_failed")
        return self._account

    def _as_state(self, timestamp: datetime) -> AccountState:
        open_positions = {
            sym: qty for sym, (qty, _avg) in self._account.open_positions.items()
        }
        # is_combine is True for the Combine stages; EFA / Funded stages flip it.
        is_combine = self._account.stage in (
            "combine_active", "combine_passed", "combine_failed",
        )
        return AccountState(
            equity=self._account.equity,
            realized_pnl_today=self._account.realized_pnl,
            unrealized_pnl=self._account.unrealized_pnl,
            open_positions=open_positions,
            pending_intent_count=0,
            high_water_equity=self._account.high_water_equity,
            is_combine=is_combine,
            timestamp=timestamp,
            start_balance=self._account.start_balance,
        )

    def _merge_state(self, state: AccountState) -> SimAccount:
        """Update SimAccount's high-water from a (possibly EoD-ratcheted) state."""
        from dataclasses import replace

        return replace(
            self._account,
            high_water_equity=state.high_water_equity,
        )
