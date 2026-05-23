# Plan 9 — Mac Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Ship the deployment layer that ties everything together. After this plan:
- `python -m bot.runtime` starts the bot end-to-end (load config + secrets + connect broker + start event loop)
- macOS LaunchAgent .plist auto-starts on login; auto-restarts on unclean exit
- Broker-truth reconcile on every startup REFUSES to start if broker state ≠ journal state
- Hostname VPS-guard fail-closed for `env=live`
- iCloud-Drive warning hard-coded (move tree to local disk before live install)

**Architecture:** `bot.runtime.main()` orchestrates the startup sequence per spec 07 §3.6 (8 steps): load_config → load_secrets → assert_host_allowed → open_journal → connect_broker → snapshot broker+journal → reconcile → hydrate runtime → start event loop. Each step is a separate function for testability. The runtime then drives the live event loop: feed bars to Strategy → emit intents → gate.approve_or_deny → execute on broker → journal everything.

**Tech Stack:** Adds `python-dotenv>=1.0` for .env loading. Everything else already present.

**Spec patches from `pre-plan1-verification.md`** (apply inline here):
- VPS/VPN ban citation: use article 8680268, NOT 10305426. Update startup docstring + telemetry alert reason text.
- Topstep dual pricing path: surface both options ($49+$149 vs $95+$0) in `runtime.main()` startup banner.

**Scope notes:**
- iCloud-on-iCloud-tree check: emit WARN at startup if `Path(__file__).resolve()` includes `Mobile Documents`. Don't block — operator decides.
- LaunchAgent .plist is templated; install instructions in `deploy/README.md`.
- Heartbeat file is updated every 30s by the event loop (Docker HEALTHCHECK reads it).

**Deliverable:**
- `python -m bot.runtime --config config/bot.example.yml` runs end-to-end against a synthetic broker + in-memory journal (the smoke test).
- LaunchAgent .plist + install script + uninstall script
- `bot/runtime.py` 8-step contract verified by integration test
- Tag `plan-09-mac-deploy-complete`

---

## Scope: Single batch-agent. ~10 tasks.

### Tasks

1. **Add `python-dotenv` dep** + verify. Commit: `chore(deps): python-dotenv for .env loading`.

2. **`load_secrets()` helper** — `src/bot/runtime/secrets.py`. Reads `.env` via `python-dotenv`, validates required env vars per `cfg.broker`. Returns frozen `SecretsDict` (no plaintext fields by accident). Tests: missing var raises, valid env passes. Commit: `feat(runtime): load_secrets with per-broker required-var validation`.

3. **`assert_host_allowed()` + hostname whitelist** — `src/bot/runtime/host_guard.py`. For `env=live`: assert `socket.gethostname() ∈ cfg.live_hostnames`. Else: skip (paper/backtest unrestricted). Tests: live + allowed passes, live + denied raises, paper skips check. Citation updated to article 8680268. Commit: `feat(runtime): assert_host_allowed hostname guard (Topstep VPS ban article 8680268)`.

4. **iCloud-tree warning** — `src/bot/runtime/icloud_check.py`. At startup, warn (via telemetry) if `Path.cwd()` contains "Mobile Documents". Don't block. Test: synthesize an iCloud-shaped path, verify warning emitted. Commit: `feat(runtime): iCloud-tree startup warning (SQLite WAL + LaunchAgent unsafe on iCloud)`.

5. **`Reconcile` contract** — `src/bot/runtime/reconcile.py`. Already partially exists in spec 07 §4.2. Implement: `reconcile(broker_state: BrokerState, journal_state: JournalState) -> ReconcileResult`. Symmetric diff of positions + open orders. `BrokerState` and `JournalState` are dataclasses with `positions: dict[str, int]` + `open_orders: dict[str, dict]` + `account_equity: float`. `ReconcileResult.ok: bool` + `.position_diff: dict[str, tuple[broker_qty, journal_qty]]` + `.order_diff: dict[client_order_id, tuple[broker_dict|None, journal_dict|None]]`. Tests: clean, phantom-position mismatch, orphan-journal-order mismatch. Commit: `feat(runtime): reconcile (broker truth vs journal — refuse start on mismatch)`.

6. **`hydrate_runtime()` builder** — `src/bot/runtime/hydrate.py`. Constructs the live `RuntimeState` from a clean reconcile result: position dict from broker, day_pnl from broker.account_summary, high_water_equity from journal's last equity_snapshot. Tests with mocks. Commit: `feat(runtime): hydrate_runtime (state composition from broker + journal)`.

7. **`bot.runtime.main()` orchestrator** — `src/bot/runtime/main.py`. The 8-step contract:
   1. `cfg = load_config(args.config)`
   2. `secrets = load_secrets(cfg)` — exit 3 on missing
   3. `assert_host_allowed(cfg)` — exit 4 on mismatch
   4. `journal = await open_journal(cfg.journal_path)` — `:memory:` in dev/backtest
   5. `broker = await connect_broker(cfg, secrets)` — sim / ib_paper / topstepx per cfg.broker
   6. `bs = await snapshot_broker(broker); js = await snapshot_journal(journal)`
   7. `rr = reconcile(bs, js)`; if `not rr.ok and cfg.halt_on_journal_desync`: log CRITICAL + exit 5
   8. `runtime = hydrate_runtime(rr, bs, js, cfg, secrets, broker, journal)` + `await run_event_loop(runtime)`
   Wire telemetry. Tests with mocks for each exit path + happy path. Commit: `feat(runtime): main orchestrator (8-step startup contract)`.

8. **CLI entry point `python -m bot.runtime`** — `src/bot/runtime/__main__.py` + `cli.py`. argparse: `--config PATH`, `--check` (exit after reconcile, don't start event loop — useful for smoke tests). Tests: `--help` succeeds, `--check` exits 0 with synthetic config. Commit: `feat(runtime): python -m bot.runtime CLI`.

9. **macOS LaunchAgent .plist + scripts** — `deploy/com.user.topstepbot.plist` + `deploy/install.sh` + `deploy/uninstall.sh` + `deploy/check_heartbeat.sh` + `deploy/README.md`. LaunchAgent runs `docker compose up` against the project's docker-compose.yml. KeepAlive with `SuccessfulExit=false`. Heartbeat monitor as a second LaunchAgent every 60s. Tests: shellcheck-style validation that scripts are well-formed (no actual install in CI). Commit: `feat(deploy): macOS LaunchAgent .plist + install/uninstall + heartbeat scripts`.

10. **Final verify + tag** — ruff + mypy + pytest + end-to-end smoke run (`python -m bot.runtime --config config/bot.example.yml --check`). Tag `plan-09-mac-deploy-complete`.

## Out-of-scope

- ❌ Dockerfile / docker-compose actually invoked in CI (templated only; operator runs `docker compose up` manually)
- ❌ Encrypted secrets backup (`age` integration) — deferred to v2
- ❌ Web dashboard
- ❌ Clock-skew detection vs broker server time (spec 07 §3.7 — deferred)
- ❌ Programmatic LaunchAgent management — operator runs install.sh manually

## Constraints

- Each task one commit.
- ruff + mypy strict clean after each.
- `from __future__ import annotations`, `from datetime import UTC` everywhere.
- All async, no `asyncio.run()` in tests.
- Reconcile + hydrate + main orchestrator MUST be 100% testable with mocks.
- The CLI's `--check` mode is the load-bearing smoke test for end-to-end integration.

## Test counts target

405 + ~30 = ~435.

## Notes for executor

- The existing `bot.config.BotConfig` from Plan 1 already has the schema. Plan 9 just adds `live_hostnames: list[str] = []` field if not already there.
- The Journal Plan 7 shipped `query_*` helpers — use them in `snapshot_journal`.
- The TopstepXExecutionClient's hostname guard (Plan 8 T3) is DUPLICATIVE of Plan 9's `assert_host_allowed`. The Plan 8 guard fires at broker-connect time; Plan 9 guard fires at runtime startup. Both layers are intentional (defense in depth). Don't refactor away.
