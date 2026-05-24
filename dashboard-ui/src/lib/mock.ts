/**
 * Fixture data used by the Overview scaffold until the backend API is wired up.
 *
 * The shapes here MUST match `src/lib/api.ts`. If you add a field to a type,
 * extend the fixture too — components rely on the contract being honored.
 */

import type {
  AccountSummary,
  BotDetail,
  BotIntent,
  BotSummary,
  EquityPoint,
  Fill,
  FleetResponse,
  Position,
  WorkingOrder,
} from "./api";

const NOW = 1_716_580_800_000; // 2026-05-24 fixed for deterministic tests
const MIN = 60_000;
const HR = 60 * MIN;

// 9:30 ET = 13:30 UTC. NQ regular session 9:30-16:00 ET. Use a "next open"
// timestamp for closed-window demos.
const NEXT_RTH_OPEN = NOW + 16 * HR;

export const mockBots: BotSummary[] = [
  {
    name: "surgebot_nq",
    display_name: "SurgeBot",
    strategy: "ORB",
    symbol: "MNQ",
    state: "IN_TRADE",
    position: {
      side: "long",
      contracts: 2,
      avg_price: 18_042.5,
      unrealized_pnl: 145.0,
      unrealized_r: 1.2,
    },
    daily_pnl: 312.5,
    daily_r: 2.1,
    schedule_open: true,
    next_window_at: null,
    tick_size: 0.25,
    last_heartbeat: NOW - 4_000,
  },
  {
    name: "propbot_es",
    display_name: "PropBot",
    strategy: "TrendFollowing",
    symbol: "MES",
    state: "ARMED_WAITING",
    position: null,
    daily_pnl: 0,
    daily_r: 0,
    schedule_open: true,
    next_window_at: null,
    tick_size: 0.25,
    last_heartbeat: NOW - 1_000,
  },
  {
    name: "goldbot_gc",
    display_name: "Gold Bot",
    strategy: "MeanReversion",
    symbol: "MGC",
    state: "IN_TRADE",
    position: {
      side: "short",
      contracts: 1,
      avg_price: 2_398.3,
      unrealized_pnl: -68.0,
      unrealized_r: -0.55,
    },
    daily_pnl: -42.0,
    daily_r: -0.4,
    schedule_open: true,
    next_window_at: null,
    tick_size: 0.1,
    last_heartbeat: NOW - 2_000,
  },
  {
    name: "es_scalper",
    display_name: "ES Scalper",
    strategy: "ORB",
    symbol: "MES",
    state: "DISABLED",
    position: null,
    daily_pnl: 0,
    daily_r: 0,
    schedule_open: false,
    next_window_at: NEXT_RTH_OPEN,
    tick_size: 0.25,
    last_heartbeat: NOW - 45_000,
  },
  {
    name: "luxbot",
    display_name: "Lux Bot",
    strategy: "Signal",
    symbol: "MNQ",
    state: "ARMED_WAITING",
    position: null,
    daily_pnl: 78.5,
    daily_r: 0.6,
    schedule_open: true,
    next_window_at: null,
    tick_size: 0.25,
    last_heartbeat: NOW - 3_000,
  },
  {
    name: "nq_maintenance",
    display_name: "NQ Maintenance",
    strategy: "TrendFollowing",
    symbol: "MNQ",
    state: "ARMED_WAITING",
    position: null,
    daily_pnl: -15.0,
    daily_r: -0.1,
    schedule_open: false,
    next_window_at: NOW + 2 * HR + 14 * MIN,
    tick_size: 0.25,
    last_heartbeat: NOW - 8_000,
  },
];

export const mockAccount: AccountSummary = {
  balance: 49_120.5,
  equity: 49_197.5,
  open_pnl: 77.0,
  closed_pnl_today: 333.5,
  high_water: 49_460.0,
  distance_to_mll: 1_197.5,
  distance_to_target: 803.0,
  mll_value: 48_000.0,
  target_value: 50_000.0,
  contracts_open: 3,
};

export const mockFleet: FleetResponse = {
  bots: mockBots,
  account: mockAccount,
  server_time: NOW,
  active_profile: "default",
};

// ─── Per-bot detail fixtures ─────────────────────────────────────────────

const surgebotIntent: BotIntent = {
  watching_for: "Long in trade @ 18,042.50; trailing stop 18,032.25 (1R away)",
  schedule_open: true,
  detail: {
    side: "long",
    entry: 18_042.5,
    stop: 18_032.25,
    target: 18_063.0,
  },
  max_trades_remaining: 1,
};

const surgebotPosition: Position = {
  side: "long",
  contracts: 2,
  avg_price: 18_042.5,
  stop: 18_032.25,
  target: 18_063.0,
  unrealized_pnl: 145.0,
  unrealized_r: 1.2,
  mfe: 168.0,
  mae: -22.0,
  opened_at: NOW - 12 * MIN,
};

const surgebotOrders: WorkingOrder[] = [
  {
    id: "WO-9281",
    side: "long",
    type: "STOP",
    contracts: 2,
    limit_price: null,
    stop_price: 18_032.25,
    time_in_force: "DAY",
    submitted_at: NOW - 12 * MIN,
  },
  {
    id: "WO-9282",
    side: "long",
    type: "LIMIT",
    contracts: 2,
    limit_price: 18_063.0,
    stop_price: null,
    time_in_force: "DAY",
    submitted_at: NOW - 12 * MIN,
  },
];

const surgebotFills: Fill[] = [
  {
    id: "F-1144",
    ts: NOW - 12 * MIN,
    side: "long",
    contracts: 2,
    price: 18_042.5,
    realized_pnl: 0,
    realized_r: null,
    reason: "entry",
  },
  {
    id: "F-1141",
    ts: NOW - 95 * MIN,
    side: "long",
    contracts: 1,
    price: 18_031.25,
    realized_pnl: 167.5,
    realized_r: 1.5,
    reason: "target",
  },
  {
    id: "F-1140",
    ts: NOW - 122 * MIN,
    side: "short",
    contracts: 1,
    price: 18_018.75,
    realized_pnl: -55.0,
    realized_r: -1.0,
    reason: "stop",
  },
];

const surgebotEquity: EquityPoint[] = Array.from({ length: 60 }, (_, i) => ({
  ts: NOW - (60 - i) * MIN,
  equity: 49_000 + Math.sin(i / 6) * 60 + i * 3.3,
}));

export const mockBotDetail: Record<string, BotDetail> = {
  surgebot_nq: {
    summary: mockBots[0]!,
    position: surgebotPosition,
    working_orders: surgebotOrders,
    recent_fills: surgebotFills,
    intent: surgebotIntent,
    equity_series: surgebotEquity,
  },
};
