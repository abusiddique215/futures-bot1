import { Circle, Pause, TrendingDown, TrendingUp } from "lucide-react";
import type { BotState } from "@/lib/api";
import { cn } from "@/lib/utils";
import { rMultiple } from "@/lib/format";

interface Props {
  state: BotState;
  /** Unrealized R, only used when state === "IN_TRADE". */
  unrealizedR?: number;
  className?: string;
}

/**
 * The three explicit visual states: icon + dot/color + text label.
 * Trader-grade requirement: never communicate via color alone.
 */
export function BotStateIndicator({ state, unrealizedR = 0, className }: Props) {
  if (state === "DISABLED") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-2 text-text-muted text-xs font-medium uppercase tracking-wide",
          className,
        )}
      >
        <Pause className="h-3.5 w-3.5" aria-hidden />
        <span>Disabled</span>
      </span>
    );
  }
  if (state === "ARMED_WAITING") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-2 text-info text-xs font-medium uppercase tracking-wide",
          className,
        )}
      >
        <span className="pulse-dot bg-info" aria-hidden />
        <span>Armed — Watching</span>
      </span>
    );
  }
  if (state === "ERROR") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-2 text-danger text-xs font-medium uppercase tracking-wide",
          className,
        )}
      >
        <Circle className="h-3.5 w-3.5 fill-danger" aria-hidden />
        <span>Error</span>
      </span>
    );
  }
  // IN_TRADE — color reflects whether the open trade is favorable
  const Icon = unrealizedR >= 0 ? TrendingUp : TrendingDown;
  const tone = unrealizedR >= 0 ? "text-profit" : "text-loss";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 text-xs font-medium uppercase tracking-wide",
        tone,
        className,
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      <span>In Trade · {rMultiple(unrealizedR)}</span>
    </span>
  );
}
