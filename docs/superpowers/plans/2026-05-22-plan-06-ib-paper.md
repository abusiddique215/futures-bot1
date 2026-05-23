# Plan 6 — IB Paper Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Full implementation of `IBExecutionClient` (via `ib_async`). Replaces Plan 2's `IBLiveBarStream` skeleton with a working live bar feed + executes orders against IB Paper. After this plan: bot can paper-trade MNQ on Interactive Brokers.

**Architecture:** `IBExecutionClient` implements the `ExecutionClient` Protocol. Connects to IB Gateway on `localhost:7497` (paper). Resolves front-month MNQ contract via `qualifyContractsAsync`. Submits MARKET + BRACKET orders. Reconnects on disconnect with exponential backoff up to 5 minutes. Live bars come from `IBLiveBarStream` (Plan 2 skeleton, now filled in). Wires into Plan 4's `BacktestEngine`-style loop (sync engine becomes async live engine).

**Tech Stack:** `ib-async 2.1.0` (already installed). Note: this is the 2.x major version per pre-Plan-1 verification — the spec was written for 1.x. We MUST verify API surface as the first task.

**ib-async API note:** Some 1.x → 2.x breaking changes are possible. Plan 2 only imported but didn't exercise the API. This plan exercises it. Surface incompatibilities in Task 1.

**Scope notes:**
- ib_async 2.x integration tests are MOCKED in CI (no actual IB Gateway). A separate `@pytest.mark.live_paper` test exists for manual nightly verification (deferred).
- Reconnect logic spec'd at 5-min deadline for IB paper per spec 02 §3.3.
- Order placement is async (`ib.placeOrder` returns a Trade object).
- Plan 6 ships SKELETON for force-flatten wiring — Plan 7's full impl wires alerts.

**Deliverable:**
- `IBExecutionClient` passes all 8 methods of the `ExecutionClient` Protocol against a mock `IB()` instance.
- `IBLiveBarStream.connect()` no longer raises NotImplementedError; emits Bars via `BarAggregator`.
- Conformance test (spec 02 §3.9): identical event sequence vs `SimExecutionClient` for `place_market_buy_then_fill`.
- Tag `plan-06-ib-paper-complete`.

---

## Scope

This plan is dense (real broker integration). Single batch-agent execution. ~10 tasks. Aim for ~200 lines of code + ~30 new tests.

### Tasks

1. **Verify `ib_async 2.x` API surface** — small smoke test that imports `ib_async.IB, Future, MarketOrder, LimitOrder` and instantiates them (no network). If 1.x → 2.x renamed anything, surface here. Commit: `chore(ib): verify ib_async 2.x API surface`.

2. **`IBExecutionClient.__init__` + state** — `bot/execution/ib_client.py`. Constructor takes `host, port, client_id`. State: `_ib: IB | None`, `_contracts: dict[str, Contract]`, `_recent: dict[str, OrderEvent]` (idempotency cache). Tests: construction, initial state empty. Commit: `feat(execution): IBExecutionClient init + state`.

3. **`connect()` + contract resolution** — Async connect to `localhost:7497`; resolve `Future("MNQ", exchange="CME")` to a qualified contract. Mock `ib_async.IB` via dependency injection (constructor takes an `ib_factory: Callable[[], IB]`). Tests: connect creates IB instance + resolves contracts. Commit: `feat(execution): IBExecutionClient.connect + contract resolution`.

4. **`place_order` — MARKET** — Simple market order: `ib.placeOrder(contract, MarketOrder(action=intent.side, totalQuantity=intent.quantity))`. Idempotent on `intent.client_order_id` via `_recent` cache. Returns `OrderEvent(status="PENDING", broker_order_id=str(trade.order.orderId))`. Tests: place market, check cache hit on duplicate. Commit: `feat(execution): IBExecutionClient.place_order MARKET + idempotency`.

5. **`place_order` — BRACKET** — Use `IB.bracketOrder(action, quantity, limitPrice, takeProfitPrice, stopLossPrice)`. Convert `intent.bracket.stop_loss_ticks` × `minTick(0.25 for MNQ)` to dollar offsets; entry fill price reference depends on Mode — for v1, use a notional limit (since IB bracketOrder needs a limit). Document as deviation. Tests: bracket order produces 3 child orders, parent.transmit=False, last child transmit=True. Commit: `feat(execution): IBExecutionClient.place_order BRACKET (3-leg OCO)`.

6. **`cancel_order` + `cancel_all`** — `ib.cancelOrder(order)` + iterate open orders. Tests: cancel emits OrderEvent(status="CANCELED"). Commit: `feat(execution): IBExecutionClient.cancel_order + cancel_all`.

7. **`get_positions` / `get_open_orders` / `get_account`** — Snapshot queries. Use `ib.positions()` + `ib.openOrders()` + `ib.accountSummary()`. Convert IB types to our `Position` / `Order` / `AccountState` dataclasses. Tests with mock. Commit: `feat(execution): IBExecutionClient snapshot queries`.

8. **Reconnect strategy** — `_on_disconnect` handler with exponential backoff (1s → 2s → 4s → 8s → 16s → 32s → 60s cap). 5-minute deadline → emit telemetry alert. Tests with mock that disconnects then reconnects. Commit: `feat(execution): IBExecutionClient reconnect with 5-min deadline`.

9. **`IBLiveBarStream` full impl** — Replaces Plan 2 skeleton's NotImplementedError. `connect()` connects to IB Gateway + subscribes to 5-sec bars via `ib.reqRealTimeBars`. `subscribe()` async-iterates the 5-sec bars through `BarAggregator` → yields aggregated `Bar` instances. Tests with mock IB. Commit: `feat(data): IBLiveBarStream.connect + subscribe (Plan 2 skeleton filled in)`.

10. **Conformance test + final verify + tag** — `tests/test_execution_conformance.py`: parameterized over `[sim, ib_paper_mock]`, asserts identical `OrderEvent` sequence for `place_market_buy_then_fill`. Verify ruff + mypy + pytest. Tag `plan-06-ib-paper-complete`.

## Constraints

- ib_async network calls are MOCKED in tests. Use `ib_async.IB` substitute with `unittest.mock.AsyncMock` or a custom Fake.
- All async work uses `asyncio` — make tests `async def` to avoid the asyncio.run loop warning Plan 3 hit.
- The actual nightly live-paper test is marked `@pytest.mark.live_paper` + `@pytest.mark.skip` for now.
- Spec patches from `pre-plan1-verification.md`: ib-async 2.x is the installed version; the spec 02 referenced 1.x. Surface API drift in Task 1 if any.

## Out-of-scope for Plan 6

- ❌ Live nightly paper-test automation (manual for v1)
- ❌ Trailing stops (v1 uses static brackets)
- ❌ Partial-fill handling beyond logging (v1 sizes orders to 1 contract for MNQ entry, so partials don't happen)
- ❌ IBC headless 2FA automation (operator launches IB Gateway manually)
- ❌ `commission_per_trade` accounting in TradeReport — defer to Plan 7
