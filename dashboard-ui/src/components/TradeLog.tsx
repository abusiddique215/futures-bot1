import type { RecentTrade } from "@/lib/api";
import { dollars } from "@/lib/format";

interface Props {
  trades: RecentTrade[];
}

/**
 * Trade log — newest-first list of fills from the bot's journal.
 * The journal exposes up to ~20 recent fills by default; the panel
 * renders them as a static table (no virtualization needed at this
 * volume, and avoids pulling in an extra dep just to scroll <100 rows).
 */
export function TradeLog({ trades }: Props) {
  if (trades.length === 0) {
    return (
      <div className="text-xs text-text-muted py-4 text-center">
        No fills yet today.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-text-muted uppercase tracking-wide">
            <th className="text-left font-medium py-1.5 pr-2">When</th>
            <th className="text-left font-medium py-1.5 pr-2">Side</th>
            <th className="text-right font-medium py-1.5 pr-2">Qty</th>
            <th className="text-right font-medium py-1.5 pr-2">Price</th>
          </tr>
        </thead>
        <tbody className="font-mono text-text-primary">
          {trades.map((t) => (
            <tr key={t.client_order_id} className="border-t border-border/60">
              <td className="py-1.5 pr-2 text-text-secondary">
                {new Date(t.timestamp).toLocaleTimeString()}
              </td>
              <td
                className={
                  "py-1.5 pr-2 " +
                  (t.side === "BUY" || t.side === "long"
                    ? "text-profit"
                    : "text-loss")
                }
              >
                {t.side.toUpperCase()}
              </td>
              <td className="py-1.5 pr-2 text-right">{t.quantity}</td>
              <td className="py-1.5 pr-2 text-right">
                {dollars(t.fill_price)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
