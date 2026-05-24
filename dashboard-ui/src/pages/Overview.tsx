import { useEffect } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type BotDetail, type FleetView } from "@/lib/api";
import { AccountStatePanel } from "@/components/AccountStatePanel";
import { FleetGrid } from "@/components/FleetGrid";
import { useUiStore } from "@/store/ui";
import { getWsClient, type WsEvent } from "@/lib/ws";

/**
 * Overview — fleet summary + account roll-up. Live updates over WS.
 *
 * Data sources:
 *   - `useQuery(['fleet'])`           → /api/fleet (refetch every 5s).
 *   - `useQuery(['account_summary'])` → /api/account_summary (every 5s).
 *   - `useQueries(['bot', name])`     → /api/bots/<name> for each bot
 *     (lazy enrichment of the FleetGrid cards). Refetch on
 *     account_update/fill events for the matching bot.
 *   - WebSocket `/ws` (channel "fleet") — patches the query caches on
 *     incoming bar_tick / account_update / fill events.
 */
export function OverviewPage() {
  const queryClient = useQueryClient();
  const setWsStatus = useUiStore((s) => s.setWsStatus);
  const noteEvent = useUiStore((s) => s.noteEvent);
  const setActiveProfile = useUiStore((s) => s.setActiveProfile);

  const { data: fleet, isLoading, error } = useQuery({
    queryKey: ["fleet"],
    queryFn: api.getFleet,
    refetchInterval: 5_000,
  });

  // Keep Zustand activeProfile in sync with backend on every fleet refresh.
  useEffect(() => {
    if (fleet?.active_profile) setActiveProfile(fleet.active_profile);
  }, [fleet?.active_profile, setActiveProfile]);

  const { data: account } = useQuery({
    queryKey: ["account_summary"],
    queryFn: api.getAccountSummary,
    refetchInterval: 5_000,
  });

  const botQueries = useQueries({
    queries: (fleet?.bots ?? []).map((b) => ({
      queryKey: ["bot", b.name],
      queryFn: () => api.getBot(b.name),
      refetchInterval: 10_000,
      enabled: Boolean(fleet),
    })),
  });

  const details: Record<string, BotDetail | null> = {};
  (fleet?.bots ?? []).forEach((b, i) => {
    details[b.name] = (botQueries[i]?.data as BotDetail | undefined) ?? null;
  });

  // ── WebSocket subscription ────────────────────────────────────────────
  useEffect(() => {
    const ws = getWsClient();
    const unsubStatus = ws.onStatus(setWsStatus);
    const unsub = ws.onEvent((event: WsEvent) => {
      noteEvent(Date.now());
      // Any per-bot account or fill event invalidates the per-bot detail +
      // the aggregated account summary. Bar ticks are noisy and don't
      // change rolled-up numbers, so we leave the cache untouched.
      if (
        event.kind === "account_update" ||
        event.kind === "fill" ||
        event.kind === "bot_state_change"
      ) {
        const data = event.data as { bot?: string };
        if (data.bot) {
          queryClient.invalidateQueries({ queryKey: ["bot", data.bot] });
        }
        queryClient.invalidateQueries({ queryKey: ["account_summary"] });
        // Heartbeat update — the fleet query carries heartbeat_age.
        queryClient.invalidateQueries({ queryKey: ["fleet"] });
      }
    });
    ws.connect();
    ws.subscribe(["fleet"]);
    return () => {
      unsub();
      unsubStatus();
    };
  }, [queryClient, setWsStatus, noteEvent]);

  if (isLoading) return <LoadingState />;
  if (error || !fleet) return <ErrorState message={String(error)} />;

  return (
    <div className="flex flex-col gap-4 py-4">
      {account && <AccountStatePanel account={account} />}

      <div className="flex items-baseline justify-between mt-2">
        <h2 className="text-base font-semibold text-text-primary">
          Fleet ({fleet.bots.length})
        </h2>
        <FleetMetaLine fleet={fleet} />
      </div>

      <FleetGrid bots={fleet.bots} details={details} />
    </div>
  );
}

function FleetMetaLine({ fleet }: { fleet: FleetView }) {
  const hbLabel =
    fleet.heartbeat_age === null
      ? "no heartbeat"
      : `heartbeat ${Math.round(fleet.heartbeat_age)}s ago`;
  return (
    <span className="text-xs text-text-muted font-mono">
      profile: <span className="text-text-primary">{fleet.active_profile}</span>
      {" · "}
      {hbLabel}
    </span>
  );
}

function LoadingState() {
  return (
    <div className="py-8 text-sm text-text-muted">Loading fleet…</div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="py-8 text-sm text-danger" role="alert">
      Failed to load fleet: {message}
    </div>
  );
}
