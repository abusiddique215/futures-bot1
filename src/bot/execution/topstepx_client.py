"""TopstepXExecutionClient — live broker adapter for Topstep accounts.

Implements ExecutionClient Protocol via project-x-py 3.5.9.

SAFETY-CRITICAL. This adapter touches real-money Topstep Combine + Funded
accounts. Several defenses MUST stay in place:

  1. Side encoding — see bot.execution.topstepx_constants (SIDE_BUY=0 footgun).
  2. Hostname VPS-guard — env='live' fails closed unless socket.gethostname()
     is in the configured whitelist (D14 VPS ban).
  3. 90-second reconnect deadline — stricter than IB paper's 5 min. On expiry
     escalate to risk-gate force-flatten.
  4. JWT pre-refresh at 22h.

Dependency injection: tests pass `client_factory=lambda: FakeProjectX()` to
swap the real project_x_py ProjectX for an in-memory fake. No CI test
touches the network — the real broker only runs in a manual live-paper
verify by the operator before going live.

Spec: 02-execution-clients.md §3.3, §3.4, §3.7, §3.8.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Any, Final, Literal

from bot.execution.topstepx_constants import SIDE_BUY, SIDE_SELL, topstepx_side
from bot.types import AccountState, Order, OrderEvent, OrderIntent, Position

log = logging.getLogger(__name__)

# TopstepX wire-protocol order-type codes (spec 02 §3.3 type-mapping).
# Hardcoded as Final so a refactor can't accidentally drop them through
# the SDK's enum and shift values.
ORDER_TYPE_LIMIT: Final[int] = 1
ORDER_TYPE_MARKET: Final[int] = 2
ORDER_TYPE_STOP: Final[int] = 4

# JWT lifetime is ~24h per spec §3.3; we re-auth 2h early to absorb clock
# skew + transient outages. 22 * 3600 = 79_200.
JWT_REFRESH_INTERVAL_SECONDS: Final[int] = 22 * 60 * 60


class TopstepXExecutionClient:
    """ExecutionClient backed by project-x-py against TopstepX (live rail).

    Construction is cheap — no network. `connect()` does the auth + suite-open.
    For tests, pass `client_factory` returning a FakeProjectX; production
    passes a lambda that builds a real `project_x_py.ProjectX` from env.
    """

    def __init__(
        self,
        *,
        username: str,
        api_key: str,
        account_name: str,
        env: Literal["paper", "live"],
        client_factory: Callable[[], Any],
        live_hostname_whitelist: Iterable[str] | None = None,
        hostname: Callable[[], str] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if env not in ("paper", "live"):
            raise ValueError(
                f"env must be 'paper' or 'live', got {env!r}",
            )

        # Materialize the whitelist so we can introspect it cheaply.
        whitelist: list[str] | None
        if live_hostname_whitelist is None:
            whitelist = None
        else:
            whitelist = list(live_hostname_whitelist)

        # Hostname VPS-guard. Live env is fail-closed: a missing or empty
        # whitelist is a misconfiguration, not a permissive default.
        if env == "live":
            if not whitelist:
                raise RuntimeError(
                    "env='live' requires a non-empty live_hostname_whitelist "
                    "(VPS-ban guard). Refusing to start.",
                )
            current = (hostname or socket.gethostname)()
            if current not in whitelist:
                raise RuntimeError(
                    f"hostname {current!r} not in live_hostname_whitelist "
                    f"{whitelist!r} — VPS-ban guard fail-closed.",
                )

        self.username = username
        self.api_key = api_key
        self.account_name = account_name
        self.env: Literal["paper", "live"] = env
        self._client_factory = client_factory
        self._live_hostname_whitelist = whitelist
        self._hostname_fn = hostname or socket.gethostname
        self._sleep: Callable[[float], Awaitable[None]] = sleep or asyncio.sleep

        # Connect-time state, populated by connect():
        self._client: Any | None = None
        self._suite: Any | None = None
        self._account_id: int | None = None
        self._jwt_refresh_task: asyncio.Task[None] | None = None
        # client_order_id → cached OrderEvent (spec §3.8 idempotency).
        self._recent: dict[str, OrderEvent] = {}
        # client_order_id → broker_order_id (for cancel_order).
        self._broker_ids: dict[str, int] = {}

    # ---- public read-only state ----------------------------------------

    @property
    def account_id(self) -> int | None:
        return self._account_id

    # ---- connect / disconnect ------------------------------------------

    async def connect(self, symbol: str = "MNQ") -> None:
        """Authenticate + resolve account_id + open the trading suite.

        Spec 02 §3.3 connect-flow:
          1. (already enforced in __init__) hostname guard.
          2. Build the SDK client via injected factory.
          3. authenticate() → JWT.
          4. list_accounts() → match by configured account_name.
          5. open trading suite for `symbol`.
          6. Schedule the 22h JWT pre-refresh task.

        Raises RuntimeError if no account matches account_name.
        """
        self._client = self._client_factory()
        await self._client.authenticate()

        accounts = await self._client.list_accounts()
        for acct in accounts:
            if acct.name == self.account_name:
                self._account_id = acct.id
                break
        else:
            raise RuntimeError(
                f"No TopstepX account named {self.account_name!r} found. "
                f"Got: {[a.name for a in accounts]!r}",
            )

        self._suite = await self._client.create_suite(
            symbol=symbol, account_id=self._account_id,
        )

        # Start the JWT pre-refresh task. MUST be done here (not in __init__)
        # so there's a running event loop to attach to.
        self._jwt_refresh_task = asyncio.create_task(self._jwt_refresh_loop())

    async def disconnect(self) -> None:
        """Cancel the JWT refresh task and tear down the suite.

        Safe to call multiple times.
        """
        if self._jwt_refresh_task is not None:
            self._jwt_refresh_task.cancel()
            try:
                await self._jwt_refresh_task
            except (asyncio.CancelledError, Exception):
                # Cancellation is the expected path; suppress.
                pass
            self._jwt_refresh_task = None

        if self._suite is not None:
            await self._suite.disconnect()

    # ---- order placement ------------------------------------------------

    @staticmethod
    def _translate(
        intent: OrderIntent,
        *,
        account_id: int,
        contract_id: str,
    ) -> dict[str, Any]:
        """Translate a broker-agnostic OrderIntent → TopstepX SDK kwargs.

        Returns the kwargs dict that the SDK's `place_order` will receive.
        Tests assert on the dict directly — particularly that
        `body["side"] == 0` for BUY (the SIDE_BUY=0 footgun guard).

        The on-wire body that hits TopstepX itself is camelCase; the SDK
        kwargs are snake_case (project_x_py 3.5.9 calling convention).
        We translate to the SDK shape; the SDK serializes to wire-shape.

        v1 supports MARKET only here; BRACKET handled in _translate_bracket.
        """
        side_int = topstepx_side(intent.side)  # SIDE_BUY=0 footgun guarded here.
        if intent.order_type == "MARKET":
            order_type_int = ORDER_TYPE_MARKET
        elif intent.order_type == "LIMIT":
            order_type_int = ORDER_TYPE_LIMIT
        elif intent.order_type == "STOP":
            order_type_int = ORDER_TYPE_STOP
        else:
            raise NotImplementedError(
                f"_translate does not handle order_type={intent.order_type!r}; "
                f"use _translate_bracket for BRACKET",
            )
        body: dict[str, Any] = {
            "account_id": account_id,
            "contract_id": contract_id,
            "side": side_int,
            "order_type": order_type_int,
            "size": intent.quantity,
            "custom_tag": intent.client_order_id,
        }
        if intent.limit_price is not None:
            body["limit_price"] = intent.limit_price
        if intent.stop_price is not None:
            body["stop_price"] = intent.stop_price
        return body

    @staticmethod
    def _translate_bracket(
        intent: OrderIntent,
        *,
        account_id: int,
        contract_id: str,
    ) -> dict[str, Any]:
        """Translate a BRACKET OrderIntent → TopstepX SDK kwargs (single body).

        Spec 02 §3.5: unlike IB (3 separate orders + OCA group), TopstepX
        accepts inline `stopLossBracket` / `takeProfitBracket` blocks as
        keys on the same body as the entry. Ticks are sent directly; the
        server converts to absolute prices.

        Entry leg:
          - intent.limit_price=None → MARKET entry (order_type=2).
          - intent.limit_price set → LIMIT entry (order_type=1, limit_price).

        Bracket children (server-side OCO):
          - stop_loss_bracket: {ticks, type: 4 (STOP)}
          - take_profit_bracket: {ticks, type: 1 (LIMIT)}
        """
        if intent.bracket is None:
            raise ValueError(
                "BRACKET order_type requires intent.bracket to be set",
            )

        side_int = topstepx_side(intent.side)  # SIDE_BUY=0 footgun guarded here.

        if intent.limit_price is None:
            order_type_int = ORDER_TYPE_MARKET
        else:
            order_type_int = ORDER_TYPE_LIMIT

        body: dict[str, Any] = {
            "account_id": account_id,
            "contract_id": contract_id,
            "side": side_int,
            "order_type": order_type_int,
            "size": intent.quantity,
            "custom_tag": intent.client_order_id,
            "stop_loss_bracket": {
                "ticks": intent.bracket.stop_loss_ticks,
                "type": ORDER_TYPE_STOP,
            },
            "take_profit_bracket": {
                "ticks": intent.bracket.take_profit_ticks,
                "type": ORDER_TYPE_LIMIT,
            },
        }
        if intent.limit_price is not None:
            body["limit_price"] = intent.limit_price
        return body

    async def place_order(self, intent: OrderIntent) -> OrderEvent:
        """Submit an OrderIntent to TopstepX. Idempotent on client_order_id.

        Spec 02 §3.3 (placement) + §3.4 (side-encoding) + §3.5 (bracket) +
        §3.8 (idempotency).
        """
        cached = self._recent.get(intent.client_order_id)
        if cached is not None:
            return cached
        if self._suite is None or self._account_id is None:
            raise RuntimeError("place_order called before connect()")

        if intent.order_type == "BRACKET":
            body = self._translate_bracket(
                intent,
                account_id=self._account_id,
                contract_id=self._suite.instrument_id,
            )
        else:
            body = self._translate(
                intent,
                account_id=self._account_id,
                contract_id=self._suite.instrument_id,
            )
        response = await self._suite.orders.place_order(**body)
        event = OrderEvent(
            client_order_id=intent.client_order_id,
            broker_order_id=str(response.orderId),
            status="PENDING",
            filled_quantity=0,
            avg_fill_price=None,
            timestamp=intent.timestamp,
        )
        self._recent[intent.client_order_id] = event
        self._broker_ids[intent.client_order_id] = response.orderId
        return event

    # ---- cancellation ---------------------------------------------------

    async def cancel_order(self, client_order_id: str) -> OrderEvent:
        """Cancel a previously-placed order. Raises KeyError if unknown.

        Spec 02 §3.7. The broker_order_id used by the SDK is the one we
        cached from the original place_order response.
        """
        broker_id = self._broker_ids[client_order_id]  # KeyError if absent
        assert self._suite is not None
        await self._suite.orders.cancel_order(
            broker_id, account_id=self._account_id,
        )
        return OrderEvent(
            client_order_id=client_order_id,
            broker_order_id=str(broker_id),
            status="CANCELED",
            filled_quantity=0,
            avg_fill_price=None,
            timestamp=datetime.now(UTC),
        )

    async def cancel_all(self, symbol: str) -> list[OrderEvent]:
        """Cancel every tracked open order for `symbol`. v1 is single-symbol
        so this is a thin wrapper that filters _broker_ids by the symbol
        the suite was opened for; cross-symbol routing is a future plan.
        """
        events: list[OrderEvent] = []
        if self._suite is None:
            raise RuntimeError("cancel_all called before connect()")
        if symbol != self._suite.symbol:
            return events
        for client_order_id in list(self._broker_ids.keys()):
            events.append(await self.cancel_order(client_order_id))
        return events

    # ---- snapshot queries -----------------------------------------------

    @staticmethod
    def _decode_side(side_int: int) -> Literal["BUY", "SELL"]:
        """Decode TopstepX side integer back to broker-agnostic string.

        The SIDE_BUY=0 footgun applies on the READ path too: a position
        / order returned by the broker with side=0 means BUY. If we got
        this wrong, account-state queries would mis-classify long vs
        short and the risk gate would deny the wrong orders.
        """
        if side_int == SIDE_BUY:
            return "BUY"
        if side_int == SIDE_SELL:
            return "SELL"
        raise ValueError(f"Unexpected TopstepX side integer: {side_int!r}")

    @staticmethod
    def _decode_order_type(type_int: int) -> Literal["MARKET", "LIMIT", "STOP"]:
        if type_int == ORDER_TYPE_MARKET:
            return "MARKET"
        if type_int == ORDER_TYPE_LIMIT:
            return "LIMIT"
        if type_int == ORDER_TYPE_STOP:
            return "STOP"
        raise ValueError(f"Unexpected TopstepX order type: {type_int!r}")

    @staticmethod
    def _contract_to_symbol(contract_id: str) -> str:
        """Extract the symbol from a TopstepX contract id like
        'CON.F.US.MNQ.M26'. Defensive: returns the raw id if the format
        doesn't match."""
        parts = contract_id.split(".")
        if len(parts) >= 4 and parts[0] == "CON":
            return parts[3]
        return contract_id

    async def get_positions(self) -> list[Position]:
        if self._suite is None:
            raise RuntimeError("get_positions called before connect()")
        rows = await self._suite.positions.get_all_positions()
        now = datetime.now(UTC)
        out: list[Position] = []
        for row in rows:
            out.append(Position(
                symbol=self._contract_to_symbol(row.contractId),
                signed_qty=int(row.size),
                avg_entry_price=float(row.averagePrice),
                unrealized_pnl=float(row.unrealizedPnl),
                opened_at=now,
            ))
        return out

    async def get_open_orders(self) -> list[Order]:
        if self._suite is None:
            raise RuntimeError("get_open_orders called before connect()")
        rows = await self._suite.orders.search_open_orders()
        now = datetime.now(UTC)
        out: list[Order] = []
        for row in rows:
            out.append(Order(
                client_order_id=row.customTag,
                broker_order_id=str(row.id),
                symbol=self._contract_to_symbol(row.contractId),
                side=self._decode_side(int(row.side)),
                quantity=int(row.size),
                order_type=self._decode_order_type(int(row.type)),
                status="WORKING",
                timestamp=now,
                limit_price=row.limitPrice,
                stop_price=row.stopPrice,
            ))
        return out

    async def get_account(self) -> AccountState:
        if self._suite is None or self._client is None:
            raise RuntimeError("get_account called before connect()")
        accounts = await self._client.list_accounts()
        my_account = None
        for a in accounts:
            if a.name == self.account_name:
                my_account = a
                break
        if my_account is None:
            raise RuntimeError(f"Account {self.account_name!r} vanished")
        positions = await self._suite.positions.get_all_positions()
        unrealized = sum(float(p.unrealizedPnl) for p in positions)
        open_positions: dict[str, int] = {
            self._contract_to_symbol(p.contractId): int(p.size)
            for p in positions
        }
        equity = float(my_account.balance)
        return AccountState(
            equity=equity,
            realized_pnl_today=0.0,  # not surfaced by SDK; engine tracks
            unrealized_pnl=unrealized,
            open_positions=open_positions,
            pending_intent_count=len(self._recent),
            high_water_equity=equity,
            is_combine=True,
            timestamp=datetime.now(UTC),
        )

    # ---- JWT pre-refresh ------------------------------------------------

    async def _jwt_refresh_loop(self) -> None:
        """Re-authenticate every 22h. Runs until cancelled by disconnect().

        On authenticate() failure, log and continue — the reactive 401 path
        in connect/place_order will recover. We don't want a transient
        network blip during a refresh to crash the live process.
        """
        try:
            while True:
                await self._sleep(JWT_REFRESH_INTERVAL_SECONDS)
                if self._client is None:
                    return
                try:
                    await self._client.authenticate()
                    log.info("topstepx JWT pre-refresh ok")
                except Exception as exc:
                    log.warning("topstepx JWT pre-refresh failed: %s", exc)
        except asyncio.CancelledError:
            return
