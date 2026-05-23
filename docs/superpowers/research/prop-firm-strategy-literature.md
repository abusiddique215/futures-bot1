# Prop-Firm Futures Strategy Literature Survey (NQ / MNQ, Topstep $50K Combine)

Date compiled: 2026-05-22
Scope: Strategies documented in academic and practitioner literature for intraday Nasdaq-100 E-mini and Micro futures, evaluated against Topstep $50K Combine constraints (profit target $3,000; trailing intraday max-loss $2,000; optional daily-loss $1,000; 50% best-day consistency rule; no published HFT/news blackout but anti-HFT prohibited-conduct clause).

Important framing note: "Surge mode" vs "Maintenance mode" are largely *position-sizing and risk-overlay* distinctions, not always different strategies. The same ORB logic at 3 NQ contracts is Surge; at 1 MNQ it is Maintenance. The lists below reflect which logics have track-record evidence at each risk profile, but several appear in both with different parameters.

---

## 1. Topstep $50K Combine rules — current as of May 2026 (verify before coding)

| Rule | $50K Combine value |
|---|---|
| Profit target | $3,000 |
| Trailing Max Loss Limit (MLL) | $2,000, trails high-water EOD balance, never decreases, locks at starting balance once reached |
| Daily Loss Limit (DLL) | $1,000, optional on Standard plan, soft-breach (auto-liquidate for the day, not a Combine failure) |
| Max contracts | 5 NQ or 50 MNQ (10 MNQ = 1 NQ equivalent) |
| Consistency rule | Best single day must be 50% or less of total cycle profit to clear payout |
| News trading | Allowed; no published blackout window. Topstep recommends caution. (Source: Topstep Help Center, April 2026 review) |
| HFT / order-stuffing | Prohibited under "Prohibited Conduct" — sub-second orders, excessive cancels, simulated-fill exploits |
| Copy trading across accounts | Restricted; net opposite positions across linked accounts treated as wash/synthetic hedge |

Sources:
- https://help.topstep.com/en/articles/8284197-trading-combine-parameters
- https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit
- https://help.topstep.com/en/articles/10490293-daily-loss-limit-in-the-trading-combine-and-express-funded-account
- https://help.topstep.com/en/articles/10296582-prohibited-conduct
- https://help.topstep.com/en/articles/8284211-what-are-economic-releases
- https://thetradingplaybook.com/rules/topstep/news-trading-policy

---

## 2. Community knowledge (forums, Reddit, YouTube)

Most-cited strategies in prop-firm-futures community discussions (futures.io, r/PropTradingFirms, r/algotrading, Twitter/X algotrading):

1. **Opening Range Breakout (ORB)** — overwhelmingly the most-discussed strategy. 5-, 15-, and 30-min ranges on NQ, with the 9:30 ET cash open as anchor.
2. **VWAP reversion/fade and VWAP trend-pullback** — second-most cited. Heavy use in scalper communities.
3. **ICT / Smart Money Concepts** — large social-media presence (YouTube/X) but very limited mechanical/automatable backtest evidence. Treat community win-rate claims (60–92%) as discretionary, not mechanical.
4. **Order-flow / footprint scalping on NQ** — popular but high turnover; conflicts with Topstep HFT prohibition if cycle times go sub-second.
5. **Time-of-day mean reversion** (e.g., midday fade, last-hour ramp) — Edgeful and similar stat platforms popularized this.

Skepticism notes:
- "Trading-bots-passed-funded-challenges" listicles (e.g., AutoPilot Trader 79% win, NQ Long-Only 73.5%, Sharpe 4.05) are vendor marketing without independent verification.
- Reported strategies that "passed the Combine in 3 days" are survivorship bias — the underlying probability of any single attempt passing is ~15–20%.

Source: https://www.fortraders.com/blog/trading-bots-passed-funded-challenges (treat as marketing)

---

## 3. Documented intraday NQ strategies — literature summary

### 3.1 Opening Range Breakout (Zarattini, Aziz, Barbon 2023/2024)

- 5-min ORB on QQQ (closely tied to NQ) over 2016–2023 returned 1,484% vs 169% for buy-and-hold QQQ, including leverage constraints.
- Mechanism: at minute 5 from cash open, take the breakout of the first 5-min candle in direction of bar; stop = opposite extreme; target = N×ATR or session close.
- Followup 2024 paper "Beat the Market" on SPY momentum from same authors confirmed effect.
- Win rate typically reported 40–55% with 1:2 or better R; trend-filtered version closer to 55%.
- Source: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
- Source: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172
- Independent backtest review: https://quantmacro.substack.com/p/paper-review-an-effective-intraday

### 3.2 Toby Crabel ORB / Stretch / NR7-ID

- "Stretch" = 10-day average of (open − nearest extreme of that day). Buy stop at Open + Stretch; sell stop at Open − Stretch.
- NR7 = today's range narrower than each of the prior 6 days. NR7-ID combines narrow-range + inside-day for "double compression."
- Oxford-Strat backtest confirms positive expectancy on US index futures, sensitive to stretch parameterization.
- Source: https://oxfordstrat.com/trading-strategies/opening-range-breakout/
- Source: https://oxfordstrat.com/trading-strategies/nr7/

### 3.3 VWAP fade / session-VWAP mean reversion

- Mechanical fade of 2nd standard-deviation band with delta or footprint exhaustion confirmation.
- Backtest win rates reported around 49% (un-filtered VWAP); high volatility / drawdowns when faded against trend days.
- Documented failure mode: faded against momentum trend days (NQ +300pts) the 2nd-deviation band acts as continuation, not resistance.
- Source: https://www.quantvps.com/blog/backtest-vwap-trading-strategy-python
- Source: https://www.quantifiedstrategies.com/vwap-trading-strategy/

### 3.4 Intraday momentum continuation (Maróy 2025, Li-Yuan-Zhou 2024)

- Maróy 2025 "Improvements to Intraday Momentum Strategies" — building on Zarattini/Aziz/Barbon 2024 — reports Sharpe >3.0, >50% annualized with optimized exits on SPY/QQQ.
- "Systematic Momentum" (Management Science, 2024/2025) extends momentum to intraday horizons.
- Source: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5095349
- Source: https://pubsonline.informs.org/doi/10.1287/mnsc.2024.08236

### 3.5 ICT / Smart Money Concepts — credibility caveats

- Community claims 60–92% win rates on NQ, but the methodology requires "market context" / discretionary read.
- Practitioner sources acknowledge: "Backtesting on historical data is not possible for ICT strategies, as it requires analyzing market context, making it harder to automate."
- Bottom line: ICT lacks peer-reviewed support; any "high win-rate" figure for ICT comes from manual trade-by-trade subjective journaling, not mechanical replay.
- Source: https://medium.com/@space.garaa/i-backtested-2-600-trades-using-smart-money-concepts-heres-what-actually-works-bb3c671098c6 (community)
- Source: https://strategyarena.io/blog/smart-money-concepts-ict-strategie (community)

### 3.6 ES/NQ pairs (statistical arbitrage)

- Z-score spread mean-reversion using cointegration; in practice ES and NQ are highly correlated but NOT robustly cointegrated long-term — beta-drift makes a static hedge ratio fail.
- For Topstep specifically: holding net opposite positions in highly-correlated CME products risks being flagged as a synthetic hedge.
- Source: https://blog.quantinsti.com/pairs-trading-basics/
- Source: https://github.com/bradleyboyuyang/Statistical-Arbitrage

### 3.7 Mean reversion at intraday extremes (Bollinger / Keltner reversion)

- Lower frequency than VWAP fade; uses 5- or 15-min Bollinger band touches with RSI divergence.
- Lower win-rate (~45%) but higher per-trade R when the trade works.
- Failure mode: regime-dependent. Breaks badly in strong trending sessions (NQ has many).

### 3.8 Time-of-day patterns (open drive, lunch chop, close ramp)

- 9:30–10:30 ET = "opening drive" with elevated range and continuation odds.
- 11:30–13:30 ET = "lunch chop" with reduced range; many ORB systems sit out.
- 14:30–16:00 ET = closing ramp / MOC imbalance — directional bias varies but volume picks up.
- Source: https://ninjatrader.com/futures/blogs/the-statistical-analysis-of-trading-patterns/

### 3.9 Larry Williams volatility breakout

- Buy stop at Close + k × (yesterday's High − Low); k typically 0.4–0.7.
- Held intraday, flat at session close. Average ~15% annual on diversified futures basket per QuantifiedStrategies.
- Failure mode: chop / low-volatility regimes wear it down with false breaks.
- Source: https://www.quantifiedstrategies.com/larry-williams-volatility-strategy/

---

## 4. Anti-pattern list — strategies that VIOLATE Topstep rules

| Anti-pattern | Topstep rule it breaks |
|---|---|
| HFT / order-flow scalping with sub-second holds and excessive cancels | "Prohibited Conduct" — sub-second order placement, excessive cancels, simulated-fill exploits |
| Copy-trading same logic across multiple Combine accounts | Treated as coordinated trading; account termination if net opposite positions detected |
| Hedging NQ vs MNQ vs QQQ (or any correlated CME pair) across linked accounts | Synthetic hedge / wash-trade rule; CME Rules 432, 531, 533, 534, 539 invoked |
| Pre-placed paired buy/sell stops timed to FOMC/CPI/NFP release | News-trading allowed in general, but "pre-placed paired stops fired automatically on release" listed as prohibited exploit pattern |
| Strategies that pass by exploiting sim-fill mechanics (e.g., always lift-the-offer through a wide spread the sim "fills") | Explicit prohibited-conduct clause |
| Single big-day overshoot that violates 50% consistency rule | Not a Combine failure but blocks payout on funded account |

Sources:
- https://help.topstep.com/en/articles/10296582-prohibited-conduct
- https://support.apextraderfunding.com/hc/en-us/articles/40463541656603 (correlated-instruments analogue at Apex)
- https://www.proptradingvibes.com/blog/takeprofittrader-copy-trading-rules

---

## 5. Realistic difficulty — community-reported data

| Metric | Value | Source |
|---|---|---|
| Topstep Combine pass rate (per-evaluation, 2025 cohort) | 16.8% | https://tradecovex.com/guides/how-many-combines-passed-express-topstep-2025 |
| Trader-level: traders who passed at least one Combine eventually | 51.8% | same |
| Funded → at least one payout | 33.3% of funded | same |
| All Combine starters → Live Funded Account | 0.71% | same |
| Industry: traders who passed AND received payout | ~7% | https://atmosfunded.com/prop-firm-statistics/ |
| Industry: typical per-attempt pass rate (futures prop) | 10–25% | various |
| Vendor claim: ROI-based strategies passing rate (Jan–Sept 2023) | ~43% | https://www.fortraders.com/blog/trading-bots-passed-funded-challenges (treat skeptically — vendor) |

Survivorship bias warning: every "this bot passed" social-media post is N=1 from a sample where ~83% of attempts fail. The 16.8% Topstep number is the right anchor.

---

## 6. Recent academic literature (2023–2026)

1. Zarattini, Aziz (2023) — "Can Day Trading Really Be Profitable? Evidence … ORB strategy on QQQ" — 5-min ORB on QQQ, 1,484% vs 169% benchmark. https://www.semanticscholar.org/paper/4d55f526cc56f08662cb8976796cd3b719ef6d2b
2. Zarattini, Aziz, Barbon (2024) — "Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)" — extends ORB to noise-boundary intraday momentum. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172
3. Maróy (2025) — "Improvements to Intraday Momentum Strategies Using Parameter Optimization and Different Exit Strategies" — Sharpe >3.0, >50% annual returns. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5095349
4. Li, Yuan, Zhou (2024/2025) — "Systematic Momentum: A New Class of Price Patterns" — Management Science. https://pubsonline.informs.org/doi/10.1287/mnsc.2024.08236
5. arXiv 2501.07135 (2025) — "Follow the Leader: Enhancing Systematic Trend-Following Using Network Momentum." https://arxiv.org/pdf/2501.07135

Microstructure observations 2023–2026:
- 0DTE option flow on QQQ now significantly drives NQ intraday gamma flips, especially in the last hour.
- Overnight session is statistically gaining edge versus RTH on QQQ/NQ (overnight effect paper, Applied Economics and Finance 2025).
- Algorithmic share of US equity-index futures volume is now estimated 80%+, raising bid-ask competition and reducing edges that worked pre-2020.

---

## 7. Open-source repos worth studying

| Repo | Purpose | URL |
|---|---|---|
| TradersPost/pinescript | NQ futures EMA-crossover and other Pine strategies | https://github.com/TradersPost/pinescript |
| dearvn/trading-futures-tradingview-script | NQ/ES pine scripts | https://github.com/dearvn/trading-futures-tradingview-script |
| vedaaaaaaant/pj_orb_backtester | ORB-strategy backtester scaffolding | https://github.com/vedaaaaaaant/pj_orb_backtester |
| aouyang1/Futures | Futures DB/backtester/analysis | https://github.com/aouyang1/Futures |
| simonpucher/AgenaTrader | C# Open_Range_Breakout_Strategy.cs reference impl | https://github.com/simonpucher/AgenaTrader |
| robbyrobaz/nq-l2-scalping | NQ L2 order-flow scalping (use as anti-pattern reference) | https://github.com/robbyrobaz/nq-l2-scalping |
| bradleyboyuyang/Statistical-Arbitrage | HFT-style stat-arb framework | https://github.com/bradleyboyuyang/Statistical-Arbitrage |
| enzoampil/fastquant | Python backtest framework (ORB issue #247) | https://github.com/enzoampil/fastquant |
| QuantConnect/Lean (general) | Backtest engine, has ORB examples | https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/ |

No flagship "open-source Topstep-passing bot" exists. Vendors keep working systems private.

---

## 8. Realistic per-day P&L target for Topstep $50K Combine

- Profit target $3,000. Trailing MLL $2,000. Optional DLL $1,000.
- To pass in ~10 trading days at sustainable risk: ~$300/day net.
- To pass in ~5 trading days (Surge): ~$600/day net.
- One-NQ-tick = $5.00; 12 ticks/day net = $60/contract = need 3–5 NQ contracts to hit Surge daily target.
- One-MNQ-tick = $0.50; same ticks at 10 MNQ = $60/day → matches roughly the same dollar risk as 1 NQ, but with finer granularity.
- Consistency rule constraint: if you make $1,500 on day 1 you need $1,500 over remaining days to clear payout — biasing toward smaller daily wins.
- Realistic Maintenance target post-funding: $150–$400/day on $50K funded, with strict daily stop.

---

## 9. Strategy candidate ranking — SURGE MODE (pass $3K in 5–10 days)

> Criteria: must be capable of producing $500–$1,000+ days without breaching $2K trailing drawdown.

### S1. 5-minute Opening Range Breakout (Zarattini-style)

- Mechanism: at 09:35 ET, take direction of first 5-min bar on close-of-bar break; stop opposite extreme; target intraday close or N×ATR.
- Timeframe: 5-min entries, intraday hold.
- Win rate / R: 40–55%, average R 1:2 (Zarattini/Aziz 2023).
- Weakness: overnight gaps and choppy non-trend days produce false breaks.
- Topstep risk: low. Trade duration measured in minutes-to-hours, far above any HFT threshold.
- Sources: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284, https://quantmacro.substack.com/p/paper-review-an-effective-intraday

### S2. 15-minute ORB with VWAP confirmation

- Mechanism: at 09:45 ET, take breakout of first 15-min range only if in direction of VWAP slope.
- Timeframe: 15-min entries, intraday.
- Win rate / R: ~55% with VWAP filter (community, futures.io / trading123).
- Weakness: filter cuts trade count; some Surge days produce zero signals.
- Topstep risk: low.
- Sources: https://www.trading123.net/opening-range-strategy-ninjatrader-blog-post/, https://onlypropfirms.com/lessons/the-15-minute-opening-range-strategy

### S3. Larry Williams volatility breakout (1-day chart)

- Mechanism: buy stop at PrevClose + 0.5 × (PrevHigh − PrevLow); sell stop mirror. Flat at session close.
- Timeframe: daily-set levels, intraday execution.
- Win rate / R: ~50% with positive expectancy; ~15% annual on basket (QuantifiedStrategies backtest).
- Weakness: chop regimes, low-VIX days; double-stop losses possible.
- Topstep risk: low (intraday only).
- Sources: https://www.quantifiedstrategies.com/larry-williams-volatility-strategy/

### S4. Intraday momentum continuation (Maróy / Zarattini-Barbon noise-boundary)

- Mechanism: identify noise-boundary breach from prior-day close ± stdev × move; enter in breach direction.
- Timeframe: 1-min decisions, multi-hour holds.
- Win rate / R: Sharpe >3.0 reported (Maróy 2025); win rates not isolated but R favorable.
- Weakness: parameter-sensitive; needs walk-forward optimization.
- Topstep risk: low if holds > 30s.
- Sources: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5095349, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172

### S5. NR7-ID breakout (Crabel)

- Mechanism: on a day flagged NR7+Inside, place buy stop above prior day's high and sell stop below prior day's low. Expansion bar follows.
- Timeframe: daily setup, intraday execution.
- Win rate / R: positive expectancy on index futures (Oxford-Strat).
- Weakness: setups are rare (4–8 per year per market), so Surge use limited to days when pattern flags.
- Topstep risk: low.
- Sources: https://oxfordstrat.com/trading-strategies/nr7/, https://oxfordstrat.com/trading-strategies/toby-crabel-narrow-range-1/

### S6. Pre-FOMC drift + post-FOMC trend-follow (event-driven)

- Mechanism: enter in direction of 30-min pre-release drift; reverse only if post-release first-15-min bar closes opposite.
- Timeframe: 1- and 5-min around scheduled releases.
- Win rate / R: not formally documented; community/vendor.
- Weakness: HIGHEST adverse-slippage risk; one bad print can hit $2K MLL in one minute.
- Topstep risk: MODERATE — news trading is technically allowed but "pre-placed paired stops on release" is explicitly listed as prohibited exploit pattern. Must be a single directional position, not paired stops.
- Sources: https://help.topstep.com/en/articles/8284211-what-are-economic-releases, https://thetradingplaybook.com/rules/topstep/news-trading-policy

### S7. Gap-and-go on cash open

- Mechanism: gap > 0.5% from prior close → enter at 09:30 in gap direction, stop = prior close, target = 1.5–2× gap.
- Timeframe: 1- or 5-min open execution.
- Win rate / R: ~55% on gap-direction continuation per practitioner reports.
- Weakness: failed gaps (fade fills) produce sharp reversals.
- Topstep risk: low.
- Source: https://ninjatrader.com/futures/blogs/the-statistical-analysis-of-trading-patterns/

---

## 10. Strategy candidate ranking — MAINTENANCE MODE (consistent small wins, never breach)

> Criteria: must be capable of $100–$400/day with very low daily drawdown variance and consistency-rule compliance.

### M1. 5-min ORB at small size (1–2 MNQ)

- Mechanism: same as S1 but sized to risk $50–$100/trade.
- Timeframe: 5-min.
- Win rate / R: 40–55%.
- Weakness: daily P&L granularity tiny; off-days still drag.
- Topstep risk: low.
- Sources: same as S1.

### M2. VWAP trend-pullback (continuation, not fade)

- Mechanism: on trend-day (price persistently above/below VWAP), enter on touch of VWAP with delta/momentum confirmation in trend direction.
- Timeframe: 1- or 5-min.
- Win rate / R: ~55–60% on trend days; do not take on chop days.
- Weakness: requires a trend-day filter (e.g., ADX, opening drive volume).
- Topstep risk: low.
- Sources: https://medium.com/@steady-turtle-trading/how-professional-traders-really-use-vwap-its-not-what-you-think-cff7bfd9ecd0

### M3. Time-of-day "first-hour high/low" reversion

- Mechanism: after 10:30 ET, fade extremes of the first hour back to first-hour midpoint, only when VWAP and prior-day-close support reversal.
- Timeframe: 5-min.
- Win rate / R: 55–60% community-reported; smaller R (~1:1).
- Weakness: trend days punish it (Wednesdays of Fed weeks).
- Topstep risk: low.
- Sources: https://ninjatrader.com/futures/blogs/the-statistical-analysis-of-trading-patterns/

### M4. Opening drive scalp (single-bar holds, 30s+)

- Mechanism: enter on 09:30 5-min bar with strong volume + delta, exit on first opposite 1-min bar.
- Timeframe: 1-min.
- Win rate / R: ~60% community; R ~1:1.
- Weakness: HFT-adjacent — keep cycle time ≥ 30s, do NOT cancel/resubmit aggressively.
- Topstep risk: moderate — must monitor order-cancel-replace count to stay clear of HFT clause.
- Sources: https://onlypropfirms.com/lessons/the-15-minute-opening-range-strategy

### M5. Mean-reversion at 2-stdev VWAP band (filtered)

- Mechanism: fade VWAP +2/−2σ ONLY when (a) cumulative delta is exhausting and (b) on non-trend day flagged by ADX < 20.
- Timeframe: 5-min.
- Win rate / R: ~49% raw; ~55%+ when filtered for non-trend days.
- Weakness: trend-day blowup risk is the main reason this is Maintenance-only at small size.
- Topstep risk: low.
- Sources: https://www.quantvps.com/blog/backtest-vwap-trading-strategy-python

### M6. Last-hour close-ramp continuation

- Mechanism: at 15:00 ET, if price is above/below VWAP and rising/falling 15-min MA slope, take a position in direction, hold to 15:55 ET or stop.
- Timeframe: 5-min.
- Win rate / R: community-reported 55%+ on QQQ; reasonable R.
- Weakness: MOC imbalance days can whip; less reliable on Fed days.
- Topstep risk: low.
- Source: https://www.quantifiedstrategies.com/intraday-momentum-trading-strategy/

### M7. Crabel "stretch" — open ± 10-day stretch

- Mechanism: place opposite buy/sell stops at Open + Stretch and Open − Stretch; first trigger wins; second cancelled. Flat at close.
- Timeframe: daily-set, intraday execution.
- Win rate / R: positive expectancy, modest R, low frequency.
- Weakness: low trade count per month — slow grind.
- Topstep risk: low.
- Source: https://oxfordstrat.com/trading-strategies/opening-range-breakout/

### M8. Inside-Day fade (mean reversion after compression)

- Mechanism: on day-after Inside Day, fade move that exceeds 1.5× ATR back toward prior-day midpoint.
- Timeframe: 15-min.
- Win rate / R: ~55%, R ~1:1.
- Weakness: misses any true expansion days.
- Topstep risk: low.
- Sources: https://oxfordstrat.com/trading-strategies/toby-crabel-narrow-range-1/

---

## 11. Recommended exclusions for ANY mode

- ICT/SMC as primary signal (cannot be mechanically backtested; reliability claims unverified).
- ES/NQ pairs (cointegration fragile + correlated-symbol rule risk if any other account holds the other leg).
- Sub-30-second-hold scalping (HFT-adjacent; prohibited-conduct risk; sim-fill exploit risk).
- News-time paired bracket entries (explicitly prohibited as exploit pattern).
- Any strategy that produces a single >50% day (Combine passes, payout blocked by consistency rule).

---

## 12. Open questions to resolve before coding

1. Will the bot operate on a single account or rotate across multiple Combine resets? Multi-account requires NO copy-trading logic.
2. Will data feed support sub-second timestamps for HFT-clause defense (proof of intentional non-HFT)?
3. Will Surge mode auto-switch to Maintenance once funded, or are they separate deployments?
4. What's the live-broker order routing latency target? Sub-second is fine, sub-100ms creates audit risk under Topstep prohibited-conduct.

---

## Citations summary

Primary academic:
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5095349
- https://pubsonline.informs.org/doi/10.1287/mnsc.2024.08236
- https://arxiv.org/pdf/2501.07135

Primary Topstep rules:
- https://help.topstep.com/en/articles/8284197-trading-combine-parameters
- https://help.topstep.com/en/articles/10296582-prohibited-conduct
- https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit

Pass-rate / difficulty:
- https://tradecovex.com/guides/how-many-combines-passed-express-topstep-2025
- https://atmosfunded.com/prop-firm-statistics/

Community practitioner:
- https://oxfordstrat.com/trading-strategies/opening-range-breakout/
- https://oxfordstrat.com/trading-strategies/nr7/
- https://ninjatrader.com/futures/blogs/the-statistical-analysis-of-trading-patterns/
- https://www.quantifiedstrategies.com/larry-williams-volatility-strategy/
- https://www.quantifiedstrategies.com/vwap-trading-strategy/

GitHub:
- https://github.com/TradersPost/pinescript
- https://github.com/vedaaaaaaant/pj_orb_backtester
- https://github.com/aouyang1/Futures
- https://github.com/bradleyboyuyang/Statistical-Arbitrage
