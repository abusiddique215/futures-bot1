import { useParams } from "react-router-dom";
import { BotIntentPanel } from "@/components/BotIntentPanel";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { mockBotDetail } from "@/lib/mock";

export function BotDetailPage() {
  const { name = "" } = useParams<{ name: string }>();
  // TODO(T8): useQuery for /api/bots/{name}, subscribe to ws bot:<name>.
  const detail = mockBotDetail[name];

  if (!detail) {
    return (
      <div className="py-6">
        <Card>
          <CardBody>
            <p className="text-sm text-text-secondary">
              No mock data for <span className="font-mono">{name}</span> yet —
              once the backend ships, this page will render live data from
              <span className="font-mono"> /api/bots/{name}</span>.
            </p>
          </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 py-4">
      <div className="lg:col-span-4 flex flex-col gap-4">
        <BotIntentPanel intent={detail.intent} />
      </div>

      <div className="lg:col-span-5">
        <Card>
          <CardHeader>
            <CardTitle>Equity curve</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="text-xs text-text-muted">
              Chart goes here (lightweight-charts) — T8.
            </div>
          </CardBody>
        </Card>
      </div>

      <div className="lg:col-span-3 flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Working orders</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="text-xs text-text-muted">
              {detail.working_orders.length} pending — table in T8.
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Recent fills</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="text-xs text-text-muted">
              {detail.recent_fills.length} fills — log in T8.
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
