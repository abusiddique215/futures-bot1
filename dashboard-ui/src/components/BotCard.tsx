import { useState } from "react";
import { Link } from "react-router-dom";
import { Clock } from "lucide-react";
import type { BotSummary } from "@/lib/api";
import { contracts, dollars, pnlClass, price, rMultiple, timeAgo, timeUntil } from "@/lib/format";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { BotStateIndicator } from "@/components/BotStateIndicator";

interface Props {
  bot: BotSummary;
  /** Pass a fixed time for deterministic tests. */
  now?: number;
}

export function BotCard({ bot, now: nowProp }: Props) {
  // Snapshot clock once on first render when no `now` is supplied (test-friendly).
  const [fallbackNow] = useState(() => Date.now());
  const now = nowProp ?? fallbackNow;
  const inTrade = bot.position !== null;
  const positionLabel = inTrade
    ? contracts(bot.position!.contracts, bot.position!.side)
    : "Flat";

  return (
    <Link
      to={`/bots/${bot.name}`}
      className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-lg"
      aria-label={`Open ${bot.display_name} detail`}
    >
      <Card className="hover:border-border/80 hover:bg-bg-2 transition-colors p-4">
        {/* Top row: name + strategy + heartbeat */}
        <div className="flex items-start justify-between mb-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-text-primary truncate">
                {bot.display_name}
              </h3>
              <Badge tone="neutral">{bot.symbol}</Badge>
            </div>
            <p className="text-xs text-text-muted mt-0.5">{bot.strategy}</p>
          </div>
          <span
            className="text-[10px] text-text-muted font-mono shrink-0"
            title={`Last heartbeat: ${new Date(bot.last_heartbeat).toISOString()}`}
          >
            {timeAgo(bot.last_heartbeat, now)}
          </span>
        </div>

        {/* State line */}
        <BotStateIndicator
          state={bot.state}
          unrealizedR={bot.position?.unrealized_r ?? 0}
          className="mb-3"
        />

        {/* Position / metric grid */}
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Metric label="Position" value={positionLabel} mono={inTrade} />
          {inTrade ? (
            <Metric
              label="Open P&L"
              value={dollars(bot.position!.unrealized_pnl, { sign: true })}
              tone={pnlClass(bot.position!.unrealized_pnl)}
              mono
            />
          ) : bot.schedule_open ? (
            <Metric label="Open P&L" value={dollars(0, { sign: false })} mono tone="text-flat" />
          ) : (
            <ScheduleClosed nextOpen={bot.next_window_at} now={now} />
          )}

          <Metric
            label="Daily P&L"
            value={dollars(bot.daily_pnl, { sign: bot.daily_pnl !== 0 })}
            tone={pnlClass(bot.daily_pnl)}
            mono
          />
          <Metric
            label="Daily R"
            value={rMultiple(bot.daily_r)}
            tone={pnlClass(bot.daily_r)}
            mono
          />
        </div>

        {inTrade && bot.position && (
          <div className="mt-3 pt-3 border-t border-border text-[11px] text-text-muted font-mono flex justify-between">
            <span>Entry {price(bot.position.avg_price, bot.tick_size)}</span>
            <span>{bot.position.contracts}x</span>
          </div>
        )}
      </Card>
    </Link>
  );
}

function Metric({
  label,
  value,
  tone,
  mono,
}: {
  label: string;
  value: string;
  tone?: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-text-muted">{label}</div>
      <div
        className={[
          "text-sm font-medium",
          mono ? "font-mono" : "",
          tone ?? "text-text-primary",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {value}
      </div>
    </div>
  );
}

function ScheduleClosed({ nextOpen, now }: { nextOpen: number | null; now: number }) {
  if (nextOpen === null) {
    return (
      <div>
        <div className="text-[10px] uppercase tracking-wide text-text-muted">Schedule</div>
        <div className="text-xs text-text-secondary">Out of window</div>
      </div>
    );
  }
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-text-muted">Next window</div>
      <div className="text-xs text-info inline-flex items-center gap-1 font-mono">
        <Clock className="h-3 w-3" aria-hidden />
        in {timeUntil(nextOpen, now)}
      </div>
    </div>
  );
}
