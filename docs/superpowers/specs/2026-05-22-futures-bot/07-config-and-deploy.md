# 07 — Config and Deploy

**Project**: Topstep Futures Trading Bot
**Date**: 2026-05-22
**Status**: Spec — research phase
**Owner**: abu.siddique215@gmail.com

---

## 1. Purpose

Define the deployment and runtime configuration surface: typed config schema (Pydantic v2), secrets boundary, on-disk file layout, Docker layout (Mac-only for live), macOS auto-start, and the **restart and state-recovery contract** that makes "broker is source of truth" (`00 §7 item 6`) concrete. Out of scope: strategy/risk/observability internals (`03/04/06`), historical-data layout (`01`), broker-adapter internals (`02`).

---

## 2. Inherited decisions

From `00-architecture-overview.md`:

- **D13** — Python 3.12.
- **D14** — Hosting: user's physical Mac. Topstep ToS bans VPS/VPN for Funded. Live = exactly one machine. Cloud allowed only for backtest workloads that never touch a Topstep account.
- **D15** — Docker on the Mac, auto-start on login, structured logs to local disk.
- `00 §7 item 6` — broker truth on restart; reconcile vs SQLite journal; refuse to start on mismatch.
- `00 §7 item 5` — VPS/VPN ban → hostname check when `env=live`.
- `D12` — SQLite journal/audit; broker is position truth.
- `D16` — JSON-lines logs + Telegram alerts (`06-observability.md` owns the taxonomy).

---

## 3. Design

### 3.1 Config schema (Pydantic v2)

Root model `BotConfig` loaded from `bot/config/bot.yml`. Strategy params live in a separate YAML referenced by `strategy_profile`.

```python
from datetime import time
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class DataConfig(BaseModel):
    historical_root: Path                       # parquet store, partitioned by year-month
    historical_vendor: Literal["firstratedata"]
    live_source: Literal["ib", "topstepx"]      # bar/tick feed during live
    symbol_primary: Literal["MNQ", "NQ"] = "MNQ"
    bar_seconds: int = 60                       # 1-min bars per 03-strategies

class TelegramConfig(BaseModel):
    # NB: actual token/chat_id live in env vars; these are *names* the loader
    # resolves against the environment, not secret values themselves.
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    min_severity: Literal["INFO", "WARN", "CRITICAL"] = "WARN"
    # NB: severity strings match `06-observability.md` §3.2 / §3.6 (WARN, not WARNING).

class BotConfig(BaseModel):
    env: Literal["dev", "paper", "live"]
    broker: Literal["sim", "ib_paper", "topstepx"]
    account_id: str                             # IB account or TopstepX accountId
    strategy: Literal["orb"]                    # extensible later
    strategy_profile: Path                      # path to surge.yml or maintenance.yml
    risk_policy: Literal[
        "combine_50k",
        "efa_standard_50k",
        "efa_consistency_50k",
    ]
    data: DataConfig
    telegram: TelegramConfig
    news_calendar: Path
    flat_by_warning_ct: time = time(14, 0)      # soft warn — 04-risk-engine
    flat_by_force_ct:   time = time(15, 10)     # hard flatten — 04-risk-engine
    halt_on_journal_desync: bool = True

    @field_validator("flat_by_force_ct")
    @classmethod
    def force_after_warning(cls, v: time, info) -> time:
        warn = info.data.get("flat_by_warning_ct")
        if warn and v <= warn:
            raise ValueError("flat_by_force_ct must be after flat_by_warning_ct")
        return v

    @field_validator("broker")
    @classmethod
    def broker_matches_env(cls, v: str, info) -> str:
        env = info.data.get("env")
        allowed = {
            "dev":   {"sim", "ib_paper", "topstepx"},
            "paper": {"ib_paper", "topstepx"},      # topstepx practice sub-acct OK
            "live":  {"topstepx"},
        }
        if env and v not in allowed[env]:
            raise ValueError(f"broker={v} not allowed in env={env}")
        return v
```

Notes: `strategy_profile` is a *path* (03 owns the schema). `risk_policy` is a tag (04 owns the registry). No secrets in the model — only env-var *names*. The `env`/`broker` cross-validator prevents "live env, paper broker".

### 3.2 Secrets handling

`.env` at project root (`bot/.env`), **gitignored**, loaded with `python-dotenv` *before* `BotConfig` construction. Required env vars:

| Var | Purpose | Used when |
|---|---|---|
| `IB_USERNAME` | Interactive Brokers login | `broker=ib_paper` |
| `IB_PASSWORD` | IB password | `broker=ib_paper` |
| `IB_GATEWAY_HOST` | default `127.0.0.1` | `broker=ib_paper` |
| `IB_GATEWAY_PORT` | default `4002` (paper) | `broker=ib_paper` |
| `TOPSTEPX_USERNAME` | TopstepX login | `broker=topstepx` |
| `TOPSTEPX_API_KEY` | TopstepX/ProjectX API key | `broker=topstepx` |
| `TELEGRAM_BOT_TOKEN` | bot token | always |
| `TELEGRAM_CHAT_ID` | numeric chat id | always |

Rules: logger filter strips secret values defensively. `load_secrets()` validates required vars for active `broker`; missing → fail-fast naming the var. Encrypted backup: `secrets/secrets.age` (via `age` — see §6). Backup is committed, passphrase is not.

```bash
age -p -o secrets/secrets.age bot/.env   # encrypt
age -d -o bot/.env secrets/secrets.age   # decrypt
```

### 3.3 File layout

```
bot/
  config/
    bot.yml                      # BotConfig instance (committed; no secrets)
    profiles/
      surge.yml                  # 03-strategies — aggressive params
      maintenance.yml            # 03-strategies — conservative params
    news_calendar.yml            # 04-risk-engine — FOMC/NFP/CPI events
  data/
    historical/                  # 01-data-pipeline — parquet, YYYY/MM partitions
    reports/                     # 05-backtest-harness — backtest outputs
  logs/                          # JSON-lines, daily rotation
  state/
    heartbeat                    # mtime updated every 30s
    state.sqlite                 # 06-observability — trade journal (WAL)
  secrets/
    secrets.age                  # encrypted .env backup
  .env                           # gitignored
  .gitignore
  pyproject.toml
  Dockerfile
  docker-compose.yml
  src/
    bot/
      __init__.py
      config.py                  # this spec
      secrets.py                 # this spec
      reconcile.py               # this spec
      runtime.py                 # this spec — hydrate / main()
      adapters/                  # 02-execution-clients
      strategy/                  # 03-strategies
      risk/                      # 04-risk-engine
      journal/                   # 06-observability
      data/                      # 01-data-pipeline
```

Notes: `state.sqlite` under `state/` so the Docker mount is one dir. `data/historical/` is a separate mount (large, rarely changed). `logs/` is separate (frequent append, cheap discard).

### 3.4 Docker layout (on Mac, NOT for cloud)

#### Dockerfile

```dockerfile
# bot/Dockerfile
FROM python:3.12-slim

# system deps for pyarrow, lxml (news cal parsing), tzdata for America/Chicago
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential tzdata ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

ENV TZ=UTC \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install \
      "ib_async>=1.0" \
      "project-x-py>=3.5.8" \
      "nautilus_trader>=1.200" \
      "pydantic>=2.7" \
      "pydantic-settings>=2.3" \
      "python-telegram-bot>=21" \
      "python-dotenv>=1.0" \
      "pyarrow>=16" \
      "loguru>=0.7" \
      "aiosqlite>=0.20"

COPY src/ ./src/
ENV PYTHONPATH=/app/src

# Healthcheck: state/heartbeat must be < 90s old.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=2 \
  CMD test "$(date +%s)" -lt "$(($(stat -c %Y /app/state/heartbeat 2>/dev/null || echo 0) + 90))" || exit 1

ENTRYPOINT ["python", "-m", "bot.runtime"]
```

#### docker-compose.yml

```yaml
# bot/docker-compose.yml
services:
  bot:
    build: .
    container_name: topstep-bot
    restart: unless-stopped
    env_file: .env                        # mounted read-only at runtime
    environment:
      - TZ=UTC
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
      - ./logs:/app/logs
      - ./state:/app/state
      - ./.env:/app/.env:ro
    # Host networking is only needed when IB Gateway runs on the Mac host
    # (127.0.0.1:4002). Comment the network_mode line and use the sidecar
    # below if you want everything in containers.
    network_mode: host

  # OPTIONAL — IB Gateway in a sidecar. Pick *one* of:
  #   (a) IB Gateway as a native Mac app on host  → use network_mode: host above.
  #   (b) IB Gateway sidecar here                 → remove network_mode: host,
  #                                                  set IB_GATEWAY_HOST=ibgateway
  #                                                  in .env, use a depends_on.
  # ibgateway:
  #   image: ghcr.io/extrange/ib-gateway:stable
  #   container_name: ib-gateway
  #   restart: unless-stopped
  #   env_file: .env                      # TWS_USERID, TWS_PASSWORD
  #   ports:
  #     - "127.0.0.1:4002:4002"
  #   volumes:
  #     - ./ibgateway:/root/Jts
```

Tradeoff (also §6): host IB Gateway = easy 2FA, ties deploy to a manual app launch. Sidecar = clean compose-up but brittle headless auth. `broker=topstepx` (live) doesn't need a gateway at all.

### 3.5 macOS auto-start (LaunchAgent)

Install: `~/Library/LaunchAgents/com.user.topstepbot.plist`. The plist runs `docker compose up`; the container's `restart: unless-stopped` handles intra-session crashes. `KeepAlive` with `SuccessfulExit=false` means only unclean exits relaunch — clean shutdown stays down.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.user.topstepbot</string>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/docker</string>
    <string>compose</string>
    <string>-f</string>
    <string>/Users/abusiddique/projects/topstep-bot/docker-compose.yml</string>
    <string>up</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/abusiddique/projects/topstep-bot</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>

  <key>StandardOutPath</key>
  <string>/Users/abusiddique/projects/topstep-bot/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/abusiddique/projects/topstep-bot/logs/launchd.err.log</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
```

Install / uninstall:

```bash
# install
cp deploy/com.user.topstepbot.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.user.topstepbot.plist

# tail status
launchctl list | grep topstepbot
tail -f logs/launchd.out.log

# uninstall
launchctl unload -w ~/Library/LaunchAgents/com.user.topstepbot.plist
```

Runtime tree must be on local disk, not iCloud — see §6.

### 3.6 Restart / state-recovery sequence (load-bearing, per 00 §7 item 6)

Runs on every cold start, in order, no exceptions:

1. **Load config**: `BotConfig.model_validate(yaml.safe_load(open("config/bot.yml")))`. Validation failure → exit 2, log to stderr.
2. **Load secrets**: `load_secrets()` reads `.env` via `python-dotenv`, asserts every var required by `cfg.broker` is present. Missing → exit 3.
3. **Hostname guard**: if `cfg.env == "live"`, assert `socket.gethostname()` matches a whitelisted value (e.g. user's Mac). Wrong host → exit 4, **CRITICAL** Telegram. This enforces D14.
4. **Open SQLite journal**: `state/state.sqlite` in WAL mode. Migrations applied if schema version drifts.
5. **Connect broker** per `cfg.broker`. Query in parallel:
   - `broker.get_positions()`
   - `broker.get_open_orders()`
   - `broker.get_account()`
6. **Reconcile** against journal (last session's final upserted `position_state` and `orders` rows):
   - For every broker-shown position: journal must show a matching open position with matching qty and side.
   - For every broker-shown open order: journal must show a matching pending intent + accepted order with the same `client_order_id`.
   - Symmetric: journal positions absent from broker = mismatch; journal orders absent from broker = mismatch.
7. **Mismatch + `halt_on_journal_desync=True`**: emit JSON-lines `journal_reconcile_mismatch_HALT` with full diff; send **CRITICAL** Telegram containing diff (positions and orders, both sides); exit 5. Human review required before next start (override via explicit operator flag).
8. **Pass**: hydrate runtime (position from broker, day P&L from `get_account()`, high-water equity from journal's `equity_snapshots`); warm indicators by replaying last N bars (03 sets N); start data feed → event loop → strategy → risk engine; write `session_id` row.

This is the single hardest contract in the bot.

### 3.7 Failure-mode handling during normal operation

| Failure | Detection | Response |
|---|---|---|
| **Broker disconnect** | adapter heartbeat | pause new entries; position-management via journal-derived state; reconnect with exponential backoff (1s → 2s → 4s → … max 60s); on reconnect, run mini-reconcile before resuming entries |
| **Data-feed gap** | bar-timestamp jump | backfill from broker REST historical if possible; if not, pause new entries until N bars of fresh data have flowed |
| **Process crash** | container exit | Docker `restart: unless-stopped` + LaunchAgent KeepAlive both bring it back; §3.6 reconcile catches any divergence on restart |
| **Mac sleep / clock skew** | clock-port comparison vs broker server time | if drift > 2s warn; > 10s halt (per `bot-architecture-patterns §7`) |
| **iCloud sync during runtime** | file mtime jitter on `state.sqlite` | not allowed — see §6, working tree must be on local disk |

### 3.8 Health check (file-based heartbeat)

Event loop writes `state/heartbeat` (one-line ISO ts, atomic rename) every **30s**. Two consumers: Docker `HEALTHCHECK` (inline above, `unhealthy` after ~90s stale) and an **external shell monitor** run by a second LaunchAgent every 60s:

```bash
#!/usr/bin/env bash
# scripts/check_heartbeat.sh
HB=/Users/abusiddique/projects/topstep-bot/state/heartbeat
NOW=$(date +%s)
MTIME=$(stat -f %m "$HB" 2>/dev/null || echo 0)
AGE=$((NOW - MTIME))
if [[ $AGE -gt 90 ]]; then
  curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
       -d chat_id="${TELEGRAM_CHAT_ID}" \
       -d text="CRITICAL: heartbeat stale ${AGE}s on $(hostname)"
fi
```

External by design — a bot too wedged to heartbeat is too wedged to alert itself.

### 3.9 Cloud usage policy

Config-encoded, runtime-enforced:

| `env` value | Allowed host | Touches Topstep? |
|---|---|---|
| `dev` | anywhere (laptop, cloud, container) | no |
| `paper` | anywhere (IB paper is not Topstep) | **only** if `broker=topstepx` against a Practice sub-account — then Mac-only |
| `live` | **user's Mac only** (hostname-whitelisted) | yes — Topstep ToS |

`05-backtest-harness.md` runs `env=dev` on cloud freely (historical data only). Hostname guard (§3.6 step 3) is the enforcement point: no cloud process ever holds a Funded TopstepX key.

---

## 4. Implementation sketch

### 4.1 `config.py` and `secrets.py`

```python
# config.py
def load_config(path: Path) -> BotConfig:
    return BotConfig.model_validate(yaml.safe_load(path.read_text()))

# secrets.py
REQUIRED_BY_BROKER = {
    "sim":      [],
    "ib_paper": ["IB_USERNAME", "IB_PASSWORD"],
    "topstepx": ["TOPSTEPX_USERNAME", "TOPSTEPX_API_KEY"],
}
ALWAYS_REQUIRED = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
LIVE_HOSTNAME_WHITELIST = {"abus-mac.local", "abus-mac"}

@dataclass(frozen=True)
class SecretsDict:
    ib_user: str | None; ib_pass: str | None
    ib_host: str;        ib_port: int
    topstepx_user: str | None; topstepx_key: str | None
    telegram_token: str; telegram_chat: str

def load_secrets(cfg: BotConfig, dotenv_path: str = ".env") -> SecretsDict:
    load_dotenv(dotenv_path, override=False)
    missing = [v for v in ALWAYS_REQUIRED + REQUIRED_BY_BROKER[cfg.broker]
               if not os.getenv(v)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {missing}")
    return SecretsDict(...)  # populate from os.environ

def assert_host_allowed(cfg: BotConfig) -> None:
    if cfg.env == "live" and socket.gethostname() not in LIVE_HOSTNAME_WHITELIST:
        raise RuntimeError("env=live but hostname not in whitelist; Topstep ToS")
```

### 4.2 `reconcile.py`

```python
@dataclass
class BrokerState:
    positions: dict[str, int]           # symbol -> signed qty
    open_orders: dict[str, dict]        # client_order_id -> {symbol, side, qty, price}
    account_equity: float; day_pnl: float

@dataclass
class JournalState:
    positions: dict[str, int]
    open_orders: dict[str, dict]
    high_water_equity: float

@dataclass
class ReconcileResult:
    ok: bool
    position_diff: dict[str, tuple[int, int]] = field(default_factory=dict)
    order_diff:    dict[str, tuple[dict | None, dict | None]] = field(default_factory=dict)

def reconcile(broker: BrokerState, journal: JournalState) -> ReconcileResult:
    pos_diff, ord_diff = {}, {}
    for sym in set(broker.positions) | set(journal.positions):
        b, j = broker.positions.get(sym, 0), journal.positions.get(sym, 0)
        if b != j: pos_diff[sym] = (b, j)
    for coid in set(broker.open_orders) | set(journal.open_orders):
        b, j = broker.open_orders.get(coid), journal.open_orders.get(coid)
        if b != j: ord_diff[coid] = (b, j)
    return ReconcileResult(not (pos_diff or ord_diff), pos_diff, ord_diff)
```

### 4.3 `runtime.py` entry point

```python
@dataclass
class RuntimeState:
    cfg: BotConfig; secrets: SecretsDict
    broker: BrokerPort; journal: JournalPort
    position: dict[str, int]; day_pnl: float; high_water_equity: float

def hydrate_runtime(rr, broker_state, journal_state, cfg, secrets, broker, journal) -> RuntimeState:
    return RuntimeState(cfg, secrets, broker, journal,
                        position=dict(broker_state.positions),
                        day_pnl=broker_state.day_pnl,
                        high_water_equity=journal_state.high_water_equity)

async def main() -> int:
    cfg = load_config(Path("config/bot.yml"))
    secrets = load_secrets(cfg); assert_host_allowed(cfg)
    journal = await open_journal("state/state.sqlite")
    broker  = await connect_broker(cfg, secrets)
    bs = await snapshot_broker(broker); js = await snapshot_journal(journal)
    rr = reconcile(bs, js)
    if not rr.ok and cfg.halt_on_journal_desync:
        logger.critical("journal_reconcile_mismatch_HALT",
                        position_diff=rr.position_diff, order_diff=rr.order_diff)
        await send_telegram_critical(secrets, format_diff(rr))
        return 5
    runtime = hydrate_runtime(rr, bs, js, cfg, secrets, broker, journal)
    await run_event_loop(runtime)   # strategy + risk + data feed
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

LaunchAgent `.plist`, `Dockerfile`, `docker-compose.yml` are inline in §3.4/§3.5 above.

---

## 5. Testing strategy

| Test | Mechanism | Pass criterion |
|---|---|---|
| **Config validation — invalid env** | construct `BotConfig(env="prod", ...)` | `ValidationError` raised; message names `env` |
| **Config cross-validator** | `env="live", broker="ib_paper"` | `ValidationError` from `broker_matches_env` |
| **Config cross-validator** | `flat_by_force_ct <= flat_by_warning_ct` | `ValidationError` from `force_after_warning` |
| **Secret-load — missing var** | empty `.env`, `broker=topstepx` | `RuntimeError("Missing required env vars: ['TOPSTEPX_USERNAME', 'TOPSTEPX_API_KEY', ...]")` |
| **Hostname guard** | mock `socket.gethostname()` → `"ec2-1-2-3-4"` with `env=live` | `RuntimeError` mentioning ToS |
| **Reconcile — clean** | broker positions == journal positions, orders match | `ReconcileResult.ok == True` |
| **Reconcile — phantom position** | broker has `MNQ: +2`, journal has `MNQ: 0` | `ok=False`, `position_diff == {"MNQ": (2, 0)}` |
| **Reconcile — orphan journal order** | journal has open order broker doesn't show | `ok=False`, `order_diff[coid] == (None, {...})` |
| **Halt-on-desync path** | inject failing reconcile + `halt_on_journal_desync=True` | exit code 5; Telegram CRITICAL captured by stub |
| **Heartbeat staleness** | stop bot, wait 90s, run monitor script | Telegram CRITICAL within 60s of staleness |
| **LaunchAgent survives reboot** | install plist, `sudo reboot`, observe | container `topstep-bot` in `docker ps` within 2 min of login; heartbeat fresh |
| **LaunchAgent restarts after crash** | `docker kill topstep-bot` | LaunchAgent + compose `restart: unless-stopped` brings it back; reconcile passes |
| **Encrypted-backup round-trip** | `age -p -o secrets.age .env` then decrypt | byte-identical `.env` recovered |
| **Secrets not logged** | seed logs with all 8 env vars, grep | zero matches in `logs/*.jsonl` |

Unit tests under `pytest`. LaunchAgent + heartbeat tests are manual checklists in `docs/runbooks/`.

---

## 6. Open questions

- **Auto-start**: LaunchAgent vs `cron @reboot` vs programmatic `launchctl submit`. LaunchAgent is Apple-blessed with the `KeepAlive` semantics we need; `cron @reboot` has no supervised restart. Tentative: **LaunchAgent**. Confirm on user's macOS version.
- **IB Gateway placement**: host vs Docker sidecar. Sidecar = reproducible but headless IBKR auth + daily re-auth + 2FA in container is brittle. Tentative: **host on Mac** for v1. `broker=topstepx` doesn't trigger this.
- **iCloud Drive / App Translocation**: project root currently lives under `~/Library/Mobile Documents/com~apple~CloudDocs/...` (iCloud). LaunchAgent executing from iCloud-synced paths is **not safe** — eviction, unstable mtimes, broken SQLite WAL semantics. Deployed tree must be on local disk (`~/projects/topstep-bot/`); deploy via `rsync -a --delete` or a git remote. Test before production install.
- **Backup tool**: `age` (simple, modern, single binary) vs `gpg` (ubiquitous, baroque). Tentative: **`age`**; document both, recovery may be executed years later.
- **Hostname whitelist**: hard-coded in `secrets.py` is brittle. Move to `bot.yml` (`live_hostnames: [...]`) once hostname is finalized.

---

## 7. References

Local:

- `./00-architecture-overview.md` — D13, D14, D15, §7 item 6 (broker truth on restart), §7 item 5 (VPS ban)
- `./01-data-pipeline.md` — owns `data/historical/` partitioning referenced by `DataConfig`
- `./02-execution-clients.md` — owns `BrokerPort` queried during reconcile (§3.6 step 5)
- `./03-strategies.md` — owns `strategy_profile` YAML schema referenced by `BotConfig.strategy_profile`
- `./04-risk-engine.md` — owns `risk_policy` registry referenced by `BotConfig.risk_policy`; owns `news_calendar.yml` schema
- `./06-observability.md` — owns SQLite journal schema, Telegram alert taxonomy, log event names (`journal_reconcile_mismatch_HALT`)
- `../research/bot-architecture-patterns.md` — §5 (restart sequence), §7 (failure modes), §9 (config layering)

External:

- Pydantic v2 docs — https://docs.pydantic.dev/latest/
- `python-dotenv` — https://github.com/theskumar/python-dotenv
- `age` encryption — https://github.com/FiloSottile/age
- Apple `launchd.plist` reference — `man 5 launchd.plist`
- Apple TN2083 (Daemons and Agents) — https://developer.apple.com/library/archive/technotes/tn2083/
- Docker Compose v2 spec — https://docs.docker.com/compose/compose-file/
- IB Gateway Docker image — https://github.com/extrange/ib-gateway-docker
- `project-x-py` — https://github.com/TexasCoding/project-x-py
- `ib_async` — https://github.com/ib-api-reloaded/ib_async
