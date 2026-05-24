import type { BotDetail, FleetBotEntry } from "@/lib/api";
import { BotCard } from "@/components/BotCard";

interface Props {
  bots: FleetBotEntry[];
  /** Optional per-bot detail map, keyed by bot.name, used to enrich cards. */
  details?: Record<string, BotDetail | null>;
}

export function FleetGrid({ bots, details }: Props) {
  if (bots.length === 0) {
    return (
      <div className="card-surface p-6 text-center text-text-muted text-sm">
        No bots configured.
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {bots.map((bot) => (
        <BotCard key={bot.name} bot={bot} detail={details?.[bot.name] ?? null} />
      ))}
    </div>
  );
}
