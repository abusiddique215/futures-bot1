import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useUiStore } from "@/store/ui";
import { cn } from "@/lib/utils";

/**
 * Topbar dot showing live data feed health.
 *   green  — WS open AND fleet heartbeat fresh (<30s)
 *   amber  — WS connecting OR heartbeat stale (30-120s)
 *   red    — WS closed/error OR no heartbeat OR >120s old
 */
export function HeartbeatIndicator() {
  const wsStatus = useUiStore((s) => s.wsStatus);
  const { data: fleet } = useQuery({
    queryKey: ["fleet"],
    queryFn: api.getFleet,
    refetchInterval: 5_000,
  });

  const age = fleet?.heartbeat_age;
  const wsOk = wsStatus === "open";
  let tone: "ok" | "warn" | "down";
  let label: string;

  if (age === null || age === undefined) {
    tone = "down";
    label = "No heartbeat";
  } else if (age > 120) {
    tone = "down";
    label = `${Math.round(age)}s old`;
  } else if (age > 30 || !wsOk) {
    tone = "warn";
    label = wsOk ? `${Math.round(age)}s old` : wsStatus;
  } else {
    tone = "ok";
    label = "Live";
  }

  const toneClass =
    tone === "ok" ? "bg-profit" : tone === "warn" ? "bg-warn" : "bg-loss";

  return (
    <span
      className="inline-flex items-center gap-2 text-xs text-text-secondary"
      title={`WebSocket: ${wsStatus}; heartbeat age: ${age ?? "none"}`}
    >
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          toneClass,
          tone === "ok" && "animate-pulse-dot",
        )}
        aria-hidden
      />
      <span className="uppercase tracking-wide font-medium">{label}</span>
    </span>
  );
}
