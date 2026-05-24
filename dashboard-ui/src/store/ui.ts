import { create } from "zustand";
import type { WsStatus } from "@/lib/ws";

interface UiState {
  /** Active profile name — Topbar can switch. */
  activeProfile: string;
  setActiveProfile: (name: string) => void;

  /** Live WS connection status, mirrored from the singleton client. */
  wsStatus: WsStatus;
  setWsStatus: (status: WsStatus) => void;

  /** Server-reported timestamp of the latest event, for heartbeat freshness. */
  lastEventAt: number | null;
  noteEvent: (ts: number) => void;
}

export const useUiStore = create<UiState>((set) => ({
  activeProfile: "default",
  setActiveProfile: (name) => set({ activeProfile: name }),

  wsStatus: "closed",
  setWsStatus: (status) => set({ wsStatus: status }),

  lastEventAt: null,
  noteEvent: (ts) => set({ lastEventAt: ts }),
}));
