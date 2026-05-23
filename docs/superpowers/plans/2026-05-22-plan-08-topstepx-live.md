# Plan 8 — TopstepX Live Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Ship `TopstepXExecutionClient` (live broker for Topstep Combine + Funded). After this plan: bot can execute orders against TopstepX Practice (paper) and Combine/Funded (live, real money) accounts. This is the most safety-critical adapter — `SIDE_BUY=0` is a real-money footgun.

**Architecture:** `TopstepXExecutionClient` implements `ExecutionClient` Protocol via `project-x-py>=3.5.9`. REST + SignalR (websocket) hybrid. JWT auth with 22-hour pre-refresh. Hostname VPS-guard fail-closed. 90-second reconnect deadline (live, where every second of disconnect is unhedged exposure under trailing MLL). Side encoding HARDCODED with required unit test that asserts `SIDE_BUY==0`.

**Tech Stack:**
- `project-x-py>=3.5.9,<4.0` (bump from Plan 1's stripped deps). Pre-Plan-1 verification confirmed PyPI presence + Python 3.12+ support.
- All other deps already in place.

**Critical defensive items (from spec 02 §3.4 + 00 §7):**
1. **`SIDE_BUY: Final[int] = 0` / `SIDE_SELL: Final[int] = 1`** — Required unit test asserts both. Loud constant names. Comment must say: "DO NOT change. TopstepX inverts the conventional 0/1. Wrong value = silent loss."
2. **Hostname VPS-guard** — At connect time, `socket.gethostname()` must match a whitelist. Live env only. Fail-closed.
3. **90-second reconnect deadline** — Stricter than IB paper's 5 min. After deadline expires → emit `LiveBrokerDownCritical` telemetry + escalate to risk gate force-flatten.
4. **JWT pre-refresh at 22 hours** — Token life ~24h; refresh proactively before expiry.

**Scope:**
- TopstepXExecutionClient with all 8 ExecutionClient methods
- Side-encoding defensive constants + required unit test
- Hostname guard with whitelist
- Reconnect with 90s deadline
- Mocked SDK in tests (no real network)
- Tag `plan-08-topstepx-live-complete`

**Out of scope:**
- ❌ Manual live-paper test against real TopstepX Practice account (operator runs this once before live)
- ❌ TopstepX market-data subscription (we use IB live bars; TopstepX is order-only in v1)
- ❌ JWT refresh storms / 401 retry handling beyond pre-emptive refresh

---

## Scope: Single batch-agent. ~10 tasks. ~30 new tests.

### Tasks

1. **Bump `project-x-py` pin to `>=3.5.9,<4.0`** + install + verify v3 API surface. Note any 3.5.8 → 3.5.9 changes. Commit: `chore(deps): project-x-py 3.5.9 for TopstepX live`.

2. **Side-encoding defensive constants + unit test** — `src/bot/execution/topstepx_constants.py` containing `SIDE_BUY: Final[int] = 0`, `SIDE_SELL: Final[int] = 1`, `topstepx_side(side: Literal["BUY", "SELL"]) -> int`. Required unit test asserts literal values. Commit: `feat(execution): TopstepX side-encoding constants + required unit test`.

3. **`TopstepXExecutionClient.__init__` + hostname guard** — `src/bot/execution/topstepx_client.py`. Constructor takes username, api_key, account_name, live_hostname_whitelist (Iterable[str] | None), env (Literal["paper", "live"]). On `live` env: assert `socket.gethostname()` ∈ whitelist; else raise RuntimeError. Tests: hostname allowed, hostname blocked (mocked), paper env skips check. Commit: `feat(execution): TopstepXExecutionClient init + hostname VPS-guard`.

4. **`connect()` + JWT auth** — `await client.authenticate()` via project-x-py. Resolve `account_id` via `list_accounts()` matching `account_name`. Open suite via `await client.create_suite("MNQ")`. Wire event handlers. JWT pre-refresh at 22h (use `asyncio.create_task` background loop). Mock SDK. Tests: connect succeeds, JWT refresh task scheduled. Commit: `feat(execution): TopstepXExecutionClient.connect + JWT pre-refresh`.

5. **`place_order` MARKET + idempotency** — Translate `OrderIntent` → body with `side=SIDE_BUY|SIDE_SELL` (the load-bearing inversion), `type=2` for MARKET, `customTag=client_order_id`. POST to `/api/Order/place`. Idempotency cache. Required test: `test_translate_buy_emits_side_zero` — verifies BUY produces `body["side"] == 0`. Commit: `feat(execution): TopstepXExecutionClient.place_order MARKET + side-encoding test`.

6. **`place_order` BRACKET** — Inline `stopLossBracket` + `takeProfitBracket` with `ticks` values (TopstepX server handles conversion). Single REST call, not 3 like IB. Tests with mock SDK. Commit: `feat(execution): TopstepXExecutionClient.place_order BRACKET (server-attached OCO)`.

7. **`cancel_order` / `cancel_all` / snapshot queries** — Translate to SDK calls. Tests. Commit: `feat(execution): TopstepXExecutionClient.cancel + snapshot queries`.

8. **Reconnect with 90-second deadline** — On SignalR disconnect, exponential backoff (1s→2s→4s→8s→16s→32s→60s cap). Track elapsed; if > 90s, emit telemetry CRITICAL alert + invoke `gate.force_flatten_now("LIVE_BROKER_DOWN")` via callback. Tests with mock that disconnects + simulates long down period. Commit: `feat(execution): TopstepXExecutionClient 90s reconnect deadline → force-flatten escalation`.

9. **Server-side rejection handling** — Translate `errorCode != 0` responses to `OrderEvent(status="REJECTED", metadata={"errorCode": ...})`. Tests: simulate server rejection. Commit: `feat(execution): TopstepXExecutionClient server rejection translation`.

10. **Conformance test + final verify + tag** — Cross-broker conformance: `[sim, ib_paper_mock, topstepx_mock]` produce identical `OrderEvent` sequence for `place_market_buy_then_fill`. Tag `plan-08-topstepx-live-complete`.

## Constraints

- ALL tests mock the project-x-py SDK. No real network.
- Side-encoding test is non-negotiable; commit body must reference "SIDE_BUY=0 footgun" so future devs see it in `git log`.
- ruff + mypy strict clean after each commit.
- `async def` tests; no `asyncio.run()`.

## Test counts target

345 + ~30 = ~375.

## Notes for executor

- The `project-x-py` SDK may not be straightforward to import-mock if it has heavy init. Consider injecting a `client_factory: Callable[[], ProjectX]` like IB pattern.
- spec 02 §3.4 has the canonical SIDE_BUY=0 docstring; reuse verbatim.
- `_translate` static method must produce the wire body — required test calls it directly with a sample OrderIntent.
