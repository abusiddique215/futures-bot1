# Plan 22 — Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Close the three documented deferred items from Plans 19-21 + ship the missing operator-facing surfaces (smoke test, ONBOARDING, README refresh). After this plan: the codebase is genuinely production-ready — the operator can flip `enabled: true` on bots without hitting any of the known footguns, and a new contributor can onboard from README → first backtest in under 30 minutes.

**Architecture:** Three workstreams, executed in order:

1. **Policy-aware hard-flat** — `bot.risk.gate._check_hard_flat` becomes policy-driven. Combine policies enforce the 15:10 CT hard-flat (Topstep rule). EFA policies do NOT — funded accounts can trade past 15:10. Closes Plan 20's flagged gap that prevented 24/7 EFA bots from opening positions in the 15:10-17:00 CT window.

2. **Configurable account capacity** — `account_max_mini` becomes a `FleetConfig` field (default 5 for $50K Topstep baseline). CLI flag `--account-max-mini <int>` overrides. `run_fleet` reads from CLI, threads to `FleetAllocator`. Closes Plan 21's hardcoding gap so larger accounts (150K = 15 minis, etc.) work without code edits.

3. **Strategy.teardown() lifecycle hook** — Symmetric to `setup()` added in Plan 21. `FleetRuntime.run()` calls `await strategy.teardown()` on graceful shutdown. `SignalStrategy.teardown()` calls `self.stop()` for clean Discord disconnect. Closes Plan 21's "no graceful teardown" gap so Lux Bot doesn't leak a Discord client on shutdown.

4. **Comprehensive multi-bot smoke test** — Integration test that boots ALL 6 bots (via temporary copy of `config/bots/`), drives synthetic market data for a full trading session, asserts each bot's journal shows expected behavior, asserts dashboard responds, asserts allocator caps multi-bot position. The "does the whole system work end-to-end" test.

5. **`ONBOARDING.md` + README refresh** — README at repo root is currently scaffold-shaped. Refresh to reflect the actual fleet architecture, point at the 6 bots, link to the dashboard, document the 4-rail test ladder, document how to enable a bot.

**Tech Stack:** No new deps. Touches `bot.risk.gate`, `bot.risk.policies`, `bot.runtime.fleet.runtime`, `bot.runtime.cli`, `bot.runtime.main`, `bot.strategy.signal_strategy`, `bot.backtest.strategy` (Protocol).

**Scope notes:**
- Hard-flat behavior change is a SAFETY-CRITICAL change. Existing tests using `combine_intraday` must still see hard-flat enforced (regression-test all Combine paths).
- Account-max-mini change is additive; current behavior (5) becomes the default; no caller is forced to change.
- Teardown is non-mandatory (Protocol method has noop default); only SignalStrategy currently implements it.
- The smoke test runs the WHOLE FLEET (all 6 bots concurrently) — load-bearing integration test for the whole product.

**Deliverable:**
- Policy-aware hard-flat: 24/7 EFA bots can trade past 15:10 CT; Combine bots still flatten.
- `python -m bot.runtime --bots config/bots/ --dashboard --account-max-mini 15` works.
- `await strategy.teardown()` called on every bot during fleet shutdown.
- A single integration test (`tests/integration/test_full_fleet_smoke.py`) boots all 6 bots + dashboard, drives 1 trading day of data, asserts per-bot fills + dashboard response + allocator behavior.
- `ONBOARDING.md` at repo root: 5-minute first-backtest path + 30-minute "how this whole thing works."
- README.md refreshed for the multi-bot world.
- CI green (~990 tests, +20 new).
- Tag `plan-22-production-readiness-complete`.

---

## File structure

- Modify: `src/bot/risk/policies.py` — add `enforces_hard_flat: bool` Protocol attribute
- Modify: `src/bot/risk/combine_drawdown.py` — set `enforces_hard_flat = True`
- Modify: `src/bot/risk/efa_drawdown.py` — set `enforces_hard_flat = False` on both classes
- Modify: `src/bot/risk/gate.py` — `_check_hard_flat` consults `policy.enforces_hard_flat`
- Modify: `src/bot/runtime/fleet/allocator.py` — accept `account_max_mini` constructor arg (already does; verify)
- Modify: `src/bot/runtime/main.py` — thread `account_max_mini` from CLI to allocator
- Modify: `src/bot/runtime/cli.py` — add `--account-max-mini` arg, default 5
- Modify: `src/bot/backtest/strategy.py` — add optional `teardown()` to Strategy Protocol
- Modify: `src/bot/runtime/fleet/runtime.py` — call `await strategy.teardown()` after each loop
- Modify: `src/bot/strategy/signal_strategy.py` — implement `teardown()` calling `self.stop()`
- Create: `tests/integration/test_full_fleet_smoke.py`
- Create: `tests/test_risk_gate_hard_flat_policy_aware.py`
- Create: `tests/runtime/fleet/test_account_max_mini_cli.py`
- Create: `tests/test_strategy_teardown.py`
- Create: `ONBOARDING.md` at repo root
- Modify: `README.md` at repo root

---

## Tasks

### T1: Policy-aware hard-flat

`src/bot/risk/policies.py`: add `enforces_hard_flat: bool` attribute to the `DrawdownPolicy` Protocol (Protocol attributes are class-level; document the contract).

`src/bot/risk/combine_drawdown.py`: `CombineIntradayDrawdown.enforces_hard_flat: ClassVar[bool] = True`.

`src/bot/risk/efa_drawdown.py`: both classes get `enforces_hard_flat: ClassVar[bool] = False`. Document the why — EFA accounts have no daily hard-flat, only EoD trailing.

`src/bot/risk/gate.py`: `_check_hard_flat` reads `self.policy.enforces_hard_flat`; if False, returns "approved" regardless of time. If True, current behavior applies.

Tests (`tests/test_risk_gate_hard_flat_policy_aware.py`):
- Combine policy + 15:30 CT bar + new BUY → DENIED (HARD_FLAT_CLOCK)
- EFA Standard + 15:30 CT bar + new BUY → APPROVED
- EFA Consistency + 15:30 CT + new BUY → APPROVED
- All existing Combine hard-flat tests still pass (regression)

Commit: `feat(risk): policy-aware hard-flat — EFA bots can trade past 15:10 CT`.

### T2: Configurable account-max-mini via CLI

`src/bot/runtime/cli.py`: add `--account-max-mini` argparse arg, default `5`, integer.

`src/bot/runtime/main.py`: in `run_fleet`, read `args.account_max_mini` and pass to `FleetAllocator(account_max_mini=...)`.

Tests (`tests/runtime/fleet/test_account_max_mini_cli.py`):
- `python -m bot.runtime --bots config/bots/ --check` defaults to 5
- `--account-max-mini 15` propagates to allocator
- Invalid (0, negative, non-int) → argparse error

Commit: `feat(cli): --account-max-mini flag — supports non-50K Topstep accounts`.

### T3: Strategy.teardown() lifecycle hook

`src/bot/backtest/strategy.py`: extend Strategy Protocol with `async teardown(self) -> None` (optional via `hasattr` check in runtime, same pattern as `setup`).

`src/bot/runtime/fleet/runtime.py`: after each bot's LiveTradingLoop completes (whether via normal completion, exception, or fleet shutdown), call `if hasattr(strategy, 'teardown'): await strategy.teardown()`. Wrap in try/except so a teardown failure on one bot doesn't propagate.

`src/bot/strategy/signal_strategy.py`: implement `async teardown(self) -> None`: calls `await self.stop()` (the existing graceful Discord-client shutdown).

Tests (`tests/test_strategy_teardown.py`):
- FleetRuntime calls teardown() on a strategy that has the method
- Strategy without teardown() is skipped without error
- Teardown raising an exception does NOT kill the fleet (logged + swallowed)
- SignalStrategy.teardown() calls stop() (Discord pump task cancelled)

Commit: `feat(strategy): teardown() lifecycle hook — graceful Discord disconnect`.

### T4: Full-fleet smoke test

`tests/integration/test_full_fleet_smoke.py`. Single asynchronous test:
1. Setup: copy `config/bots/` to a tmp dir (so the test doesn't depend on which bots ship `enabled: true`); flip every bot to `enabled: true` in the copy; provide `LUX_BOT_FIXTURE_PATH` pointing at a tmp JSON of 1 fake signal.
2. Boot FleetRuntime with all 6 bots + SimExecutionClient + dashboard on ephemeral port.
3. Drive 30 minutes of synthetic bars (different patterns per market: NQ uptrend, GC ranging, ES ranging — 1-min bars).
4. Assert: each bot's per-bot journal has 0 errors. Dashboard `/` returns 200 + all 6 bot names. `/healthz` returns 200. At least 2 bots produced a fill (the test bar patterns trigger ORB + mean-reversion).
5. Trigger graceful shutdown. Assert: all bots' teardown ran. Dashboard stopped cleanly.

This is THE smoke test — if it passes, the whole system works end-to-end.

Commit: `test(integration): full-fleet smoke — all 6 bots + dashboard + 30 min synthetic`.

### T5: ONBOARDING.md

`ONBOARDING.md` at repo root. Structure:
- **TL;DR (5 minutes):** clone, `pip install -e .`, run a backtest, see a proof bundle.
- **What this is:** 1-paragraph product summary (VSL clone, 6 bots, $0-test-then-pay ladder).
- **Architecture:** 1-paragraph + 1 ASCII diagram (Bar stream → Strategy → RiskGate → Allocator → Broker → Journal).
- **The bot lineup:** 6-row table summarizing each bot (name, market, strategy_id, risk_policy, config path).
- **Running a backtest:** the simplest path. `python -m bot.backtest --bot surgebot_nq --start ... --end ...` → see `state/proof/...`.
- **The 4-rail test ladder:** explain backtest → IB Paper → TopstepX Sim → TopstepX Live, with the command for each rail.
- **Enabling a bot for live:** the explicit 5-step protocol with safety checks.
- **Where things live:** pointer map to `config/bots/`, `src/bot/`, `docs/superpowers/specs/`.

Commit: `docs: ONBOARDING.md — 5-minute first-backtest + full operator guide`.

### T6: README.md refresh

Current README is from Plan 1's foundation phase — pre-multi-bot. Refresh:
- Replace single-strategy intro with the 6-bot fleet framing.
- Update the "Running it" section to reference `python -m bot.runtime --bots config/bots/ --dashboard`.
- Add the test ladder section.
- Link to ONBOARDING.md for the deep dive.
- Update commit/tag count + test count (mention current state: 22 tags, 970+ tests).

Commit: `docs(readme): refresh for multi-bot fleet + dashboard + ONBOARDING link`.

### T7: Tag + push

```
git tag plan-22-production-readiness-complete
git push origin main --tags
```

Update `docs/superpowers/plans/INDEX.md` (if exists; otherwise skip).

Commit: `docs: plan-22-complete tag + index update`.

---

## Verification

```bash
cd ~/futures-bot1
source ~/.venvs/topstep-bot/bin/activate
ruff check . && mypy --strict src/ && pytest -q
python -m bot.runtime --bots config/bots/ --dashboard --check --account-max-mini 15
```

Expected:
- CI green: ~990 tests.
- `--check` exits 0; stdout includes "account_max_mini=15".
- Tag `plan-22-production-readiness-complete` pushed.

End state: every documented deferred item from Plans 19-21 is closed. The codebase is honestly "production ready" — pending user authorization to point at real Topstep credentials.
