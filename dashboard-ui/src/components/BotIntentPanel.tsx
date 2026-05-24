import { Eye, Lock } from "lucide-react";
import type { BotIntentData } from "@/lib/ws";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

interface Props {
  /** Latest BotIntentData event for this bot, or null if none received. */
  intent: BotIntentData | null;
  className?: string;
}

/**
 * "What is the bot watching for?" — the most-requested research signal.
 * Renders plain-English intent + window state. The backend emits one
 * BotIntentEvent per bar, so this panel updates each tick.
 */
export function BotIntentPanel({ intent, className }: Props) {
  if (intent === null) {
    return (
      <Card className={className}>
        <CardHeader>
          <CardTitle>Intent</CardTitle>
        </CardHeader>
        <CardBody>
          <p className="text-sm text-text-muted">
            Waiting for the first bar to determine intent…
          </p>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="inline-flex items-center gap-2">
          {intent.schedule_open ? (
            <Eye className="h-4 w-4 text-info" aria-hidden />
          ) : (
            <Lock className="h-4 w-4 text-text-muted" aria-hidden />
          )}
          Intent
        </CardTitle>
        <Badge tone={intent.schedule_open ? "info" : "neutral"}>
          {intent.schedule_open ? "Window open" : "Window closed"}
        </Badge>
      </CardHeader>
      <CardBody>
        <p className="text-sm text-text-primary leading-relaxed font-mono">
          {intent.watching_for}
        </p>

        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
          {intent.next_window_opens_in_seconds !== null && (
            <>
              <dt className="text-[11px] uppercase tracking-wide text-text-muted">
                Next window
              </dt>
              <dd className="text-xs font-mono text-text-primary text-right">
                {formatSeconds(intent.next_window_opens_in_seconds)}
              </dd>
            </>
          )}
          {intent.max_trades_remaining !== null && (
            <>
              <dt className="text-[11px] uppercase tracking-wide text-text-muted">
                Trades remaining
              </dt>
              <dd className="text-xs font-mono text-text-primary text-right">
                {intent.max_trades_remaining}
              </dd>
            </>
          )}
        </dl>
      </CardBody>
    </Card>
  );
}

function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}
