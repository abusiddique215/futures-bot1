"""Plan 23 — Trader-Grade Dashboard v2 backend.

Modules:
  profiles  — ProfileStore (per-user overrides + audit log) + ProfileOverlay
              (frozen-dataclass-safe BotSpec merging).
  intent    — extract_intent(strategy, ...) -> dict; answers
              "what is the bot watching for right now".
  events    — Pydantic v2 event models for WS payloads. Canonical kinds:
              bar_tick, account_update, bot_intent, fill, risk_decision,
              bot_state_change.
  ws_bridge — WebSocketBroadcaster: TelemetryBus sink that fans out events
              to every connected WS client.
  api       — FastAPI REST router (/api/*).
  ws_routes — FastAPI WS route (/ws) with subscribe-channel filtering.
"""
