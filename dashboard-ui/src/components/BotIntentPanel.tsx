import { Eye, Lock } from "lucide-react";
import type { BotIntent } from "@/lib/api";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

interface Props {
  intent: BotIntent;
  className?: string;
}

/**
 * "What is the bot watching for?" — the most-requested research signal.
 * Renders plain-English intent + the structured detail.
 */
export function BotIntentPanel({ intent, className }: Props) {
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

        {Object.keys(intent.detail).length > 0 && (
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
            {Object.entries(intent.detail).map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-[11px] uppercase tracking-wide text-text-muted">
                  {key.replace(/_/g, " ")}
                </dt>
                <dd className="text-xs font-mono text-text-primary text-right">
                  {formatDetail(value)}
                </dd>
              </div>
            ))}
          </dl>
        )}

        {intent.max_trades_remaining !== null && (
          <p className="mt-3 text-xs text-text-secondary">
            Trades remaining this session:{" "}
            <span className="font-mono text-text-primary">
              {intent.max_trades_remaining}
            </span>
          </p>
        )}
      </CardBody>
    </Card>
  );
}

function formatDetail(value: number | string | boolean | null): string {
  if (value === null) return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toString() : value.toFixed(2);
  }
  if (typeof value === "boolean") return value ? "yes" : "no";
  return value;
}
