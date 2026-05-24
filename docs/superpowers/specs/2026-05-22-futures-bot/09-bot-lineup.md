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

## Lux Bot — NQ 10m, Discord signal source (Plan 19)

**Status**: implemented, disabled by default.

**Differentiator**: third NQ bot, distinct from SurgeBot + PropBot because
its trade ideas arrive over an external Discord channel rather than being
generated by internal indicator logic. This is the load-bearing
differentiator visible at ~18:30 in the VSL ("RP - Lux Bot
(Discord - NQ 10m)").

**Market / timeframe**: NQ (configurable to MNQ), 10-minute bars,
AlwaysOn schedule. Discord posts can arrive overnight, weekends, around
news prints — the bot stays subscribed 24/7.

**Important distinction**: Lux Bot's Discord source is an INPUT to our
bot, not the OUTPUT product. The $99/mo Profit Insider Discord community
is a separate product we are not cloning. Users supply the channel
id(s) of whatever signal channel they actually monitor.

### Configuration

- `config/bots/lux_bot.yml` — `enabled: false` by default
- Env vars (one of):
  - `LUX_BOT_FIXTURE_PATH=path/to/signals.json` — replay-from-JSON mode
    for smoke tests / paper trading / regression runs
  - `DISCORD_BOT_TOKEN=...` — production mode; combined with
    `strategy_params.discord_channel_ids` in the yml

If neither env var is set when the registry tries to build the bot, it
raises `RuntimeError` loudly. There is no silent default.

### Signal format

`bot.signals.parser.parse_signal_message` accepts the common chat-channel
shapes:

```
BUY NQ @20100 SL=20070 TP=20160
LONG MNQH26 limit 20100 stop 20070 target 20160
SHORT 1 NQ at 20100 stop 20130 tp 20040
🟢 BUY NQ @20100 SL=20070 TP=20160          # emoji prefixes tolerated
```

Unparseable messages are logged at INFO and dropped — typos in a chat
channel are normal and must not crash the source. The parser is
case-insensitive and accepts comma-thousands (20,100) plus optional
decimals.

### Architecture

```
DiscordSignalSource ──iter_signals()──┐
                                       │
   FixtureSignalSource (test)  ────────┼─► SignalStrategy.pump (asyncio task)
                                       │       │
                                       │       ▼ collections.deque
                                       │   on_bar(bar, state) drains ≤N events
                                       │       │
                                       ▼       ▼
                            TopstepRiskGate.approve_or_deny
                                       │
                                       ▼
                            SimExecutionClient / TopstepX
                                       │
                                       ▼
                                   Journal
```

### Safety properties

1. **Signals never bypass `TopstepRiskGate`.** The pipeline above shows
   `SignalStrategy` emitting `OrderIntent`s into the gate exactly like
   `OpeningRangeBreakoutStrategy` does. There is no special-case path
   that lets a "trusted signal" skip the gate, and there is no
   strategy-side qty cap that pre-validates oversize signals.
   `TopstepRiskGate.MAX_POSITION` is the single chokepoint. Verified by
   `tests/integration/test_lux_bot_e2e.py::test_oversize_signal_denied_by_risk_gate`
   (signal claims `qty=100`, policy caps at 5; gate denies, journal
   records `MAX_POSITION` row, broker sees zero fills).

2. **Per-bar emission cap.** `max_signals_per_bar` (default 1) limits how
   many queued events convert to OrderIntents in a single `on_bar` call.
   A burst of 20 Discord messages in one minute → at most 1 intent on
   the next bar; the rest are retained for subsequent bars. Prevents a
   compromised / runaway upstream channel from stuffing the broker.

3. **Symbol drift handled.** If a signal arrives with symbol "NQ" but
   the bot is configured for "MNQH26", the prefix-match in
   `SignalStrategy._symbols_match` accepts it. Unrelated roots ("ES" →
   "MNQ" bot) are dropped. The bot's contract symbol always wins
   downstream — the OrderIntent goes out as `MNQH26` regardless of what
   the message said.

4. **Bot author messages skipped.** `DiscordSignalSource._handle_message`
   drops messages where `message.author.bot is True` — prevents echo
   loops if your own bot posts confirmations to the same channel.

### Provenance

Each emitted `OrderIntent.client_order_id` embeds the originating
signal's `source_id` (Discord message id) as
`signal-{source_id}-{counter}`. The journal's `risk_decisions` and
`fills` tables therefore allow tracing any broker fill back to the exact
Discord message that triggered it. Plan 21's dashboard surfaces this in
the per-bot trade view.

### Open items for Plan 21

- `FleetRuntime` does NOT currently know to start a strategy's
  background pump task. The integration test calls `strat.start()`
  explicitly. Production wiring (a `Strategy.setup(loop)` hook or
  similar) is deferred to Plan 21.
- Dashboard should surface signal-message provenance: clicking a fill
  should reveal the Discord message text + author + channel id from the
  journal.

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
