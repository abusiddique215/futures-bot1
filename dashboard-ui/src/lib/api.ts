/**
 * Typed REST client for the Plan 23 dashboard backend.
 *
 * The shapes here MIRROR the backend Pydantic models in
 * `src/bot/dashboard/v2/api.py`. When the backend changes a field, this
 * file changes too. Anything richer (per-bot strategy "intent", working
 * orders, mfe/mae) is not in the backend yet — surface as placeholders
 * in the UI rather than fabricating shapes the server won't return.
 *
 * Endpoint surface:
 *   GET    /api/fleet
 *   GET    /api/bots/{name}
 *   GET    /api/account_summary
 *   POST   /api/bots/flatten_all
 *   GET    /api/profiles
 *   POST   /api/profiles
 *   DELETE /api/profiles/{name}
 *   POST   /api/profiles/{name}/activate
 *   GET    /api/profiles/{name}/overrides
 *   PUT    /api/profiles/{name}/overrides/{bot}/{block}    body: {key, value}
 *   GET    /api/profiles/{name}/prefs
 *   PUT    /api/profiles/{name}/prefs                      body: {prefs}
 *   GET    /api/profiles/{name}/history
 */

// ─── Shared enums ─────────────────────────────────────────────────────────

export type BotState = "DISABLED" | "ARMED_WAITING" | "IN_TRADE" | "LOCKED";

// ─── /api/fleet ──────────────────────────────────────────────────────────

export interface FleetBotEntry {
  name: string;
  enabled: boolean;
  symbol: string;
  strategy_id: string;
  /** "running" | "no_data" — journal-status derived. */
  status: string;
}

export interface FleetView {
  bots: FleetBotEntry[];
  /** ISO timestamp string or null. */
  heartbeat: string | null;
  /** Seconds since the fleet heartbeat (null when no heartbeat). */
  heartbeat_age: number | null;
  active_profile: string;
}

// ─── /api/account_summary ────────────────────────────────────────────────

export interface AccountSummary {
  balance: number;
  equity: number;
  open_pnl: number;
  closed_pnl_today: number;
  high_water: number;
  contracts_open: number;
}

// ─── /api/bots/{name} ────────────────────────────────────────────────────

export interface RecentTrade {
  client_order_id: string;
  symbol: string;
  side: string;
  quantity: number;
  fill_price: number;
  /** ISO timestamp. */
  timestamp: string;
}

export interface EquityCurvePoint {
  /** ISO timestamp. */
  timestamp: string;
  equity: number;
  realized_pnl: number;
}

export interface BotDetail {
  name: string;
  symbol: string;
  enabled: boolean;
  state: BotState;
  /** {symbol: signed_qty}. Empty when flat. */
  open_positions: Record<string, number>;
  realized_pnl_today: number;
  equity: number;
  high_water_equity: number;
  recent_trades: RecentTrade[];
  equity_curve: EquityCurvePoint[];
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

export interface CreatedProfile {
  name: string;
  forked_from: string;
}

export type OverridesPayload = Record<
  string,
  Record<string, Record<string, unknown>>
>;

export interface OverridesResponse {
  overrides: OverridesPayload;
}

export interface EffectiveSpec {
  name: string;
  strategy_params: Record<string, unknown>;
  risk_params: Record<string, unknown>;
  schedule_params: Record<string, unknown>;
}

export interface SetOverrideResponse {
  bot: string;
  block: string;
  key: string;
  value: unknown;
  spec: EffectiveSpec;
}

export interface ChangedBot {
  name: string;
  hash_before: string;
  hash_after: string;
  spec: EffectiveSpec;
}

export interface ActivateResponse {
  active: string;
  changed_bots: ChangedBot[];
  unchanged_bots: string[];
  restart_required: boolean;
}

export interface HistoryRow {
  timestamp: string;
  user: string;
  bot: string;
  block: string;
  key: string;
  before: unknown;
  after: unknown;
}

export interface HistoryView {
  history: HistoryRow[];
}

export interface PrefsView {
  prefs: Record<string, unknown>;
}

export interface FlattenResponse {
  flattened: string[];
  failed: { bot: string; error: string }[];
}

// ─── Client ──────────────────────────────────────────────────────────────

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
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  // Fleet + bots
  getFleet: (): Promise<FleetView> => request<FleetView>("/api/fleet"),
  getBot: (name: string): Promise<BotDetail> =>
    request<BotDetail>(`/api/bots/${encodeURIComponent(name)}`),
  getAccountSummary: (): Promise<AccountSummary> =>
    request<AccountSummary>("/api/account_summary"),
  flattenAll: (): Promise<FlattenResponse> =>
    request<FlattenResponse>("/api/bots/flatten_all", { method: "POST" }),

  // Profiles
  listProfiles: (): Promise<ProfileListResponse> =>
    request<ProfileListResponse>("/api/profiles"),
  createProfile: (payload: CreateProfilePayload): Promise<CreatedProfile> =>
    request<CreatedProfile>("/api/profiles", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteProfile: (name: string): Promise<void> =>
    request<void>(`/api/profiles/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  activateProfile: (name: string): Promise<ActivateResponse> =>
    request<ActivateResponse>(
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
  ): Promise<SetOverrideResponse> =>
    request<SetOverrideResponse>(
      `/api/profiles/${encodeURIComponent(name)}/overrides/${encodeURIComponent(bot)}/${encodeURIComponent(block)}`,
      {
        method: "PUT",
        body: JSON.stringify({ key, value }),
      },
    ),
  getHistory: (name: string): Promise<HistoryView> =>
    request<HistoryView>(
      `/api/profiles/${encodeURIComponent(name)}/history`,
    ),

  // Prefs (Settings page)
  getPrefs: (name: string): Promise<PrefsView> =>
    request<PrefsView>(`/api/profiles/${encodeURIComponent(name)}/prefs`),
  setPrefs: (name: string, prefs: Record<string, unknown>): Promise<PrefsView> =>
    request<PrefsView>(`/api/profiles/${encodeURIComponent(name)}/prefs`, {
      method: "PUT",
      body: JSON.stringify({ prefs }),
    }),
};
