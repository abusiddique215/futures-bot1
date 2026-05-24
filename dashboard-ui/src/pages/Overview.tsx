import { AccountStatePanel } from "@/components/AccountStatePanel";
import { FleetGrid } from "@/components/FleetGrid";
import { mockFleet } from "@/lib/mock";

/**
 * Overview page — scaffold renders the static mock fleet until the
 * backend `/api/fleet` endpoint is live. Replace `mockFleet` with the
 * TanStack Query result in T7.
 */
export function OverviewPage() {
  // TODO(T7): swap for useQuery({ queryKey: ['fleet'], queryFn: api.getFleet }).
  const { bots, account, server_time } = mockFleet;

  return (
    <div className="flex flex-col gap-4 py-4">
      <AccountStatePanel account={account} />

      <div className="flex items-baseline justify-between mt-2">
        <h2 className="text-base font-semibold text-text-primary">
          Fleet ({bots.length})
        </h2>
        <span className="text-xs text-text-muted font-mono">
          mock data · backend pending
        </span>
      </div>

      <FleetGrid bots={bots} now={server_time} />
    </div>
  );
}
