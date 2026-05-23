# Plan 5 — ORB Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Ship the 5-min Opening Range Breakout strategy with **Surge** and **Maintenance** YAML profiles. Wire into BacktestEngine and produce a first real PnL backtest report against synthetic bars.

**Architecture:** `OpeningRangeBreakoutStrategy(profile: ORBProfile)` implements the `Strategy` Protocol from Plan 4. State machine per session:
1. `WARMUP` (before 09:30 ET)
2. `BUILDING_RANGE` (09:30-09:35 ET — track high/low/volume)
3. `WAITING_BREAKOUT` (09:35 ET onward — emit BUY if close > range_high, SELL if close < range_low; one trade per day per profile.max_trades)
4. `IN_TRADE` (until bracket hits or 14:00 ET flatten)
5. `DONE` (after first trade or max_trades reached)

ATR is computed over the last N bars (configurable). Stop = entry ± atr_mult × ATR; take-profit = entry ± tp_r × stop_distance.

**Tech Stack:** No new deps. Uses Plan 1-4.

**Scope (tight given context):**
- ORB strategy with Surge + Maintenance profiles
- BacktestEngine integration test producing a real PnL trace
- Walk-forward, parameter sweep, Monte Carlo are PARKED — deferred to a future v2 plan once first live results justify the tooling investment.
- `state_snapshot` on TradeLog deferred (RuleReplayReporter would need it; v1 RuleReplay smoke-tests via empty replay).

**Deliverable:** `python -m bot.backtest --strategy orb --profile config/profiles/surge.yml --symbol MNQ --start ... --end ...` runs against ingested parquet + emits a report with non-zero trade count + the rule-replay reporter passes.

---

## File Structure

```
src/bot/strategy/
├── __init__.py
├── orb.py                   # OpeningRangeBreakoutStrategy + ORBProfile
└── profile_loader.py        # YAML → ORBProfile

config/profiles/
├── surge.yml                # aggressive: 2 MNQ, 1.0×ATR, 2.0R, no time filter, max 2/day
└── maintenance.yml          # conservative: 1 MNQ, 0.8×ATR, 1.5R, 09:30-11:30 ET, max 1/day

tests/
├── test_strategy_orb_profile.py
├── test_strategy_orb_state_machine.py
├── test_strategy_orb_atr.py
├── test_strategy_orb_breakout_signal.py
└── test_strategy_orb_integration.py     # full backtest run
```

---

## Tasks

### Task 1: `ORBProfile` + YAML loader

`src/bot/strategy/orb.py` (initial) + `src/bot/strategy/profile_loader.py`:

`ORBProfile` Pydantic v2 model:
```python
class ORBProfile(BaseModel):
    symbol: Literal["MNQ", "NQ"] = "MNQ"
    quantity: int = Field(default=1, ge=1)
    range_minutes: int = Field(default=5, ge=1, le=30)
    atr_period: int = Field(default=14, ge=1)
    atr_mult: float = Field(default=1.0, gt=0)
    tp_r_multiple: float = Field(default=2.0, gt=0)
    session_start_et: time = time(9, 30)
    cutoff_time_et: time | None = None   # None = no per-session cutoff
    max_trades_per_day: int = Field(default=1, ge=1)
```

`load_orb_profile(path: Path) -> ORBProfile` reads YAML → model_validate.

Two profiles:
- `surge.yml`: quantity=2, atr_mult=1.0, tp_r=2.0, cutoff=None, max_trades=2
- `maintenance.yml`: quantity=1, atr_mult=0.8, tp_r=1.5, cutoff=11:30, max_trades=1

Tests: load valid YAML, reject invalid (atr_mult=0), default values.

Commit: `feat(strategy): ORBProfile Pydantic model + YAML loader + surge/maintenance profiles`.

### Task 2: ATR computation helper

`src/bot/strategy/orb.py` — `_compute_atr(bars: list[Bar], period: int) -> float | None`:
- True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
- ATR = simple average of last `period` TRs
- Returns None if fewer than period+1 bars available

Tests: hand-built 3-bar fixtures, verify ATR matches expected math.

Commit: `feat(strategy): ATR (true range simple average) helper`.

### Task 3: ORB state machine — range building + breakout signal

`OpeningRangeBreakoutStrategy(profile)` class implementing `Strategy.on_bar(bar, state) -> Iterable[OrderIntent]`.

State tracked per-instance (resets on new trading day detected via UTC day boundary OR 17:00 CT session boundary):
- `range_high`, `range_low`: floats (None until range complete)
- `bars_in_range`: counter
- `recent_bars`: bounded deque for ATR
- `trades_today`: counter
- `current_position_sym`: tracks our own open intent for closing logic
- `last_day_key`: trading day key (`(timestamp - 17:00 CT).date()` for Topstep day boundary)

Logic per `on_bar`:
1. Compute trading day key; reset state if day changed.
2. Append to `recent_bars` for ATR (drop oldest beyond atr_period+1).
3. Convert bar.timestamp to ET for session checks.
4. If `bars_in_range < range_minutes` and now ≥ session_start_et: update range_high/low, increment bars_in_range.
5. After range complete: if `trades_today >= max_trades_per_day` OR (cutoff and now > cutoff): skip.
6. Compute ATR. If None (not enough warmup), skip.
7. If `bar.close > range_high`: emit BUY bracket with `stop_loss_ticks = ticks_from_dollars(atr × atr_mult)`, `take_profit_ticks = stop_loss_ticks × tp_r_multiple`. quantity = profile.quantity. Increment trades_today.
8. If `bar.close < range_low`: emit SELL bracket (analogous).

Tests:
- Build range during 9:30-9:35 ET; no signal during build.
- After build: bar with close > range_high → BUY intent with correct stop/TP ticks.
- After build: bar with close < range_low → SELL intent.
- After max_trades: no more intents same day.
- New day: state resets, range rebuilds.

Commit: `feat(strategy): OpeningRangeBreakoutStrategy state machine + breakout signal`.

### Task 4: BacktestEngine integration test

`tests/test_strategy_orb_integration.py` — synthesizes a sequence of 1-min Bars representing one trading day where:
- 9:30-9:35 ET: builds a range [16500, 16510]
- 9:36 ET: bar closes at 16515 (above range) → BUY signal
- Bars 9:37-10:00: price drifts up to 16530 → bracket TP hit
- Run through BacktestEngine + TopstepRiskGate (Combine policy + safety buffer + news=off)
- Assert: TradeLog has ≥1 fill, final realized_pnl > 0, no rule violations from RuleReplay.

This is the **first real backtest**. The numbers will be small (one trade) but the pipeline is exercised end-to-end.

Commit: `test(strategy): ORB integration with BacktestEngine — first real backtest`.

### Task 5: CLI extension — `--strategy orb`

`src/bot/backtest/cli.py` — extend `--strategy` to accept `orb`, add `--profile PATH` argument (required if strategy=orb).

Wire `orb` choice to load profile + construct OpeningRangeBreakoutStrategy.

Test: CLI invocation with synthetic small parquet fixture (Plan 2's `nq_2023z_clean.csv` already exists; ingest, then run CLI with --strategy orb --profile config/profiles/surge.yml --symbol NQ --start ... --end ... --contract 2023Z). Verify exit 0, summary printed.

Commit: `feat(backtest): CLI --strategy orb + --profile`.

### Task 6: Final verification + tag

```bash
ruff check src/ tests/
mypy src/ tests/
pytest -q
git tag plan-05-orb-strategy-complete
```

---

## Out-of-scope for Plan 5

- ❌ Walk-forward (rolling + anchored) — parked
- ❌ Parameter sweep — parked
- ❌ Monte Carlo trade-bootstrap — parked
- ❌ v2 strategies (Maróy, Williams vol breakout, NR7, VWAP pullback) — parked
- ❌ News calendar wiring during backtest (gate already has `_NoNews` default; if real news calendar needed, pass via gate construction in CLI)

These deferred items can be added as a "Plan 5b" once we see first backtest results justify the tooling investment.

---

## Notes

- Use `from datetime import UTC` consistently.
- Bar timestamps are UTC; convert to ET (`zoneinfo.ZoneInfo("America/New_York")`) for session-time checks.
- `ticks_from_dollars(d, symbol)` helper = `d / TICK_VALUES[symbol]`. Add to `bot.constants` if needed.
- The integration test (T4) is the load-bearing verification — if it fails, the gate+engine+strategy interaction has a bug.
