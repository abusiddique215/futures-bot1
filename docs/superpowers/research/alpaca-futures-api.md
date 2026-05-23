# Alpaca Futures API Support — Research Findings

**Research date:** 2026-05-22
**Subject:** Can Alpaca serve as the broker for an NQ/MNQ futures trading bot (paper and/or live)?

---

## Bottom line (read this first)

**Alpaca does NOT currently offer futures trading — not paper, not live, not via API, not via UI.** This conclusion is consistent across every primary source examined: Alpaca's own docs, the 2024 and 2025 year-in-review blog posts, the most recent Alpaca staff forum reply (February 2026), the BrokerChooser 2026 review, the alpaca-py SDK (v0.43.4, 2026-04-29), and the official `alpacahq/alpaca-mcp-server` v2.

**The premise in the original research brief is incorrect.** Alpaca did not "add futures in 2024." That feature has been on a "roadmap / future plans" footnote since at least 2019 and was explicitly deprioritized again in February 2026. Forex, futures, and bonds-other-than-Treasuries remain unavailable.

**Implication for the spec:** if NQ/MNQ paper trading is a hard requirement, **Alpaca cannot be the broker.** You'll need a different broker for futures (see Alternatives section at the bottom). Alpaca remains a strong option for equities/ETF/options/crypto paper trading if the bot scope is widened or split across brokers.

---

## Evidence that futures are not supported (primary sources)

| Source | Date | Quote / Finding |
|---|---|---|
| Alpaca docs — Getting Started — https://docs.alpaca.markets/us/docs/getting-started | live (fetched 2026-05-22) | Supported asset classes listed as stocks, options, crypto. Verbatim: *"Stay tuned for our API updates as we have on roadmap plans for futures, FX, and much more!"* — i.e. futures are still roadmap, not shipped. |
| Alpaca docs — Trading API — https://docs.alpaca.markets/us/docs/trading-api | live (fetched 2026-05-22) | Lists stocks (incl. fractional), crypto, options. Futures not listed. |
| Alpaca docs — Paper Trading — https://docs.alpaca.markets/us/docs/paper-trading | live (fetched 2026-05-22) | Paper trading covers stocks, crypto, options. No mention of futures. |
| Alpaca blog — 2024 Year in Review — https://alpaca.markets/blog/alpaca-2024-year-in-review/ | Jan 2025 | New launches listed: options, IRA accounts via Broker API, FIX API, High-Yield Cash. Futures not mentioned. |
| Alpaca blog — 2025 in Review — https://alpaca.markets/blog/alpacas-2025-in-review/ | early 2026 | 2025 launches: multi-leg options, fixed income (US Treasuries), 24/5 equity trading, tokenization, securities lending. Forward-looking 2026 roadmap quote: *"Product offerings we look to deliver include global stocks, index options, and more."* Futures absent from both the achievements list and the forward roadmap. |
| Alpaca community forum — "Futures trade in alpaca" (thread #11632) — https://forum.alpaca.markets/t/futures-trade-in-alpaca/11632 | Most recent Alpaca staff reply: **February 2026** | Alpaca staff: *"Futures are not currently on the project timelines for the next two quarters. Bonds and global stocks are being worked on first."* (Strongest evidence — recent, official, dated.) |
| Alpaca community forum — "Support for futures trading" (thread #1476) — https://forum.alpaca.markets/t/support-for-futures-trading/1476 | Sept 2023 (last staff reply) | Dan Whitnable (Alpaca): *"No futures on the immediate roadmap, but options are on the way."* |
| BrokerChooser — Alpaca Trading Review 2026 — https://brokerchooser.com/broker-reviews/alpaca-trading-review | 2026 | Confirms via third party: *"You can't trade futures at Alpaca Trading. There is no forex, bonds, futures, funds, or CFDs."* (URL returned 403 to WebFetch but is corroborated by the BrokerChooser snippet in multiple search aggregators and by the dedicated `/alpaca-trading-futures` subpage.) |
| Digital By Default — Alpaca Review 2026 — https://digitalbydefault.ai/blog/alpaca-markets-review-2026 | 2026 | Lists asset classes as US stocks/ETFs, options, crypto, tokenized equities. No futures. |
| alpaca-py PyPI — https://pypi.org/pypi/alpaca-py/json | v0.43.4 uploaded **2026-04-29** | SDK has no `FuturesHistoricalDataClient`, no `FuturesDataStream`, no futures order request models. Asset classes covered: stocks, crypto, options. |
| alpaca-py GitHub — https://github.com/alpacahq/alpaca-py | v0.43.4 | README/examples cover stocks, crypto, options. No `futures/` example notebook. Recent changelog adds perpetual crypto and ASCX exchange (v0.42.1), DataFeed for overnight equity trading (v0.41.0) — no futures. |
| Alpaca MCP server — https://github.com/alpacahq/alpaca-mcp-server | v2 (current) | README: *"trade stocks, ETFs, crypto, and options."* No futures tools. |

**Staleness check:** every source above either is the live docs/PyPI as of 2026-05-22, a 2026 article, or the most recent Alpaca staff response in the forum (Feb 2026). The conclusion is current, not stale.

---

## Per-question answers

> Because Q1 is "no," Q2–Q10 and Q12–Q13 collapse to "not applicable." They are recorded as such for completeness rather than padded with speculative information.

### 1. Does Alpaca currently offer futures trading via API in 2026?
**No.** See evidence table. The single most authoritative quote is Alpaca staff, Feb 2026: *"Futures are not currently on the project timelines for the next two quarters."* — https://forum.alpaca.markets/t/futures-trade-in-alpaca/11632

### 2. Which futures contracts are tradable? NQ/MNQ?
**Not applicable.** No futures contracts of any kind — CME, ICE, micro, full-size, financial, energy, metals, ag. Specifically NQ and MNQ are not tradable on Alpaca.

### 3. Paper trading for futures?
**Not applicable.** Alpaca paper trading is well-supported but only for stocks, crypto, and options (https://docs.alpaca.markets/us/docs/paper-trading). Default $100k starting balance, resettable. No futures sandbox exists.

### 4. Account requirements / minimums / approval timeline for futures?
**Not applicable.** No futures account product to apply for.

### 5. Historical futures market data?
**Not applicable.** Alpaca Market Data API covers stocks (~6+ years), crypto, and options. No futures data feed. Source: https://alpaca.markets/data and https://docs.alpaca.markets/us/

### 6. Real-time futures WebSocket?
**Not applicable.** Alpaca's WebSocket / SSE streams exist for equity bars/trades/quotes, crypto, and options. No futures stream classes in alpaca-py (no `FuturesDataStream` in the SDK).

### 7. Order types for futures?
**Not applicable.** For reference, Alpaca's equity/options/crypto order surface does support market, limit, stop, stop-limit, trailing stop, and bracket/OCO — but only on those asset classes.

### 8. Position/P&L tracking, margin behavior for futures?
**Not applicable.** Alpaca's margin engine is Reg-T equities margin (and crypto margin is not offered for most retail accounts). No futures SPAN / intraday-vs-overnight futures margin engine exists.

### 9. Trading session hours for futures (Sunday 6pm ET open etc.)?
**Not applicable.** Alpaca recently added 24/5 *equity* trading (https://alpaca.markets/blog/alpacas-2025-in-review/), but this is not the CME futures session. Sunday 6pm ET futures open is irrelevant because there are no futures.

### 10. Rate limits?
**For equities/options/crypto** (in case Alpaca is used for a non-futures sibling system): standard Alpaca limit is 200 API requests/minute on the free tier and configurable higher on paid Algo Trader Plus / Unlimited. Not specific to futures since futures don't exist on the platform.

### 11. Official Python SDK details
- **Package:** `alpaca-py` (the legacy `alpaca-trade-api` is deprecated; do not start a new project on it).
- **Latest version:** **0.43.4**, released **2026-04-29** (confirmed via PyPI JSON API: https://pypi.org/pypi/alpaca-py/json).
- **Python compatibility:** Python 3.8 – 3.14.
- **Install:** `pip install alpaca-py`
- **Source:** https://github.com/alpacahq/alpaca-py, https://alpaca.markets/sdks/python/

**Working code patterns (equities/options/crypto — futures patterns DO NOT EXIST):**

```python
# Connect with API keys + paper endpoint
from alpaca.trading.client import TradingClient
trading_client = TradingClient("API_KEY_ID", "API_SECRET", paper=True)

# Get account info
account = trading_client.get_account()
print(account.buying_power, account.cash, account.portfolio_value)

# Query positions / fills
positions = trading_client.get_all_positions()
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus
orders = trading_client.get_orders(
    filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=50)
)

# Cancel all open orders for a symbol (no native single-symbol cancel; filter then cancel)
open_orders = trading_client.get_orders(
    filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=["AAPL"])
)
for o in open_orders:
    trading_client.cancel_order_by_id(o.id)
```

**Subscribing to "live MNQ minute bars" and "place a market buy on MNQ with bracket attached":**
These cannot be written for Alpaca because MNQ is not a tradable symbol on the platform. There is no futures data stream and no futures order request model in alpaca-py. Any code claiming to do this would be fabricated.

### 12. Known limitations / quirks
The futures-specific quirks the brief asked about (optimistic paper fills, no overnight carry, data lag) all presuppose a feature that doesn't exist. For *Alpaca paper trading in general* (equities/options/crypto), the documented quirks are: no simulation of dividends, borrow fees, market impact, slippage, or regulatory fees; PDT rule enforced; order quantities not checked against real liquidity; no fill emails. Source: https://docs.alpaca.markets/us/docs/paper-trading

### 13. Pricing — futures fees / data?
**Not applicable.** No futures = no futures pricing schedule. (For context only: Alpaca's market data tiers are free SIP-IEX, Algo Trader Plus, and Unlimited; these cover equities/options/crypto.)

### 14. Alpaca MCP server (`alpacahq/alpaca-mcp-server`) — futures support?
**No.** Current version is V2 (a complete rewrite using FastMCP + OpenAPI). README explicitly scopes it to *"stocks, ETFs, crypto, and options."* No futures tools, no futures resources. Source: https://github.com/alpacahq/alpaca-mcp-server

---

## What this means for the trading bot spec

1. **The Alpaca-based design path is blocked for NQ/MNQ.** Adapt the spec to either (a) swap the broker layer, or (b) split: Alpaca for equities/options sibling strategies, a different broker for futures.
2. **Don't waste time prototyping against alpaca-py expecting futures.** There is no symbol, no order model, no data stream, no MCP tool. It will fail at the API call level, not at the strategy level.
3. **Architecture impact:** abstract the broker behind an interface (`BrokerAdapter`, `MarketDataAdapter`) so swapping brokers is a localized change. This is the single most important takeaway given the false premise.

---

## Alternatives for NQ/MNQ paper trading via Python (pointer list, not a deep dive)

| Broker / Platform | Python SDK / API | Paper trading | Notes |
|---|---|---|---|
| **Interactive Brokers** | `ib_async` (fork of `ib_insync`, actively maintained), official `ibapi` | Yes — paper account standard | Most production-credible. Steeper learning curve. Real CME data subscription required for live ticks. |
| **Tradovate** | Official REST + WebSocket API | Yes — demo accounts free | Futures-native broker. Cleanest API among futures-focused brokers. |
| **TopstepX / ProjectX** | REST API (OpenAPI-spec) | Yes — funded-trader sim | Popular for prop / evaluation accounts; check rate limits before relying on it for HFT. |
| **NinjaTrader** | NinjaScript (C#) primarily; Python via bridges | Yes | Less native for pure-Python stacks. |
| **Tradier** | REST API | Yes | Equities + options only — does NOT add futures. Skip if futures-only is the need. |
| **databento + paper-fill simulator** | `databento` Python SDK for CME data | DIY paper fills | If you only need realistic CME data and will simulate fills yourself, databento is the cleanest data source. Pair with one of the brokers above for live execution. |

A reasonable default for a Python-first NQ/MNQ bot in 2026 is **Tradovate (paper + live) + databento (historical CME data)** or **Interactive Brokers via `ib_async`** if you want one broker for everything.

---

## References (consolidated)

- https://docs.alpaca.markets/us/docs/getting-started
- https://docs.alpaca.markets/us/docs/trading-api
- https://docs.alpaca.markets/us/docs/paper-trading
- https://docs.alpaca.markets/us/
- https://alpaca.markets/
- https://alpaca.markets/blog/alpaca-2024-year-in-review/
- https://alpaca.markets/blog/alpacas-2025-in-review/
- https://forum.alpaca.markets/t/futures-trade-in-alpaca/11632  (Feb 2026 staff reply — most recent authoritative statement)
- https://forum.alpaca.markets/t/support-for-futures-trading/1476
- https://forum.alpaca.markets/t/futures-planned/251
- https://github.com/alpacahq/alpaca-py
- https://pypi.org/project/alpaca-py/  (v0.43.4, 2026-04-29)
- https://github.com/alpacahq/alpaca-mcp-server  (V2, stocks/ETFs/crypto/options only)
- https://alpaca.markets/sdks/python/
- https://brokerchooser.com/broker-reviews/alpaca-trading-review  (3rd-party confirmation, 2026)
- https://digitalbydefault.ai/blog/alpaca-markets-review-2026  (3rd-party confirmation, 2026)
