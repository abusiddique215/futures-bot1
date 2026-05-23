# 06 — Observability

**Project**: Topstep Futures Trading Bot
**Date**: 2026-05-22
**Status**: Spec — research/design only, no code execution
**Owner**: abu.siddique215@gmail.com
**Parent**: [`00-architecture-overview.md`](./00-architecture-overview.md)

---

## 1. Purpose

Define the three observability surfaces the bot uses to (a) make every decision auditable after the fact, (b) detect divergence between the bot's internal state and broker truth, and (c) notify a human when — and *only* when — human awareness or intervention is actually required.

Observability for this bot is **non-negotiable infrastructure**, not a nice-to-have:

- **Forensics**: when the bot does something surprising on a Combine account, we must be able to reconstruct *exactly* what it saw, what it decided, and why — down to the tick. A Combine costs $198 to retry; an unexplained loss is worse than the loss itself because it kills our ability to fix the bug.
- **Broker reconciliation** (per [00 §7 item 6](./00-architecture-overview.md#7-critical-defensive-items-every-sibling-spec-must-respect)): on every restart, the bot reconciles its journal against broker truth and **refuses to start on mismatch**. This is impossible without a durable trade journal.
- **Alert hygiene**: an alert stream that cries wolf gets muted. Muted alerts are worse than no alerts. We design for *signal*, not for *volume*.

This spec is the contract every other component honors when it emits events: what format, where it goes, who sees it.

---

## 2. Inherited decisions

From [`00-architecture-overview.md`](./00-architecture-overview.md):

| Ref | Decision | Implication for this spec |
|-----|----------|---------------------------|
| [D12](./00-architecture-overview.md#2-locked-decisions-with-reasoning) | Storage: **SQLite** for trade journal + audit; **broker is source of truth on restart** | We design the journal schema and reconciliation contract here. No event sourcing. |
| [D16](./00-architecture-overview.md#2-locked-decisions-with-reasoning) | Observability stack: **JSON-lines structured logs + SQLite trade journal + Telegram alerts** | All three surfaces are in scope for this doc. No external dashboards (Grafana, Datadog) in v1. |
| [§7 item 6](./00-architecture-overview.md#7-critical-defensive-items-every-sibling-spec-must-respect) | Broker truth on restart: query broker, reconcile vs journal, refuse start on mismatch | The journal MUST be durable, queryable, and complete enough that reconciliation is a real check, not theater. |
| [§7 item 5](./00-architecture-overview.md#7-critical-defensive-items-every-sibling-spec-must-respect) | VPS / VPN ban for live | Telegram must run in **polling** mode — no inbound webhook to the user's Mac. |

---

## 3. Design

### 3.1 Three observability surfaces

The bot emits to three independent surfaces. Each has a distinct purpose, retention, and failure mode.

| Surface | Purpose | Storage | Retention | Failure mode |
|---------|---------|---------|-----------|--------------|
| **Structured logs (JSON-lines)** | Forensics, offline replay, debugging | `logs/YYYY-MM-DD.jsonl` on local disk | 90 days local, rotated daily | If disk full → log to stderr, raise CRITICAL alert. Strategy loop continues. |
| **SQLite trade journal** | Durable record of orders / fills / positions / rule decisions / equity. Source for restart reconciliation. | `data/journal.sqlite3` | Indefinite (small footprint) | If write fails → CRITICAL alert + force-flatten + halt. Journal write failure is unrecoverable. |
| **Telegram alerts** | Real-time human notification | Telegram cloud | Telegram-side history | If Telegram unreachable → log a `telegram_delivery_failed` event; do NOT block trading. |

**Crucial invariant**: the three surfaces are **independent**. A Telegram outage does not stop logging. A log-disk outage does not stop journal writes. A journal write failure DOES halt trading, because reconciliation guarantees are gone.

### 3.2 Log schema (JSON-lines)

Every line in `logs/YYYY-MM-DD.jsonl` is a single JSON object on one line. No multi-line records. UTF-8, LF line endings.

**Canonical example:**

```json
{"ts":"2026-05-22T14:23:01.234Z","lvl":"INFO","comp":"strategy","evt":"orb_high_set","payload":{"symbol":"MNQ","level":21450.25}}
```

**Field contract:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ts` | string (ISO 8601, UTC, millisecond precision, `Z` suffix) | yes | Event timestamp from the bot's monotonic clock, normalized to UTC. |
| `lvl` | enum: `DEBUG` / `INFO` / `WARN` / `ERROR` / `CRITICAL` | yes | Severity. |
| `comp` | enum (see §3.3) | yes | Component that emitted the line. |
| `evt` | string (snake_case slug) | yes | Event type from the fixed taxonomy (§3.4). |
| `payload` | object | yes (may be `{}`) | Event-specific data. Schema-free at the file level; per-`evt` shape documented in §3.4. |
| `trace_id` | string (UUIDv4) | optional | Set when one logical action (e.g. one `OrderIntent`) spans multiple components. Used to stitch a trace across `strategy → risk → executor_*`. |

**Style rules:**

- All times UTC in logs (not Chicago, not naive). Telegram and journal may display Chicago for human-readability, but the source-of-truth field is UTC.
- Floats use up to 4 decimal places (sufficient for MNQ tick resolution of 0.25).
- `payload` keys are snake_case.
- Never log secrets (broker tokens, Telegram bot token, account IDs). A redaction filter wraps the logger.

### 3.3 Component slugs (enumerated, fixed)

The `comp` field is closed-set. Adding a new value requires a spec amendment.

| Slug | Owner |
|------|-------|
| `strategy` | `03-strategies.md` — Strategy subclass, ORB signal generation |
| `risk` | `04-risk-engine.md` — TopstepRiskGate, phantom MLL, news throttle |
| `executor_ib` | `02-execution-clients.md` — IB paper rail |
| `executor_topstepx` | `02-execution-clients.md` — TopstepX live rail |
| `data` | `01-data-pipeline.md` — bar/tick ingestion, contract roll |
| `clock` | Force-flatten scheduler, session boundary alerts |
| `journal` | This spec — SQLite writes, reconciliation |
| `alert` | This spec — Telegram delivery |
| `bootstrap` | `07-config-and-deploy.md` — startup, config load, restart reconciliation |

### 3.4 Event taxonomy (fixed slugs)

`evt` is closed-set per component. Listed by lifecycle stage. `DEBUG`-only events are sampled at 1/100 in steady state (configurable).

**Data ingestion** (`comp=data`)
| `evt` | Default `lvl` | Notes |
|-------|---------------|-------|
| `bar_received` | DEBUG | High volume; sampled. |
| `tick_received` | DEBUG | Very high volume; sampled. |

**Strategy / Risk decisions** (`comp=strategy` or `comp=risk`)
| `evt` | Default `lvl` | Notes |
|-------|---------------|-------|
| `order_intent_emitted` | INFO | Strategy emits. Payload includes intent dict. |
| `order_intent_approved` | INFO | Risk gate pass. |
| `order_intent_denied` | WARN | Risk gate reject. **Payload MUST include `rule` field** (which Topstep rule fired). |

**Execution** (`comp=executor_ib` or `comp=executor_topstepx`)
| `evt` | Default `lvl` | Notes |
|-------|---------------|-------|
| `order_placed` | INFO | Broker accepted. |
| `order_filled` | INFO | Full or partial fill. |
| `order_rejected` | ERROR | Broker rejected. |
| `order_canceled` | INFO | Cancel confirmed. |

**Position lifecycle** (`comp=executor_*`)
| `evt` | Default `lvl` | Notes |
|-------|---------------|-------|
| `position_opened` | INFO | First fill on flat book. |
| `position_closed` | INFO | Net flat after fill. |
| `position_updated` | INFO | Size or avg-price change. |

**Phantom MLL state machine** (`comp=risk`)
| `evt` | Default `lvl` | Notes |
|-------|---------------|-------|
| `phantom_mll_update` | DEBUG | Every tick — sampled or aggregated. |
| `phantom_mll_locked` | INFO | MLL trail anchor moved up. |
| `phantom_mll_triggered` | CRITICAL | Distance to MLL ≤ safety buffer. |

**Time-based controls** (`comp=clock` or `comp=risk`)
| `evt` | Default `lvl` | Notes |
|-------|---------------|-------|
| `flat_by_warning` | WARN | 14:00 CT — 70 min before hard flat. |
| `flat_by_trigger` | CRITICAL | 15:10 CT — force flatten executed. |
| `news_window_entered` | INFO | Pre-FOMC/NFP/CPI throttle on. |
| `news_window_exited` | INFO | Throttle off. |

**Broker connectivity** (`comp=executor_*`)
| `evt` | Default `lvl` | Notes |
|-------|---------------|-------|
| `broker_connect` | INFO | Initial connect / reconnect success. |
| `broker_disconnect` | WARN | Connection lost. CRITICAL if duration > 60s (see §3.6). |
| `broker_reconnect_attempt` | INFO | Each attempt. |
| `broker_reconnect_succeeded` | INFO | Recovery. |

**Journal & startup** (`comp=journal` or `comp=bootstrap`)
| `evt` | Default `lvl` | Notes |
|-------|---------------|-------|
| `journal_reconcile_pass` | INFO | Startup reconciliation ok. |
| `journal_reconcile_mismatch_HALT` | CRITICAL | Per [00 §7 item 6](./00-architecture-overview.md#7-critical-defensive-items-every-sibling-spec-must-respect) — bot refuses to start. |
| `equity_snapshot` | INFO | Periodic; see §3.7 cadence. |

### 3.5 SQLite trade journal schema

Database file: `data/journal.sqlite3`. WAL mode (`PRAGMA journal_mode=WAL`) for concurrent reader (the replay tool) while the bot writes. `synchronous=NORMAL` is acceptable; we accept potential loss of the last fsync window because broker truth wins on restart anyway.

```sql
CREATE TABLE orders (
    client_order_id     TEXT PRIMARY KEY,
    broker_order_id     TEXT,
    symbol              TEXT NOT NULL,
    side                TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    qty                 INTEGER NOT NULL,
    type                TEXT NOT NULL,        -- MKT, LMT, STP, STP_LMT, BRACKET
    status              TEXT NOT NULL,        -- PENDING, PLACED, FILLED, PARTIAL, REJECTED, CANCELED
    ts_emitted          TEXT NOT NULL,        -- UTC ISO 8601
    ts_filled           TEXT,
    avg_fill_price      REAL
);
CREATE INDEX idx_orders_ts_emitted ON orders(ts_emitted);
CREATE INDEX idx_orders_broker_id  ON orders(broker_order_id);

CREATE TABLE fills (
    fill_id             TEXT PRIMARY KEY,     -- broker-provided or synthesized
    client_order_id     TEXT NOT NULL REFERENCES orders(client_order_id),
    qty                 INTEGER NOT NULL,
    price               REAL NOT NULL,
    ts                  TEXT NOT NULL
);
CREATE INDEX idx_fills_ts                ON fills(ts);
CREATE INDEX idx_fills_client_order_id   ON fills(client_order_id);

CREATE TABLE positions (
    snapshot_ts         TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    signed_qty          INTEGER NOT NULL,     -- positive long, negative short
    PRIMARY KEY (snapshot_ts, symbol)
);
CREATE INDEX idx_positions_ts ON positions(snapshot_ts);

CREATE TABLE risk_decisions (
    ts                  TEXT NOT NULL,
    intent_json         TEXT NOT NULL,        -- serialized OrderIntent
    decision            TEXT NOT NULL CHECK (decision IN ('APPROVED','DENIED')),
    rule                TEXT,                 -- which rule fired on DENIED
    state_snapshot_json TEXT NOT NULL         -- equity, MLL distance, position, etc.
);
CREATE INDEX idx_risk_decisions_ts ON risk_decisions(ts);

CREATE TABLE equity_snapshots (
    ts                  TEXT PRIMARY KEY,
    equity              REAL NOT NULL,
    realized_today      REAL NOT NULL,
    unrealized          REAL NOT NULL,
    high_water          REAL NOT NULL
);

CREATE TABLE account_state (
    ts                  TEXT PRIMARY KEY,
    equity              REAL NOT NULL,
    dll_remaining       REAL NOT NULL,        -- $1000 - realized_today, floored at 0
    mll_distance        REAL NOT NULL,        -- dollars between equity and trailing MLL
    is_locked           INTEGER NOT NULL      -- 0/1; true if account is rule-locked
);
```

**Index policy**: every `ts` column is indexed. Forensic queries are always time-bounded; without these indexes, a full-table scan on a year of fills would dominate replay time.

**Write discipline**:

- Orders, fills, risk decisions: written **synchronously** on emit. These are the reconciliation primitives — losing one means startup-halt next restart.
- Equity / account snapshots: batched (write every 5s) — losing the last 5s is acceptable.
- All writes go through `TradeJournal` (§4). No component touches SQLite directly.

### 3.6 Telegram alert taxonomy

Three categories of alert, plus an explicit OFF list. Categories map to throttling policy, not to a `lvl` field.

| Category | Examples | Throttle policy |
|----------|----------|-----------------|
| **CRITICAL** | `phantom_mll_triggered`, `journal_reconcile_mismatch_HALT`, `broker_disconnect` lasting > 60 s, `flat_by_trigger` (force-flatten executed), order_rejected on a flatten attempt | **Immediate, never throttled.** Every event delivered. |
| **WARN** | `order_intent_denied`, `flat_by_warning` (14:00 CT), repeated `order_rejected` for non-flatten orders, repeated `broker_reconnect_attempt` | **Rate-limited: max 1 message per minute per category-key.** Dedup key = `(category, evt, minute_bucket)`. |
| **INFO** | `order_filled`, `position_closed`, end-of-day P&L summary, session-start banner | **Digest-style.** Batched hourly during session + a single end-of-day summary at 15:15 CT. |
| **OFF** | `bar_received`, `tick_received`, `equity_snapshot`, `phantom_mll_update` (the non-triggered variant) | Never sent to Telegram. Logged + journaled only. |

**Delivery details:**

- **Mode**: `python-telegram-bot` (v22+) in **polling mode**. The bot pulls from Telegram; Telegram never pushes to us. This sidesteps the [VPS/VPN ban](./00-architecture-overview.md#7-critical-defensive-items-every-sibling-spec-must-respect) (no inbound port exposed) and the home-NAT/firewall problem (we initiate every connection).
- **Credentials**: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in `.env` (see `07-config-and-deploy.md`). Never logged.
- **Queue**: single in-process `asyncio.Queue`. Producer side is non-blocking; if the queue is full (>1000 messages), oldest **INFO** messages are dropped first, then **WARN**. **CRITICAL** is never dropped — if the queue is full of CRITICAL, that itself triggers a force-flatten because something is deeply wrong.
- **Dedup hash**: `sha256(f"{category}|{evt}|{minute_bucket}|{symbol or ''}")`. Cached in a 60-second TTL set.
- **Delivery failure**: log `telegram_delivery_failed`, retry with exponential backoff (1s, 2s, 4s, 8s, 16s, then drop). Telegram outage MUST NOT block the strategy loop.

**Message format example** (CRITICAL):

```
🚨 CRITICAL [phantom_mll_triggered]
2026-05-22 09:23:01 CT
Symbol: MNQ
Equity: $48,734.50
MLL distance: $12.00
Action: force_flatten initiated
```

INFO digests are concatenated tables, one row per `order_filled` / `position_closed`.

### 3.7 Equity-curve snapshot cadence

- **Every 5 minutes** during the trading window: 09:30 ET (CME equity-index session open) through 15:10 CT (hard flat-by).
- **Once at session close** (15:10 CT, after flatten confirms).
- **Once at startup** (immediately after reconciliation passes).
- **Once at shutdown** (graceful stop signal).

Snapshots write to `equity_snapshots` *and* emit an `equity_snapshot` log line. On big-move days we may want sub-minute cadence — see §6 open questions.

### 3.8 Forensic replay path

Given any session date, we can reconstruct the full decision timeline:

```
python -m bot.replay --date=2026-05-22
```

The CLI queries `orders`, `fills`, `risk_decisions`, `equity_snapshots`, and reads `logs/2026-05-22.jsonl`, then renders a chronological timeline to stdout. Each row shows: time, component, event, key payload fields.

**v1 is CLI text output.** v2 will render an HTML timeline with embedded equity-curve chart. We are not building a web dashboard in v1 — logs + Telegram + CLI replay are sufficient for a solo operator.

### 3.9 Performance budget

The strategy loop runs at tick frequency (potentially > 100 events/sec for NQ during volatile open). Logging MUST NOT block it.

| Constraint | Target |
|------------|--------|
| Synchronous overhead per log emit (strategy thread) | < 50 µs (enqueue only) |
| Journal write latency (synchronous orders/fills path) | < 5 ms per write |
| Telegram delivery latency (best-effort) | < 2 s end-to-end |
| Log file flush interval | Every 100 events or 250 ms, whichever first |

Implementation: an async writer thread drains a `queue.SimpleQueue` to the JSONL file. The strategy thread only enqueues. The journal uses a separate connection on its own thread with synchronous writes for orders/fills (loss-intolerant) and batched writes for snapshots (loss-tolerant).

---

## 4. Implementation sketch

Python pseudocode — not production code. Real implementation lives under `bot/observability/`.

```python
# bot/observability/logger.py
class StructuredLogger:
    def __init__(self, log_dir: Path, component: str):
        self.component = component
        self._queue = queue.SimpleQueue()
        self._writer = threading.Thread(target=self._drain, daemon=True)
        self._writer.start()

    def emit(self, lvl: str, evt: str, payload: dict, trace_id: str | None = None) -> None:
        line = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "lvl": lvl,
            "comp": self.component,
            "evt": evt,
            "payload": payload,
        }
        if trace_id:
            line["trace_id"] = trace_id
        self._queue.put(line)

    def _drain(self):
        # Writes to logs/YYYY-MM-DD.jsonl, flushes every 100 events or 250 ms.
        ...
```

```python
# bot/observability/journal.py
# Library choice: aiosqlite (matches 07-config-and-deploy Dockerfile dep).
# Async I/O integrates cleanly with the Nautilus async event loop. The strategy
# thread does NOT call these methods directly — observability has its own
# task/loop drained from a queue (see §3.9 performance budget).
import aiosqlite

class TradeJournal:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path, isolation_level=None)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()

    async def record_order(self, order: Order) -> None:
        # Synchronous-from-caller's-perspective write; raise on failure.
        # (Synchronous in the sense of "must complete before returning".)
        ...

    async def record_fill(self, fill: Fill) -> None: ...

    async def record_risk_decision(self, intent: OrderIntent, decision: str,
                                   rule: str | None, state: dict) -> None: ...

    async def record_equity_snapshot(self, snap: EquitySnapshot) -> None:
        # Batched; flushed every 5 s.
        ...

    async def reconcile_against_broker(self,
                                       broker_positions: list[Position],
                                       broker_open_orders: list[Order]) -> bool:
        """Returns True on match. False triggers HALT in bootstrap."""
        journal_pos = await self._latest_positions()
        journal_open = await self._open_orders()
        return (sorted(broker_positions) == sorted(journal_pos)
                and sorted(broker_open_orders) == sorted(journal_open))
```

```python
# bot/observability/alerter.py
class TelegramAlerter:
    def __init__(self, token: str, chat_id: str):
        self._bot = Bot(token)
        self._chat_id = chat_id
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._dedup: dict[str, float] = {}  # hash → expiry epoch

    async def alert(self, category: str, evt: str, message: str,
                    symbol: str | None = None) -> None:
        if category == "CRITICAL":
            await self._send_now(message)  # never throttled
            return
        key = self._dedup_key(category, evt, symbol)
        if self._seen(key):
            return
        await self._queue.put((category, message))

    def _dedup_key(self, category, evt, symbol) -> str:
        minute_bucket = int(time.time() // 60)
        raw = f"{category}|{evt}|{minute_bucket}|{symbol or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()
```

```python
# bot/observability/equity.py
class EquityCurveSnapshotter:
    def __init__(self, journal: TradeJournal, logger: StructuredLogger,
                 account_provider: AccountProvider, interval_s: int = 300):
        ...

    async def run(self):
        # Clock-driven loop; on each tick compute snapshot from account_provider,
        # write to journal, emit `equity_snapshot` log line.
        ...
```

```python
# bot/replay.py
class ForensicReplay:
    def __init__(self, journal_path: Path, log_dir: Path):
        ...

    def render(self, date: date) -> str:
        # Query journal tables ORDER BY ts; merge with logs/{date}.jsonl;
        # return chronological timeline as text.
        ...
```

---

## 5. Testing strategy

| Test | What it asserts | How |
|------|-----------------|-----|
| **Log schema test** | Every `emit()` call produces a JSON line that matches the schema (required fields, allowed `lvl`, allowed `comp`, allowed `evt`). | `jsonschema` validator over a canned set of 100 calls covering every `(comp, evt)` pair. |
| **Journal reconciliation: clean** | Matching broker + journal → reconcile returns True, bot starts. | Fixture: identical position/order lists; call `reconcile_against_broker`. |
| **Journal reconciliation: mismatch HALT** | Inject fake broker position the journal doesn't know about → reconcile returns False, bootstrap emits `journal_reconcile_mismatch_HALT`, process exits non-zero. | Fixture: broker has MNQ long 1, journal has flat; assert HALT path. |
| **Alert rate-limit (WARN)** | 1000 WARN events for the same `(category, evt)` in 1 second → at most 60 Telegram messages delivered (one per minute bucket). | Spin a `TelegramAlerter` with a mock `Bot.send_message`, count calls. |
| **Critical never-throttled** | 100 CRITICAL events in 1 second → all 100 delivered, no dedup. | Same harness as above with `category="CRITICAL"`. |
| **Telegram outage tolerance** | Bot.send_message raises for 30 s straight → strategy loop still ticks, queued messages eventually drain on recovery. | Mock raises 30 s, then succeeds; assert strategy clock kept advancing. |
| **Replay determinism** | Given a synthetic session (canned orders/fills/decisions), the replay reconstruction matches the input event-by-event. | Seed journal + log file; run `ForensicReplay.render`; diff vs golden text. |
| **Equity-snapshot cadence** | During a simulated 09:30–15:10 session, exactly N=(390/5)+3 snapshots are recorded (390 min window + startup + close + shutdown). | Time-mocked harness; count rows in `equity_snapshots`. |
| **Log rotation** | Crossing midnight UTC closes the current file and opens `YYYY-MM-DD.jsonl` for the new date. | Inject clock that crosses midnight mid-stream; assert two files exist. |
| **Disk-full failure mode** | Simulate ENOSPC on log write → stderr fallback fires, CRITICAL Telegram emitted, strategy continues. | Mock filesystem; assert behavior chain. |

Conformance test integration: this spec adds the **journal reconciliation test** to the cross-broker conformance suite owned by `02-execution-clients.md`. Every `ExecutionClient` must produce position/order snapshots in a format the journal can ingest and compare.

---

## 6. Open questions

| # | Question | Decision needed by |
|---|----------|--------------------|
| O1 | **Log retention**: 90 days local OK, or do we need offsite backup (e.g., Backblaze B2, S3 Glacier) for audit? Topstep has not requested audit logs in published cases, but a Funded account dispute could require months of evidence. | Before first Funded conversion. |
| O2 | **Telegram dedup window**: 1-minute bucket on WARN sufficient, or do we need finer granularity (e.g., 15 s) for time-sensitive alerts like `broker_reconnect_attempt`? Counterpoint: finer buckets defeat the anti-fatigue goal. | After 2 weeks of paper trading. |
| O3 | **Equity-snapshot cadence on big-move days**: bump from 5 min to 1 min if intraday range > X ticks or realized P&L moves > Y in a 5-min window? Adds journal load but matches the volatility regime. | After backtest analysis of intraday volatility distribution. |
| O4 | **Sentry / self-hosted error tracker** for uncaught exceptions, or are CRITICAL logs + Telegram sufficient for a solo dev on one machine? Sentry adds a paid dependency and an outbound connection; logs are already there. Bias toward "logs are enough" unless we see a class of bug that the logs miss. | After 30 days of live paper running. |
| O5 | **Alert frequency cap** (the question parked from [00 §9](./00-architecture-overview.md#9-open-questions-parked-for-sibling-specs-to-resolve)): we propose the category-based throttle in §3.6. Validate empirically against a week of paper alerts before locking. | Same window as O2. |
| O6 | **Journal corruption recovery**: if SQLite WAL gets corrupted (extremely rare but possible), what's the recovery procedure? Restore from broker truth? Document the runbook. | Before live Combine. |

---

## 7. References

- Parent: [`00-architecture-overview.md`](./00-architecture-overview.md) — D12 (storage), D16 (observability), §7 item 6 (broker truth on restart).
- Sibling: [`02-execution-clients.md`](./02-execution-clients.md) — provides broker-side position/order data the journal reconciles against.
- Sibling: [`04-risk-engine.md`](./04-risk-engine.md) — owns phantom-MLL state machine; this spec defines the log/journal/alert surface for it.
- Sibling: [`07-config-and-deploy.md`](./07-config-and-deploy.md) — `.env` schema for `TELEGRAM_BOT_TOKEN`, log directory paths, Docker volume mounts for `logs/` and `data/`.
- Research: [`../research/bot-architecture-patterns.md`](../research/bot-architecture-patterns.md) — broker-as-source-of-truth principle, no-event-sourcing decision.
- External: [`python-telegram-bot` v22+ docs](https://docs.python-telegram-bot.org/) — polling mode reference.
- External: SQLite WAL mode — [`https://www.sqlite.org/wal.html`](https://www.sqlite.org/wal.html).
