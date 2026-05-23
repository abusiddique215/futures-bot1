# NQ / MNQ Futures Data Sources — Research

Date: 2026-05-22
Scope: Historical + live data for E-mini Nasdaq-100 (NQ) and Micro E-mini Nasdaq-100 (MNQ), targeting a solo dev Python bot for backtesting (5+ yrs minute bars) and paper-then-live trading.

> **CME license note up-front:** CME Globex data feeds are licensed at the **exchange** level, not the **vendor** level. Whether you go through Databento, IBKR, Tradovate, IQFeed, or dxFeed, you will still owe CME a per-exchange fee. The "non-professional" rate for CME Globex (covers NQ + MNQ) is currently ~**$3–5/exchange/month** for non-display/automated use, billed by the vendor. Many vendor prices below *include* this CME pass-through; some add it on top. Always confirm.

---

## 1. Per-source comparison

### Alpaca futures
- **Coverage:** None for NQ / MNQ. Alpaca's market data API covers equities, equity options, and crypto only. Futures trading and futures market data are **not available** as of May 2026.
- **Recommendation:** Skip. Don't try to fudge NQ via QQQ — basis blows up around news / overnight.

### Polygon.io (Futures Beta)
- **Coverage:** CME Globex (CME, CBOT, NYMEX, COMEX) — includes NQ + MNQ. In **beta** as of 2026; access rolling out in batches.
- **History depth advertised:** 10+ years of trades/quotes.
- **Granularity:** Tick (trades + quotes), aggregated bars (sec/min/hour/day).
- **Delivery:** REST, WebSocket, flat-file dumps. Official Python SDK.
- **Cost:** Pricing tier not yet finalized for beta; stock futures bundle from Polygon historically lands in the $99–$199/mo range for retail/individual.
- **Continuous contracts:** No native panama/ratio rolled series — per-expiration contracts; you build the continuous yourself.
- **License:** Standard non-display + non-redistribution for individual subscription. CME fees may be passed through.
- **Verdict:** Solid candidate **if** they grant access; beta status = no SLA promise yet.

### Databento (GLBX.MDP3 dataset)
- **Coverage:** Full CME Globex MDP 3.0 — every NQ + MNQ expiration, going back to ~2010 for full-depth MBO; OHLCV bars back further.
- **Granularity:** MBO (full order book), MBP-10, MBP-1 (top of book), trades (tick), OHLCV-1s / 1m / 1h / 1d.
- **Delivery:** Python SDK (`databento`), REST, live WebSocket. Native pandas DataFrame integration. CSV / DBN / JSON export.
- **Live latency:** Sub-millisecond from CME colocation; vendor-grade.
- **Cost:**
  - **$125 free credits** on signup — historical only, ~6 months of MNQ minute bars or several years of daily.
  - **Usage-based historical:** ~$2–$10/GB depending on schema (OHLCV cheap, MBO expensive). 5 yrs of NQ + MNQ 1-min OHLCV ≈ a few dollars.
  - **Live CME:** Usage-based live tier was **discontinued April 2025**. Live now requires a subscription: **Standard $179/mo**, Plus / Unlimited higher.
- **Continuous contracts:** Provides per-expiration symbols + symbology helpers (`continuous` resolution, e.g. `NQ.n.0` front-month). Roll method configurable (calendar, open interest, volume).
- **License:** Non-display and automated trading allowed under individual / Standard plan. CME pass-through included in subscription. No redistribution.
- **Verdict:** Gold-standard data quality. Backtesting on $125 free credit is realistic. The $179/mo cliff for live data is the catch.

### dxFeed
- **Coverage:** Full CME including NQ + MNQ. Up to 2 yrs tick, 9 yrs minute, 40 yrs daily.
- **Granularity:** Tick, minute, daily, plus market replay.
- **Delivery:** REST + streaming API, Python client (`dxfeed-python`). Less polished SDK than Databento.
- **Cost:** Plans advertised from $19/mo, but the cheap tiers are heavily restricted (delayed / limited symbols). Realistic real-time CME futures plan is **$50–$120/mo** before CME pass-through.
- **Continuous:** Provides continuous symbology; rolled series available.
- **License:** Non-pro + algorithmic OK on retail plans. No redistribution.
- **Verdict:** Decent middle ground; less developer mindshare than Databento, harder to find Python tutorials.

### CQG
- **Coverage:** All CME futures including NQ + MNQ.
- **Granularity:** Tick + bars.
- **Delivery:** REST, WebSocket, FIX, Continuum API.
- **Cost:** **$595/mo base** (Integrated Client) + $45 API add-on + per-fill charges. CQG Data Factory historical priced separately ($100+ packages).
- **License:** Professional-grade, redistribution possible.
- **Verdict:** **Skip for solo dev.** Institutional pricing.

### IQFeed (DTN)
- **Coverage:** CME including NQ + MNQ. **180 days tick**, multi-year minute, decades of daily.
- **Granularity:** True tick-by-tick, 1-sec, 1-min, daily.
- **Delivery:** Proprietary TCP socket protocol. Python wrappers exist (`pyiqfeed`, `iqfeed-py`) but third-party and somewhat dated.
- **Cost:** Base IQFeed **~$24.87/mo** for the North American futures surcharge, **+ ~$1/mo per exchange** for CME-only non-pro Globex package **only if you have a funded futures account at a qualified broker**. Without that: standard non-pro fees apply (~$25/exchange/mo).
- **Live latency:** Low; long-trusted retail-tier feed.
- **Continuous:** Yes, continuous symbols (`@NQ#`, `@MNQ#`).
- **License:** Non-display / algorithmic permitted on non-pro plan.
- **Verdict:** Excellent value **if** you already have a futures broker account that qualifies you for the $1/exchange tier. Otherwise mediocre.

### Tradovate
- **Coverage:** All CME including NQ + MNQ.
- **Granularity:** Tick + bars via API.
- **Delivery:** REST + WebSocket. Unofficial Python wrappers exist; no official Python SDK.
- **Cost:** Market data **$12/mo** for the basic CME bundle as part of a Tradovate brokerage account. (Free month with new account.) API access has historically required a separate fee but recent plans bundle it.
- **History:** Live tick + recent bars; **limited historical depth** (months, not years). Not a backtesting source.
- **License:** Non-pro for the account holder. No redistribution.
- **Verdict:** Good **live data** source if you plan to broker through Tradovate anyway. Will **not** cover 5 yrs of historical.

### Interactive Brokers (IBKR)
- **Coverage:** CME futures incl. NQ + MNQ. Top of book (L1) via the **US Securities Snapshot & Futures Value Bundle**.
- **Granularity:** L1 ticks (snapshots, not true tick stream — rate-limited), 1-min bars. Historical bars only ~few years deep via API; daily bars further.
- **Delivery:** TWS API, IB Gateway. Python: `ib_insync` (community), official `ibapi`.
- **Cost:** **~$10/mo non-pro** for the futures bundle, **waived at $30/mo commissions**. CME exchange fees pass-through small (single dollars).
- **Live latency:** ~250 ms snapshot quotes — IBKR is **not a true tick feed**, it aggregates and throttles. Fine for swing / minute-bar bots, problematic for HFT or tight scalping.
- **Continuous:** `ContFut` contract type provides front-month continuous; method = back-adjusted, not Panama. Limited customization.
- **License:** Non-display / algo permitted for account holder.
- **Verdict:** Cheapest live feed if you broker through IBKR. **Throttled quotes** are the key caveat.

### Yahoo Finance (`yfinance`)
- **Coverage:** Continuous NQ via `NQ=F`, MNQ via `MNQ=F`. Per-expiration not reliably available.
- **Granularity:** 1-min bars limited to last ~7 days; 5-min ~60 days; daily for years.
- **Delivery:** `yfinance` Python library (scrapes Yahoo). Unofficial; rate-limited; breaks periodically.
- **Cost:** Free.
- **Live latency:** 15-min delayed nominally; sometimes real-time but unreliable.
- **Continuous:** Yes, but the rollover logic is opaque, **gaps and stale ticks during overnight Globex session are common**, and bar boundaries don't align with CME session boundaries. Don't use for backtesting strategies sensitive to volume or intraday microstructure.
- **License:** Yahoo TOS forbids redistribution and "commercial" use — gray area for personal algo trading.
- **Verdict:** **Prototyping only.** Do not use for production backtests on a prop-firm strategy.

### TradingView (unofficial)
- **Coverage:** NQ, MNQ, all CME via CME_MINI feed (15-min delayed on free tier).
- **Granularity:** Tick / 1-min / etc., depending on Pine timeframe, accessed via unofficial `tvdatafeed` Python lib.
- **Cost:** TradingView Premium (~$60/mo) for real-time CME; unofficial scraping libraries break frequently when TV updates auth.
- **Delivery:** No public REST API. `tvdatafeed` does WebSocket scraping with a TV account.
- **License:** TV TOS forbids automated scraping; commercial / algo use of TV data is **not permitted**. You will get banned.
- **Verdict:** Don't build a trading bot on TradingView data. Use it for charts, not feeds.

### Nasdaq Data Link (formerly Quandl)
- **Coverage:** Historical futures continuous series via the legacy `CHRIS/CME_NQ#` family — but this dataset is **deprecated / stale**; CHRIS continuous contracts haven't been actively maintained since the Quandl→Nasdaq transition.
- **Granularity:** Daily only for free tiers; intraday requires premium publisher data.
- **Cost:** Free tier for daily; paid datasets vary by publisher.
- **Delivery:** REST + Python (`nasdaqdatalink`).
- **Continuous:** Yes, but stale.
- **License:** Free-tier data CC-licensed; premium has redistribution restrictions.
- **Verdict:** Useful for **daily-bar context** (long-term trend overlays), not for minute-bar backtests.

### Free CME sample / educational data
- CME offers sample MDP 3.0 captures (a few days) for free on their developer portal.
- **Use case:** Test your parser, not a backtest.

### AlgoSeek
- **Coverage:** 157 most liquid futures incl. NQ + MNQ; data starts **May 2009**.
- **Granularity:** Tick → daily, OHLCV + trades + quotes.
- **Cost:** **Quote-based**, typically **$500–$5000+ one-time** per dataset for retail individual licenses; institutional pricing higher.
- **Delivery:** S3 / SFTP flat files (CSV / Parquet).
- **Continuous:** Provides both per-expiration and continuous.
- **License:** Non-redistribution; quant research and algorithmic trading permitted.
- **Verdict:** High quality. One-time purchase = no recurring fee. Worth considering for the historical leg if going production.

### Kibot
- **Coverage:** Top-25 continuous + per-expiration including NQ. **Since 2009.**
- **Granularity:** Tick w/ bid-ask, 1-sec, 1-min, daily.
- **Cost:** One-time purchase: **$30–$100 per instrument** for intraday minute history; tick+quote ~$100–$300 per instrument. Bundles cheaper per-symbol.
- **Delivery:** ZIP download (CSV).
- **Continuous:** Yes, back-adjusted continuous available as a separate file.
- **License:** Personal use license; no redistribution.
- **Verdict:** **Best low-cost one-time historical option** for solo dev. Buy once, own the data.

### TickData (now part of OneTick)
- **Coverage:** Deep historical for all CME including NQ + MNQ. 15+ yrs tick.
- **Granularity:** Tick + quotes.
- **Cost:** Quote-based, **$1000+ typical** for individual futures product full history.
- **Delivery:** Flat files.
- **Verdict:** Overkill for v1.

### FirstRateData
- **Coverage:** NQ from Jan 2008, MNQ from launch (2019).
- **Granularity:** 1-min, 5-min, 30-min, 1-hour, daily. **No tick.**
- **Cost:** **One-time ~$129** for full NQ history, ~$99 for MNQ. Bundles available.
- **Delivery:** ZIP / CSV download.
- **Continuous:** Yes, back-adjusted + non-adjusted variants provided.
- **License:** Personal & commercial use OK; no redistribution.
- **Verdict:** **Very strong fit for the historical leg of a solo dev's backtest** — buy once, no monthly fee, clean continuous + per-contract files.

---

## 2. Tier-1 recommendation — under $50/mo, realistic for solo dev

**Backtest historical:** One-time purchase of **FirstRateData NQ + MNQ minute bars** (~$200 one-time, both instruments incl. continuous + per-contract). Supplement with **Databento $125 free credit** for any micro-tick / OHLCV-1s data you might want for re-sampling experiments.

**Live for paper trading:** Run through **Interactive Brokers** with the US Futures Value Bundle (~$10/mo, waived at $30/mo commissions). Use `ib_insync` for the Python API.

**Total realistic monthly:** **$0–$10/mo** (free if commissions cover the data fee) + the ~$200 one-time for historical.

**Why this combo:**
- FirstRateData gives you clean, license-clean, 15+ years of NQ + MNQ minute bars in one zip — no API rate limits, no surprises.
- IBKR live feed is the cheapest non-throttled-enough live source that also gives you order routing. Same broker = same data = no reconciliation pain between backtest and live execution.
- Throttled IBKR snapshots (~4/sec for futures) are perfectly fine for minute-bar strategies; if you scale down to sub-minute, that's when you graduate to Tier 2.

## 3. Tier-2 recommendation — production, tick / sub-second, accuracy critical

**Both historical and live: Databento GLBX.MDP3.**
- Historical OHLCV-1s or trades/MBP-1 for the lookback window you need (one-time spend ~$50–$300 depending on schema).
- Live: Databento Standard plan **$179/mo** (includes CME pass-through, sub-ms colocation feed).
- Same SDK, same symbology, same data lineage as backtest. Zero reconciliation drift between research and production.

**Total monthly: ~$179/mo**, plus initial historical spend.

**When to upgrade to Tier 2:**
- Strategy uses sub-minute features (e.g. order-book imbalance, micro-momentum, scalping).
- You're trading a prop-firm account where slippage assumptions must match reality.
- You need MBO / full-depth order book for liquidity-aware execution.

**Alternative Tier 2 if you want broker-bundled data + execution in one:**
- **IQFeed + Tradovate broker** — IQFeed (~$25/mo for non-pro CME Globex through a qualified broker, drops to ~$5–$10/mo) + Tradovate execution + Tradovate's own $12/mo data for redundancy. Cheaper than Databento but lower data quality (no MBO, 180-day tick limit).

---

## 4. Watch-outs (the "garbage data = blown account" list)

1. **yfinance continuous NQ has stale ticks across the Globex overnight session and silently misses some 15-minute and 1-hour bar boundaries.** Backtests run on this data will show fake edges that vanish in real trading. Never use for anything you'd risk capital on.
2. **CME license fees pass through every vendor.** Posted vendor prices often exclude the ~$3–5/mo CME non-pro fee. Confirm before signing up.
3. **Continuous-contract roll method matters.** A panama-stitched continuous looks different from a ratio-adjusted one, and from a non-adjusted spliced one. Document which one your backtest used and replicate the same logic live, or your live strategy will drift from your backtest by the cumulative roll gap (often 5–15% of price over 5 years on NQ).
4. **IBKR is snapshot-throttled, not true tick.** Fine for minute bars; misleading for anything tick-driven.
5. **TradingView and Yahoo scraping violate TOS** — fine for prototyping, not for anything you'd let run unattended.
6. **MNQ before 2019** does not exist — MNQ launched May 2019. Don't backtest MNQ on synthesized NQ/10 data without warning yourself that 2008–2019 MNQ is fabricated.
7. **Databento's $125 free credit covers historical only**, not live. Don't plan to do paper trading on the free tier.
8. **Tradovate historical depth is shallow** — months, not years. Use Tradovate for execution + live data only.

---

## 5. Suggested concrete starting plan

1. Spend ~$200 today on FirstRateData (NQ + MNQ continuous + per-expiration 1-min).
2. Sign up for Databento, claim the $125 credit, pull a few weeks of MBP-1 + trades for NQ Z25 and MNQ Z25 to validate your tick handling code path against high-quality data.
3. Open IBKR paper account, subscribe to the Futures Value Bundle, wire up `ib_insync`, paper-trade your strategy with live NQ/MNQ ticks.
4. When ready to go live: either (a) continue with IBKR for execution + cheap data if your strategy is minute-bar oriented, or (b) upgrade to Databento Standard ($179/mo) + a discount futures broker (Tradovate / AMP / Optimus) for execution if you need sub-second accuracy.
