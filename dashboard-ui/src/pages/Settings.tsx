import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useUiStore } from "@/store/ui";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

type Theme = "dark" | "light" | "system";

const REFRESH_OPTIONS = [
  { label: "1 second", value: 1_000 },
  { label: "5 seconds (default)", value: 5_000 },
  { label: "15 seconds", value: 15_000 },
  { label: "30 seconds", value: 30_000 },
];

const TZ_OPTIONS = [
  "UTC",
  "America/Chicago",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/London",
];

/**
 * Settings — UI preferences persisted to the active profile's prefs.json
 * (via PUT /api/profiles/{name}/prefs). Theme defaults to dark.
 */
export function SettingsPage() {
  const queryClient = useQueryClient();
  const activeProfile = useUiStore((s) => s.activeProfile);

  const { data: prefs } = useQuery({
    queryKey: ["prefs", activeProfile],
    queryFn: () => api.getPrefs(activeProfile),
  });

  // Local overrides applied on top of the fetched prefs. Saving clears
  // the overrides so the fresh server values become the source of truth.
  const [overrides, setOverrides] = useState<{
    theme?: Theme;
    refresh_rate_ms?: number;
    timezone?: string;
  }>({});

  const serverPrefs = (prefs?.prefs ?? {}) as Record<string, unknown>;
  const theme: Theme =
    overrides.theme ??
    (typeof serverPrefs.theme === "string"
      ? (serverPrefs.theme as Theme)
      : "dark");
  const refreshMs: number =
    overrides.refresh_rate_ms ??
    (typeof serverPrefs.refresh_rate_ms === "number"
      ? serverPrefs.refresh_rate_ms
      : 5_000);
  const tz: string =
    overrides.timezone ??
    (typeof serverPrefs.timezone === "string"
      ? serverPrefs.timezone
      : "America/Chicago");

  const setTheme = (v: Theme) =>
    setOverrides((o) => ({ ...o, theme: v }));
  const setRefreshMs = (v: number) =>
    setOverrides((o) => ({ ...o, refresh_rate_ms: v }));
  const setTz = (v: string) =>
    setOverrides((o) => ({ ...o, timezone: v }));

  const save = useMutation({
    mutationFn: () =>
      api.setPrefs(activeProfile, {
        theme,
        refresh_rate_ms: refreshMs,
        timezone: tz,
      }),
    onSuccess: () => {
      setOverrides({});
      queryClient.invalidateQueries({ queryKey: ["prefs", activeProfile] });
    },
  });

  return (
    <div className="py-4 max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle>Settings</CardTitle>
          <span className="text-xs text-text-muted font-mono">
            profile: {activeProfile}
          </span>
        </CardHeader>
        <CardBody className="flex flex-col gap-5">
          <Field label="Theme">
            <select
              value={theme}
              onChange={(e) => setTheme(e.target.value as Theme)}
              className="bg-bg-2 border border-border rounded px-2 py-1 text-sm font-mono text-text-primary"
            >
              <option value="dark">dark (default)</option>
              <option value="light">light</option>
              <option value="system">system</option>
            </select>
            {theme !== "dark" && (
              <p className="mt-1 text-xs text-text-muted">
                Note: light/system themes ship in a follow-up — dark stays
                forced for now (the trader-grade default).
              </p>
            )}
          </Field>

          <Field label="Refresh rate">
            <select
              value={refreshMs}
              onChange={(e) => setRefreshMs(Number(e.target.value))}
              className="bg-bg-2 border border-border rounded px-2 py-1 text-sm font-mono text-text-primary"
            >
              {REFRESH_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Timezone">
            <select
              value={tz}
              onChange={(e) => setTz(e.target.value)}
              className="bg-bg-2 border border-border rounded px-2 py-1 text-sm font-mono text-text-primary"
            >
              {TZ_OPTIONS.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </Field>

          <div className="flex items-center gap-3">
            <Button
              variant="primary"
              size="sm"
              onClick={() => save.mutate()}
              disabled={save.isPending}
            >
              {save.isPending ? "Saving…" : "Save"}
            </Button>
            {save.isSuccess && (
              <span className="text-xs text-profit">Saved.</span>
            )}
            {save.error && (
              <span className="text-xs text-danger" role="alert">
                {(save.error as Error).message}
              </span>
            )}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs uppercase tracking-wide text-text-muted">
        {label}
      </span>
      {children}
    </label>
  );
}
