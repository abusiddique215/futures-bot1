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
