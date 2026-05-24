# Plan 15 — SurgeBot (NQ + Voodoo Tiered) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Ship the first user-facing bot from the VSL lineup. SurgeBot trades NQ futures with a "Daily Exit" pattern, uses tiered position sizing [1, 2, 4, 5 contracts] keyed to account equity (the "Voodoo Strategy Tiered - $20k [1,2,4,5]" visible at ~18:00 in the VSL), and runs the Combine-aggressive risk profile (designed to hit the $3K profit target before the trailing MLL bites). After this plan: `python -m bot.runtime --bots config/bots/surgebot_nq.yml --check` boots, and a backtest against historical NQ data produces a proof bundle (Plan 13) showing the bot's claimed shape.

**Architecture:** SurgeBot is a `BotSpec` (Plan 12) wiring three pieces: the existing `OpeningRangeBreakoutStrategy` (or a new `VoodooStrategy` if the team wants a distinct entry logic) as the *signal generator*, a new `TieredSizingDecorator` that wraps the strategy to scale position size by account profit, and `CombineIntradayDrawdown` as the risk policy. The MarketSpec (Plan 14) resolves contract specs for NQ/MNQ.

**Tech Stack:** No new deps. Reuses Plan 11 (TopstepX Sim), Plan 12 (BotSpec + FleetRuntime), Plan 13 (ProofGenerator), Plan 14 (MarketSpec for NQ), existing ORB strategy, existing CombineIntradayDrawdown policy.

**VSL fidelity (observable constraints honored):**
- **Market**: NQ1! (CME NASDAQ-100 E-mini Futures) — verified at ~18:00 in the VSL ("NQ1! · NASDAQ 100 E-mini Futures · 1h · CME")
- **Daily Exit**: bot flattens before hard-flat 15:10 CT — implemented via existing `MarketHours` schedule from Plan 12
- **Tiered sizing**: starts at 1 contract; scales to 2 at +$500 profit; 4 at +$1,500; 5 at +$2,500 — these breakpoints are MY DESIGN under the visible [1,2,4,5] tier list (the VSL doesn't reveal exact breakpoints). Document the design choice + leave configurable via `tiered_breakpoints` YAML field.
- **Reversal + target labels visible**: ORB strategy already implements directional entry + TP target (configured via `reward_ratio`). Honor the observable shape; don't claim our ORB rules match Voodoo's — they almost certainly don't (sales VSLs hide trade logic).

**Internal strategy logic disclaimer:** The VSL never reveals SurgeBot's actual entry/exit rules. We use ORB as a placeholder entry strategy that satisfies all observable constraints. A future plan may replace ORB with a different strategy after backtest research — the bot identity (SurgeBot, NQ, Daily Exit, Tiered sizing, Combine-aggressive) stays the same.

**Deliverable:**
- `config/bots/surgebot_nq.yml` — full BotSpec.
- `src/bot/strategy/tiered_sizing.py` — `TieredSizingDecorator` wraps any Strategy.
- Registry entry: `register_strategy("orb_5m_tiered", lambda p: TieredSizingDecorator(OpeningRangeBreakoutStrategy(**p["strategy"]), **p["tiered"]))`.
- Backtest harness run: `python -m bot.backtest --bot surgebot_nq --start 2024-01-01 --end 2024-12-31` produces a `state/proof/surgebot_nq_<ts>/report.html`.
- TopstepX Sim run: `python -m bot.execution.topstepx_sim --scenario combine_pass_50k --bot surgebot_nq` exits 0 with stage=combine_passed.
- CI green (~612 + ~15 new tests).
- Tag `plan-15-surgebot-complete`.

---

## File structure

- Create: `src/bot/strategy/tiered_sizing.py` — `TieredSizingDecorator`
- Create: `src/bot/strategy/profiles/surgebot.py` — pre-built parameter profile (Voodoo-shaped defaults)
- Modify: `src/bot/runtime/fleet/registry.py` — register "orb_5m_tiered"
- Create: `config/bots/surgebot_nq.yml`
- Modify: `src/bot/backtest/cli.py` — add `--bot <name>` flag that reads BotSpec
- Modify: `src/bot/execution/topstepx_sim/cli.py` — add `--bot <name>` flag
- Create: `tests/strategy/test_tiered_sizing.py`
- Create: `tests/integration/test_surgebot_e2e.py`

---

## Tasks

### T1: `TieredSizingDecorator`

`src/bot/strategy/tiered_sizing.py`. Class wraps any `Strategy`:
```
TieredSizingDecorator(
    inner: Strategy,
    tier_breakpoints: list[tuple[float, int]] = [(0, 1), (500, 2), (1500, 4), (2500, 5)],
    symbol: str = "MNQ",
)
```

`on_bar(bar, state) -> Iterable[OrderIntent]`:
1. `tier_qty = self._tier_for(state.equity - state.start_balance)` — linear scan of breakpoints.
2. For each intent from `self.inner.on_bar(bar, state)`: override `intent.qty` to `tier_qty`. Yield modified intent.

For micro contracts (MNQ), multiply tier_qty by 10 (1 mini = 10 micros).

Tests:
- Profit < $500 → tier_qty = 1 (or 10 for MNQ).
- Profit $1,000 → tier_qty = 2 (or 20 for MNQ).
- Profit $3,000 → tier_qty = 5 (or 50 for MNQ).
- Decorator passes through bars + state to inner strategy unchanged.
- Empty inner output → empty decorated output.

Commit: `feat(strategy): TieredSizingDecorator for [1,2,4,5]-style position scaling`.

### T2: Surgebot strategy profile + registry entry

`src/bot/strategy/profiles/surgebot.py`:
```python
SURGEBOT_DEFAULTS = {
    "strategy": {  # OpeningRangeBreakoutStrategy params
        "range_minutes": 5,
        "atr_multiplier": 1.0,
        "reward_ratio": 2.0,
        "max_trades_per_day": 2,
    },
    "tiered": {
        "tier_breakpoints": [(0, 1), (500, 2), (1500, 4), (2500, 5)],
    },
}
```

`bot.runtime.fleet.registry`: pre-register `"orb_5m_tiered"` factory.

Tests:
- Registry returns a `TieredSizingDecorator` wrapping `OpeningRangeBreakoutStrategy` from "orb_5m_tiered" id.
- SURGEBOT_DEFAULTS round-trips through YAML.

Commit: `feat(strategy,registry): surgebot profile + orb_5m_tiered registration`.

### T3: BotSpec YAML

`config/bots/surgebot_nq.yml`:
```yaml
name: surgebot_nq
enabled: true
symbol: MNQH26   # Q1 2026 contract; continuous-roll handled by data layer
strategy_id: orb_5m_tiered
strategy_params:
  strategy:
    range_minutes: 5
    atr_multiplier: 1.0
    reward_ratio: 2.0
    max_trades_per_day: 2
  tiered:
    tier_breakpoints:
      - [0, 1]
      - [500, 2]
      - [1500, 4]
      - [2500, 5]
risk_policy: combine_intraday
risk_params:
  start_balance: 50000
  mll_amount: 2000
  max_mini: 5
schedule_type: market_hours
schedule_params:
  open_ct: "08:30"
  close_ct: "15:00"   # 10 min before hard-flat to flat positions clean
journal_path: state/journal_surgebot_nq.db
```

Tests:
- Loading this YAML through `load_bot_specs` returns a valid BotSpec.
- `BotRegistry.build(spec)` produces a ResolvedBot whose strategy is a TieredSizingDecorator.

Commit: `feat(config): surgebot_nq.yml — first user-facing bot`.

### T4: Backtest CLI `--bot` integration

`src/bot/backtest/cli.py`: add `--bot <name>` flag that reads `config/bots/<name>.yml`, hydrates the BotSpec, builds the strategy + risk policy, runs `BacktestEngine`. Existing CLI flags stay supported.

Tests:
- `python -m bot.backtest --bot surgebot_nq --start 2024-01-01 --end 2024-01-31 --data-fixture tests/data/fixtures/nq_1min_jan2024.csv` produces a TradeLog + emits `state/proof/surgebot_nq_<ts>/report.html` via Plan-13 ProofGenerator.
- Missing `--bot` value → falls through to legacy single-strategy path.

Commit: `feat(backtest): --bot flag wires multi-bot config through backtest pipeline`.

### T5: TopstepX Sim CLI `--bot` integration

`src/bot/execution/topstepx_sim/cli.py`: add `--bot <name>` flag — combines a scenario (Combine-pass / Combine-fail / etc.) with a specific bot's strategy. Replaces the placeholder strategy in scenarios with the bot's actual strategy.

Tests:
- `python -m bot.execution.topstepx_sim --scenario combine_pass_50k --bot surgebot_nq` exits 0; stdout shows surgebot strategy + combine_passed terminal stage.
- Same scenario without `--bot` still works (uses scenario default).

Commit: `feat(topstepx_sim): --bot flag — run scenarios with bot-specific strategy`.

### T6: End-to-end integration test

`tests/integration/test_surgebot_e2e.py`. Drives synthetic NQ bars (1 trading day, 8:30 CT → 15:00 CT, with a price pattern that produces 2 ORB entries) through the FleetRuntime → TopstepXSimClient → Journal. Asserts:
- Bot opened 2 positions.
- Each position used tier_qty = 1 (no profit yet).
- All positions closed by 15:00.
- Journal has 2 fills + 0 risk denials.
- ProofGenerator can run against the journal and produces a non-empty equity curve.

Commit: `test(integration): SurgeBot end-to-end (fleet → sim → journal → proof)`.

### T7: Docs + tag

Update `docs/superpowers/specs/2026-05-22-futures-bot/03-strategies.md` to document SurgeBot. Add a `docs/superpowers/specs/2026-05-22-futures-bot/09-bot-lineup.md` describing the 6 bots with their config locations.

Then:
```
git tag plan-15-surgebot-complete
git push origin plan-15-wt --tags  # (or main, depending on branch)
```

Commit: `docs(spec): SurgeBot + bot-lineup spec 09`.

---

## Verification

```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -x -q
python -m bot.backtest --bot surgebot_nq --start 2024-01-01 --end 2024-01-31 --data-fixture tests/data/fixtures/nq_1min_jan2024.csv
python -m bot.execution.topstepx_sim --scenario combine_pass_50k --bot surgebot_nq
open state/proof/surgebot_nq_*/report.html
```

End state: SurgeBot is the first deployable bot. Plan 16 (PropBot) follows the same pattern with different entry logic + funded-account risk profile.
