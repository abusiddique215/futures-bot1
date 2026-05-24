import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Settings as SettingsIcon } from "lucide-react";
import { api } from "@/lib/api";
import { getWsClient, type BotIntentData, type WsEvent } from "@/lib/ws";
import { useUiStore } from "@/store/ui";
import { BotIntentPanel } from "@/components/BotIntentPanel";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { EquityCurve } from "@/components/EquityCurve";
import { PositionsTable } from "@/components/PositionsTable";
import { TradeLog } from "@/components/TradeLog";
import { ParamsEditor } from "@/components/ParamsEditor";
import { dollars, pnlClass } from "@/lib/format";

/**
 * Per-bot detail page. Three-column trader layout:
 *
 *   [Intent + Snapshot]   [Equity curve]              [Positions + TradeLog]
 *
 * Live updates: subscribe to WS channel `bot:<name>` and patch the
 * TanStack Query cache on incoming account_update / fill / state_change
 * events. Latest `bot_intent` event drives the IntentPanel directly
 * (kept in local state since the intent payload isn't part of the REST
 * BotDetail shape).
 */
export function BotDetailPage() {
  const { name = "" } = useParams<{ name: string }>();
  const queryClient = useQueryClient();
  const noteEvent = useUiStore((s) => s.noteEvent);
  const activeProfile = useUiStore((s) => s.activeProfile);
  const [intent, setIntent] = useState<BotIntentData | null>(null);
  const [tuneOpen, setTuneOpen] = useState(false);

  const { data: detail, isLoading, error } = useQuery({
    queryKey: ["bot", name],
    queryFn: () => api.getBot(name),
    enabled: Boolean(name),
    refetchInterval: 10_000,
  });

  // ── WS subscription for live updates ─────────────────────────────────
  useEffect(() => {
    if (!name) return;
    const ws = getWsClient();
    const unsub = ws.onEvent((event: WsEvent) => {
      const data = event.data as { bot?: string };
      if (data.bot !== name) return;
      noteEvent(Date.now());
      switch (event.kind) {
        case "bot_intent":
          setIntent(event.data as BotIntentData);
          break;
        case "account_update":
        case "fill":
        case "bot_state_change":
          queryClient.invalidateQueries({ queryKey: ["bot", name] });
          break;
        default:
          // bar_tick / risk_decision are observed but don't require
          // re-fetch of the journal-derived detail.
          break;
      }
    });
    ws.connect();
    ws.subscribe(["fleet", `bot:${name}`]);
    return () => {
      unsub();
    };
  }, [name, queryClient, noteEvent]);

  if (!name) {
    return <div className="py-6 text-sm text-danger">Missing bot name.</div>;
  }
  if (isLoading) {
    return <div className="py-6 text-sm text-text-muted">Loading bot…</div>;
  }
  if (error || !detail) {
    return (
      <div className="py-6">
        <Card>
          <CardBody>
            <p className="text-sm text-danger">
              Failed to load <span className="font-mono">{name}</span>:{" "}
              {String(error)}
            </p>
          </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 py-4">
      {/* Left column: intent + snapshot */}
      <div className="lg:col-span-4 flex flex-col gap-4">
        <BotIntentPanel intent={intent} />
        <Card>
          <CardHeader>
            <CardTitle>{name}</CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setTuneOpen((v) => !v)}
              aria-expanded={tuneOpen}
            >
              <SettingsIcon className="h-3.5 w-3.5" aria-hidden />
              Tune
            </Button>
          </CardHeader>
          <CardBody className="grid grid-cols-2 gap-3 text-sm">
            <Snapshot
              label="State"
              value={detail.state.replace("_", " ")}
              tone={
                detail.state === "IN_TRADE"
                  ? "text-profit"
                  : detail.state === "DISABLED"
                    ? "text-text-muted"
                    : "text-info"
              }
            />
            <Snapshot label="Symbol" value={detail.symbol} mono />
            <Snapshot
              label="Realized today"
              value={dollars(detail.realized_pnl_today, { sign: true })}
              tone={pnlClass(detail.realized_pnl_today)}
              mono
            />
            <Snapshot label="Equity" value={dollars(detail.equity)} mono />
            <Snapshot
              label="High water"
              value={dollars(detail.high_water_equity)}
              mono
            />
            <Snapshot
              label="Enabled"
              value={detail.enabled ? "yes" : "no"}
              tone={detail.enabled ? "text-profit" : "text-loss"}
            />
          </CardBody>
        </Card>
        {tuneOpen && (
          <ParamsEditor botName={name} profileName={activeProfile} />
        )}
      </div>

      {/* Center: equity curve */}
      <div className="lg:col-span-5 flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Equity curve</CardTitle>
          </CardHeader>
          <CardBody>
            {detail.equity_curve.length > 1 ? (
              <EquityCurve series={detail.equity_curve} />
            ) : (
              <p className="text-xs text-text-muted py-8 text-center">
                No equity data yet — waiting for the first snapshot.
              </p>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Recent fills</CardTitle>
          </CardHeader>
          <CardBody>
            <TradeLog trades={detail.recent_trades} />
          </CardBody>
        </Card>
      </div>

      {/* Right column: positions + working orders placeholder */}
      <div className="lg:col-span-3 flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Positions</CardTitle>
          </CardHeader>
          <CardBody>
            <PositionsTable positions={detail.open_positions} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Working orders</CardTitle>
          </CardHeader>
          <CardBody>
            <p className="text-xs text-text-muted">
              Backend doesn't expose pending orders yet — ships in a
              follow-up plan.
            </p>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function Snapshot({
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
