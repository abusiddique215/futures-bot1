# 09 — Bot Lineup

VSL-aligned bot family. Each bot is a `BotSpec` YAML under `config/bots/<name>.yml` + a `Strategy` class registered in `bot.runtime.fleet.registry`. Per-bot risk policy + schedule + market.

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
