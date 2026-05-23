# Tradovate and TopstepX / ProjectX APIs — 2026 Research

**Research date:** 2026-05-22
**Context:** Selecting broker rails for a Python NQ/MNQ trading bot. Two operating
modes (Surge for Topstep Combine eval-passing, Maintenance for funded payout
farming). Need (1) a free paper-trading rail for dev/test and (2) a live path
into a Topstep funded account.

**Staleness note:** ProjectX / TopstepX is moving fast. The single biggest event
in this space happened in Feb–Apr 2026 (ProjectX → TopstepX consolidation, TFD
acquisition). Anything older than Q1 2026 should be re-verified before relying
on it.

---

## TL;DR

| Question | Answer |
|---|---|
| Free paper rail for dev? | **Tradovate Demo** (14-day free trial, real-time data, NQ/MNQ supported). After 14d the demo expires and you must subscribe — practically: rotate emails, or use IBKR paper as a longer-running second rail. |
| Live Topstep rail? | **TopstepX API (built on ProjectX Gateway)** — $29/mo ($14.50 w/ `topstep` code). Works with Combine, Express Funded, Live Funded *and* the free Practice Account. |
| Same adapter? | **No.** Different auth, different transport (Tradovate raw WS frames + custom JSON envelope; TopstepX REST + SignalR hubs), different order semantics (Tradovate `placeOrder`/`placeOSO`; ProjectX flat `Order/place` with embedded brackets). |
| Topstep still on Tradovate? | Existing accounts yes; **all new Combines are TopstepX-only** since Aug 2025. Tradovate is being slowly squeezed out of the Topstep pipeline. |

---

## BROKER A — Tradovate

### 1. API surface (2026)

- **REST + WebSocket**, split by purpose. REST for auth and one-shot ops;
  WebSocket for streaming user/account events and market data. Two separate
  WebSocket endpoints — operations WS and market-data WS.
- **Demo REST base:** `https://demo.tradovateapi.com/v1`
- **Demo WS:** `wss://demo.tradovateapi.com/v1/websocket`
- **Live REST base:** `https://live.tradovateapi.com/v1`
- **Live WS:** `wss://live.tradovateapi.com/v1/websocket`
- **Market data WS (shared):** `wss://md.tradovateapi.com/v1/websocket`
  (separate from ops WS; requires its own auth handshake)
- **Auth:** OAuth-like access tokens via `POST /auth/accesstokenrequest`.
  Credentials = Tradovate username + password + `cid` (app ID) + `sec` (one of
  your personal API secret keys). Returns a bearer token + an MD-specific
  short-lived token (`mdAccessToken`).
- Source: <https://api.tradovate.com/>,
  <https://community.tradovate.com/t/api-websocket-and-marketdata-websocket/4037>

### 2. Free demo

- **Yes, free for 14 days.** $50,000 sim balance. Real-time market data
  included for the trial period.
- **NQ and MNQ both supported** (Tradovate is a CME-only futures broker; NQ
  and MNQ are first-class). MNQ initial margin ~$825, day-trade margin ~$50.
- After 14 days the demo expires; continued sim trading typically requires a
  paid Tradovate subscription. Common community workaround: new email →
  new trial. Treat that as fragile.
- Sources: <https://info.tradovate.com/simulated-trading>,
  <https://www.tradovate.com/resources/markets/?p=MNQ>

### 3. Order types

- Market, Limit, Stop, Stop-Limit. Trailing Stop supported (see
  `cullen-b/Tradovate-Python-Client` `PlaceTrailStop.py`).
- **OSO / OCO / brackets** via `placeOSO` (Order-Sends-Order) and `placeOCO`
  endpoints — this is how you build a bracket (entry + TP + SL).
- Source: <https://api.tradovate.com/>, GitHub example repos under
  <https://github.com/tradovate>

### 4. Positions, P&L, margin

- Position state and fills are pushed via the user-events WS — recommended
  pattern is reactive (subscribe, don't poll). REST endpoints exist for
  one-shot queries (`position/list`, `account/list`).
- Tradovate enforces broker-level margin checks; in demo it mirrors the live
  margin model, including day-trade vs initial.
- Source: <https://github.com/tradovate/example-api-faq/blob/main/docs/RestApiVsWebSocketApi.md>

### 5. Market data

- **Real-time CME data included in the 14-day demo.** That's the key win.
- On **live** accounts, since Sept 2022 CME requires all API users to
  register as a CME sub-vendor under an Individual License Agreement (ILA).
  Non-pro fees: ~$12/mo CME L1 bundle, ~$41/mo for L2 across
  CME/CBOT/NYMEX/COMEX. Pro fees: ~$156/mo per exchange.
- Tradovate **also** charges a $25/mo API subscription on live accounts.
  Total live-API monthly: ~$37–$525 depending on tier.
- **The "free API" path on live Tradovate is essentially blocked by CME fees.**
- Sub-minute bars / ticks: yes (market depth, time & sales available via MD WS).
- Sources:
  <https://support.tradovate.com/s/article/Non-Professional-Monthly-Data-Rates-Tradovate>,
  <https://community.tradovate.com/t/is-cme-sub-vendor-requirement-for-api-access-is-290-per-month/6215>,
  <https://blog.pickmytrade.trade/tradovate-automation-skip-the-api-fee-and-cme-license/>

### 6. Rate limits

- Tradovate does not publish a precise public rate-limit table. Community
  consensus: order placement is throttled at the account level (a few orders
  per second is safe; bursts can be rejected). The WS connection has its own
  heartbeat (`[]` keepalive) every ~2.5s — failing to send it disconnects you.
- Source: <https://github.com/tradovate/example-api-faq>

### 7. Python clients (current state)

| Client | Stars | Last meaningful update | Status |
|---|---|---|---|
| `cullen-b/Tradovate-Python-Client` | ~30 | 6 commits total, low activity | Skeleton, REST-only. Has auth, market/limit/trail-stop placement, position queries. **No WebSocket.** |
| `antonio-hickey/TradovatePy` | ~42 | 26 commits, no releases | More structured but also REST-heavy. |
| `tradovate` (PyPI) | low | no releases in 12+ months | Effectively abandoned. |

- **There is no actively-maintained, full-featured, WebSocket-capable Python
  Tradovate client in 2026.** Plan to write the WS layer yourself (or port
  from Tradovate's own JS/C# examples).
- Official Tradovate org publishes example code in JS/C#, not Python.
- Sources: <https://github.com/cullen-b/Tradovate-Python-Client>,
  <https://github.com/antonio-hickey/TradovatePy>,
  <https://github.com/tradovate>,
  <https://snyk.io/advisor/python/tradovate>

### 8. Minimal code shape (Tradovate demo)

```python
# Auth (REST)
POST https://demo.tradovateapi.com/v1/auth/accesstokenrequest
{
  "name": "your_username",
  "password": "your_password",
  "appId": "MyBot",
  "appVersion": "1.0",
  "cid": <your-cid>,
  "sec": "<your-secret-key>"
}
# -> {"accessToken": "...", "mdAccessToken": "...", "expirationTime": "..."}

# Operations WS
ws = connect("wss://demo.tradovateapi.com/v1/websocket")
# 1) wait for server "o" frame
# 2) authorize: "authorize\n1\n\n<accessToken>"
# 3) subscribe to user events: "user/syncrequest\n2\n\n{...}"
# 4) heartbeat with "[]" every ~2.5s

# Market data WS (subscribe to MNQ 1-minute bars)
md = connect("wss://md.tradovateapi.com/v1/websocket")
# authorize with mdAccessToken
# "md/getChart\n3\n\n{\"symbol\":\"MNQM6\",\"chartDescription\":{\"underlyingType\":\"MinuteBar\",\"elementSize\":1,\"elementSizeUnit\":\"UnderlyingUnits\"}}"

# Bracket order (entry + TP + SL in one call)
POST /order/placeOSO  # parent market + child OCO (limit TP, stop SL)
```

Tradovate uses a **custom text-framed WS protocol** — `<op>\n<id>\n<query>\n<body>`
— not JSON-only and not SignalR. Plan adapter work accordingly.

### 9. Demo → live

- Same code, same protocol; only base URL changes (`demo.` → `live.`).
- To go live you need: funded Tradovate brokerage account, $25/mo API
  subscription, CME ILA registration + monthly data fees. Cleanest path is
  the prop-firm route below.

### 10. Prop firms on Tradovate in 2026

- Topstep: **existing** accounts can still use Tradovate. **New** Combines
  (post-Aug 2025) are TopstepX-only; account resets after Aug 2025 are also
  TopstepX-only. The Tradovate path is being phased out.
- Other firms still on Tradovate: Apex, MyFundedFutures, TradeDay (post-
  ProjectX-shutdown migrations are still settling).
- Source: <https://proptradingvibes.com/blog/topstep-trading-platforms>,
  <https://blog.pickmytrade.trade/projectx-tradingview-alerts-guide-futures/>

---

## BROKER B — TopstepX / ProjectX

### 1. Platform consolidation — what actually happened

- ProjectX was a multi-tenant trading platform powering several prop firms
  (Bulenox, Tradeify, Lucid, Alpha Futures, Phidias, TradeDay, **Topstep**).
- **End of Feb 2026:** ProjectX went exclusive to Topstep. The other firms
  scrambled to find new infra.
- **April 1, 2026:** Topstep acquired **The Futures Desk (TFD)**, folding
  TFD's tech into TopstepX.
- **Late April 2026:** TopstepX API access launched publicly.
- The "ProjectX Gateway API" branding and docs survive because TopstepX is
  built on it. Effectively: ProjectX is now Topstep-internal, and **the
  public API for Topstep traders is what's documented at
  `gateway.docs.projectx.com` against the `api.topstepx.com` host.**
- Source: <https://proptradingvibes.com/blog/topstep-trading-platforms>,
  <https://help.topstep.com/en/articles/11187768-topstepx-api-access>

### 2. API surface

- **REST + SignalR (over WebSocket).** Microsoft SignalR — *not* raw WS,
  *not* socket.io. You need a SignalR client (`signalrcore` for Python).
- **REST base:** `https://api.topstepx.com`
- **User hub (SignalR):** `https://rtc.topstepx.com/hubs/user`
- **Market hub (SignalR):** `https://rtc.topstepx.com/hubs/market`
- **Auth:** API key + username → `POST /api/Auth/loginKey` → JWT session
  token. Token expiry not explicitly documented (community reports ~24h).
  Use the JWT as `Authorization: Bearer <token>` and as `accessToken` for
  the SignalR connection.
- **Public docs:** <https://gateway.docs.projectx.com/>
- Sources:
  <https://gateway.docs.projectx.com/docs/getting-started/connection-urls/>,
  <https://gateway.docs.projectx.com/docs/getting-started/authenticate/authenticate-api-key/>

### 3. Combine / paper / sim access

- **Free Practice Account** is offered to all active Combine, Express, or
  Funded users. $150k sim balance, 15-lot max, unlimited free resets.
  **Must be manually activated** in the dashboard add-ons.
- **The API subscription works across all environments** — Practice,
  Combine, Express Funded, Live Funded — once you're paying $29/mo
  ($14.50 with `topstep` code).
- **There is NO standalone free sandbox.** You cannot use the API without
  a paid subscription, even for the Practice Account.
- **There is NO sandbox/test environment separate from your real account.**
  All API orders are considered final, no reversal.
- Sources:
  <https://help.topstep.com/en/articles/8284134-practice-account>,
  <https://help.topstep.com/en/articles/11187768-topstepx-api-access>

### 4. Python SDK — `project-x-py`

- **`TexasCoding/project-x-py`** — community SDK, **actively maintained**.
- ~30 stars, **481 commits**, 16 releases, latest v3.5.8 (Sept 2025),
  MIT license, 1,300+ tests, semver since v3.1.1, async-first.
- Requires Python 3.12+.
- Features: SignalR streaming wrapper, async orders, historical bars,
  59+ TA indicators (Polars-backed), L2 orderbook, multi-instrument
  trading suite, RTH/ETH session filtering (experimental).
- Other Python repos exist (`phsphd/Topstepx_Python_API`,
  `mceesincus/tsxapi4py`) — fewer features, less polish. `project-x-py`
  is the clear choice.
- Source: <https://github.com/TexasCoding/project-x-py>,
  <https://project-x-py.readthedocs.io/en/stable/>

### 5. Order types

| API code | Meaning |
|---|---|
| 1 | Limit |
| 2 | Market |
| 4 | Stop |
| 5 | TrailingStop |
| 6 | JoinBid |
| 7 | JoinAsk |

- Side: `0` = Bid (buy), `1` = Ask (sell). (Yes, counterintuitive — buying
  *hits the bid* in ProjectX's model. Confirm in paper first.)
- **Brackets are first-class:** the `Order/place` body accepts inline
  `stopLossBracket` and `takeProfitBracket` objects (ticks-based). Much
  cleaner than Tradovate's OSO/OCO construction.
- **Two flavors of brackets** at the platform level:
  - *Position Brackets* — server-managed, attach to whole position, auto-
    adjust as size changes.
  - *Auto-OCO Brackets* — per-entry-order, one OCO pair per fill.
- `linked_order_id` for manual OCO relationships.
- Sources:
  <https://gateway.docs.projectx.com/docs/api-reference/order/order-place/>,
  <https://help.tradesyncer.com/en/articles/11746420-projectx-bracket-orders-explained-position-brackets-vs-auto-oco-brackets>

### 6. Market data

- Real-time quotes, trades, depth via SignalR market hub
  (`GatewayQuote`, `GatewayTrade`, `GatewayDepth` events).
- Historical bars via REST: `POST /api/History/retrieveBars`
  (this endpoint has its own rate limit, separate from the global).
- Market data is included in the $29 subscription — **no separate
  CME fee, no ILA** (TopstepX handles redistribution licensing). This is
  the single biggest cost advantage vs Tradovate live.

### 7. Rate limits

- Not published in spec form. `project-x-py` defaults to **60 req/min,
  burst 10** as conservative client-side throttling.
- `POST /api/History/retrieveBars` has its own (stricter) limit.
- Server returns HTTP 429 on excess; backoff + retry required.
- Sources: <https://project-x-py.readthedocs.io/en/stable/configuration.html>,
  <https://docs.pickmytrade.io/docs/projectx-error-codes-topstepx-fix-guide/>

### 8. Topstep rule enforcement — server vs client

- Trailing drawdown, daily loss limit, max contract size, end-of-day
  liquidation are **enforced server-side** by ProjectX/TopstepX. You
  cannot exceed them via the API — the server will reject the order
  (`errorCode != 0`) or auto-liquidate.
- **You still want a client-side rule engine** for: (a) predicting *before*
  submitting an order that it would violate a rule (so you can size down
  rather than eat a rejection), (b) tracking the trailing high-water mark
  in real time for your own logic, (c) defending against
  "almost-violations" with safety margin.
- Source (rule list, not API spec):
  <https://help.projectx.com/components/orders> and Topstep rules doc
  already in `/docs/superpowers/research/topstep-rules.md`.

### 9. Minimal code shape (project-x-py)

```python
import asyncio
from project_x import ProjectX

async def main():
    # uses PROJECTX_USERNAME + PROJECTX_API_KEY env vars
    async with ProjectX.from_env() as client:
        await client.authenticate()

        # Historical bars
        bars = await client.get_bars("MNQ", days=5, interval=1)  # 1-min

        # Real-time + orders via TradingSuite
        suite = await client.create_suite("MNQ")
        # subscribe to quotes
        @suite.events.on("quote")
        async def on_quote(q):
            print(q.bid, q.ask)

        # Place a bracket-armed market order
        resp = await suite.orders.place_market_order(
            contract_id=suite.instrument_id,
            side=0, size=1,
            stop_loss_ticks=10,
            take_profit_ticks=20,
        )

asyncio.run(main())
```

Raw REST equivalent for placing the same order:

```http
POST https://api.topstepx.com/api/Order/place
Authorization: Bearer <jwt>
{
  "accountId": 12345,
  "contractId": "CON.F.US.MNQ.M26",
  "type": 2,
  "side": 0,
  "size": 1,
  "stopLossBracket":  {"ticks": 10, "type": 4},
  "takeProfitBracket":{"ticks": 20, "type": 1}
}
```

### 10. Production readiness

- ProjectX gateway is several years old (powered multiple prop firms
  pre-2026) — mature core.
- TopstepX-specific evolution is fast post-TFD acquisition; expect
  endpoints to be added/changed quarterly. Pin SDK versions.
- "No sandbox" + "all orders final" + "VPS/VPN forbidden" means **bugs
  cost real money / real account violations** even when run against
  Practice. Treat Practice like prod.
- Community reports of error-code surprises are tracked at
  <https://docs.pickmytrade.io/docs/projectx-error-codes-topstepx-fix-guide/>
  — worth scanning before going live.

---

## Side-by-side

| Dimension | Tradovate | TopstepX / ProjectX |
|---|---|---|
| Free paper rail | **Yes, 14d** with real-time data | Practice Account is free, **but API needs $14.50–29/mo subscription** |
| Live cost (API + data) | ~$37/mo minimum (sub) + $290+ CME ILA — pricey | **$14.50–29/mo all-in** (data bundled) |
| Topstep funded payouts | Existing accounts only; phasing out | **Yes, primary path going forward** |
| Auth | OAuth-style: user+pass+cid+secret → token + mdToken | API key + username → JWT |
| Transport | REST + custom text-framed WS (ops) + separate MD WS | REST + SignalR (user hub + market hub) |
| Order semantics | `placeOrder`, `placeOSO`, `placeOCO` (separate calls) | Single `Order/place` with inline brackets |
| Bracket model | OSO/OCO order-graph | Server-managed position brackets *or* per-order auto-OCO |
| Python SDK | None production-grade; community skeletons only | `project-x-py` — actively maintained, async, polished |
| Rate limit | Not published; safe ~few orders/sec | ~60 req/min, burst 10 (client-enforced default) |
| Sandbox | Demo env mirrors live, separate host | **No separate sandbox** — Practice is the test target |
| VPS allowed | Yes (live is unrestricted) | **No — Topstep ToS bans VPS/VPN even with API** |
| Sub-minute bars | Yes (MD WS) | Yes (REST + stream) |
| RTH/ETH | Both | Both (RTH/ETH filter experimental in SDK) |

---

## Recommendation

### v1 paper rail: **Tradovate Demo**

- Free, real-time CME data, NQ/MNQ first-class, no subscription needed for
  the first 14 days. Perfect for the first development sprint where you'll
  be churning the strategy and adapter code anyway.
- Limitation: 14-day clock. Plan to either (a) cycle demo trials during
  development, or (b) graduate to TopstepX Practice as soon as you sign up
  for a Topstep Combine (you'll do this anyway for the eval).
- **IBKR paper as a longer-running second rail** — see below.

### v1.5 prop-firm rail: **TopstepX API on Practice → Combine → Funded**

- Same code path runs against Practice ($150k sim, free with Combine sub),
  Combine, and Funded — only the `accountId` changes. This is the *one*
  big advantage TopstepX has over Tradovate: zero-friction promotion from
  sim to live.
- $14.50/mo (with `topstep` discount code) is negligible vs CME ILA costs
  on raw Tradovate.
- Use `project-x-py` rather than rolling your own SignalR client unless
  you have a strong reason — it already handles auth refresh,
  reconnection, rate-limit throttling, and bracket order shape.

### Separate adapters required

The two APIs are **not** similar enough for one adapter. Distinct work in:

1. **Auth flow** — credential model differs entirely (Tradovate cid/sec
   pair vs TopstepX username+key → JWT).
2. **Streaming transport** — Tradovate's custom text-frame WS protocol
   (`<op>\n<id>\n\n<body>` with periodic `[]` heartbeats) vs SignalR
   handshake/negotiate/invoke. Different libraries, different reconnect
   semantics, different message framing.
3. **Bracket model** — Tradovate requires composing OSO + OCO; TopstepX
   accepts inline `stopLossBracket`/`takeProfitBracket` on a single
   `Order/place`. Your strategy layer should emit broker-agnostic
   "entry + sl_ticks + tp_ticks" intents and let each adapter translate.

Design the strategy layer against a thin abstract `BrokerAdapter` with
methods like `place_bracket(symbol, side, size, sl_ticks, tp_ticks)`,
`subscribe_bars(symbol, interval)`, `get_positions()`, `get_account()`,
and stream events. Two concrete adapters: `TradovateAdapter` and
`TopstepXAdapter`. The Topstep rule engine sits *above* both adapters,
not inside either.

### IBKR paper as backup

- **Viable as a second free paper rail**, not as your live Topstep path
  (IBKR is its own brokerage, not a Topstep route).
- Pros: indefinite paper account (no 14-day expiry), `ib_async` (the
  maintained successor to `ib_insync`) is solid, NQ/MNQ available.
- Cons: requires running TWS or IB Gateway locally (annoying for CI/headless),
  different contract-month rolling semantics, IBKR paper market data is
  delayed unless you pay for the data subscription (CME real-time on paper
  costs).
- **Use IBKR paper for long-running soak tests** (multi-day stability,
  reconnect handling) where Tradovate's 14-day clock is a blocker. Not
  the primary rail.
- Sources: <https://github.com/erdewit/ib_insync>,
  <https://ib-insync.readthedocs.io/api.html>,
  <https://supa.is/article/interactive-brokers-python-api-2026-automated-trading-live-markets>

---

## "Watch out for" callouts

1. **TopstepX `side` encoding is inverted from convention.** `0` = buy
   (Bid), `1` = sell (Ask). Hardcode the constants in your adapter with
   loud names; this is the #1 silent-loss footgun in the API.
2. **TopstepX has no sandbox.** The Practice Account *is* your testbed,
   and even there your API actions are accounted-for and final. A bug
   that machine-guns orders will burn through your Practice account fast
   and still trip Topstep's "prohibited behaviors" radar if it looks like
   abuse.
3. **VPS/VPN ban on TopstepX.** Topstep ToS forbids running automation
   from a VPS or via VPN — even with the official API. This is a
   deployment architecture constraint, not a code one: plan for the bot
   to run on the same physical machine the user trades from. Cloud
   deployment of the live Topstep rail is **not** compliant.
4. **Tradovate has no production-grade Python SDK in 2026.** You'll be
   writing the WS layer yourself. Budget time for it. The two existing
   community clients are REST-only skeletons and won't carry you to
   real-time bars + reactive fills.
5. **CME data fees nuke "free live Tradovate API".** Outside of a prop
   firm wrapping the data redistribution, expect $300+/mo of CME fees
   to use Tradovate's live API directly. The TopstepX subscription
   bundles this; Tradovate doesn't.
6. **Topstep's Tradovate path is shrinking.** New Combines are
   TopstepX-only since Aug 2025. Building heavily on Tradovate for the
   live Topstep rail is fighting the tide.

---

## Sources (consolidated)

### Tradovate
- <https://api.tradovate.com/>
- <https://info.tradovate.com/simulated-trading>
- <https://www.tradovate.com/resources/markets/?p=MNQ>
- <https://www.tradovate.com/pricing/>
- <https://support.tradovate.com/s/article/Tradovate-API-Access>
- <https://support.tradovate.com/s/article/Non-Professional-Monthly-Data-Rates-Tradovate>
- <https://community.tradovate.com/t/api-websocket-and-marketdata-websocket/4037>
- <https://community.tradovate.com/t/is-cme-sub-vendor-requirement-for-api-access-is-290-per-month/6215>
- <https://github.com/tradovate>
- <https://github.com/tradovate/example-api-faq/blob/main/docs/RestApiVsWebSocketApi.md>
- <https://github.com/cullen-b/Tradovate-Python-Client>
- <https://github.com/antonio-hickey/TradovatePy>
- <https://blog.pickmytrade.trade/tradovate-automation-skip-the-api-fee-and-cme-license/>

### TopstepX / ProjectX
- <https://gateway.docs.projectx.com/>
- <https://gateway.docs.projectx.com/docs/getting-started/authenticate/authenticate-api-key/>
- <https://gateway.docs.projectx.com/docs/getting-started/connection-urls/>
- <https://gateway.docs.projectx.com/docs/api-reference/order/order-place/>
- <https://help.topstep.com/en/articles/11187768-topstepx-api-access>
- <https://help.topstep.com/en/articles/8284134-practice-account>
- <https://help.topstepx.com/settings/api>
- <https://help.projectx.com/components/orders>
- <https://help.tradesyncer.com/en/articles/11746420-projectx-bracket-orders-explained-position-brackets-vs-auto-oco-brackets>
- <https://github.com/TexasCoding/project-x-py>
- <https://project-x-py.readthedocs.io/en/stable/quickstart.html>
- <https://project-x-py.readthedocs.io/en/stable/configuration.html>
- <https://docs.pickmytrade.io/docs/projectx-error-codes-topstepx-fix-guide/>
- <https://docs.pickmytrade.io/docs/connect-projectx-to-topstep-api/>
- <https://proptradingvibes.com/blog/topstep-trading-platforms>
- <https://proptradingvibes.com/blog/topstepx-platform-guide>
- <https://lunefi.com/blog/topstepx-auto-trader-2026-best-bots-api-setup-rules-success-stories>

### IBKR (backup rail)
- <https://www.interactivebrokers.com/en/trading/ib-api.php>
- <https://ib-insync.readthedocs.io/api.html>
- <https://supa.is/article/interactive-brokers-python-api-2026-automated-trading-live-markets>
