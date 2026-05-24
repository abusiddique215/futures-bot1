/**
 * Multiplexed WebSocket client with auto-reconnect.
 *
 * Server contract (matches plan §T5 and §T3):
 *   - Client → server:  { action: "subscribe", channels: ["fleet", "bot:surgebot_nq"] }
 *                       { action: "unsubscribe", channels: [...] }
 *   - Server → client:  { type: "bar_tick" | "fill" | "risk_decision" | "account_update" | "bot_intent",
 *                          channel: "fleet" | "bot:<name>",
 *                          ts: number,  // epoch ms
 *                          payload: { ... }  // event-specific
 *                        }
 *
 * Reconnect: exponential backoff, capped at 30s. On reconnect, all
 * active subscriptions are re-sent automatically.
 */

import type { AccountSummary, BotIntent, Fill, BotSummary } from "./api";

// ─── Event payload types ─────────────────────────────────────────────────

export interface BarTickPayload {
  bot: string;
  symbol: string;
  bar: { ts: number; o: number; h: number; l: number; c: number; v: number };
}

export interface AccountUpdatePayload {
  /** "fleet" for aggregate updates or a bot name for per-bot. */
  scope: "fleet" | string;
  account: AccountSummary;
  /** Per-bot summaries when scope === "fleet". */
  bots?: BotSummary[];
}

export interface FillPayload {
  bot: string;
  fill: Fill;
}

export interface RiskDecisionPayload {
  bot: string;
  /** "allowed" | "rejected" | "skipped" — strings to stay decoupled. */
  decision: string;
  reason: string;
  detail: Record<string, unknown>;
}

export interface BotIntentPayload {
  bot: string;
  intent: BotIntent;
}

export type WsEvent =
  | { type: "bar_tick"; channel: string; ts: number; payload: BarTickPayload }
  | {
      type: "account_update";
      channel: string;
      ts: number;
      payload: AccountUpdatePayload;
    }
  | { type: "fill"; channel: string; ts: number; payload: FillPayload }
  | {
      type: "risk_decision";
      channel: string;
      ts: number;
      payload: RiskDecisionPayload;
    }
  | {
      type: "bot_intent";
      channel: string;
      ts: number;
      payload: BotIntentPayload;
    };

export type WsEventType = WsEvent["type"];

// ─── Type guard (narrow JSON.parse output) ───────────────────────────────

function isWsEvent(value: unknown): value is WsEvent {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  if (typeof v.type !== "string") return false;
  if (typeof v.channel !== "string") return false;
  if (typeof v.ts !== "number") return false;
  if (typeof v.payload !== "object" || v.payload === null) return false;
  return (
    v.type === "bar_tick" ||
    v.type === "account_update" ||
    v.type === "fill" ||
    v.type === "risk_decision" ||
    v.type === "bot_intent"
  );
}

// ─── Client ──────────────────────────────────────────────────────────────

type Listener = (event: WsEvent) => void;
type StatusListener = (status: WsStatus) => void;

export type WsStatus = "connecting" | "open" | "closed" | "error";

export interface WsClientOptions {
  url?: string;
  /** Initial reconnect backoff in ms (doubles each failure, capped at maxBackoffMs). */
  initialBackoffMs?: number;
  maxBackoffMs?: number;
  /** Inject a custom WebSocket constructor (testing). */
  WebSocketImpl?: typeof WebSocket;
}

function defaultWsUrl(): string {
  if (typeof window === "undefined") return "ws://127.0.0.1:8765/ws";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws`;
}

export class WsClient {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private readonly listeners = new Set<Listener>();
  private readonly statusListeners = new Set<StatusListener>();
  private readonly channels = new Set<string>();
  private status: WsStatus = "closed";
  private backoff: number;
  private readonly initialBackoff: number;
  private readonly maxBackoff: number;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;
  private readonly Ws: typeof WebSocket;

  constructor(opts: WsClientOptions = {}) {
    this.url = opts.url ?? defaultWsUrl();
    this.initialBackoff = opts.initialBackoffMs ?? 500;
    this.maxBackoff = opts.maxBackoffMs ?? 30_000;
    this.backoff = this.initialBackoff;
    this.Ws = opts.WebSocketImpl ?? WebSocket;
  }

  // ─── Public API ───────────────────────────────────────────────────────

  connect(): void {
    if (this.ws && this.ws.readyState === this.Ws.OPEN) return;
    if (this.ws && this.ws.readyState === this.Ws.CONNECTING) return;
    this.intentionalClose = false;
    this.openSocket();
  }

  close(): void {
    this.intentionalClose = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.setStatus("closed");
  }

  subscribe(channels: string[]): void {
    for (const ch of channels) this.channels.add(ch);
    this.send({ action: "subscribe", channels });
  }

  unsubscribe(channels: string[]): void {
    for (const ch of channels) this.channels.delete(ch);
    this.send({ action: "unsubscribe", channels });
  }

  onEvent(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  onStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  getStatus(): WsStatus {
    return this.status;
  }

  // ─── Internals ────────────────────────────────────────────────────────

  private openSocket(): void {
    this.setStatus("connecting");
    try {
      this.ws = new this.Ws(this.url);
    } catch {
      this.setStatus("error");
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.setStatus("open");
      this.backoff = this.initialBackoff;
      // Re-subscribe to anything we had before the disconnect.
      if (this.channels.size > 0) {
        this.send({
          action: "subscribe",
          channels: Array.from(this.channels),
        });
      }
    };

    this.ws.onmessage = (ev: MessageEvent<string>) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!isWsEvent(parsed)) return;
      for (const listener of this.listeners) listener(parsed);
    };

    this.ws.onerror = () => {
      this.setStatus("error");
    };

    this.ws.onclose = () => {
      this.ws = null;
      if (this.intentionalClose) {
        this.setStatus("closed");
        return;
      }
      this.setStatus("closed");
      this.scheduleReconnect();
    };
  }

  private send(payload: object): void {
    if (!this.ws || this.ws.readyState !== this.Ws.OPEN) return;
    this.ws.send(JSON.stringify(payload));
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    const delay = this.backoff;
    this.backoff = Math.min(this.backoff * 2, this.maxBackoff);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, delay);
  }

  private setStatus(status: WsStatus): void {
    if (this.status === status) return;
    this.status = status;
    for (const listener of this.statusListeners) listener(status);
  }
}

/** Lazily-constructed singleton for app-wide use. */
let _client: WsClient | null = null;
export function getWsClient(): WsClient {
  if (!_client) _client = new WsClient();
  return _client;
}
