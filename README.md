# Topstep Futures Trading Bot Fleet

Python automated futures trading for the Topstep prop firm — a fleet of six independent bots running concurrently against a single Topstep account, with policy-aware risk gating, a cross-bot account-cap allocator, and a local read-only dashboard.

The product is the fleet: SurgeBot (NQ ORB), PropBot (NQ trend), Lux Bot (external Discord signals), NQ Maintenance (24/7 mean reversion), Gold Bot (GC mean reversion), and ES Scalper (ES mean reversion). Each bot has its own strategy, risk policy, and schedule. The runtime runs all six in one `asyncio.gather`, exposes a side-car dashboard, and writes per-bot SQLite journals for end-of-day reconcile.

## Quick start

```bash
# Setup
python3.13 -m venv ~/.venvs/topstep-bot
source ~/.venvs/topstep-bot/bin/activate
pip install -e ".[dev]"

# Smoke-check the fleet without a broker
python -m bot.runtime --bots config/bots/ --check

# Run the suite (~990 tests)
pytest -q

# Boot the fleet with the dashboard (sim broker — no Topstep deps)
python -m bot.runtime --bots config/bots/ --dashboard
```

The dashboard binds to `127.0.0.1:8765`. Override with `--dashboard-port 9090`. Larger accounts override the fleet-wide position cap with `--account-max-mini 15` (default 5 = Topstep $50K Combine; $100K = 10, $150K = 15).

## The 4-rail test ladder

Strategies promote up the ladder one rail at a time. Each rail's proof bundle is the prerequisite for the next.

1. **Backtest** — `python -m bot.backtest --bot <name> --start <date> --end <date> --data-fixture <csv>`. Historical CSV bars + `SimExecutionClient`. Zero cost, zero live deps.
2. **IB Paper** — `python -m bot.runtime --config config/<bot>.yml`. Live bars + paper fills via Interactive Brokers Gateway.
3. **TopstepX Sim** — `python -m bot.runtime --bots config/bots/`. Real TopstepX account in simulated mode. Full auth + reconciliation path.
4. **TopstepX Live** — same command, with `enabled: true` flipped on the relevant YAMLs and the operator's authorization. Real money.

See [`ONBOARDING.md`](./ONBOARDING.md) for the full operator playbook, including the 5-step protocol for promoting a bot to live and an architecture diagram.

## What's where

- `src/bot/` — runtime source.
- `config/bots/*.yml` — the six bot specs.
- `tests/` — ~990 tests (unit + integration; the full-fleet smoke test is `tests/integration/test_full_fleet_smoke.py`).
- `docs/superpowers/specs/2026-05-22-futures-bot/` — the architecture spec (11 documents).
- `docs/superpowers/plans/` — 22 chronological implementation plans.

## Project state (2026-05-24)

22 implementation plans landed and tagged. 992 tests passing. Six bots configured (one currently `enabled: true` by default — PropBot, the EFA-account trend bot; the rest ship disabled and require explicit operator opt-in via `enabled: true`). Hard-flat behaviour is policy-driven (Combine enforces 15:10 CT; EFA does not). The cross-bot `FleetAllocator` caps account-wide exposure; the `--account-max-mini` CLI flag tunes it per Topstep account size.

This codebase is genuinely production-ready pending the operator's TopstepX credentials and live authorization.

See [`CLAUDE.md`](./CLAUDE.md) for repo behavioural guidelines (assistant + contributor).
