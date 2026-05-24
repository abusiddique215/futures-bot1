import { Link } from "react-router-dom";
import type { BotDetail, FleetBotEntry } from "@/lib/api";
import { dollars, pnlClass } from "@/lib/format";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { BotStateIndicator } from "@/components/BotStateIndicator";

interface Props {
  bot: FleetBotEntry;
  /** Lazy per-bot detail (positions, P&L) for the card body. Optional —
   *  card renders a skeleton row when unavailable. */
  detail?: BotDetail | null;
}

export function BotCard({ bot, detail }: Props) {
  // Derive a "state" tag that doesn't require the per-bot detail call
  // to be in flight — when no detail, fall back to enabled/disabled and
  // journal status.
  const state = detail
    ? detail.state
    : !bot.enabled
      ? "DISABLED"
      : "ARMED_WAITING";
  const positionsCount = detail
    ? Object.values(detail.open_positions).filter((q) => q !== 0).length
    : 0;
  const flat = positionsCount === 0;

  return (
    <Link
      to={`/bots/${bot.name}`}
      className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-lg"
      aria-label={`Open ${bot.name} detail`}
    >
      <Card className="hover:border-border/80 hover:bg-bg-2 transition-colors p-4">
        {/* Top row: name + strategy + status badge */}
        <div className="flex items-start justify-between mb-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-text-primary truncate">
                {bot.name}
              </h3>
              <Badge tone="neutral">{bot.symbol}</Badge>
            </div>
            <p className="text-xs text-text-muted mt-0.5">{bot.strategy_id}</p>
          </div>
          <Badge tone={bot.status === "running" ? "info" : "neutral"}>
            {bot.status}
          </Badge>
        </div>

        {/* State line */}
        <BotStateIndicator state={state} className="mb-3" />

        {/* Metric grid */}
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Metric
            label="Position"
            value={flat ? "Flat" : `${positionsCount} open`}
            mono={!flat}
          />
          <Metric
            label="Daily P&L"
            value={detail ? dollars(detail.realized_pnl_today, { sign: true }) : "—"}
            tone={detail ? pnlClass(detail.realized_pnl_today) : undefined}
            mono
          />
          <Metric
            label="Equity"
            value={detail ? dollars(detail.equity) : "—"}
            mono
          />
          <Metric
            label="High water"
            value={detail ? dollars(detail.high_water_equity) : "—"}
            mono
          />
        </div>
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
      <div className="text-[10px] uppercase tracking-wide text-text-muted">
        {label}
      </div>
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
