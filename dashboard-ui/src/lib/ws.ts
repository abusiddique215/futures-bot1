/**
 * Multiplexed WebSocket client with auto-reconnect.
 *
 * Server contract (matches `src/bot/dashboard/v2/ws_bridge.py`):
 *   - Client → server:  { action: "subscribe", channels: ["fleet"] }
 *                       { action: "subscribe", channels: ["bot:alpha"] }
 *   - Server → client:  { kind: <kind>, data: <object> }
 *
 *   kind ∈ { bar_tick | account_update | bot_intent | fill | risk_decision | bot_state_change }
 *
 * Channel semantics (server-side):
 *   "fleet"     — every event
 *   "bot:<n>"   — events whose `data.bot === <n>`
 *
 * Reconnect: exponential backoff capped at 30s. On reconnect, all active
 * subscriptions are re-sent automatically.
 */

// ─── Event payload types ─────────────────────────────────────────────────

export interface BarPayload {
  ts: string;
  o: number;
  h: number;
  low: number;
  c: number;
  v: number;
}

export interface BarTickData {
  bot: string;
  symbol: string;
  bar: BarPayload;
}

export interface AccountUpdateData {
  bot: string;
  state: "DISABLED" | "ARMED_WAITING" | "IN_TRADE" | "LOCKED";
  equity: number;
  balance: number;
  realized_pnl_today: number;
  unrealized_pnl: number;
  high_water: number;
  distance_to_mll: number;
  distance_to_target: number | null;
  contracts_open: number;
  dll_remaining: number;
}

export interface BotIntentData {
  bot: string;
  watching_for: string;
  schedule_open: boolean;
  next_window_opens_in_seconds: number | null;
  max_trades_remaining: number | null;
}

export interface FillData {
  bot: string;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  fill_price: number;
  timestamp: string;
  client_order_id: string;
}

export interface RiskDecisionData {
  bot: string;
  approved: boolean;
  rule: string | null;
  reason: string | null;
  timestamp: string;
}

export interface BotStateChangeData {
  bot: string;
  from_state: string;
  to_state: string;
  reason: string;
  timestamp: string;
}

export type WsEvent =
  | { kind: "bar_tick"; data: BarTickData }
  | { kind: "account_update"; data: AccountUpdateData }
  | { kind: "bot_intent"; data: BotIntentData }
  | { kind: "fill"; data: FillData }
  | { kind: "risk_decision"; data: RiskDecisionData }
  | { kind: "bot_state_change"; data: BotStateChangeData }
  | { kind: string; data: Record<string, unknown> };

export type WsEventKind = WsEvent["kind"];

// ─── Type guard ──────────────────────────────────────────────────────────

function isWsEvent(value: unknown): value is WsEvent {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  if (typeof v.kind !== "string") return false;
  if (typeof v.data !== "object" || v.data === null) return false;
  return true;
}

// ─── Client ──────────────────────────────────────────────────────────────

type Listener = (event: WsEvent) => void;
type StatusListener = (status: WsStatus) => void;

export type WsStatus = "connecting" | "open" | "closed" | "error";

export interface WsClientOptions {
  url?: string;
  initialBackoffMs?: number;
  maxBackoffMs?: number;
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
    this.send({ action: "subscribe", channels: Array.from(this.channels) });
  }

  onEvent(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  onStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => {
      this.statusListeners.delete(listener);
    };
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
