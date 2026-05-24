import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";

type Block = "strategy_params" | "risk_params" | "schedule_params";
const BLOCKS: Block[] = ["strategy_params", "risk_params", "schedule_params"];

interface Props {
  botName: string;
  /** Active profile to which overrides are written. */
  profileName: string;
}

/**
 * ParamsEditor — diff-preview editor for one bot's parameter blocks.
 *
 * Renders three blocks (strategy_params, risk_params, schedule_params).
 * For each key currently overridden in the profile, shows base vs
 * override side-by-side and lets the user edit / reset.
 *
 * Base values are fetched from the bot detail's effective spec
 * (`/api/bots/{name}` doesn't expose those today, so we use the most
 * recent `setOverride` response when available, else show "—"). When
 * the user types a new override and hits Save, we PUT
 * `/api/profiles/{name}/overrides/{bot}/{block}` with `{key, value}`.
 *
 * "Reset to base" is a no-op placeholder for now — the backend doesn't
 * expose a delete-one-override endpoint, so resetting requires editing
 * the YAML directly. We surface the limitation in the UI rather than
 * pretending the action worked.
 */
export function ParamsEditor({ botName, profileName }: Props) {
  const queryClient = useQueryClient();
  const { data: overrides, isLoading } = useQuery({
    queryKey: ["overrides", profileName],
    queryFn: () => api.getOverrides(profileName),
  });

  const botOverrides = overrides?.overrides[botName] ?? {};

  // Local form state for new keys: a freeform "add an override" row per block.
  const [draft, setDraft] = useState<
    Record<Block, { key: string; value: string }>
  >({
    strategy_params: { key: "", value: "" },
    risk_params: { key: "", value: "" },
    schedule_params: { key: "", value: "" },
  });

  const save = useMutation({
    mutationFn: (args: {
      block: Block;
      key: string;
      value: unknown;
    }) =>
      api.setOverride(profileName, botName, args.block, args.key, args.value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["overrides", profileName] });
      queryClient.invalidateQueries({ queryKey: ["bot", botName] });
    },
  });

  const handleSave = (block: Block, key: string, raw: string) => {
    if (!key.trim()) return;
    // Best-effort literal parse: numeric → number, "true"/"false" → bool,
    // otherwise pass-through string. Backend re-validates by re-running
    // the factory and returns 400 on bad shape.
    const parsed = parseValue(raw);
    save.mutate({ block, key: key.trim(), value: parsed });
  };

  if (isLoading) {
    return (
      <Card>
        <CardBody>
          <p className="text-sm text-text-muted">Loading overrides…</p>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="inline-flex items-center gap-2">
          Tune Bot
          <Badge tone="info">{profileName}</Badge>
        </CardTitle>
        {save.isSuccess && (
          <Badge tone="info">Saved · restart required</Badge>
        )}
      </CardHeader>
      <CardBody className="flex flex-col gap-5">
        {BLOCKS.map((block) => (
          <BlockEditor
            key={block}
            block={block}
            overrides={botOverrides[block] ?? {}}
            draftKey={draft[block].key}
            draftValue={draft[block].value}
            onDraftKey={(v) =>
              setDraft((d) => ({
                ...d,
                [block]: { ...d[block], key: v },
              }))
            }
            onDraftValue={(v) =>
              setDraft((d) => ({
                ...d,
                [block]: { ...d[block], value: v },
              }))
            }
            onSave={(k, v) => handleSave(block, k, v)}
            saving={save.isPending}
          />
        ))}
        {save.error && (
          <p className="text-xs text-danger" role="alert">
            Save failed: {(save.error as Error).message}
          </p>
        )}
      </CardBody>
    </Card>
  );
}

function BlockEditor({
  block,
  overrides,
  draftKey,
  draftValue,
  onDraftKey,
  onDraftValue,
  onSave,
  saving,
}: {
  block: Block;
  overrides: Record<string, unknown>;
  draftKey: string;
  draftValue: string;
  onDraftKey: (v: string) => void;
  onDraftValue: (v: string) => void;
  onSave: (key: string, raw: string) => void;
  saving: boolean;
}) {
  const entries = useMemo(() => Object.entries(overrides), [overrides]);
  return (
    <section>
      <h3 className="text-xs uppercase tracking-wide text-text-muted mb-2">
        {block}
      </h3>

      {/* Current overrides (diff view: base vs override). Base column is
          "—" because the backend doesn't return the base alongside the
          overrides; the operator sees them by switching profiles. */}
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-text-muted">
            <th className="text-left font-medium pr-2 pb-1">Key</th>
            <th className="text-left font-medium pr-2 pb-1">Base</th>
            <th className="text-left font-medium pr-2 pb-1">Override</th>
            <th className="text-right font-medium pb-1"></th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k} className="border-t border-border/60">
              <td className="py-1.5 pr-2 text-text-primary">{k}</td>
              <td className="py-1.5 pr-2 text-text-muted">—</td>
              <td className="py-1.5 pr-2 text-text-primary">{formatVal(v)}</td>
              <td className="py-1.5 text-right">
                <button
                  onClick={() => onSave(k, formatVal(v))}
                  className="text-xs text-text-muted hover:text-text-primary"
                  type="button"
                  disabled
                  title="Backend does not expose a per-key reset endpoint yet — edit overrides.yaml directly to reset."
                >
                  Reset
                </button>
              </td>
            </tr>
          ))}
          {entries.length === 0 && (
            <tr>
              <td colSpan={4} className="py-2 text-text-muted">
                No overrides set.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {/* Add / set one override */}
      <div className="mt-2 flex items-center gap-2 text-xs">
        <input
          aria-label={`${block} key`}
          placeholder="key"
          value={draftKey}
          onChange={(e) => onDraftKey(e.target.value)}
          className="bg-bg-2 border border-border rounded px-2 py-1 font-mono text-text-primary w-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        />
        <input
          aria-label={`${block} value`}
          placeholder="value"
          value={draftValue}
          onChange={(e) => onDraftValue(e.target.value)}
          className="bg-bg-2 border border-border rounded px-2 py-1 font-mono text-text-primary flex-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        />
        <Button
          size="sm"
          variant="primary"
          onClick={() => onSave(draftKey, draftValue)}
          disabled={saving || !draftKey.trim()}
        >
          Save
        </Button>
      </div>
    </section>
  );
}

function formatVal(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

function parseValue(raw: string): unknown {
  const t = raw.trim();
  if (t === "") return "";
  if (t === "true") return true;
  if (t === "false") return false;
  if (t === "null") return null;
  const num = Number(t);
  if (!Number.isNaN(num) && /^-?\d/.test(t)) return num;
  // Try JSON parse for arrays/objects.
  try {
    return JSON.parse(t);
  } catch {
    return t;
  }
}
