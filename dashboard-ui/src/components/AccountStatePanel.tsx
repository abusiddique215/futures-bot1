import { ArrowDown, ArrowRight, ArrowUp } from "lucide-react";
import type { AccountSummary } from "@/lib/api";
import { dollars, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Props {
  account: AccountSummary;
  className?: string;
}

/**
 * Risk header strip — fleet-aggregated rollup. Sourced from
 * `GET /api/account_summary` (sum across per-bot journal snapshots).
 *
 * Visible: Balance · Equity · Open P&L · Closed P&L Today · High Water ·
 * Contracts open. The full MLL / Profit Target progress bars need
 * per-account broker state that the backend doesn't expose yet — when
 * that lands (Plan 24+), they go here.
 */
export function AccountStatePanel({ account, className }: Props) {
  const equityDrawdown = account.high_water - account.equity;

  return (
    <div
      className={cn(
        "card-surface px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-3",
        className,
      )}
    >
      <Stat label="Balance" value={dollars(account.balance)} mono />
      <Stat label="Equity" value={dollars(account.equity)} mono />

      <Stat
        label="Open P&L"
        value={dollars(account.open_pnl, { sign: true })}
        tone={pnlClass(account.open_pnl)}
        arrow={signArrow(account.open_pnl)}
        mono
      />
      <Stat
        label="Closed Today"
        value={dollars(account.closed_pnl_today, { sign: true })}
        tone={pnlClass(account.closed_pnl_today)}
        arrow={signArrow(account.closed_pnl_today)}
        mono
      />
      <Stat label="High Water" value={dollars(account.high_water)} mono />
      <Stat
        label="Drawdown"
        value={dollars(equityDrawdown)}
        tone={equityDrawdown > 0 ? "text-loss" : "text-flat"}
        mono
      />
      <Stat
        label="Contracts"
        value={`${account.contracts_open}`}
        mono
        tone={account.contracts_open > 0 ? "text-accent" : "text-flat"}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
  mono,
  arrow,
}: {
  label: string;
  value: string;
  tone?: string;
  mono?: boolean;
  arrow?: "up" | "down" | "flat";
}) {
  const ArrowIcon =
    arrow === "up"
      ? ArrowUp
      : arrow === "down"
        ? ArrowDown
        : arrow === "flat"
          ? ArrowRight
          : null;
  return (
    <div className="min-w-[110px]">
      <div className="text-[10px] uppercase tracking-wide text-text-muted">
        {label}
      </div>
      <div
        className={cn(
          "text-sm font-medium inline-flex items-center gap-1.5",
          mono && "font-mono",
          tone ?? "text-text-primary",
        )}
      >
        {ArrowIcon && <ArrowIcon className="h-3.5 w-3.5" aria-hidden />}
        {value}
      </div>
    </div>
  );
}

function signArrow(value: number): "up" | "down" | "flat" {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "flat";
}
