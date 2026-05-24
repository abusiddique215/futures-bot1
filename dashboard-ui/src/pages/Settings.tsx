import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";

export function SettingsPage() {
  return (
    <div className="py-4">
      <Card>
        <CardHeader>
          <CardTitle>Settings</CardTitle>
        </CardHeader>
        <CardBody>
          <p className="text-sm text-text-secondary">
            Theme override, refresh rate, timezone — wired in T10. Defaults to
            dark mode (always on for the scaffold).
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
