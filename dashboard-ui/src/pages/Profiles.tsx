import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";

export function ProfilesPage() {
  return (
    <div className="py-4">
      <Card>
        <CardHeader>
          <CardTitle>Profiles</CardTitle>
        </CardHeader>
        <CardBody>
          <p className="text-sm text-text-secondary">
            Profile CRUD (create / fork / delete / activate) ships in T10 against
            <span className="font-mono"> /api/profiles</span>.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
