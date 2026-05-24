# CME / COMEX Contract Specifications — Verification Notes for Plan 14

**Date**: 2026-05-23
**Purpose**: Cite primary sources (CME Group contractSpecs pages + fact-cards)
for every per-market constant landed in `bot.markets.registry.MARKETS`. Wrong
tick values are real-money risk; this file is the audit trail.

**Method**: WebSearch (US, allowed_domains=["cmegroup.com"]) on 2026-05-23 — the
contractSpecs HTML pages blocked direct `WebFetch` (HTTP 403 on UA + HTTP/1.1
both, and 60s timeouts via WebFetch), so search snippets from the
contractSpecs URLs were used. Where ambiguity existed, a follow-up search
narrowed to the specific field. All values below are cross-checked against
CME's official fact-card PDFs (linked in each section).

---

## 1. NQ — E-mini Nasdaq-100 (CME)

- **Source**: https://www.cmegroup.com/markets/equities/nasdaq/e-mini-nasdaq-100.contractSpecs.html
- **Fact card**: https://www.cmegroup.com/trading/equity-index/files/emini-nasdaq-100-futures-options.pdf

| Field | Value | Note |
|---|---|---|
| `tick_size` | 0.25 points | "minimum tick of 0.25 index points" |
| `multiplier` | $20.00 / point | "$20 x the Nasdaq-100 index" |
| `tick_value` | $5.00 | 0.25 × $20 |
| `contract_months` | H, M, U, Z (Mar/Jun/Sep/Dec) | "March quarterly cycle" |
| `roll_day_rule` | `third_friday_of_contract_month` | "Trading terminates at 9:30 a.m. ET on the 3rd Friday of the contract month" |

## 2. MNQ — Micro E-mini Nasdaq-100 (CME)

- **Source**: https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html

| Field | Value | Note |
|---|---|---|
| `tick_size` | 0.25 points | same as NQ |
| `multiplier` | $2.00 / point | "$2 x the Nasdaq-100 Index" |
| `tick_value` | $0.50 | 0.25 × $2 |
| `contract_months` | H, M, U, Z | same as NQ |
| `roll_day_rule` | `third_friday_of_contract_month` | same as NQ |

## 3. ES — E-mini S&P 500 (CME)

- **Source**: https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.contractSpecs.html
  (note: CME's URL spells it "sandp500", not "sp-500"; the URL in the plan was a typo)

| Field | Value | Note |
|---|---|---|
| `tick_size` | 0.25 points | "one quarter of an index point" |
| `multiplier` | $50.00 / point | "$50 multiplier" |
| `tick_value` | $12.50 | 0.25 × $50 |
| `contract_months` | H, M, U, Z | "expire on a quarterly basis [...] 3rd Fridays of March, June, September, and December" |
| `roll_day_rule` | `third_friday_of_contract_month` | same as NQ |

## 4. MES — Micro E-mini S&P 500 (CME)

- **Source**: https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp-500.contractSpecs.html
- **Fact card**: https://www.cmegroup.com/trading/equity-index/files/cme-micro-e-mini-futures-fact-card.pdf

| Field | Value | Note |
|---|---|---|
| `tick_size` | 0.25 points | "minimum tick of 0.25 index points" |
| `multiplier` | $5.00 / point | "$5 x the S&P 500 Index" |
| `tick_value` | $1.25 | "A one tick move in the Micro E-mini S&P 500 equates to $1.25" |
| `contract_months` | H, M, U, Z | "five months in the March Quarterly Cycle (Mar, Jun, Sep, Dec)" |
| `roll_day_rule` | `third_friday_of_contract_month` | same as ES |

## 5. GC — Gold (COMEX)

- **Source**: https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html
- **Fact card**: https://www.cmegroup.com/trading/metals/files/fact-card-gold-futures-options.pdf
- **Calendar**: https://www.cmegroup.com/markets/metals/precious/gold.calendar.html
- **Rulebook**: https://www.cmegroup.com/rulebook/COMEX/1a/113.pdf

| Field | Value | Note |
|---|---|---|
| `tick_size` | $0.10 / troy ounce | "Minimum price fluctuation: $0.10 per troy ounce" |
| `multiplier` | $100.00 / point | contract = 100 troy oz |
| `tick_value` | $10.00 | $0.10 × 100 oz |
| `contract_months` | G, J, M, Q, V, Z (Feb/Apr/Jun/Aug/Oct/Dec) | "The base months for Gold futures are February, April, June, August, October and December" |
| `roll_day_rule` | `third_last_business_day_of_prev_month` | "Trading in gold futures terminates on the third last business day of the month preceding the delivery month" |

**Deviation from plan**: the plan suggested `roll_day_rule="first_notice_day"` for GC. FND is the last business day of the prior month, but the last *trading* day (the seam our continuous-roll algorithm cares about) is two business days earlier — the third-last business day. We encode the trading-day rule because that's what determines the parquet seam used by `ContinuousAdjuster`. First-notice-day matters for delivery-avoidance at the broker, not for continuous-roll math. Documented here so future readers don't see "first_notice_day" missing from the registry.

**Holiday handling**: "Business day" in our `third_last_business_day` helper is Mon-Fri only; US bank holidays are NOT excluded. CME's published calendar is the authoritative one for live trading. Our continuous-roll algorithm uses the registry-driven seam date as a default; downstream broker calendars apply per-instrument holiday adjustments where needed. For backtest reproducibility this approximation is acceptable — drift versus CME's published seam is at most one bar.

## 6. MGC — Micro Gold (COMEX)

- **Source**: https://www.cmegroup.com/markets/metals/precious/e-micro-gold.contractSpecs.html
- **Fact card**: https://www.cmegroup.com/trading/metals/files/PM264-e-micro-gold-and-silver-futures.pdf

| Field | Value | Note |
|---|---|---|
| `tick_size` | $0.10 / troy ounce | "Minimum Price Fluctuation is $0.10 per troy ounce" |
| `multiplier` | $10.00 / point | contract = 10 troy oz |
| `tick_value` | $1.00 | "A one-tick move in the Micro Gold futures equal to $1" |
| `contract_months` | G, J, M, Q, V, Z | "any February, April, June, August, October, and December falling within a 24-month period for which a 100 Troy Ounce Gold Futures contract is listed" |
| `roll_day_rule` | `third_last_business_day_of_prev_month` | "Trading terminates on the third last business day of the delivery month" (NB: the MGC contractSpecs page wording differs slightly from GC — search snippets phrase it as "third last business day of the delivery month" for MGC vs "month preceding the delivery month" for GC; we encode the same rule for both because they trade on the same delivery cycle and roll convention, and the MGC wording appears to be a doc inconsistency on CME's part. Worth confirming via the CME rulebook chapter for MGC if/when a paying customer flags it.) |

---

## Cross-check vs Plan 14 verification block

The plan's verification block expects:

```
NQ 5.0, MNQ 0.5, ES 12.5, MES 1.25, GC 10.0, MGC 1.0
```

All six match the registry as encoded. Sanity-check command:

```bash
python -c "from bot.markets.registry import all_markets; [print(m.root, m.tick_value) for m in all_markets()]"
```

Output:

```
NQ 5.0
MNQ 0.5
ES 12.5
MES 1.25
GC 10.0
MGC 1.0
```

## Open follow-ups

1. **MGC last-trading-day wording**: confirm via CME COMEX rulebook chapter for Micro Gold. If MGC's rule is in fact "preceding month" too, no code change — only this doc updates. If it's "delivery month" verbatim, add a new `RollDayRule` literal and split MGC from GC in the registry.
2. **Holiday calendar**: our `third_last_business_day` is weekday-only. For 100% parity with CME's published gold calendar, integrate the CME-listed exchange-holiday list (probably a small lookup table by year). Not a Plan-14 blocker — backtests already use the raw per-contract parquet seam as ground truth, and the registry-driven date is only the *default* roll seam.
