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

## NQ Maintenance (NQ 24/7 Live-Only)

**Source:** VSL caption at ~23:00, verbatim — *"The live only maintenance systems trade automatically 24/7."* No chart screenshot; the bot identity (NQ, 24/7, live-only, conservative) is the load-bearing observable.

**Market:** NQ1! / MNQH26 (CME NASDAQ-100 E-mini Futures; micros for $50K Combine sizing — but bot is enabled on EFA only, see safety property below)
**Timeframe:** 1-minute or 5-minute bars (configurable via bar source; the strategy is timeframe-agnostic)
**Schedule:** `AlwaysOn` — 24/7, no session windows. Bars at every hour reach the strategy.
**Risk policy:** EFA Standard (the only live-only policy in the registry). Combine pairings are refused at boot — see safety property.
**Strategy:** `mean_reversion_bb` (`MeanReversionStrategy`) with wide bands + relaxed RSI — `bb_period=50`, `bb_stddev=3.0`, `rsi_period=21`, oversold/overbought=20/80, `reward_ratio=0.5`, `max_trades_per_day=2`. Only extreme moves pierce the bands; the bot stays on the bench most of the time.
**Position size:** Fixed 1 micro (`quantity=1` in `NQ_MAINTENANCE_DEFAULTS`).
**Config:** `config/bots/nq_maintenance.yml` (ships **DISABLED** — operator opts in only after passing Combine and moving the account to EFA)

**Safety property — combine+always is refused at boot:** `LiveOnlyGuard` (`bot.runtime.fleet.live_only_guard`) raises `IncompatibleBotSpecError` from `BotRegistry.build` whenever `schedule_type=always` is paired with `risk_policy=combine_intraday`. Topstep Combine requires a 15:10 CT hard-flat; pairing it with an AlwaysOn schedule means the bot keeps trying to re-enter against forced closes every afternoon. The guard surfaces the misconfig at boot time with a clear remediation pointer (`use efa_standard for live/funded accounts`).

**Strategy logic disclaimer:** The VSL does not reveal any maintenance-bot entry rules. The wide-BB + extreme-RSI tuning is OUR interpretation of "low-frequency, conservative" — it produces << 1 entry / day on a sinusoidal year fixture. A future plan could swap to a different signal generator; the bot identity (NQ, 24/7, EFA, conservative) is the stable contract.

**Known limitation (Plan 21 candidate):** The risk gate's `_check_hard_flat` is policy-agnostic — it denies any open-increasing intent after 15:10 CT regardless of which policy is wired. A 24/7 EFA bot therefore effectively can't open new positions in the 15:10 CT → 17:00 CT window even though EFA itself permits it. Existing positions are unaffected (the check only blocks opens). Plan 21 should either make `_check_hard_flat` policy-aware or document the daily quiet window as a first-class behavior.
