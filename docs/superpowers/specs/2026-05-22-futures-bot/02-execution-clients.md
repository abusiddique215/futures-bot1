# 02 — Execution Clients

**Owns**: `ExecutionClient` port, `IBExecutionClient` (paper), `TopstepXExecutionClient` (live), `SimExecutionClient` (backtest), the cross-broker conformance test suite, and the defensive constants that prevent the `side`-encoding silent-loss footgun.

**Status**: Spec.
**Date**: 2026-05-22.
**Reads**: `00-architecture-overview.md`, `../research/tradovate-projectx-apis.md`, `../research/alpaca-futures-api.md`.

---

## 1. Purpose

Translate a single broker-agnostic `OrderIntent` into broker-specific API calls across three rails — **SimBroker** (backtest), **IB paper** (development/soak), **TopstepX** (Practice → Combine → Funded) — while emitting a single broker-agnostic event stream (`OrderEvent`, `PositionEvent`, `AccountStateEvent`) back to the rest of the system.

This module is the **only** layer that knows about broker wire formats. Every byte of broker-specific code lives here. The Strategy never sees `side: 0`; it sees `side="BUY"`. The RiskEngine never sees a JWT; it sees an `OrderIntent`.

If a broker is added later, only this file (and its sibling concrete adapter file) changes.

---

## 2. Inherited decisions

From `00-architecture-overview.md`:

- **D6** — Paper rail is **Interactive Brokers paper** via `ib_async`. Alpaca is excluded (no futures in 2026, confirmed in `../research/alpaca-futures-api.md`).
- **D7** — Live rail is **TopstepX** via `TexasCoding/project-x-py` SDK (async, MIT, Python 3.12+, v3.5.8 Sept 2025). Same `accountId` swap moves Practice → Combine → Funded — one integration, three account states.
- **D14** — Live bot runs on the user's **physical Mac**. No VPS / no cloud / no VPN. Live `TopstepXExecutionClient` MUST refuse to start if it detects a cloud network egress (best-effort check; ToS-compliance is ultimately operator responsibility).
- **D8** — Adapters are implemented as Nautilus `ExecutionClient` subclasses so backtest/paper/live share the same Strategy and RiskEngine code paths.

---

## 3. Design

### 3.1 Common abstraction — `ExecutionClient` port

A `Protocol` (PEP 544) so the type-checker enforces the surface without forcing a base class. Concrete adapters extend Nautilus `LiveExecutionClient` under the hood; the `Protocol` is the seam that the conformance test suite asserts against.

**Methods** (all `async`):

| Method | Returns | Notes |
|---|---|---|
| `connect()` | `None` | Establishes broker session. Idempotent. Raises `BrokerConnectError` on failure after backoff exhaustion. |
| `disconnect()` | `None` | Clean shutdown. Cancels in-flight subscriptions. Does NOT cancel open orders (operator decision; see `04-risk-engine.md` force-flatten path). |
| `place_order(intent: OrderIntent)` | `OrderEvent` (PENDING) | Submits. Returns immediately with PENDING; later WORKING/FILLED/etc. arrive via event stream. Idempotent on `client_order_id`. |
| `cancel_order(client_order_id: str)` | `OrderEvent` (CANCELED on success) | |
| `cancel_all(symbol: str)` | `list[OrderEvent]` | Best-effort. Returns events for each cancelled order. |
| `get_positions()` | `list[Position]` | Snapshot from broker (broker is source of truth — see D12). |
| `get_open_orders()` | `list[Order]` | Snapshot from broker. |
| `get_account()` | `AccountState` | Equity, margin, buying power. |

**Events emitted** (pushed onto an `asyncio.Queue` consumed by the engine):

- `OrderEvent` — every state transition on an order.
- `PositionEvent` — every position delta (open, increase, decrease, close).
- `AccountStateEvent` — equity / margin / day-pnl snapshot (debounced; 1 Hz max).

The Strategy/RiskEngine consume these via Nautilus's event bus. The adapter is responsible for translating broker-native events into these three shapes.

### 3.2 `IBExecutionClient` (paper rail)

**Library**: `ib_async` (maintained fork of `ib_insync`; the upstream `ib_insync` is abandoned).
**Transport**: TCP socket to IB Gateway or TWS on `localhost:7497` (paper) / `7496` (live). Live not used in this project.
**Auth**: IB Gateway/TWS performs the login interactively at startup (or via `IBC` for headless); the Python client only authenticates against the *local* gateway with a `clientId`.

**Connect flow**:
1. Pre-check: confirm IB Gateway process is alive (`pgrep -f ibgateway` or port probe on `127.0.0.1:7497`). If not, raise `IBGatewayNotRunningError` with operator-actionable message. **Do not auto-start the gateway** — login requires 2FA which must be human-driven.
2. `IB().connectAsync(host="127.0.0.1", port=7497, clientId=<config>)`.
3. Resolve contract: `ContFuture("MNQ", exchange="CME")` then `qualifyContractsAsync(...)` → pinned `Contract` with `conId`. Front-month chosen by IB's continuous-future resolution; we override only at the **roll boundary** defined in `01-data-pipeline.md`.
4. Subscribe to account updates: `reqAccountUpdatesAsync(True)`.

**Order placement**:
- Market / Limit / Stop / Stop-Limit → `MarketOrder`, `LimitOrder`, `StopOrder`, `StopLimitOrder`.
- **Bracket** → `IB.bracketOrder(action, quantity, limitPrice, takeProfitPrice, stopLossPrice)` returns a 3-tuple (parent, takeProfit, stopLoss) with `parent.transmit=False` and `stopLoss.transmit=True`. Submit in order: parent → takeProfit → stopLoss. The OCO link is implicit via `parent.ocaGroup` set by `bracketOrder()`.
- We translate `Bracket.stop_loss_ticks` / `take_profit_ticks` to absolute prices using the contract's `minTick` (0.25 for MNQ) at the moment of the parent fill — pre-submission for limit-parents, on-fill callback for market-parents.

**Reconnect strategy**:
- `IB.disconnectedEvent` triggers exponential backoff: 1s → 2s → 4s → 8s → 16s → 32s → 60s (cap).
- Reconnect deadline: **5 minutes**. If not reconnected by then, emit `BrokerDownAlert` to Telegram (see `06-observability.md`) and continue retrying every 60s. The RiskEngine's force-flatten path uses the *other* rail only on TopstepX, not on IB paper (paper-rail downtime is non-fatal).
- After reconnect, immediately call `get_positions()` + `get_open_orders()` and reconcile against journal (see `07-config-and-deploy.md` startup reconciliation).

**Known quirks**:
- IB paper fills are **optimistically priced** — limit orders fill at the limit even when the real market would have skipped. Documented in §6 Open Questions; backtest harness (`05-backtest-harness.md`) uses a realistic-slippage model that is *not* the IB paper engine.
- Continuous-future contract resolution can hand back a different `conId` across days near roll. We pin `conId` per-session and invalidate at the configured roll date.

### 3.3 `TopstepXExecutionClient` (live rail)

**Library**: `project-x-py` (v3.5.8+, pinned in `pyproject.toml`).
**Transport**: REST (`https://api.topstepx.com`) + SignalR over WebSocket on two hubs (`https://rtc.topstepx.com/hubs/user`, `.../market`).
**Auth**: `POST /api/Auth/loginKey` with `{"userName": ..., "apiKey": ...}` → JWT. Use as `Authorization: Bearer <jwt>` on REST and as the `accessToken` query/header on the SignalR negotiate.

**Connect flow**:
1. Pre-check: assert running on the configured local machine (best-effort: compare `socket.gethostname()` to `EXPECTED_HOST` env; fail closed if mismatch). This is the D14 VPS-ban guard.
2. `client = ProjectX.from_env()` — reads `PROJECTX_USERNAME` + `PROJECTX_API_KEY` from env (loaded from `.env` via Pydantic settings, see `07-config-and-deploy.md`).
3. `await client.authenticate()` — JWT in memory; SDK refreshes ~24h.
4. **Account discovery**: `await client.list_accounts()` → pick the account whose `name` matches config (`TOPSTEPX_ACCOUNT_NAME`). Store `account_id`. This is the single value that flips Practice → Combine → Funded.
5. `suite = await client.create_suite(symbol="MNQ")` — opens both SignalR hubs, subscribes to user events for `account_id` and market events for the front-month MNQ contract.
6. Wire SDK event handlers (`suite.events.on("order")`, `"position"`, `"account"`, `"quote"`) → translate → emit `OrderEvent` / `PositionEvent` / `AccountStateEvent`.

**Order placement**:
- All order types route through `suite.orders.place_order(...)` which accepts an inline body with `stopLossBracket` / `takeProfitBracket`. We **never** decompose a bracket into separate parent + OCO calls on TopstepX (unlike IB) — the platform models brackets as a server-managed attachment.
- `type` mapping: `LIMIT=1`, `MARKET=2`, `STOP=4`, `STOP_LIMIT` (not first-class — emulate via stop + limit pair if needed; v1 sticks to MARKET + BRACKET).
- `side` mapping: see §3.4 **CRITICAL**.

**Reconnect strategy**:
- SignalR clients reconnect on transport drop. `project-x-py` exposes `on_disconnect` / `on_reconnect` callbacks.
- Same exponential backoff as IB (1s → 60s cap), but **reconnect deadline is shorter: 90 seconds**, because TopstepX positions are real money under a trailing MLL that ticks on unrealized P&L (§00.5 D7 + §00 critical-item #2).
- On deadline expiry: emit `LiveBrokerDownCritical` → trigger `04-risk-engine.md`'s force-flatten path. The force-flatten path is: (a) RiskEngine commands `cancel_all` + close-position; (b) if that fails because the broker is down, the operator gets a paging Telegram alert with the exact `accountId` and a one-line manual-flatten command. **There is no second broker to flatten via** — TopstepX is the only path to the Topstep account.
- Token refresh: JWT lifetime is undocumented (~24h reported). We pre-emptively re-auth at 22h and on any 401.

**Server-side rule enforcement**:
- TopstepX enforces trailing MLL, DLL, position cap, 3:10 PM flat **on the server**. The adapter MUST treat a rejection (`errorCode != 0`) as informational, not fatal — it means our client-side `TopstepRiskGate` (see `04-risk-engine.md`) failed to predict the server's decision, which is a bug worth logging loudly but not a reason to crash.
- The adapter translates server rejections into `OrderEvent(status="REJECTED")` with the error code in a `metadata` field.

### 3.4 CRITICAL DEFENSIVE SECTION — TopstepX `side` encoding

**This is a real-money silent-loss footgun.** ProjectX/TopstepX inverts the conventional `0/1` mapping:

- `0` = **Bid side = BUY** (you are hitting the bid to buy)
- `1` = **Ask side = SELL** (you are hitting the ask to sell)

The intuitive (and wrong) reading is `0=sell, 1=buy`. A junior dev refactoring this code will get it backwards. Every silent loss in the TopstepX community forum starts here.

**Required defensive measures, all of which MUST appear in `topstepx_client.py`:**

```python
from typing import Final, Literal

# TopstepX wire protocol — DO NOT REORDER, DO NOT CHANGE.
# Source: gateway.docs.projectx.com/docs/api-reference/order/order-place/
# Confirmed: research/tradovate-projectx-apis.md §BROKER B.5
# These constants are loud on purpose. If you "simplify" them, you will lose money.
SIDE_BUY:  Final[int] = 0   # Bid
SIDE_SELL: Final[int] = 1   # Ask

_SIDE_MAP: Final[dict[Literal["BUY", "SELL"], int]] = {
    "BUY":  SIDE_BUY,
    "SELL": SIDE_SELL,
}

def topstepx_side(side: Literal["BUY", "SELL"]) -> int:
    return _SIDE_MAP[side]
```

**Required unit test** (must live next to the adapter, must run in CI on every commit):

```python
def test_topstepx_side_encoding_is_inverted_from_intuition():
    assert SIDE_BUY  == 0, "TopstepX: 0 is BUY (Bid). Do not change."
    assert SIDE_SELL == 1, "TopstepX: 1 is SELL (Ask). Do not change."
    assert topstepx_side("BUY")  == 0
    assert topstepx_side("SELL") == 1

def test_order_intent_translation_buy_emits_zero():
    intent = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                          order_type="MARKET", client_order_id="t-1",
                          timestamp=datetime.now(UTC))
    body = TopstepXExecutionClient._translate(intent, account_id=1, contract_id="c")
    assert body["side"] == 0  # NOT 1.
```

No PR touching `topstepx_client.py` merges without this test passing.

### 3.5 Bracket model translation

`OrderIntent.bracket: Bracket | None` is broker-agnostic — ticks offsets only. The adapter computes prices and assembles the broker-specific structure.

| Aspect | `OrderIntent` | IB | TopstepX |
|---|---|---|---|
| Bracket primitive | `Bracket(stop_loss_ticks, take_profit_ticks)` | `IB.bracketOrder()` returns parent + 2 children, OCO via `ocaGroup` | Inline `stopLossBracket: {ticks, type}` + `takeProfitBracket: {ticks, type}` |
| Submission | One `place_order()` call | 3 sequential `placeOrder` calls; `transmit=True` only on the last | Single `Order/place` call |
| Modification | Replace bracket → cancel + re-place | Modify child orders individually | Modify via `Order/modify` with new bracket block |
| Server adjustment | n/a | Static prices; we re-place on partial fills | **Position Brackets** auto-track position size; **Auto-OCO** one-per-entry. We use Auto-OCO (per `Order/place`) for predictability. |
| Tick → price conversion | Adapter responsibility | `parent_fill_price ± ticks * minTick(0.25)` | Send ticks directly — server converts |

For market entries with brackets, IB's `bracketOrder()` requires a `limitPrice` for the parent. We use `take_profit_price` as the parent limit on a `LimitIfTouched` parent variant, OR — for true market entry — we submit the parent as `MarketOrder` with `transmit=False`, attach children with `parentId` set, and `transmit=True` only on the last child. This is the standard `ib_async` bracket idiom.

### 3.6 Auth model differences

| Aspect | IB | TopstepX |
|---|---|---|
| Credential type | Username + password (entered in Gateway UI) | Username + API key (env var) |
| Local process required | **Yes — IB Gateway or TWS must be running** before `connect()` | **No** — direct REST + SignalR |
| 2FA | Yes, mobile-app prompt at login | No — API key replaces password+2FA |
| Token lifetime | Session lives as long as Gateway runs; auto-relogins via IBC if configured | JWT ~24h (undocumented exactly; treat as 22h to be safe) |
| Refresh strategy | Gateway-side; Python client just reconnects | Pre-emptive `await client.authenticate()` at 22h mark + reactive on any 401 |
| Failure mode | Gateway crash → all sessions die | JWT expiry → 401 storm → reconnect + re-auth |

For headless operation on the Mac (per D14 + D15), IB Gateway with **IBC** (Interactive Brokers Controller) is preferred over TWS — smaller footprint, headless-friendly, scriptable login. See §6 Open Questions for the unresolved Gateway-vs-TWS choice.

### 3.7 Reconnect strategy (common)

| State on disconnect | Action |
|---|---|
| No open orders, flat | Backoff + reconnect. No risk. |
| Open orders, flat | Backoff + reconnect. On reconnect, fetch `get_open_orders()`, reconcile against journal, cancel any orphans. |
| Open position | **Critical**. Backoff + reconnect. Reconnect deadline: 90s on TopstepX, 5 min on IB paper. On deadline expiry: TopstepX → escalate to `04-risk-engine.md` force-flatten + Telegram alert; IB paper → log and continue (no money at risk). |
| Mid-`place_order` retry | Use `client_order_id` (§3.8) — broker dedupes; we will not double-fill. |

Backoff sequence: `1, 2, 4, 8, 16, 32, 60, 60, 60, ...` seconds. Jitter ±20% to avoid thundering-herd on shared infra. Cap at 60s.

### 3.8 Idempotency

`OrderIntent.client_order_id` is the dedup key. Requirements:

- **Unique across restarts** — generated as `f"{strategy_id}-{epoch_micros}-{uuid7()[:8]}"`. The epoch component makes restarts deterministic-looking in logs; the UUIDv7 suffix prevents collision on rapid-fire orders.
- **Persisted before submission** — the journal (`docs/.../06-observability.md` SQLite schema) records the `client_order_id` and `intent` *before* the broker call, so a crash mid-submit doesn't lose the ID.
- **Submitted as the broker's idempotency key**: IB → `Order.orderRef` field; TopstepX → `customTag` field (or fallback to recording our own ID in `metadata` and dedupe client-side if the platform rejects duplicates).
- **Adapter MUST NOT submit duplicate `client_order_id`s on retry** — before any `place_order` retry, the adapter consults its in-memory recent-submissions cache (last 5 minutes); on cache hit, skip submission and return the cached `OrderEvent`. Restart populates the cache from the journal (the last 5 minutes of intents).

### 3.9 Conformance test suite contract

A single shared `pytest` suite, parameterized over three fixtures (`SimExecutionClient`, `IBExecutionClient`-paper, `TopstepXExecutionClient`-Practice), asserts that **identical `OrderIntent` inputs produce identical (modulo timestamps and broker IDs) `OrderEvent` sequences**.

**Assertions** (each test is parameterized across all three adapters):

- `place_market_buy_then_fill`: input `OrderIntent(BUY, MARKET, 1)`; expected event sequence `[PENDING, WORKING, FILLED]` with `filled_quantity=1`.
- `place_bracket_then_take_profit_fill`: input bracketed market entry; simulate TP touch; expect parent `FILLED`, SL `CANCELED`, TP `FILLED`.
- `place_bracket_then_stop_fill`: mirror of above.
- `cancel_working_limit`: expect `[PENDING, WORKING, CANCELED]`.
- `cancel_all_clears_all_open`: place N, `cancel_all`, expect N × `CANCELED`.
- `restart_resumes_state`: place, kill adapter, restart; `get_open_orders()` matches pre-kill state.
- `duplicate_client_order_id_is_idempotent`: submit same `OrderIntent` twice; assert single broker order, two `place_order()` returns reference the same `broker_order_id`.

**Non-determinism handling**:
- For IB paper: fill timing is non-deterministic; we assert *event-set equality* (same set, any order) and *invariant assertions* (no FILLED before WORKING) rather than exact ordering.
- For TopstepX Practice: same approach; we additionally tag each test with `@pytest.mark.live_practice` and skip in default CI (run manually or on a nightly schedule).
- For SimExecutionClient: fully deterministic — exact event sequence is asserted.

**Where this lives**: `tests/conformance/test_execution_client_conformance.py`, importable from each adapter's own test module.

---

## 4. Implementation sketch

```python
# execution/ports.py
from typing import Protocol, Literal
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class Bracket:
    stop_loss_ticks: int
    take_profit_ticks: int

@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: int
    order_type: Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "BRACKET"]
    client_order_id: str
    timestamp: datetime
    limit_price: float | None = None
    stop_price: float | None = None
    bracket: Bracket | None = None

    # ----- helper methods (called by 04 RiskEngine) -----
    def signed_qty(self) -> int:
        """+quantity for BUY, -quantity for SELL. Used by Rule 4 max-position."""
        return self.quantity if self.side == "BUY" else -self.quantity

    def is_open_increasing_exposure(self, open_positions: dict[str, int]) -> bool:
        """True iff applying this intent would grow |position| on `symbol`.
        A flattening / reducing order returns False. Used by Rule 1 (hard-flat)."""
        current = open_positions.get(self.symbol, 0)
        projected = current + self.signed_qty()
        return abs(projected) > abs(current)

    def is_market_or_limit_open(self) -> bool:
        """True iff this intent opens exposure (vs. being a bracket child).
        Used by Rule 2 sub-check (STOP_REQUIRED). The strategy only ever emits
        MARKET / LIMIT / BRACKET intents; stops and stop-limits arrive as
        bracket children submitted by the adapter."""
        return self.order_type in ("MARKET", "LIMIT", "BRACKET")

    def with_stop(self, ticks: int) -> "OrderIntent":
        """Return a NEW OrderIntent with bracket.stop_loss_ticks replaced.
        Used by Rule 3 + §3.6 safety-buffer augmentation in 04."""
        if self.bracket is None:
            raise ValueError("with_stop() called on intent without a bracket")
        new_bracket = replace(self.bracket, stop_loss_ticks=ticks)
        return replace(self, bracket=new_bracket)

@dataclass(frozen=True)
class Position:
    """Broker-reported position snapshot. Returned by ExecutionClient.get_positions().
    The driver collapses a list[Position] into AccountState.open_positions
    (dict[symbol, signed_qty]) for the RiskEngine — see 04 §4.1."""
    symbol: str
    signed_qty: int              # +long, -short
    avg_entry_price: float
    unrealized_pnl: float
    opened_at: datetime

@dataclass(frozen=True)
class OrderEvent:
    client_order_id: str
    broker_order_id: str
    status: Literal["PENDING", "WORKING", "PARTIAL_FILL", "FILLED",
                    "CANCELED", "REJECTED"]
    filled_quantity: int
    avg_fill_price: float | None
    timestamp: datetime
    metadata: dict | None = None  # broker-specific error codes etc.

class ExecutionClient(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def place_order(self, intent: OrderIntent) -> OrderEvent: ...
    async def cancel_order(self, client_order_id: str) -> OrderEvent: ...
    async def cancel_all(self, symbol: str) -> list[OrderEvent]: ...
    async def get_positions(self) -> list[Position]: ...
    async def get_open_orders(self) -> list[Order]: ...
    async def get_account(self) -> AccountState: ...
```

```python
# execution/ib_client.py
from ib_async import IB, ContFuture, MarketOrder, LimitOrder

class IBExecutionClient:
    def __init__(self, host: str, port: int, client_id: int):
        self._ib = IB()
        self._host, self._port, self._cid = host, port, client_id
        self._contracts: dict[str, Contract] = {}
        self._recent: LRU[str, OrderEvent] = LRU(maxsize=10_000)

    async def connect(self) -> None:
        if not _ib_gateway_running(self._host, self._port):
            raise IBGatewayNotRunningError(self._host, self._port)
        await self._ib.connectAsync(self._host, self._port, clientId=self._cid)
        await self._resolve_contracts(["MNQ"])
        self._ib.disconnectedEvent += self._on_disconnect

    async def place_order(self, intent: OrderIntent) -> OrderEvent:
        if cached := self._recent.get(intent.client_order_id):
            return cached
        contract = self._contracts[intent.symbol]
        if intent.order_type == "BRACKET":
            parent, tp, sl = self._ib.bracketOrder(
                action=intent.side,  # IB accepts "BUY"/"SELL" verbatim
                quantity=intent.quantity,
                limitPrice=intent.limit_price or 0,
                takeProfitPrice=self._tp_price(contract, intent),
                stopLossPrice=self._sl_price(contract, intent),
            )
            for o in (parent, tp, sl):
                o.orderRef = intent.client_order_id
            trades = [self._ib.placeOrder(contract, o) for o in (parent, tp, sl)]
            ev = _trade_to_event(trades[0], intent, status="PENDING")
        else:
            order = _build_ib_order(intent)
            order.orderRef = intent.client_order_id
            trade = self._ib.placeOrder(contract, order)
            ev = _trade_to_event(trade, intent, status="PENDING")
        self._recent[intent.client_order_id] = ev
        return ev
```

```python
# execution/topstepx_client.py
from project_x import ProjectX
from typing import Final, Literal

SIDE_BUY:  Final[int] = 0   # Bid
SIDE_SELL: Final[int] = 1   # Ask

_TYPE_MAP: Final[dict[str, int]] = {
    "LIMIT": 1, "MARKET": 2, "STOP": 4,
}

class TopstepXExecutionClient:
    def __init__(self, username: str, api_key: str, account_name: str):
        self._username, self._api_key = username, api_key
        self._account_name = account_name
        self._client: ProjectX | None = None
        self._suite = None
        self._account_id: int | None = None
        self._recent: LRU[str, OrderEvent] = LRU(maxsize=10_000)

    async def connect(self) -> None:
        _assert_running_on_local_host()  # D14 guard
        self._client = ProjectX(username=self._username, api_key=self._api_key)
        await self._client.authenticate()
        accounts = await self._client.list_accounts()
        self._account_id = next(a.id for a in accounts if a.name == self._account_name)
        self._suite = await self._client.create_suite("MNQ")
        self._wire_event_handlers()

    @staticmethod
    def _translate(intent: OrderIntent, account_id: int, contract_id: str) -> dict:
        body = {
            "accountId":  account_id,
            "contractId": contract_id,
            "type":       _TYPE_MAP[intent.order_type if intent.order_type != "BRACKET" else "MARKET"],
            "side":       SIDE_BUY if intent.side == "BUY" else SIDE_SELL,
            "size":       intent.quantity,
            "customTag":  intent.client_order_id,
        }
        if intent.limit_price is not None:
            body["limitPrice"] = intent.limit_price
        if intent.bracket is not None:
            body["stopLossBracket"]   = {"ticks": intent.bracket.stop_loss_ticks,   "type": 4}
            body["takeProfitBracket"] = {"ticks": intent.bracket.take_profit_ticks, "type": 1}
        return body

    async def place_order(self, intent: OrderIntent) -> OrderEvent:
        if cached := self._recent.get(intent.client_order_id):
            return cached
        body = self._translate(intent, self._account_id, self._suite.instrument_id)
        resp = await self._client.post("/api/Order/place", json=body)
        if resp.get("errorCode", 0) != 0:
            ev = OrderEvent(intent.client_order_id, broker_order_id="",
                            status="REJECTED", filled_quantity=0,
                            avg_fill_price=None, timestamp=utcnow(),
                            metadata={"errorCode": resp["errorCode"]})
        else:
            ev = OrderEvent(intent.client_order_id, broker_order_id=str(resp["orderId"]),
                            status="PENDING", filled_quantity=0,
                            avg_fill_price=None, timestamp=utcnow())
        self._recent[intent.client_order_id] = ev
        return ev
```

```python
# execution/sim_client.py
class SimExecutionClient:
    """In-memory; configurable fill latency and slippage. Deterministic by seed."""
    def __init__(self, *, fill_latency_ms: int = 50, slippage_ticks: int = 1,
                 rng_seed: int = 0):
        self._fill_latency_ms = fill_latency_ms
        self._slippage_ticks = slippage_ticks
        self._rng = random.Random(rng_seed)
        self._orders: dict[str, OrderEvent] = {}
        self._positions: dict[str, Position] = {}
        # ... reuses Nautilus SimBroker fill model under the hood
```

### Shared translation table (`OrderIntent` → adapter call)

| `OrderIntent` field | `SimExecutionClient` | `IBExecutionClient` | `TopstepXExecutionClient` |
|---|---|---|---|
| `side="BUY"` | `+qty` | `action="BUY"` (string) | `side=0` (int, **Bid**) |
| `side="SELL"` | `-qty` | `action="SELL"` (string) | `side=1` (int, **Ask**) |
| `order_type="MARKET"` | immediate fill at last + slippage | `MarketOrder(...)` | `type=2` |
| `order_type="LIMIT"` | resting; fills on cross | `LimitOrder(...)` | `type=1` + `limitPrice` |
| `order_type="STOP"` | resting; fills on trigger | `StopOrder(...)` | `type=4` + `stopPrice` |
| `order_type="BRACKET"` | composite | `IB.bracketOrder(...)` 3-leg | inline `stopLossBracket` + `takeProfitBracket` |
| `client_order_id` | dict key | `Order.orderRef` | body `customTag` |
| `bracket.stop_loss_ticks` | tick offset | absolute price via `minTick` | sent as `ticks` directly |

---

## 5. Testing strategy

### 5.1 The side-encoding test (the footgun)

```python
def test_translate_buy_for_topstepx_emits_side_zero():
    intent = OrderIntent(symbol="MNQ", side="BUY", quantity=1,
                          order_type="MARKET",
                          client_order_id="t-1", timestamp=datetime.now(UTC))
    body = TopstepXExecutionClient._translate(intent, account_id=1, contract_id="c")
    assert body["side"] == 0

def test_translate_sell_for_topstepx_emits_side_one():
    intent = OrderIntent(symbol="MNQ", side="SELL", quantity=1,
                          order_type="MARKET",
                          client_order_id="t-2", timestamp=datetime.now(UTC))
    body = TopstepXExecutionClient._translate(intent, account_id=1, contract_id="c")
    assert body["side"] == 1

def test_side_constants_have_loud_names_and_locked_values():
    from execution.topstepx_client import SIDE_BUY, SIDE_SELL
    assert SIDE_BUY  == 0
    assert SIDE_SELL == 1
```

These run on every commit. The PR template includes a checkbox: "If you touched `topstepx_client.py`, these tests still pass."

### 5.2 Conformance suite

Parameterized across `[sim, ib_paper, topstepx_practice]`. Default CI runs `sim` only; nightly job runs all three. Each test runs identical `OrderIntent` sequences and asserts identical resulting `OrderEvent` event-sets (modulo non-deterministic IDs/timestamps).

### 5.3 Reconnect resilience

- Use `pytest-asyncio` + a mock SignalR transport (or `aioresponses` for IB) that can be force-closed at every state: pre-connect, mid-place-order, between-order-and-fill, mid-fill-stream.
- Assert: after reconnect, journal-derived state == broker-derived state. No duplicate orders.
- Bounded retry: assert that after `reconnect_deadline_seconds`, the right escalation path fires (Telegram alert + RiskEngine force-flatten on TopstepX; log-only on IB).

### 5.4 Idempotency

- Submit same `OrderIntent` twice via `place_order()`; assert the broker (or mock) sees exactly one request, and both calls return the same `OrderEvent`.
- Kill the adapter mid-submission (mock raises after `httpx.post` enqueued); restart; resubmit; assert no duplicate at broker.

### 5.5 Auth failure paths

- Expired JWT → 401 → adapter re-auths and retries → success.
- Wrong API key → 401 persistently → adapter raises `BrokerAuthError` (no infinite retry loop).
- IB Gateway not running → `IBGatewayNotRunningError` with operator-actionable message.

### 5.6 Test ladder — the four rails

Plan 11 added a fourth rail, **TopstepX Sim**, between IB Paper and live TopstepX. The full ladder, in order of fidelity to live Topstep semantics + cost to run:

| Rail | Adapter | Cost | What it validates |
|---|---|---|---|
| 1. Backtest | `SimExecutionClient` (Plan 4) | $0 | Strategy logic, P&L math, journaling. No rules enforcement. |
| 2. IB Paper | `IBExecutionClient` (Plan 6) | $0 | Wire-format round-trip, fills against IB's paper-account fill model, reconnect handling. No Topstep rules. |
| 3. TopstepX Sim | `TopstepXSimClient` (Plan 11) | $0 | Topstep rule semantics — phantom MLL liquidation, max-position cap, hard-flat 15:10 CT, EFA scaling tiers, Consistency 50% gate. Same `CombineIntradayDrawdown` / `EFAStandardEoDDrawdown` policies as live. |
| 4. TopstepX Live | `TopstepXExecutionClient` (Plan 8) | Combine fee | The real account. Identical risk-gate code path as rail 3. |

The bot validates against rails 1 → 2 → 3 before any rail-4 spend. Rail 3 catches the classes of bug that rail 1 + 2 cannot (anything Topstep-rule-shaped) without burning a real Combine. The named scenarios in `bot.execution.topstepx_sim.scenarios` (Combine pass, Combine fail by MLL, Combine fail by max-position, EFA payout flow, EFA Consistency breach, hard-flat 15:10) are the rail-3 integration suite; rail 4 reuses the same risk-gate so a rail-3 pass implies a rail-4 pass for those rule paths.

---

## 6. Open questions

1. **TopstepX SignalR reconnect deadline**: spec'd at 90 s here. Is that aggressive enough? If we're flat, we can tolerate longer; if we hold an open position under the trailing MLL, every second of disconnect is unhedged exposure. Possible refinement: dynamic deadline — 30 s when in-position, 5 min when flat. Resolution: prototype against TopstepX Practice during build; measure realistic reconnect times under deliberate WAN flap. See `04-risk-engine.md` for the rule-engine side of the force-flatten trigger.

2. **IB paper fill realism**: how optimistic are IB paper fills for MNQ specifically? Community reports range from "near-perfect for liquid futures" to "ignores spread entirely." Action: during week-1 IB paper soak, log every `(intent_price, fill_price, contemporaneous_bid_ask)` and compute slippage distribution. If paper-fills are within 0.5 tick of true mid, we trust them; if not, we treat IB paper as a smoke-test rail only and rely on `SimExecutionClient` for performance evaluation.

3. **IB Gateway vs IB TWS for headless Docker-on-Mac**: TWS has the full UI (heavy, RAM-hungry, harder to script). Gateway is lighter and headless-friendly. `IBC` (Interactive Brokers Controller) can drive either, but is more commonly paired with Gateway. The complication: TWS auto-restart-on-logout is more robust than Gateway's. For a Mac that the user is also using interactively, Gateway-in-Docker may collide with the user's own TWS session (clientId conflict). Resolution: default to **Gateway + IBC** in Docker, document the clientId allocation so a human user can run TWS alongside on a different clientId.

4. **TopstepX `customTag` size/charset limits**: not documented. Our `client_order_id` format (`{strategy}-{epoch_micros}-{uuid7-8char}`) is ~40 chars ASCII. If TopstepX rejects, fall back to storing only the uuid7 portion in `customTag` and the full ID in our own journal.

5. **Bracket modification semantics**: if the strategy wants to trail the stop, do we (a) cancel + re-place the bracket, (b) call `Order/modify` on TopstepX, or (c) on IB modify the child stop directly? Each has different atomicity guarantees. v1 punt: only static brackets (no trailing). Revisit when a strategy needs trailing stops.

6. **Partial fills on bracket entries**: if the parent is partial-filled, IB and TopstepX handle the children differently (IB: children sit at full size, OCO closes both on any TP/SL touch — over-cover risk; TopstepX Position Brackets: auto-resize; Auto-OCO: per-entry, no auto-resize). v1 sizes orders to 1 contract for MNQ entry, so partial fills are not possible. When we lift to multi-contract entries this becomes load-bearing.

---

## 7. References

- `00-architecture-overview.md` — D6, D7, D8, D14, §7 critical defensive item #1.
- `../research/tradovate-projectx-apis.md` — TopstepX REST + SignalR shape, `side` encoding (§BROKER B.5), `project-x-py` SDK, no-sandbox warning.
- `../research/alpaca-futures-api.md` — confirms Alpaca is excluded (no futures in 2026).
- `01-data-pipeline.md` — contract roll calendar (front-month resolution for IB).
- `04-risk-engine.md` — force-flatten path on broker-down; pre-trade order denial.
- `06-observability.md` — journal schema for `client_order_id` persistence; Telegram alert taxonomy.
- `07-config-and-deploy.md` — env var loading, startup reconciliation, IB Gateway / IBC process management.
- `project-x-py` docs — <https://project-x-py.readthedocs.io/en/stable/>
- TopstepX Gateway docs — <https://gateway.docs.projectx.com/>
- `ib_async` — <https://github.com/ib-api-reloaded/ib_async>
