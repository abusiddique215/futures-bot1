"""IBExecutionClient — Interactive Brokers paper-trading adapter via ib_async.

Implements the ExecutionClient Protocol. Connects to IB Gateway on
localhost:7497 (paper) and resolves MNQ front-month contracts on demand.

Dependency injection: tests pass `ib_factory=lambda: FakeIB()` to swap out
the real `ib_async.IB` for an in-memory fake. No CI test touches the
network — the real broker only runs in nightly @pytest.mark.live_paper
fixtures (deferred).

Spec: 02-execution-clients.md §3.3 (reconnect), §3.5 (bracket-translation),
§3.8 (idempotency cache), §3.9 (conformance contract).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from bot.constants import MIN_TICK
from bot.types import (
    AccountState,
    Order,
    OrderEvent,
    OrderIntent,
    Position,
)

# IB orderType strings → our OrderType literal.
_IB_ORDER_TYPE_MAP: dict[str, str] = {
    "MKT": "MARKET",
    "LMT": "LIMIT",
    "STP": "STOP",
    "STP LMT": "STOP_LIMIT",
}

if TYPE_CHECKING:
    from ib_async import IB, Contract


def _default_ib_factory() -> IB:
    """Lazy import so importing this module doesn't require ib_async at parse time."""
    from ib_async import IB
    return IB()


class IBExecutionClient:
    """ExecutionClient backed by ib_async against IB Gateway (paper).

    Constructor takes connection parameters and (optionally) an ib_factory
    callable that returns an IB-shaped object. Tests pass a fake-IB factory;
    production lets the default ib_async.IB() be used.
    """

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        ib_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self._ib_factory: Callable[[], Any] = ib_factory or _default_ib_factory
        self._ib: Any | None = None
        self._contracts: dict[str, Contract] = {}
        self._recent: dict[str, OrderEvent] = {}
        # client_order_id → (symbol, trade) — kept for cancel_order / cancel_all.
        # For BRACKET, only the parent trade is recorded under client_order_id;
        # canceling the parent cancels the OCO group on the IB side.
        self._open_trades: dict[str, tuple[str, Any]] = {}

    async def connect(self) -> None:
        """Create IB instance, connect to gateway, qualify the MNQ contract."""
        from ib_async import Future
        self._ib = self._ib_factory()
        await self._ib.connectAsync(self.host, self.port, self.client_id)
        mnq = Future(symbol="MNQ", exchange="CME")
        qualified = await self._ib.qualifyContractsAsync(mnq)
        # qualifyContractsAsync returns a list — take the first.
        self._contracts["MNQ"] = qualified[0]

    async def disconnect(self) -> None:
        if self._ib is not None:
            self._ib.disconnect()

    async def place_order(self, intent: OrderIntent) -> OrderEvent:
        """Submit an OrderIntent. Idempotent on intent.client_order_id.

        v1 supports MARKET (this task) and BRACKET (T5). LIMIT / STOP_LIMIT
        emitted by strategies travel through BRACKET; bare LIMIT is not
        used by ORB (v1 strategy) so is unsupported for now.
        """
        cached = self._recent.get(intent.client_order_id)
        if cached is not None:
            return cached

        if self._ib is None:
            raise RuntimeError("place_order called before connect()")
        contract = self._contracts.get(intent.symbol)
        if contract is None:
            raise RuntimeError(f"No qualified contract for symbol {intent.symbol!r}")

        if intent.order_type == "MARKET":
            event = self._place_market(intent, contract)
        elif intent.order_type == "BRACKET":
            event = self._place_bracket(intent, contract)
        else:
            raise NotImplementedError(
                f"order_type={intent.order_type!r} not yet supported in IBExecutionClient"
            )

        self._recent[intent.client_order_id] = event
        return event

    def _place_market(self, intent: OrderIntent, contract: Any) -> OrderEvent:
        from ib_async import MarketOrder
        order = MarketOrder(action=intent.side, totalQuantity=intent.quantity)
        order.orderRef = intent.client_order_id  # IB-side dedup key
        assert self._ib is not None
        trade = self._ib.placeOrder(contract, order)
        self._open_trades[intent.client_order_id] = (intent.symbol, trade)
        return OrderEvent(
            client_order_id=intent.client_order_id,
            broker_order_id=str(trade.order.orderId),
            status="PENDING",
            filled_quantity=0,
            avg_fill_price=None,
            timestamp=intent.timestamp,
        )

    def _place_bracket(self, intent: OrderIntent, contract: Any) -> OrderEvent:
        """Submit a 3-leg OCO bracket via ib.bracketOrder().

        Translation:
        - entry reference = intent.limit_price (required for BRACKET v1)
        - tick offsets → points via MIN_TICK[symbol]
        - BUY:  tp = entry + tp_ticks*tick, sl = entry - sl_ticks*tick
        - SELL: tp = entry - tp_ticks*tick, sl = entry + sl_ticks*tick

        ib.bracketOrder() returns (parent, takeProfit, stopLoss) with
        transmit flags already set: parent=False, tp=False, stopLoss=True.
        We place all three in order so the LAST (sl) triggers transmission.
        """
        if intent.bracket is None:
            raise ValueError("BRACKET order_type requires intent.bracket to be set")
        if intent.limit_price is None:
            raise ValueError(
                "BRACKET order_type requires intent.limit_price as entry reference"
            )
        tick = MIN_TICK[intent.symbol]
        sl_offset = intent.bracket.stop_loss_ticks * tick
        tp_offset = intent.bracket.take_profit_ticks * tick

        if intent.side == "BUY":
            tp_price = intent.limit_price + tp_offset
            sl_price = intent.limit_price - sl_offset
        else:
            tp_price = intent.limit_price - tp_offset
            sl_price = intent.limit_price + sl_offset

        assert self._ib is not None
        bracket = self._ib.bracketOrder(
            intent.side, intent.quantity,
            intent.limit_price, tp_price, sl_price,
        )
        parent, take_profit, stop_loss = bracket
        parent.orderRef = intent.client_order_id
        take_profit.orderRef = f"{intent.client_order_id}-tp"
        stop_loss.orderRef = f"{intent.client_order_id}-sl"

        # Place in order — the LAST (stop_loss) carries transmit=True so IB
        # transmits all three legs as an OCO group.
        parent_trade = self._ib.placeOrder(contract, parent)
        self._ib.placeOrder(contract, take_profit)
        self._ib.placeOrder(contract, stop_loss)

        self._open_trades[intent.client_order_id] = (intent.symbol, parent_trade)
        return OrderEvent(
            client_order_id=intent.client_order_id,
            broker_order_id=str(parent_trade.order.orderId),
            status="PENDING",
            filled_quantity=0,
            avg_fill_price=None,
            timestamp=intent.timestamp,
        )

    async def cancel_order(self, client_order_id: str) -> OrderEvent:
        """Cancel a previously-placed order. Raises KeyError if unknown."""
        symbol_trade = self._open_trades[client_order_id]  # raises KeyError if absent
        _symbol, trade = symbol_trade
        assert self._ib is not None
        self._ib.cancelOrder(trade.order)
        # We don't have an exact cancel-ack timestamp here; use now(UTC).
        # In a wired-up engine the broker's cancelOrderEvent fills this in.
        event = OrderEvent(
            client_order_id=client_order_id,
            broker_order_id=str(trade.order.orderId),
            status="CANCELED",
            filled_quantity=0,
            avg_fill_price=None,
            timestamp=datetime.now(UTC),
        )
        return event

    async def cancel_all(self, symbol: str) -> list[OrderEvent]:
        """Cancel every tracked open order for `symbol`."""
        events: list[OrderEvent] = []
        for client_order_id, (sym, _trade) in list(self._open_trades.items()):
            if sym != symbol:
                continue
            events.append(await self.cancel_order(client_order_id))
        return events

    # ---- snapshot queries ------------------------------------------------

    async def get_positions(self) -> list[Position]:
        """Snapshot of all open positions, converted to bot.types.Position."""
        if self._ib is None:
            raise RuntimeError("get_positions called before connect()")
        now = datetime.now(UTC)
        out: list[Position] = []
        for ib_pos in self._ib.positions():
            out.append(Position(
                symbol=ib_pos.contract.symbol,
                signed_qty=int(ib_pos.position),
                avg_entry_price=float(ib_pos.avgCost),
                unrealized_pnl=0.0,  # not in Position record; comes via accountSummary
                opened_at=now,       # IB doesn't expose entry time on this record
            ))
        return out

    async def get_open_orders(self) -> list[Order]:
        """Snapshot of open orders, converted to bot.types.Order."""
        if self._ib is None:
            raise RuntimeError("get_open_orders called before connect()")
        now = datetime.now(UTC)
        out: list[Order] = []
        for ib_order in self._ib.openOrders():
            order_type = _IB_ORDER_TYPE_MAP.get(ib_order.orderType, ib_order.orderType)
            limit_price = ib_order.lmtPrice or None
            stop_price = ib_order.auxPrice or None
            out.append(Order(
                client_order_id=ib_order.orderRef,
                broker_order_id=str(ib_order.orderId),
                symbol="MNQ",   # v1 single-symbol; multi-symbol comes in P8
                side=ib_order.action,
                quantity=int(ib_order.totalQuantity),
                order_type=order_type,
                status="WORKING",
                timestamp=now,
                limit_price=limit_price,
                stop_price=stop_price,
            ))
        return out

    async def get_account(self) -> AccountState:
        """Snapshot of account equity + PnL + open positions."""
        if self._ib is None:
            raise RuntimeError("get_account called before connect()")
        summary = {v.tag: v.value for v in self._ib.accountSummary()}
        equity = float(summary.get("NetLiquidation", "0") or 0)
        realized = float(summary.get("RealizedPnL", "0") or 0)
        unrealized = float(summary.get("UnrealizedPnL", "0") or 0)
        positions = {
            p.contract.symbol: int(p.position)
            for p in self._ib.positions()
        }
        return AccountState(
            equity=equity,
            realized_pnl_today=realized,
            unrealized_pnl=unrealized,
            open_positions=positions,
            pending_intent_count=len(self._recent),
            high_water_equity=equity,  # engine updates the running high-water
            is_combine=True,
            timestamp=datetime.now(UTC),
        )
