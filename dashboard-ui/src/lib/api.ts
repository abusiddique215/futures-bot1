/**
 * Typed REST client for the Plan 23 dashboard backend.
 *
 * Endpoint surface (matches plan §T5):
 *   GET    /api/fleet
 *   GET    /api/bots/{name}
 *   POST   /api/bots/flatten_all       — kill switch
 *   GET    /api/profiles
 *   POST   /api/profiles
 *   DELETE /api/profiles/{name}
 *   POST   /api/profiles/{name}/activate
 *   GET    /api/profiles/{name}/overrides
 *   PUT    /api/profiles/{name}/overrides/{bot}/{block}
 *   GET    /api/profiles/{name}/history
 *
 * The types in this file are the FRONTEND-OWNED CONTRACT — the backend agent
 * must shape Pydantic responses to match. If we change a field here, the
 * backend must change too.
 */

// ─── Shared enums ─────────────────────────────────────────────────────────

export type BotState = "DISABLED" | "ARMED_WAITING" | "IN_TRADE" | "ERROR";
export type Side = "long" | "short";

// ─── /api/fleet ──────────────────────────────────────────────────────────

export interface BotSummary {
  /** Stable identifier, e.g. "surgebot_nq". */
  name: string;
  /** Human-readable display name, e.g. "SurgeBot". */
  display_name: string;
  /** Strategy type tag, e.g. "ORB", "TrendFollowing", "Signal". */
  strategy: string;
  /** Symbol traded, e.g. "MNQ". */
  symbol: string;
  state: BotState;
  /** Open position summary; null when flat. */
  position: {
    side: Side;
    contracts: number;
    avg_price: number;
    unrealized_pnl: number;
    unrealized_r: number;
  } | null;
  /** Realized P&L for the current session. */
  daily_pnl: number;
  /** Cumulative R for the session. */
  daily_r: number;
  /** Whether the strategy's schedule window is currently open. */
  schedule_open: boolean;
  /**
   * If schedule is closed: epoch-ms when the next window opens.
   * Null when the schedule is open (or unknown).
   */
  next_window_at: number | null;
  /** Tick size for this contract (formatting). */
  tick_size: number;
  /** Epoch-ms of the last bar / heartbeat. */
  last_heartbeat: number;
}

export interface AccountSummary {
  balance: number;
  equity: number;
  open_pnl: number;
  closed_pnl_today: number;
  high_water: number;
  /** Distance in $ from current equity to MLL. */
  distance_to_mll: number;
  /** Distance in $ from current equity to profit target. */
  distance_to_target: number;
  /** Trailing MLL value (Topstep ratchet). */
  mll_value: number;
  /** Profit target value (Topstep eval/funded). */
  target_value: number;
  /** Open contracts across the fleet. */
  contracts_open: number;
}

export interface FleetResponse {
  bots: BotSummary[];
  account: AccountSummary;
  /** Epoch-ms server time, for clock-skew correction. */
  server_time: number;
  /** Currently active profile name. */
  active_profile: string;
}

// ─── /api/bots/{name} ────────────────────────────────────────────────────

export interface Position {
  side: Side;
  contracts: number;
  avg_price: number;
  stop: number | null;
  target: number | null;
  unrealized_pnl: number;
  unrealized_r: number;
  /** Max favorable excursion in $ since entry. */
  mfe: number;
  /** Max adverse excursion in $ since entry. */
  mae: number;
  opened_at: number;
}

export interface WorkingOrder {
  id: string;
  side: Side;
  /** "LIMIT" | "STOP" | "STOP_LIMIT" | "MARKET" — strings to avoid coupling. */
  type: string;
  contracts: number;
  limit_price: number | null;
  stop_price: number | null;
  /** "DAY" | "GTC" | "IOC" */
  time_in_force: string;
  submitted_at: number;
}

export interface Fill {
  id: string;
  ts: number;
  side: Side;
  contracts: number;
  price: number;
  /** Realized P&L on this fill (closing fills only; 0 for openers). */
  realized_pnl: number;
  /** R-multiple for closing fills. */
  realized_r: number | null;
  /** Free-form reason: "stop", "target", "session_close", "manual_flatten". */
  reason: string;
}

export interface BotIntent {
  /** Plain-English: "Watching for breakout > 18045.25 OR < 17988.50". */
  watching_for: string;
  /** Whether the schedule window is currently open. */
  schedule_open: boolean;
  /** Optional key-value detail block ({"upper": 18045.25, "lower": 17988.5, ...}). */
  detail: Record<string, number | string | boolean | null>;
  /** Max additional trades allowed in this session (null = no cap). */
  max_trades_remaining: number | null;
}

export interface EquityPoint {
  ts: number;
  equity: number;
}

export interface BotDetail {
  summary: BotSummary;
  position: Position | null;
  working_orders: WorkingOrder[];
  recent_fills: Fill[];
  intent: BotIntent;
  equity_series: EquityPoint[];
}

// ─── /api/profiles ───────────────────────────────────────────────────────

export interface ProfileListResponse {
  profiles: string[];
  active: string;
}

export interface CreateProfilePayload {
  name: string;
  fork_from?: string;
}

export interface OverrideEntry {
  /** Override value — kept as unknown so callers narrow at use-site. */
  value: unknown;
  /** Base (un-overridden) value, for diff preview. */
  base: unknown;
}

export interface BotOverrides {
  strategy_params: Record<string, OverrideEntry>;
  risk_params: Record<string, OverrideEntry>;
  schedule_params: Record<string, OverrideEntry>;
}

export interface OverridesResponse {
  profile: string;
  bots: Record<string, BotOverrides>;
}

export interface SetOverrideRequest {
  value: unknown;
}

export interface HistoryEntry {
  ts: number;
  bot: string;
  block: string;
  key: string;
  old_value: unknown;
  new_value: unknown;
  actor: string;
}

// ─── Client ───────────────────────────────────────────────────────────────

export class ApiError extends Error {
  readonly status: number;
  readonly url: string;
  constructor(status: number, url: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.url = url;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, path, text || res.statusText);
  }
  // Cast at boundary — every endpoint has a typed wrapper below, callers stay typed.
  return (await res.json()) as T;
}

export const api = {
  // Fleet
  getFleet: (): Promise<FleetResponse> => request<FleetResponse>("/api/fleet"),
  getBot: (name: string): Promise<BotDetail> =>
    request<BotDetail>(`/api/bots/${encodeURIComponent(name)}`),
  flattenAll: (): Promise<{ ok: true; closed: number }> =>
    request<{ ok: true; closed: number }>("/api/bots/flatten_all", {
      method: "POST",
    }),

  // Profiles
  listProfiles: (): Promise<ProfileListResponse> =>
    request<ProfileListResponse>("/api/profiles"),
  createProfile: (payload: CreateProfilePayload): Promise<ProfileListResponse> =>
    request<ProfileListResponse>("/api/profiles", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteProfile: (name: string): Promise<ProfileListResponse> =>
    request<ProfileListResponse>(`/api/profiles/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  activateProfile: (name: string): Promise<ProfileListResponse> =>
    request<ProfileListResponse>(
      `/api/profiles/${encodeURIComponent(name)}/activate`,
      { method: "POST" },
    ),
  getOverrides: (name: string): Promise<OverridesResponse> =>
    request<OverridesResponse>(
      `/api/profiles/${encodeURIComponent(name)}/overrides`,
    ),
  setOverride: (
    name: string,
    bot: string,
    block: string,
    key: string,
    value: unknown,
  ): Promise<OverridesResponse> =>
    request<OverridesResponse>(
      `/api/profiles/${encodeURIComponent(name)}/overrides/${encodeURIComponent(bot)}/${encodeURIComponent(block)}/${encodeURIComponent(key)}`,
      {
        method: "PUT",
        body: JSON.stringify({ value } satisfies SetOverrideRequest),
      },
    ),
  getHistory: (name: string): Promise<HistoryEntry[]> =>
    request<HistoryEntry[]>(
      `/api/profiles/${encodeURIComponent(name)}/history`,
    ),
};
