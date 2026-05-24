# Plan 20 — NQ Maintenance (24/7 Live-Only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Sixth and final user-facing bot. NQ Maintenance is the 24/7 live-account variant explicitly described by the VSL caption at ~23:00: *"The live only maintenance systems trade automatically 24/7."* After this plan: all 6 bots from the VSL-aligned scope are deployable. The bot validates the no-cutoff schedule path through the existing risk gate + introduces a new safety guard preventing 24/7 bots from attaching to a Combine account (Combine has a 15:10 CT hard-flat that's incompatible with 24/7 operation).

**Architecture:** NQ Maintenance is a `BotSpec` (Plan 12) wiring a conservative strategy (low-frequency, wide stops — same `MeanReversionStrategy` from Plan 17 with much wider parameters) + `AlwaysOn` schedule (Plan 12) + `EFAStandardEoDDrawdown` policy + MarketSpec for NQ/MNQ. New constraint: a `LiveOnlyGuard` in the registry that refuses to attach `AlwaysOn` bots to any `combine_*` risk policy — surfaces a clear error at boot, not in production.

**Tech Stack:** No new deps. Reuses Plan 12 (AlwaysOn schedule + FleetRuntime), Plan 13 (ProofGenerator), Plan 14 (MarketSpec), Plan 17 (MeanReversionStrategy).

**VSL fidelity (observable constraints honored):**
- **Market**: NQ (implied — the bot family includes NQ variants of every framing)
- **24/7 schedule**: explicit verbatim from VSL caption
- **Live-only**: explicit verbatim
- **Maintenance ethos**: low-frequency, conservative — not a profit-maximizer but a slow-accumulator on a funded account

**Internal strategy logic disclaimer:** No entry rules visible. Implementation reuses MeanReversionStrategy with wide BB (period=50) + relaxed RSI (oversold=20, overbought=80) → far fewer signals → maintenance pace. Could be a different strategy in a future plan — the bot identity (NQ, 24/7, live-only, conservative) stays.

**Deliverable:**
- `src/bot/runtime/fleet/live_only_guard.py` — `LiveOnlyGuard.validate(spec) -> None` (raises if `AlwaysOn` + `combine_*` policy combination detected)
- Registry integration: guard runs at `BotRegistry.build()`
- `src/bot/strategy/profiles/nq_maintenance.py` — defaults
- `config/bots/nq_maintenance.yml`
- CI green (~692 + ~15 new tests)
- Tag `plan-20-nq-maintenance-complete`

---

## File structure

- Create: `src/bot/runtime/fleet/live_only_guard.py`
- Create: `src/bot/strategy/profiles/nq_maintenance.py`
- Modify: `src/bot/runtime/fleet/registry.py` — call guard in build()
- Create: `config/bots/nq_maintenance.yml`
- Create: `tests/runtime/fleet/test_live_only_guard.py`
- Create: `tests/integration/test_nq_maintenance_e2e.py`

---

## Tasks

### T1: `LiveOnlyGuard`

`src/bot/runtime/fleet/live_only_guard.py`. Pure function `validate_schedule_x_policy(schedule_type: str, risk_policy: str) -> None`:
- If `schedule_type == "always"` and `risk_policy in ("combine_intraday",)`: raise `IncompatibleBotSpecError` with a clear message: "24/7 schedule (always) is incompatible with combine_intraday risk policy — Topstep Combine requires hard-flat at 15:10 CT. Use efa_standard for live/funded accounts."
- Other combinations: return None (allowed).

Tests:
- AlwaysOn + combine_intraday → raises with the exact error message.
- AlwaysOn + efa_standard → no error.
- MarketHours + combine_intraday → no error.
- CustomWindows + any policy → no error.

Commit: `feat(fleet): LiveOnlyGuard — prevents combine+always misconfiguration`.

### T2: Registry integration

Modify `bot.runtime.fleet.registry.BotRegistry.build`: call `validate_schedule_x_policy(spec.schedule_type, spec.risk_policy)` BEFORE constructing components. Surfaces the error at boot, not at trade time.

Tests:
- `BotRegistry.build(<combine + always spec>)` raises `IncompatibleBotSpecError`.
- Valid specs build as before (regression).

Commit: `feat(fleet): registry runs LiveOnlyGuard before component construction`.

### T3: NQ Maintenance strategy profile

`src/bot/strategy/profiles/nq_maintenance.py`:
```python
NQ_MAINTENANCE_DEFAULTS = {
    "bb_period": 50,            # very wide BB → infrequent signals
    "bb_stddev": 3.0,           # wider deviation → only extreme moves
    "rsi_period": 21,           # smoother RSI
    "rsi_oversold": 20.0,       # only extreme oversold
    "rsi_overbought": 80.0,
    "reward_ratio": 0.5,        # small TP → high win rate, slow accumulation
    "max_trades_per_day": 2,    # very low frequency
    "symbol": "MNQ",
}
```

Tests:
- Profile loads + matches MeanReversionStrategy schema.
- A synthetic year of NQ data produces < 100 trades (sanity: < 1/day).

Commit: `feat(strategy): NQ Maintenance profile (wide BB, low frequency)`.

### T4: BotSpec YAML

`config/bots/nq_maintenance.yml`:
```yaml
# 24/7 live-account-only bot per VSL caption at ~23:00.
# WILL REFUSE TO BOOT against a Combine account — use efa_standard policy only.
name: nq_maintenance
enabled: false   # disabled by default; user enables after passing Combine + on EFA
symbol: MNQH26
strategy_id: mean_reversion_bb
strategy_params:
  bb_period: 50
  bb_stddev: 3.0
  rsi_period: 21
  rsi_oversold: 20.0
  rsi_overbought: 80.0
  reward_ratio: 0.5
  max_trades_per_day: 2
risk_policy: efa_standard
risk_params:
  mll_amount: 2000
schedule_type: always
schedule_params: {}
journal_path: state/journal_nq_maintenance.db
```

Tests:
- YAML loads cleanly.
- Attempting to swap `risk_policy: combine_intraday` in the spec causes `BotRegistry.build` to raise.
- AlwaysOn schedule confirmed (should_trade returns True at all hours).

Commit: `feat(config): nq_maintenance.yml — 24/7 live-only`.

### T5: End-to-end integration test

`tests/integration/test_nq_maintenance_e2e.py`. Drives synthetic NQ bars spanning a full 24h cycle (overnight + day + overnight) through FleetRuntime → SimClient (efa_payout_flow_50k scenario) → Journal. Asserts:
- Bot trades during ALL hours (no schedule filter).
- Fewer trades than SurgeBot would have made (< 5 over 24h).
- EFA EoD-trailing floor advances only at session boundary (regression check).
- No hard-flat triggered (the bot never reaches 15:10 CT in a way that forces close).

Commit: `test(integration): NQ Maintenance end-to-end (24/7 schedule + EFA)`.

### T6: Docs + tag

Append NQ Maintenance section to `09-bot-lineup.md`. Document the combine+always incompatibility as a first-class safety property.

Then:
```
git tag plan-20-nq-maintenance-complete
git push origin plan-20-wt --tags  # (or main)
```

Commit: `docs(spec): NQ Maintenance + combine+always incompatibility`.

---

## Verification

```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -x -q
python -m bot.runtime --bots config/bots/ --check  # all 6 bots load (5 enabled by default, 1 disabled)
```

Expected output: summary table with all 6 bots, one marked DISABLED (nq_maintenance), the rest ENABLED.

End state: All 6 user-facing bots from the VSL lineup are deployable. Plan 21 (dashboard + allocator) is the final piece.
