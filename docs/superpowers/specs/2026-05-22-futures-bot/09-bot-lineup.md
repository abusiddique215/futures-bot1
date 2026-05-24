# 09 — Bot Lineup

VSL-aligned bot family. Each bot is a `BotSpec` YAML under `config/bots/<name>.yml` + a `Strategy` class registered in `bot.runtime.fleet.registry`. Per-bot risk policy + schedule + market.

## SurgeBot (NQ Voodoo Tiered)

**Source:** "SURGEBOT" large title at ~15:00 + "RP - SurgeBot [Daily Exit]" overlay at ~18:30 in the VSL. Strategy report: "Voodoo Strategy Tiered - $20k [1,2,4,5]" at ~18:00 on NQ chart — the tiered position-sizing list is the load-bearing visible signal.

**Market:** NQ1! / MNQ (CME NASDAQ-100 E-mini Futures; micros for $50K Combine sizing)
**Timeframe:** 5-minute bars
**Schedule:** Market hours 08:30 → 15:00 CT (10-minute cushion before Topstep's 15:10 CT hard-flat)
**Risk policy:** Combine Intraday (real-time trailing MLL — Combine-aggressive)
**Strategy:** `orb_5m_tiered` = `OpeningRangeBreakoutStrategy` wrapped in `TieredSizingDecorator`
**Position size:** Tiered [1, 2, 4, 5] minis keyed to realized profit ($0, $500, $1500, $2500 breakpoints) — for MNQ this is multiplied by 10 (micros-per-mini), so 10/20/40/50 micros
**Config:** `config/bots/surgebot_nq.yml`

**Tier breakpoint design:** The VSL shows the position-tier list [1,2,4,5] but not the dollar thresholds. The $500/$1500/$2500 breakpoints are OUR design — conservative early scaling on a $50K Combine. Override via YAML if backtest research surfaces better thresholds.

**Strategy logic disclaimer:** Voodoo's actual entry rules are not revealed by the VSL. ORB is used as a placeholder entry strategy that satisfies the observable constraints (5-minute timeframe, Daily Exit pattern, target-based exits). A future plan may swap ORB for a different signal generator while keeping the SurgeBot identity.

## PropBot (NQ Trend)

**Source:** "RP - PropBot - Trend [Daily Exit]" overlay visible on NQ chart at ~18:30 in the VSL. Testimonial at ~24:00: *"Just had my first payout from running PropBot…"*

**Market:** NQ1! / MNQH26 (CME NASDAQ-100 E-mini Futures)
**Timeframe:** 5-minute bars (configurable)
**Schedule:** Market hours 09:00 → 14:30 CT (earlier-than-SurgeBot start avoids opening volatility; earlier close cushions EoD trailing)
**Risk policy:** EFA Standard (funded-account, EoD-trailing MLL — designed to never approach the trailing drawdown)
**Strategy:** `trend_ema_pullback` (TrendFollowingStrategy) — EMA 20/50 alignment + price pullback to fast EMA within 0.5×ATR, exit at +1.5R, trend reversal, or EoD
**Position size:** Fixed 1 micro (no tiered scaling — funded-account conservatism)
**Config:** `config/bots/propbot_nq.yml`

**Strategy logic disclaimer:** The VSL does not reveal PropBot's entry rules. The EMA-pullback design is OUR interpretation of "Trend" with conservative funded-account constraints. Document changes if backtest research surfaces a better entry.

## Gold Bot (GC Session-Windowed)

**Source:** "RP - Gold Bot" overlay on GC1! chart at ~19:00 in the VSL, with seven visible session-window strings on the chart screen.

**Market:** GC1! / MGCH26 (COMEX Gold Futures; micros sized for $50K Combine)
**Timeframe:** 10-minute bars (configurable; per VSL "10" in chart header)
**Schedule:** CustomWindows (7 windows, see config) — three broad sessions (US regular, Asian overnight, US AM+PM splits) + four narrow news-event windows
**Risk policy:** EFA Standard (maintenance/live-family, EoD-trailing MLL)
**Strategy:** `mean_reversion_bb` (MeanReversionStrategy) — Bollinger-band + RSI entries, mid-band exits, stddev-based stop
**Position size:** Fixed 1 micro
**Config:** `config/bots/gold_bot.yml`

**Timezone interpretation:** Default `America/New_York` (ET) — the VSL never labels the timezone; ET assumed for US-resident-trader audience. Change `tz` in YAML if a future plan verifies CT.

**Narrow news-event windows interpretation:** 08:20-08:40 (pre-NFP / pre-data), 09:55-10:10 (10:00 ET data drops), 13:55-14:15 (FOMC-style 14:00 ET releases). The VSL doesn't label these; they correspond to common high-impact economic release times in ET.

**Strategy logic disclaimer:** The VSL does not reveal Gold Bot's entry rules. The Bollinger+RSI mean-reversion design is OUR interpretation of mid-day gold chop. `MeanReversionStrategy` is parameterized cleanly so Plans 18 (ES Scalper) and 20 (NQ Maintenance) reuse the class with different tunings.

## ES Scalper (ES 10m Daily Exit)

**Source:** "RP - ES Scalper (10m) [Daily Exit]" overlay on ES1! chart at ~20:00 in the VSL, with the strategy report showing 3,029 trades / 73.65% profitable / 1.097 profit factor / +$68,300 net / $24,400 max drawdown.

**Market:** ES1! / MESH26 (CME S&P 500 E-mini Futures; micros sized for $50K Combine)
**Timeframe:** 10-minute bars (per VSL "10" in chart header + "(10m)" in bot label)
**Schedule:** Market hours 08:30 → 14:45 CT (25-minute cushion before Topstep's 15:10 CT hard-flat — scalper needs cleanup time)
**Risk policy:** EFA Standard (maintenance/live-family, EoD-trailing MLL)
**Strategy:** `mean_reversion_bb` (MeanReversionStrategy) — same class as Gold Bot, tighter parameters
**Position size:** Fixed 1 micro
**Config:** `config/bots/es_scalper.yml`

**Parameter tightening vs Gold Bot (rationale):** ES Scalper turns over faster than Gold Bot. The tunings encode the "scalper" framing:
- `bb_period` 10 vs Gold's 20 — half the BB lookback → faster band response, more entry triggers per session.
- `bb_stddev` 1.5 vs 2.0 — narrower bands → looser entry threshold.
- `rsi_period` 9 / `rsi_oversold` 35 / `rsi_overbought` 65 vs Gold's 14 / 30 / 70 — shorter, less extreme thresholds → more frequent oversold/overbought signals.
- `reward_ratio` 0.75 vs 1.0 — smaller stop distance (sigma × 0.75) → faster stop-out / re-entry cycle.
- `max_trades_per_day` 10 vs 3 — sized to the VSL's implied ~10+ trades/day cadence (3,029 trades over the strategy-report window).

**VSL claim comparison protocol:** When a real ES FirstRateData fixture is available (deferred — not built in Plan 18), the backtest harness should print actual trade count / win rate / net profit alongside the VSL claim (3,029 / 73.65% / $68,300). Mismatches are not pass/fail — the VSL strategy report is opaque about period, contract sizing, and slippage assumptions. Treat as sanity check only.

**Strategy logic disclaimer:** The VSL does not reveal ES Scalper's entry rules. The tightened mean-reversion design is OUR interpretation of "Scalper (10m) [Daily Exit]" reusing Gold Bot's strategy class. Document parameter changes if backtest research surfaces a better tuning.
