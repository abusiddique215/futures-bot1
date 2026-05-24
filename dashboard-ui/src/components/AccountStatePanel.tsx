import { ArrowDown, ArrowRight, ArrowUp } from "lucide-react";
import type { AccountSummary } from "@/lib/api";
import { dollars, percent, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Props {
  account: AccountSummary;
  className?: string;
}

/**
 * Risk header strip — fixed at the top of every screen.
 * Balance · Equity · Open P&L · Closed P&L Today · MLL distance · Profit Target · Contracts open
 *
 * Every value carries: color (sign-aware) + arrow icon + monospace number.
 * Visual hierarchy: risk warnings (MLL) dominate when distance shrinks.
 */
export function AccountStatePanel({ account, className }: Props) {
  const mllRatio = mllProgress(account);
  const targetRatio = targetProgress(account);
  const mllTone = mllRatio > 0.5 ? "bg-danger" : mllRatio > 0.25 ? "bg-warn" : "bg-profit";

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

      {/* MLL distance — drains red as equity approaches MLL */}
      <div className="min-w-[180px]">
        <div className="flex items-baseline justify-between">
          <span className="text-[10px] uppercase tracking-wide text-text-muted">
            Distance to MLL
          </span>
          <span className="text-xs text-text-muted font-mono">
            {percent(mllRatio)} used
          </span>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <span className="font-mono text-sm text-text-primary">
            {dollars(account.distance_to_mll)}
          </span>
        </div>
        <div className="mt-1 h-1.5 bg-bg-3 rounded overflow-hidden">
          <div
            className={cn("h-full transition-all", mllTone)}
            style={{ width: `${Math.min(100, Math.round(mllRatio * 100))}%` }}
            role="progressbar"
            aria-valuenow={Math.round(mllRatio * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="MLL usage"
          />
        </div>
      </div>

      {/* Profit target progress */}
      <div className="min-w-[180px]">
        <div className="flex items-baseline justify-between">
          <span className="text-[10px] uppercase tracking-wide text-text-muted">
            To Profit Target
          </span>
          <span className="text-xs text-text-muted font-mono">
            {percent(targetRatio)} done
          </span>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <span className="font-mono text-sm text-text-primary">
            {dollars(account.distance_to_target)}
          </span>
        </div>
        <div className="mt-1 h-1.5 bg-bg-3 rounded overflow-hidden">
          <div
            className="h-full bg-profit transition-all"
            style={{ width: `${Math.min(100, Math.max(0, Math.round(targetRatio * 100)))}%` }}
            role="progressbar"
            aria-valuenow={Math.round(targetRatio * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Profit target progress"
          />
        </div>
      </div>

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
    arrow === "up" ? ArrowUp : arrow === "down" ? ArrowDown : arrow === "flat" ? ArrowRight : null;
  return (
    <div className="min-w-[110px]">
      <div className="text-[10px] uppercase tracking-wide text-text-muted">{label}</div>
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

function mllProgress(a: AccountSummary): number {
  // Fraction of the buffer between high_water and MLL that has been consumed.
  const buffer = a.high_water - a.mll_value;
  if (buffer <= 0) return 1;
  const used = a.high_water - a.equity;
  return Math.max(0, Math.min(1, used / buffer));
}

function targetProgress(a: AccountSummary): number {
  // Span: from MLL floor up to the profit target. Fill = how high equity has climbed.
  const span = a.target_value - a.mll_value;
  if (span <= 0) return 0;
  return Math.max(0, Math.min(1, (a.equity - a.mll_value) / span));
}
