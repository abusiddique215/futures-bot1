# Plan 7 — Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Ship the logging + journaling + alerting layer. After this plan:
- All gate decisions + sim/IB fills + state snapshots persist to SQLite (aiosqlite, WAL)
- JSON-lines logs go to `logs/<date>.jsonl`
- Telegram polling client sends WARN+ alerts (no inbound port — VPS-ban-safe)
- The risk gate's `_Telemetry` Protocol is satisfied by a real `Telemetry` impl

**Architecture:** `bot.journal.Journal` (aiosqlite-backed, WAL mode) writes structured rows. `bot.observability.logger` configures loguru with a JSON serializer. `bot.observability.telegram.TelegramAlerter` posts via `python-telegram-bot` polling mode. `bot.observability.bus.TelemetryBus` is the central fan-out: subscribers (Journal, JSONLogger, Telegram) attach.

**Tech Stack:** New deps: `loguru>=0.7`, `python-telegram-bot>=21.4` (both already in spec 07 Plan 1 deps but not installed — add to pyproject in T1). `aiosqlite>=0.20` already installed by Plan 1? Check; if not, add.

**Scope notes:**
- v1: synchronous Journal writes are FINE (`asyncio.run_in_executor` wrap for backtest sync engine). Plan 9 may add async-native journal.
- Telegram is POLLING mode (no inbound webhook). No web server.
- Backtest doesn't send Telegram alerts (env-conditional).
- For backtest replay: Journal can be in-memory SQLite (`:memory:`).

**Deliverable:**
- `bot.journal.Journal` 6-table schema applied
- BacktestEngine emits all decisions/fills to Journal automatically
- TelemetryBus integration test fans out to Journal + JSONLogger (+ Telegram stub)
- Tag `plan-07-observability-complete`

---

## Scope

Single batch-agent. ~10 tasks. Aim for ~30 new tests.

### Tasks

1. **Add deps + verify** — `loguru`, `python-telegram-bot`, `aiosqlite` (if not installed). Pip install + smoke imports. Commit: `chore(deps): loguru + python-telegram-bot for observability`.

2. **JSON-lines logger config** — `bot/observability/logger.py`. `configure_json_logger(path: Path, level: str = "INFO")`. Uses loguru's serializer. Tests: emit a log + read JSONL + verify schema. Commit: `feat(observability): JSON-lines logger config`.

3. **SQLite Journal schema + migrations** — `bot/journal/schema.py` + `bot/journal/journal.py`. Tables: `orders`, `fills`, `positions`, `risk_decisions`, `equity_snapshots`, `sessions`. Use aiosqlite + WAL mode. `Journal.apply_migrations()` is idempotent. Tests: open in-memory journal, verify schema. Commit: `feat(journal): aiosqlite schema + migrations (6 tables, WAL)`.

4. **`Journal.record_*` methods** — `record_order(order)`, `record_fill(fill)`, `record_position(position)`, `record_risk_decision(decision)`, `record_equity_snapshot(state)`, `record_session_start()`. Each is async. Tests: round-trip a record, query back. Commit: `feat(journal): record_* methods for 6 event types`.

5. **`Journal.query_*` for reconcile** — `get_open_orders()`, `get_open_positions()`, `get_last_equity_snapshot()`, `get_best_day_pnl_so_far()`, `get_net_pnl_so_far()`. The last two satisfy the `JournalProvider` Protocol from Plan 3 — making `Journal` a drop-in real `JournalProvider` for the risk gate's rule 6. Commit: `feat(journal): query helpers satisfying JournalProvider Protocol for rule 6`.

6. **`TelegramAlerter` polling-mode** — `bot/observability/telegram.py`. Uses `python-telegram-bot`'s `Bot` class (POST-only, no Updater/polling for outbound). Method `async send(text, severity)`. Severity filter via config (Plan 1's `TelegramConfig.min_severity`). Tests with mock httpx. Commit: `feat(observability): TelegramAlerter (polling-mode safe)`.

7. **`TelemetryBus` fan-out** — `bot/observability/bus.py`. Pub-sub. Subscribers: `JournalSink`, `JSONLogSink`, `TelegramSink`. Single `alert(kind, **kw)` method matches the `_Telemetry` Protocol from Plan 3. Tests: alert reaches all subscribers. Commit: `feat(observability): TelemetryBus fan-out + sink Protocols`.

8. **Wire `Journal` into `BacktestEngine`** — Engine constructor accepts optional `journal: Journal | None`. If provided, calls `journal.record_*` on each event. For backtest, use in-memory journal by default. Tests: run backtest with journal, assert rows persisted. Commit: `feat(backtest): wire Journal into BacktestEngine`.

9. **Wire `TelemetryBus` into `TopstepRiskGate`** — Replace the inline `_Telemetry` Protocol type with `bot.observability.bus.TelemetryBus`. Gate construction can accept None for tests (fallback to no-op). Tests: gate denials propagate to bus → journal record. Commit: `feat(risk): wire TopstepRiskGate to TelemetryBus`.

10. **Final verify + tag** — ruff + mypy + pytest, tag `plan-07-observability-complete`.

## Out-of-scope

- ❌ Real Telegram bot interactions (mocked in tests)
- ❌ Grafana/Prometheus metrics export
- ❌ Crash-replay debugger
- ❌ Multi-process journal access (single-writer assumed)
- ❌ Automated quarantine-rate alerts (defer to a v2)

## Constraints

- All tests use in-memory SQLite (`:memory:`) or `tmp_path` for files.
- Telegram tests use httpx mocks.
- Async tests via `async def` (no `asyncio.run()`).
- `pip install` may need re-run if loguru / python-telegram-bot weren't installed.
