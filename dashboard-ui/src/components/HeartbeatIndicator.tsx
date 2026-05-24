import { useUiStore } from "@/store/ui";
import { cn } from "@/lib/utils";

/**
 * Topbar dot showing live data feed health.
 *   green  — open
 *   amber  — connecting
 *   red    — closed/error
 */
export function HeartbeatIndicator() {
  const status = useUiStore((s) => s.wsStatus);

  const tone =
    status === "open"
      ? "bg-profit"
      : status === "connecting"
        ? "bg-warn"
        : "bg-loss";
  const label =
    status === "open"
      ? "Live"
      : status === "connecting"
        ? "Connecting"
        : status === "error"
          ? "Disconnected"
          : "Offline";

  return (
    <span
      className="inline-flex items-center gap-2 text-xs text-text-secondary"
      title={`WebSocket: ${status}`}
    >
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          tone,
          status === "open" && "animate-pulse-dot",
        )}
        aria-hidden
      />
      <span className="uppercase tracking-wide font-medium">{label}</span>
    </span>
  );
}
