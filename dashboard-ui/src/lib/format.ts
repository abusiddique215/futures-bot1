/**
 * Formatting helpers — day-trader terminology.
 * Every numeric display goes through here so monospace + sign + color are consistent.
 */

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const USD_NO_CENTS = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

/**
 * Format dollars. Always shows sign for non-zero (so P&L is unambiguous).
 */
export function dollars(value: number, opts: { sign?: boolean; cents?: boolean } = {}): string {
  const { sign = false, cents = true } = opts;
  const fmt = cents ? USD : USD_NO_CENTS;
  const absStr = fmt.format(Math.abs(value));
  if (!sign || value === 0) {
    return value < 0 ? `-${absStr}` : absStr;
  }
  return `${value > 0 ? "+" : "-"}${absStr}`;
}

/**
 * R-multiple — outcome expressed as multiples of initial risk.
 * +1.5R, -1.0R, 0.0R
 */
export function rMultiple(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${Math.abs(value).toFixed(2)}R`;
}

/**
 * Tick-aware price formatter. tickSize defaults to 0.25 (NQ/MNQ).
 */
export function price(value: number, tickSize: number = 0.25): string {
  const decimals = decimalsForTick(tickSize);
  return value.toFixed(decimals);
}

function decimalsForTick(tickSize: number): number {
  if (tickSize >= 1) return 0;
  // Count fractional digits in the tick size string.
  const str = tickSize.toString();
  const dot = str.indexOf(".");
  if (dot === -1) return 0;
  return str.length - dot - 1;
}

/**
 * Percent. 0.0125 → "+1.25%".
 */
export function percent(ratio: number, opts: { sign?: boolean; decimals?: number } = {}): string {
  const { sign = false, decimals = 2 } = opts;
  const pct = ratio * 100;
  const abs = Math.abs(pct).toFixed(decimals);
  if (!sign || pct === 0) {
    return pct < 0 ? `-${abs}%` : `${abs}%`;
  }
  return `${pct > 0 ? "+" : "-"}${abs}%`;
}

/**
 * Contracts label — "1 contract" / "3 contracts" / "Flat".
 * side: "long" | "short" | null (null = flat)
 */
export function contracts(qty: number, side: "long" | "short" | null): string {
  if (qty === 0 || side === null) return "Flat";
  const word = qty === 1 ? "contract" : "contracts";
  const sideLabel = side === "long" ? "Long" : "Short";
  return `${sideLabel} ${qty} ${word}`;
}

const RELATIVE = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/**
 * Time-ago string for heartbeats, fills, etc. Input: ms epoch.
 * "12s ago", "3m ago", "2h ago"
 */
export function timeAgo(epochMs: number, nowMs: number = Date.now()): string {
  const deltaSec = Math.round((epochMs - nowMs) / 1000);
  const abs = Math.abs(deltaSec);
  if (abs < 5) return "just now";
  if (abs < 60) return RELATIVE.format(deltaSec, "second");
  if (abs < 3600) return RELATIVE.format(Math.round(deltaSec / 60), "minute");
  if (abs < 86_400) return RELATIVE.format(Math.round(deltaSec / 3600), "hour");
  return RELATIVE.format(Math.round(deltaSec / 86_400), "day");
}

/**
 * Time until — "Next window opens in 2h 14m".
 */
export function timeUntil(epochMs: number, nowMs: number = Date.now()): string {
  let deltaSec = Math.max(0, Math.round((epochMs - nowMs) / 1000));
  const days = Math.floor(deltaSec / 86_400);
  deltaSec -= days * 86_400;
  const hours = Math.floor(deltaSec / 3600);
  deltaSec -= hours * 3600;
  const mins = Math.floor(deltaSec / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  if (mins > 0) return `${mins}m`;
  return `${Math.max(1, deltaSec)}s`;
}

/**
 * Sign-aware classname helper.
 * Pass a number; returns the right Tailwind text class.
 */
export function pnlClass(value: number): string {
  if (value > 0) return "text-profit";
  if (value < 0) return "text-loss";
  return "text-flat";
}
