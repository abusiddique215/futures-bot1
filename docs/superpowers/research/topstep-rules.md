# Topstep Prop Firm Rules — Current as of 2026-05-22

Researched for an algorithmic NQ/MNQ trading bot's `prop_firm_rules` engine. All facts include a source URL and a confidence label:

- **High** = stated by Topstep primary source (help.topstep.com or topstep.com), corroborated by at least one secondary source.
- **Medium** = stated by a single source, or by secondary sources only because the Topstep page renders the data as a non-extractable image.
- **Low** = inferred or community-reported, not in any primary doc.

Conflicts and gaps are flagged inline.

---

## 1. Account Sizes & Pricing

Topstep currently sells **three** Trading Combine sizes: $50K, $100K, $150K. Account sizes cannot be changed after purchase. Source: <https://help.topstep.com/en/articles/8284197-trading-combine-parameters>. **High**

**Standard Path pricing (April 2026):** monthly subscription + one-time $149 activation fee on pass.

| Account | Monthly | Activation on pass |
|---|---|---|
| $50K  | $49/mo  | $149 |
| $100K | $99/mo  | $149 |
| $150K | $149/mo | $149 |

Source: <https://help.topstep.com/en/articles/9208217-topstep-pricing> and <https://proptradingvibes.com/blog/topstep-pricing-breakdown>. **High**

A **No-Activation-Fee Path** also exists (higher monthly, no activation on pass). Exact monthly figures not in primary docs at time of research. Source: <https://proptradingvibes.com/blog/topstep-pricing-breakdown>. **Medium**

---

## 2. Per-Account Parameters

Source for parameter table: <https://help.topstep.com/en/articles/8284197-trading-combine-parameters>, <https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit>, <https://help.topstep.com/en/articles/10490293-daily-loss-limit-in-the-trading-combine-and-express-funded-account>. **High**

| Account | Profit Target | Daily Loss Limit | Max Loss Limit (trailing) | Max Position (Mini / Micro) |
|---|---|---|---|---|
| $50K  | $3,000 | $1,000 | $2,000 | 5 / 50 |
| $100K | $6,000 | $2,000 | $3,000 | 10 / 100 |
| $150K | $9,000 | $3,000 | $4,500 | 15 / 150 |

Note the 1.5:1 target-to-drawdown ratio. Micros and minis count toward the same cap at a 10:1 ratio (e.g., 50 MNQ = 5 NQ for the $50K cap).

### 2a. How the Max Loss Limit (MLL) trails — critical for bot design

Primary source: <https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit>. **High**

- The MLL is the **only hard rule**. Hitting or going below it → permanent account closure.
- It **trails upward only** (one-way ratchet). It never moves down.
- **Trading Combine:** MLL starts at `starting_balance - drawdown` (e.g., $48,000 on a $50K). It updates at end of day, **but is monitored in real time on Net P&L including unrealized (mark-to-market)**. An intraday wick that hits the MLL liquidates the account immediately, even if the position would have closed green. Once equity rises enough that the trailing MLL would reach the original starting balance, it **locks at the starting balance** and never moves again.
- **Express Funded Account (EFA):** Starts at $0 balance (the "$50K/$100K/$150K" is buying-power capacity, not cash). MLL starts at `-$2,000 / -$3,000 / -$4,500`. Trails upward as balance grows. Locks at $0 once balance has earned the full drawdown amount.
- After the **first payout** on an EFA, MLL is permanently set to $0. Source: same Topstep MLL article. **High**

One secondary source (proptradingvibes "Topstep Combine Rules 2026") claimed the Combine MLL never locks at starting balance. This **contradicts the Topstep primary source**, which explicitly states it locks. Go with the primary. **Conflict flagged.**

### 2b. Daily Loss Limit (DLL) behavior

Source: <https://help.topstep.com/en/articles/10490293-daily-loss-limit-in-the-trading-combine-and-express-funded-account>. **High**

- DLL is **optional** at purchase and gets a "Responsible Trading Discount" if selected ($10–$30 off).
- Hitting the DLL is **not a rule violation**. It auto-liquidates all positions, cancels orders, and locks the account out until the next trading day (5:00 PM CT reset).
- Calculated on Net P&L including unrealized.

### 2c. Allowed instruments

Source: <https://www.topstep.com/express-funded-account-rules/>. **High**

> "Futures products only, listed on the following exchanges: CME, COMEX, NYMEX & CBOT."

- **NQ (E-mini Nasdaq-100, CME)** — allowed
- **MNQ (Micro E-mini Nasdaq-100, CME)** — allowed
- Stocks, options, forex, spot crypto, CFDs — prohibited.

### 2d. Scaling plan in the EFA (replaces Trading Combine's Max Position)

In the EFA, max contracts is gated by current account balance, not a fixed cap. Source: <https://help.topstep.com/en/articles/8284223-what-is-the-scaling-plan>. **High** for the mechanism; **Medium** for the threshold numbers (Topstep displays them as an image; numbers below are from h2tfunding.com).

**Mechanism (High):**
- Contract caps **only step up overnight**. Intraday earnings do not unlock larger size until the next session.
- Position oversizing corrected within 10 seconds is ignored (grace).
- 10:1 micro-to-mini ratio on TopstepX. On third-party platforms (Tradovate, NinjaTrader), a micro counts as one full contract — this is a footgun for bot configuration.

**Scaling tables (Medium — secondary source: <https://h2tfunding.com/topstep-scaling-plan/>):**

*$50K EFA*

| Balance | Max contracts (lots) |
|---|---|
| < $1,500 | 2 |
| $1,500–$2,000 | 3 |
| > $2,000 | 5 |

*$100K and $150K EFA*

| Balance | Max contracts (lots) |
|---|---|
| < $1,500 | 3 |
| $1,500–$2,000 | 4 |
| $2,000–$3,000 | 5 |
| $3,000–$4,500 | 10 |
| > $4,500 | 10 ($100K) / 15 ($150K) |

Confirm against the in-platform Trade Report before encoding as constants.

---

## 3. Consistency Rule

Primary source: <https://help.topstep.com/en/articles/8284208-what-is-the-consistency-target>. **High**

Two separate consistency targets exist depending on stage:

- **Trading Combine — 50% rule.** Best single day must be ≤ 50% of total profits. If exceeded, the Profit Target effectively scales up (`required_total = 2 × best_day`), so you must keep trading and dilute the concentration before you can pass. Best-day value updates real-time and locks at 3:10 PM CT.
- **EFA Consistency variant — 40% rule.** Largest winning day must be ≤ 40% of total net profit in the payout window. If exceeded, payout request is blocked until additional days dilute the ratio. Requires at least 3 trading days meeting the target.
- **EFA Standard variant — no consistency target.** Payout gated on 5 winning days only.

---

## 4. Minimum Trading Days

- **Trading Combine:** No documented minimum day count. Practical floor is ~2 days because of the 50% consistency rule (a 1-day pass would always fail consistency unless `best_day == profit_target == 50% of target × 2`, which is impossible). Source: <https://help.topstep.com/en/articles/8284197-trading-combine-parameters>. **Medium**
- **EFA Standard:** 5 winning days ($150+ each) before first payout. After each payout, another 5 winning days for the next. Source: <https://help.topstep.com/en/articles/8284233-topstep-payout-policy>. **High**
- **EFA Consistency:** 3 trading days satisfying the 40% target before each payout. **High**
- **Live Funded Account:** 5 Benchmark Trading Days ($150+ each) per payout request. After 30 cumulative Benchmark Days, daily payouts unlock. Source: <https://www.topstep.com/live-funded-account-rules/>. **High**

A "winning day" is defined as net P&L ≥ $150 at session close. This is the post-2024 threshold (previously $200). Source: <https://proptradingvibes.com/blog/topstep-payout-rules>. **High**

---

## 5. End-of-Day Flat / Overnight Hold

Source: <https://www.topstep.com/express-funded-account-rules/>. **High**

> "All positions must be closed by 3:10 PM CT or by the product's market close, whichever comes first."

No overnight holds are permitted at any stage (Combine, EFA, or Live). The trading day window is 5:00 PM CT to 3:10 PM CT next calendar day. Source: <https://help.topstep.com/en/articles/8284197-trading-combine-parameters>. **High**

---

## 6. News Trading Restrictions

This is **not as permissive as some secondary sources frame it.** Two facts coexist:

1. **No formal news blackout window.** Topstep does not publish a hard time-buffer around CPI, FOMC, NFP, or other releases. Traders can enter and hold through prints. Source: <https://proptradingvibes.com/blog/topstep-news-trading-policy>. **Medium**
2. **"Maximum Position News Trading" is on the prohibited-strategies list.** Source: <https://help.topstep.com/en/articles/10305426-prohibited-trading-strategies-at-topstep>. **High**
   > "Trading your full position size into major news events" is prohibited.

**Reconciliation:** You can trade through news, but not with your maximum allowed contract size. A bot must implement a position-size reduction around scheduled high-impact releases. Topstep does not publish an exact threshold; this is enforced case-by-case.

In addition, the standard MLL on the Combine is monitored on unrealized P&L in real time, so a release wick can liquidate even if your trade ultimately closes profitably. This is a risk-mechanics issue, not a separate rule.

---

## 7. Express Funded Account (EFA) — Current Variants in 2026

Source: <https://help.topstep.com/en/articles/8284215-express-funded-account-parameters>, <https://www.topstep.com/express-funded-account-rules/>. **High**

Since **February 5, 2026**, the EFA has two variants at purchase time:

| Feature | EFA Standard | EFA Consistency |
|---|---|---|
| Min days before first payout | 5 winning days ($150+ each) | 3 days meeting 40% rule |
| Consistency rule on payout | None | Largest day ≤ 40% of total net profit |
| Per-payout cap formula | 50% of balance, capped per size | 50% of balance, capped per size (higher) |
| Profit split | 90/10 | 90/10 |

A trader may hold up to **5 EFAs simultaneously**. **Back2Funded** allows reactivating accounts that hit MLL (separate cost). Source: <https://proptradingvibes.com/blog/topstep-accounts-overview>. **Medium**

Older "Funded Account" terminology is retired; current stages are Trading Combine → EFA → Live Funded Account (LFA).

---

## 8. Payout Rules

Source: <https://help.topstep.com/en/articles/8284233-topstep-payout-policy>. **High**

### Profit split

- **Joined on/after Jan 12, 2026:** flat **90/10** from the first dollar.
- **Joined before Jan 12, 2026 (grandfathered):** 100% of first $10,000 lifetime profit, then 90/10.

### Per-transaction payout caps (EFA)

| Account | Standard cap | Consistency cap |
|---|---|---|
| $50K  | $2,000 | $3,000 |
| $100K | $3,000 | $4,000 |
| $150K | $5,000 | $6,000 |

Each payout is the lesser of (cap) and (50% of account balance).

**First-payout reduction (Standard, $50K):** The first payout on a $50K Standard EFA is reportedly capped at $5,000 even though the standard cap is $2,000 — this contradicts the table above and may instead refer to the $150K size. Secondary source only: <https://proptradingvibes.com/blog/topstep-first-payout-strategy>. **Low / conflict — verify in-platform before encoding.**

### Withdrawal cadence

- After each successful payout (Standard/Live): another 5 winning days + net profit > $0 since last payout to qualify for the next.
- After 30 Benchmark Days in a **Live** account: daily payouts unlock, 100% of balance accessible, $125 minimum per request.

### Payment methods

| Method | Speed | Fee |
|---|---|---|
| Aeropay (US only) | Instant | $0 |
| Wise (international) | 1–3 business days | $0 |
| ACH | 1–3 business days | $30 |
| Wire / SWIFT | 5–10 business days | $30 |

### Balance buffer

No explicit balance-buffer requirement is documented on the EFA (no reserve withholding). Payouts release directly against accumulated simulated profit once thresholds are met. Source: <https://proptradingvibes.com/blog/topstep-payout-rules>. **Medium**

On the **LFA**, total cumulative payouts cannot exceed 90% of `starting_balance + net_trading_profits`. Source: <https://www.topstep.com/live-funded-account-rules/>. **High**

---

## 9. Algorithmic & Automated Trading

Source: <https://help.topstep.com/en/articles/10305426-prohibited-trading-strategies-at-topstep>, <https://help.topstep.com/en/articles/10296582-prohibited-conduct>, <https://h2tfunding.com/does-topstep-allow-automated-trading/>.

### Explicitly allowed
- Automated strategies are permitted on **Trading Combine** and **EFA**. **High**
- The **TopstepX API** is Topstep's officially supported integration path (Python/Java/.NET). **High**
- Copy trading is allowed via TopstepX Settings → Copy Trading, and via the TopstepX API. **High** (Topstep settings panel) / **Medium** (proptradingvibes for specifics).
- Copy trading is allowed across up to 5 EFAs. **Medium**

### Explicitly prohibited (all account types)
- **High-frequency trading** ("excessive orders and cancellations"). Threshold is **not** publicly defined — enforced case-by-case.
- **Latency arbitrage** between data feeds.
- **Cross-account hedging.** Single user hedging between connected accounts or accounts at different Topstep parties.
- **Coordinated/pooled strategies** with other traders (same or opposite side to pool/hedge risk).
- **Maximum position size news trading** (full size into major releases).
- **Out-of-spread fills** ("trades outside the best bid or offer").
- **Trading within 2% of price limits.**
- **Exploiting simulated-fill mechanics** (strategies that work in sim but wouldn't in live).
- **Spoofing, market-abuse practices.**
- **Account stacking** (depleting one account aggressively then continuing in another).
- **Automated trading via ProjectX API on the Live Funded Account.** **Medium** (secondary source; ProjectX appears to be in the process of retirement in 2026).

### Copy trading / VPS restrictions
- **No remote VPS** for copy trading — trading activity must originate from the trader's personal device. Source: <https://proptradingvibes.com/blog/topstep-copy-trading-rules>. **Medium**
- Copy connections **auto-disable during payout request processing**. **Medium**

### DOM scalping / sub-second trades
Not explicitly mentioned by name, but folded into the HFT prohibition (excessive orders/cancellations). A bot doing sub-second order placement with high cancel-to-fill ratio is at risk. No documented quantitative threshold. **Medium**

---

## 10. Recent Rule Changes 2024–2026

| Date | Change | Source |
|---|---|---|
| 2024 | Winning-day threshold raised from $200 → $150 net profit | <https://proptradingvibes.com/blog/topstep-payout-rules> (**Medium**) |
| 2025 | Maximum Position Size in the Combine replaced by a balance-gated **Scaling Plan** on the EFA | <https://help.topstep.com/en/articles/8284223-what-is-the-scaling-plan> (**High**) |
| Jan 12, 2026 | New traders moved to flat **90/10** split (was 100% on first $10K lifetime) | <https://help.topstep.com/en/articles/8284233-topstep-payout-policy> (**High**) |
| Feb 5, 2026 | EFA split into **Standard** and **Consistency** variants (40% rule, higher caps on Consistency, 3-day minimum) | <https://help.topstep.com/en/articles/8284215-express-funded-account-parameters> (**High**) |
| Feb 2026 | Trading Combine pricing restructured into **Standard Path** ($49/$99/$149 + $149 activation) and **No-Activation-Fee Path** | <https://proptradingvibes.com/blog/topstep-pricing-breakdown> (**Medium**) |
| 2026 | **ProjectX API retired** (TopstepX API is now the supported integration); copy trading no longer available via ProjectX | <https://proptradingvibes.com/blog/topstep-copy-trading-rules> (**Medium — verify**) |
| 2026 | **Dynamic Live Risk Expansion** introduced on LFA — DLL and contract cap scale with cumulative net profit; "Shoulder Tap" risk-team reviews in drawdown | <https://help.topstep.com/en/articles/11748475-dynamic-live-risk-expansion> (**High**) |

---

## Bot-design constants summary (load-bearing)

A `prop_firm_rules` engine should encode at least:

```
ACCOUNTS = {
  # mll = trailing drawdown DISTANCE, not an absolute floor.
  # Combine: floor = max(starting_balance, peak_eod_equity) - mll, capped at starting_balance.
  # EFA: floor = max(0, peak_eod_equity) - mll, capped at 0.
  "50K":  {target: 3000, dll: 1000, mll: 2000, max_mini: 5,  max_micro: 50},
  "100K": {target: 6000, dll: 2000, mll: 3000, max_mini: 10, max_micro: 100},
  "150K": {target: 9000, dll: 3000, mll: 4500, max_mini: 15, max_micro: 150},
}

MLL_TRAIL = {
  combine: "unrealized_realtime, trails_on_eod_balance, locks_at_starting_balance",
  efa:     "unrealized_realtime, trails_on_eod_balance, locks_at_zero",
  efa_first_payout: "mll := 0 permanently",
}

CONSISTENCY = {
  combine: 0.50,   # best day / profit_target
  efa_consistency: 0.40,  # largest day / total net profit in payout window
  efa_standard: null,
}

SESSION = {
  open:  "17:00 CT",
  close: "15:10 CT next day",
  flatten_by: "15:10 CT",   # hard
  overnight: false,
}

PAYOUT_CAPS = {  # EFA, lesser of cap or 50% of balance
  ("50K","std"):  2000, ("50K","cons"):  3000,
  ("100K","std"): 3000, ("100K","cons"): 4000,
  ("150K","std"): 5000, ("150K","cons"): 6000,
}

MIN_WINNING_DAY = 150  # $ net P&L

PROFIT_SPLIT = 0.90  # for accounts opened >= 2026-01-12

PROHIBITED = [
  # High-confidence (Topstep primary source):
  "hft_excessive_orders_cancellations",
  "latency_arbitrage",
  "cross_account_hedging",
  "max_position_news_trading",
  "out_of_spread_fills",
  "within_2pct_of_price_limits",
  "sim_fill_exploits",
  # Medium-confidence (secondary source only — verify before treating as hard rule):
  "remote_vps_copy_trading",        # proptradingvibes 2026
  "projectx_api_on_live_account",   # ProjectX appears to be retiring in 2026
]
```

The scaling plan thresholds (section 2d) should be encoded as **Medium-confidence defaults** with a runtime hook that pulls the live values from the TopstepX Trade Report — Topstep publishes them as an image rather than text and the numbers above are from a secondary source.
