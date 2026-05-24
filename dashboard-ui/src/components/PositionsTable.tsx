interface Props {
  positions: Record<string, number>;
}

/**
 * Current positions — symbol → signed qty (negative = short).
 * Backend exposes the dict on `BotDetail.open_positions`; richer
 * per-position state (avg price, stop, target, MFE/MAE) ships in a
 * later plan.
 */
export function PositionsTable({ positions }: Props) {
  const entries = Object.entries(positions).filter(([, qty]) => qty !== 0);
  if (entries.length === 0) {
    return (
      <div className="text-xs text-text-muted py-4 text-center">Flat.</div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-text-muted uppercase tracking-wide">
            <th className="text-left font-medium py-1.5 pr-2">Symbol</th>
            <th className="text-left font-medium py-1.5 pr-2">Side</th>
            <th className="text-right font-medium py-1.5">Qty</th>
          </tr>
        </thead>
        <tbody className="font-mono text-text-primary">
          {entries.map(([symbol, qty]) => (
            <tr key={symbol} className="border-t border-border/60">
              <td className="py-1.5 pr-2">{symbol}</td>
              <td
                className={
                  "py-1.5 pr-2 uppercase " +
                  (qty > 0 ? "text-profit" : "text-loss")
                }
              >
                {qty > 0 ? "Long" : "Short"}
              </td>
              <td className="py-1.5 text-right">{Math.abs(qty)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
