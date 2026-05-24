/**
 * Test fixtures matching the real backend shapes (see `lib/api.ts`).
 * Used by Vitest component tests + the optional dev-mode skeleton.
 */

import type {
  AccountSummary,
  BotDetail,
  FleetBotEntry,
  FleetView,
} from "./api";
import type { BotIntentData } from "./ws";

export const mockBots: FleetBotEntry[] = [
  {
    name: "surgebot_nq",
    enabled: true,
    symbol: "MNQ",
    strategy_id: "orb_5m",
    status: "running",
  },
  {
    name: "propbot_es",
    enabled: true,
    symbol: "MES",
    strategy_id: "trend_ema_pullback",
    status: "running",
  },
  {
    name: "goldbot_gc",
    enabled: true,
    symbol: "MGC",
    strategy_id: "mean_reversion",
    status: "running",
  },
  {
    name: "es_scalper",
    enabled: false,
    symbol: "MES",
    strategy_id: "orb_5m_tiered",
    status: "no_data",
  },
  {
    name: "luxbot",
    enabled: true,
    symbol: "MNQ",
    strategy_id: "signal_strategy",
    status: "running",
  },
  {
    name: "nq_maintenance",
    enabled: true,
    symbol: "MNQ",
    strategy_id: "trend_ema_pullback",
    status: "running",
  },
];

export const mockAccount: AccountSummary = {
  balance: 49_120.5,
  equity: 49_197.5,
  open_pnl: 77.0,
  closed_pnl_today: 333.5,
  high_water: 49_460.0,
  contracts_open: 3,
};

export const mockFleet: FleetView = {
  bots: mockBots,
  heartbeat: new Date(Date.now() - 4_000).toISOString(),
  heartbeat_age: 4.0,
  active_profile: "default",
};

export const mockBotDetail: Record<string, BotDetail> = {
  surgebot_nq: {
    name: "surgebot_nq",
    symbol: "MNQ",
    enabled: true,
    state: "IN_TRADE",
    open_positions: { MNQ: 2 },
    realized_pnl_today: 312.5,
    equity: 49_197.5,
    high_water_equity: 49_460.0,
    recent_trades: [
      {
        client_order_id: "cid-1",
        symbol: "MNQ",
        side: "BUY",
        quantity: 2,
        fill_price: 18042.5,
        timestamp: new Date(Date.now() - 720_000).toISOString(),
      },
    ],
    equity_curve: Array.from({ length: 30 }, (_, i) => ({
      timestamp: new Date(Date.now() - (30 - i) * 60_000).toISOString(),
      equity: 49_000 + Math.sin(i / 4) * 50 + i * 6,
      realized_pnl: 0,
    })),
  },
};

export const mockIntent: BotIntentData = {
  bot: "surgebot_nq",
  watching_for: "Watching for ORB breakout > 18045.25 OR < 17988.50",
  schedule_open: true,
  next_window_opens_in_seconds: null,
  max_trades_remaining: 1,
};
