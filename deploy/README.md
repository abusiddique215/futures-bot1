# Deploy — macOS LaunchAgent

Two LaunchAgents back the live deployment:

| Agent | What it does | Restart policy |
|---|---|---|
| `com.user.topstepbot` | Runs `docker compose up` against the project's `docker-compose.yml`. | KeepAlive on non-zero exit; ThrottleInterval 10s. |
| `com.user.topstepbot-heartbeat` | Runs `check_heartbeat.sh` every 60s. Emits CRITICAL to `deploy/logs/heartbeat.err.log` if the bot's heartbeat file is older than 120s. | StartInterval 60s. |

## Prerequisites

1. **NOT on iCloud Drive.** SQLite WAL is unsafe on `~/Library/Mobile Documents/`. The install script refuses to run if the project is checked out there. (See Topstep article 8680268 — VPS/VPN ban context: same principle, the storage must be local.)
2. **Docker Desktop installed.** The compose file (not shipped in v1) starts the bot container. v1 ships only the runtime scaffold; the operator writes a minimal `docker-compose.yml` against the published image.
3. **`.env` populated** with broker credentials (TOPSTEPX_USERNAME, TOPSTEPX_API_KEY, TOPSTEPX_ACCOUNT_NAME) plus TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID. The .env loads inside the container; the LaunchAgent itself does NOT see these.

## Install

```bash
cd /path/to/topstep-bot
bash deploy/install.sh
```

The script substitutes the absolute project path into both .plist templates, copies them to `~/Library/LaunchAgents/`, runs `plutil -lint` on each, and loads them via `launchctl bootstrap`.

## Uninstall

```bash
bash deploy/uninstall.sh
```

Bootouts the agents and removes the .plist files. Logs under `deploy/logs/` are retained.

## Heartbeat

The bot writes `deploy/heartbeat.txt` every ~30s while the event loop is alive. `check_heartbeat.sh` is run every 60s by the second LaunchAgent and exits 1 (CRITICAL line on stderr) if the file is older than 120s.

A future operator-facing alerter can tail `heartbeat.err.log` or wire it into Telegram via the bot itself (chicken-and-egg note: if the bot is dead, the bot won't send the alert — that's why the heartbeat check is a separate LaunchAgent).

## Topstep references

- **VPS/VPN ban (binding)**: <https://help.topstep.com/en/articles/8680268-can-i-use-a-vpn>. The `assert_host_allowed` guard at startup enforces this — keep the local-disk requirement in the same posture.
- **Dual pricing paths**: $49 Combine + $149/mo Funded subscription, OR $95 LifeTime Combine + $0 Funded sub. Both are surfaced in the runtime startup banner so the operator sees both options on every launch.
