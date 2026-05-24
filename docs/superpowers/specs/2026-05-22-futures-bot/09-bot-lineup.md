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

**Strategy logic disclaimer:** Voodoo's actual entry rules are not revealed by the VSL. ORB is used as a placeholder entry strategy that satisfies the observable constraints (5-minute timeframe, Daily Exit pattern, target-based exits). A future plan may swap ORB for a different signal generator while keeping the SurgeBot identity (NQ, Daily Exit, Tiered sizing, Combine-aggressive).
