# Plan 16 — PropBot (NQ Trend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Second NQ user-facing bot. PropBot trades NQ futures with a "Trend [Daily Exit]" pattern (per the "RP - PropBot - Trend [Daily Exit]" overlay visible at ~18:30 in the VSL) and runs the EFA Standard funded-account risk profile (designed to never approach trailing MLL, consistent small payouts). The visible testimonial — "first payout from running PropBot" at ~24:00 in the VSL — confirms PropBot is positioned as the funded/payout bot. After this plan: PropBot deploys alongside SurgeBot in the fleet.

**Architecture:** PropBot is a `BotSpec` (Plan 12) wiring a new `TrendFollowingStrategy` (signal generator) + a conservative fixed-size position (no tiering — funded-account ethos is preservation, not aggressive scaling) + `EFAStandardEoDDrawdown` policy + market-hours-only schedule with an earlier session cutoff (e.g., 14:30 CT instead of 15:00) to ensure flat positions before the EoD trailing ratchets.

**Tech Stack:** No new deps. Reuses Plan 12 (BotSpec + FleetRuntime), Plan 13 (ProofGenerator), Plan 14 (MarketSpec for NQ/MNQ), existing `EFAStandardEoDDrawdown`. New strategy class.

**VSL fidelity (observable constraints honored):**
- **Market**: NQ1! (per "RP - PropBot - Trend [Daily Exit]" overlay on NQ chart)
- **Trend variant**: bot enters on confirmed trend (not reversal) — distinct from SurgeBot's potential mean-reversion / breakout patterns
- **Daily Exit**: flat before EoD
- **Funded-account framing**: VSL's "Just had my first payout from running PropBot" testimonial → bot is positioned for funded accounts; risk profile is EFA Standard (EoD-trailing MLL, not real-time trailing)

**Internal strategy logic disclaimer:** The VSL does not show PropBot's entry rules — only the "Trend" label. The implementation uses a simple, defensible trend-following entry: long when 20-EMA > 50-EMA (uptrend confirmed) and price pulls back to 20-EMA; short on inverse. Exit at +1.5R or trend reversal (EMAs cross back) or EoD. This is OUR design under the observable "Trend" constraint. Document the design + leave indicator params YAML-configurable.

**Deliverable:**
- `src/bot/strategy/trend_following.py` — `TrendFollowingStrategy`.
- `config/bots/propbot_nq.yml` — full BotSpec.
- Registry entry: `register_strategy("trend_ema_pullback", ...)`.
- Backtest + sim run + proof bundle produced.
- CI green (~627 + ~15 new tests).
- Tag `plan-16-propbot-complete`.

---

## File structure

- Create: `src/bot/strategy/trend_following.py` — `TrendFollowingStrategy` (EMA-pullback entry)
- Create: `src/bot/strategy/profiles/propbot.py` — defaults
- Modify: `src/bot/runtime/fleet/registry.py` — register "trend_ema_pullback"
- Create: `config/bots/propbot_nq.yml`
- Create: `tests/strategy/test_trend_following.py`
- Create: `tests/integration/test_propbot_e2e.py`

---

## Tasks

### T1: `TrendFollowingStrategy`

`src/bot/strategy/trend_following.py`. Class implements `Strategy` Protocol:
```
TrendFollowingStrategy(
    fast_ema: int = 20,
    slow_ema: int = 50,
    pullback_atr_mult: float = 0.5,  # entry triggered when price within 0.5 ATR of fast EMA
    reward_ratio: float = 1.5,
    max_trades_per_day: int = 1,
    symbol: str = "MNQ",
)
```

State:
- Rolling EMA windows (use existing `bot.strategy.profile_loader` helpers if they exist; else implement inline).
- Rolling ATR (14-period).
- Daily trade counter (resets at session open).
- Current open position direction (None / long / short).

`on_bar(bar, state) -> Iterable[OrderIntent]`:
1. Update EMAs + ATR.
2. If position open → check exit: trend reversal (EMAs cross back) or target hit or EoD.
3. If no position + EMAs aligned (uptrend if fast > slow) + price within `pullback_atr_mult` × ATR of fast EMA + daily trade count < max → emit BUY intent with bracket (TP at +reward_ratio × ATR, SL at fast EMA - 1×ATR).
4. Inverse for downtrend.

Tests:
- EMA crossover up + pullback → BUY emitted.
- EMA crossover down + pullback → SELL emitted.
- No trade when EMAs flat (within 0.1×ATR of each other) — chop filter.
- max_trades_per_day=1 → second valid signal in same day ignored.
- EoD flat: any open position generates a CLOSE intent at session cutoff.
- ATR computed correctly on 14-bar sample.

Commit: `feat(strategy): TrendFollowingStrategy (EMA pullback + ATR-bracketed exit)`.

### T2: Strategy profile + registry entry

`src/bot/strategy/profiles/propbot.py`:
```python
PROPBOT_DEFAULTS = {
    "fast_ema": 20,
    "slow_ema": 50,
    "pullback_atr_mult": 0.5,
    "reward_ratio": 1.5,
    "max_trades_per_day": 1,
}
```

Registry: `register_strategy("trend_ema_pullback", lambda p: TrendFollowingStrategy(**p))`.

Tests:
- Profile loads + matches schema.
- Registry returns TrendFollowingStrategy from "trend_ema_pullback" id.

Commit: `feat(strategy,registry): propbot profile + trend_ema_pullback registration`.

### T3: BotSpec YAML

`config/bots/propbot_nq.yml`:
```yaml
name: propbot_nq
enabled: true
symbol: MNQH26
strategy_id: trend_ema_pullback
strategy_params:
  fast_ema: 20
  slow_ema: 50
  pullback_atr_mult: 0.5
  reward_ratio: 1.5
  max_trades_per_day: 1
risk_policy: efa_standard
risk_params:
  mll_amount: 2000
schedule_type: market_hours
schedule_params:
  open_ct: "09:00"   # later than SurgeBot — avoid opening volatility
  close_ct: "14:30"  # earlier exit — funded-account conservatism
journal_path: state/journal_propbot_nq.db
```

Tests:
- YAML round-trips through `load_bot_specs`.
- `BotRegistry.build(spec)` produces correct ResolvedBot.

Commit: `feat(config): propbot_nq.yml — second NQ bot for funded accounts`.

### T4: End-to-end integration test

`tests/integration/test_propbot_e2e.py`. Drives synthetic NQ bars (1 day, 09:00 → 14:30 CT, with a clean uptrend pattern) through FleetRuntime → TopstepXSimClient (efa_payout_flow_50k scenario) → Journal. Asserts:
- 1 long position opened on EMA pullback.
- Position closed at +1.5R or EoD.
- Journal has 1 round-trip + 0 risk denials.
- EFA Standard floor doesn't move intraday (regression check on EoD-trailing semantics).

Commit: `test(integration): PropBot end-to-end (fleet → sim → journal)`.

### T5: Docs + tag

Append PropBot section to `docs/superpowers/specs/2026-05-22-futures-bot/09-bot-lineup.md` (created in Plan 15). Document the EMA-pullback design + the "Trend" framing from the VSL.

Then:
```
git tag plan-16-propbot-complete
git push origin plan-16-wt --tags  # (or main)
```

Commit: `docs(spec): PropBot lineup entry + trend-following design rationale`.

---

## Verification

```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -x -q
python -m bot.backtest --bot propbot_nq --start 2024-01-01 --end 2024-12-31 --data-fixture tests/data/fixtures/nq_1min_2024.csv
python -m bot.execution.topstepx_sim --scenario efa_payout_flow_50k --bot propbot_nq
```

End state: 2 of 6 user-facing bots deployable. Same pattern repeats for Plans 17-20.
