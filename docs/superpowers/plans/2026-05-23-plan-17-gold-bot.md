# Plan 17 — Gold Bot (GC, Session-Windowed) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** First non-NQ user-facing bot. Gold Bot trades GC1!/Gold Futures (COMEX) on a 10-minute timeframe, honoring the visible session-window strings from the VSL Gold Bot screen at ~19:00 (`0830-1500`, `2300-0130`, `0830-1130`, `1130-1500`, `0820-0840`, `0955-1010`, `1355-1415`). It runs the maintenance/live-family risk profile (24/7-eligible but constrained by the explicit session windows). After this plan: Gold Bot deploys, proving the multi-market plumbing (Plan 14) works end-to-end with a non-NQ instrument.

**Architecture:** Gold Bot is a `BotSpec` (Plan 12) wiring a generic session-aware strategy (initially the existing ORB strategy adapted for 10-minute bars, or a new mean-reversion strategy) + `CustomWindows` schedule from Plan 12 + `EFAStandardEoDDrawdown` for the live/maintenance profile + MarketSpec lookup for GC (Plan 14). The session windows are the load-bearing feature — the VSL's only legible operating-schedule artifact for Gold Bot.

**Tech Stack:** No new deps. Reuses Plan 12 (BotSpec + CustomWindows schedule), Plan 13 (ProofGenerator), Plan 14 (MarketSpec for GC/MGC), existing risk policies.

**VSL fidelity (observable constraints honored):**
- **Market**: GC1! (COMEX gold) — verified at ~19:00 ("GC1! · Gold Futures · 10 · COMEX")
- **Timeframe**: 10-minute bars — verified by the "10" in chart header
- **Session windows**: 7 windows visible, ALL implemented as the bot's schedule
- **24/7 family**: per VSL caption "live only maintenance systems trade automatically 24/7" — Gold Bot is maintenance-family, so the schedule is intentionally permissive (windows that span overnight 2300-0130 are honored)

**Critical interpretation question — flag for user before merge:**
The 7 visible time strings have no labeled timezone in the VSL. Three interpretations:
(a) All in ET (most likely for US-resident trader audience)
(b) All in CT (matches CME exchange time)
(c) Mixed (e.g., overnight 2300-0130 in ET ~= regular hours in CT)

Default to **ET** (per US-trader audience assumption); leave timezone YAML-configurable; document the ambiguity in the BotSpec config comment.

The shorter windows (0820-0840, 0955-1010, 1355-1415) almost certainly correspond to NEWS-EVENT windows (NFP at 08:30 ET, weekly oil at 10:30 ET, EIA gold at... etc.) — they're brief, time-of-day-specific filters. Implement as additional CustomWindows entries; the strategy itself decides whether news-window entries are aggressive or defensive.

**Internal strategy logic disclaimer:** The VSL never reveals Gold Bot's entry rules. The implementation uses a configurable mean-reversion strategy (similar to ORB but with a wider range setup typical of gold's mid-day chop). Document the design + leave entry params YAML-configurable.

**Deliverable:**
- `src/bot/strategy/mean_reversion.py` — `MeanReversionStrategy` (Bollinger-band mean-reversion, 10m).
- `config/bots/gold_bot.yml` — full BotSpec with all 7 session windows.
- Registry entry: `register_strategy("mean_reversion_bb", ...)`.
- Backtest run against GC FirstRateData → proof bundle.
- TopstepX Sim run with GC scenario → exits clean.
- CI green (~642 + ~20 new tests).
- Tag `plan-17-gold-bot-complete`.

---

## File structure

- Create: `src/bot/strategy/mean_reversion.py` — `MeanReversionStrategy`
- Create: `src/bot/strategy/profiles/gold_bot.py` — defaults
- Modify: `src/bot/runtime/fleet/registry.py` — register "mean_reversion_bb"
- Create: `config/bots/gold_bot.yml`
- Modify: `src/bot/data/aggregator.py` — ensure 10-min bar aggregation works (likely already does; verify)
- Create: `tests/strategy/test_mean_reversion.py`
- Create: `tests/integration/test_gold_bot_e2e.py`

---

## Tasks

### T1: `MeanReversionStrategy`

`src/bot/strategy/mean_reversion.py`. Class implements `Strategy` Protocol:
```
MeanReversionStrategy(
    bb_period: int = 20,
    bb_stddev: float = 2.0,
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
    reward_ratio: float = 1.0,  # mean-reversion uses tighter TP than trend
    max_trades_per_day: int = 3,
    symbol: str = "GC",
)
```

State: rolling Bollinger Bands + RSI.

`on_bar(bar, state)`:
1. Update BB + RSI.
2. If position open → exit at mid-band (BB middle line) or stop-loss or schedule cutoff.
3. If no position + price < lower_BB + RSI < oversold + max-trades not hit → BUY toward mid.
4. Inverse for overbought.

Tests:
- Synthetic ranging price → at least one BUY and one SELL across the test bars.
- Trending price (BB widens) → no entries (chop filter).
- max_trades_per_day cap enforced.
- Exit at mid-band.

Commit: `feat(strategy): MeanReversionStrategy (Bollinger + RSI, mid-band exit)`.

### T2: Strategy profile + registry

`src/bot/strategy/profiles/gold_bot.py` with GOLD_BOT_DEFAULTS. Registry registers "mean_reversion_bb".

Commit: `feat(strategy,registry): gold_bot profile + mean_reversion_bb registration`.

### T3: BotSpec YAML — all 7 session windows

`config/bots/gold_bot.yml`:
```yaml
# Session windows from VSL Gold Bot screen at ~19:00 in the video.
# Timezone: ET (assumed — VSL didn't label; leave configurable).
# The 7 windows include 3 broad sessions + 4 narrow news-event windows.
name: gold_bot
enabled: true
symbol: MGCH26   # Use micros for $50K Combine sizing
strategy_id: mean_reversion_bb
strategy_params:
  bb_period: 20
  bb_stddev: 2.0
  rsi_period: 14
  rsi_oversold: 30.0
  rsi_overbought: 70.0
  reward_ratio: 1.0
  max_trades_per_day: 3
risk_policy: efa_standard
risk_params:
  mll_amount: 2000
schedule_type: custom_windows
schedule_params:
  tz: America/New_York
  windows:
    # Broad sessions (per VSL screen)
    - ["08:30", "15:00"]   # US regular hours
    - ["23:00", "01:30"]   # Asian overnight (spans midnight; CustomWindows handles)
    - ["08:30", "11:30"]   # US AM session
    - ["11:30", "15:00"]   # US PM session
    # Narrow news-event windows
    - ["08:20", "08:40"]   # Pre-NFP / pre-data
    - ["09:55", "10:10"]   # 10:00 ET data drops
    - ["13:55", "14:15"]   # FOMC-style 14:00 ET
journal_path: state/journal_gold_bot.db
```

Tests:
- YAML loads + builds without error.
- Schedule.should_trade returns True at 09:00 ET, 23:30 ET; False at 18:00 ET.
- Overnight window 23:00-01:30 correctly returns True at 00:15 ET.

Commit: `feat(config): gold_bot.yml with all 7 VSL-visible session windows`.

### T4: End-to-end integration test

`tests/integration/test_gold_bot_e2e.py`. Drives synthetic GC bars (24h span, mix of in-window and out-of-window timestamps) through FleetRuntime → TopstepXSimClient → Journal. Asserts:
- Entries ONLY occur in-window.
- Mean-reversion logic produces entries in ranging segments, not trending.
- Journal records correct symbol (GC/MGC, not NQ).
- Plan-13 ProofGenerator handles GC trade data.

Commit: `test(integration): Gold Bot end-to-end (custom windows + GC market)`.

### T5: Docs + tag

Append Gold Bot section to `09-bot-lineup.md`. Document the session-window interpretation (ET assumption, news-window inference) so a future plan can revisit if user verifies the actual timezone.

Then:
```
git tag plan-17-gold-bot-complete
git push origin plan-17-wt --tags  # (or main)
```

Commit: `docs(spec): Gold Bot lineup entry + session-window interpretation`.

---

## Verification

```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -x -q
python -m bot.backtest --bot gold_bot --start 2024-01-01 --end 2024-12-31 --data-fixture tests/data/fixtures/gc_1min_2024.csv
```

End state: 3 of 6 bots deployable. Plan 18 (ES Scalper) follows the same shape — different market, simpler schedule (just MarketHours with EoD cutoff).
