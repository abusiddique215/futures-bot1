import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { api, type ProfileListResponse } from "@/lib/api";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";

/**
 * Profile manager — list, create (fork), delete, activate.
 * Confirmation modal on delete (cannot delete "default").
 */
export function ProfilesPage() {
  const queryClient = useQueryClient();
  const { data: profiles } = useQuery({
    queryKey: ["profiles"],
    queryFn: api.listProfiles,
  });

  const [newName, setNewName] = useState("");
  const [forkFrom, setForkFrom] = useState("default");
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["profiles"] });
    queryClient.invalidateQueries({ queryKey: ["fleet"] });
  };

  const create = useMutation({
    mutationFn: () => api.createProfile({ name: newName, fork_from: forkFrom }),
    onSuccess: () => {
      setNewName("");
      refresh();
    },
  });

  const activate = useMutation({
    mutationFn: (name: string) => api.activateProfile(name),
    onSuccess: () => refresh(),
  });

  const remove = useMutation({
    mutationFn: (name: string) => api.deleteProfile(name),
    onSuccess: () => {
      setPendingDelete(null);
      refresh();
    },
  });

  return (
    <div className="py-4 flex flex-col gap-4 max-w-3xl">
      <Card>
        <CardHeader>
          <CardTitle>Create profile</CardTitle>
        </CardHeader>
        <CardBody className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-text-secondary flex flex-col gap-1">
            <span className="uppercase tracking-wide">Name</span>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="alice"
              className="bg-bg-2 border border-border rounded px-2 py-1 text-sm font-mono text-text-primary"
            />
          </label>
          <label className="text-xs text-text-secondary flex flex-col gap-1">
            <span className="uppercase tracking-wide">Fork from</span>
            <select
              value={forkFrom}
              onChange={(e) => setForkFrom(e.target.value)}
              className="bg-bg-2 border border-border rounded px-2 py-1 text-sm font-mono text-text-primary"
            >
              {(profiles?.profiles ?? ["default"]).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <Button
            variant="primary"
            size="sm"
            onClick={() => create.mutate()}
            disabled={create.isPending || !newName.trim()}
          >
            {create.isPending ? "Creating…" : "Create"}
          </Button>
          {create.error && (
            <p className="text-xs text-danger w-full" role="alert">
              {(create.error as Error).message}
            </p>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Profiles</CardTitle>
        </CardHeader>
        <CardBody>
          {!profiles ? (
            <p className="text-sm text-text-muted">Loading…</p>
          ) : (
            <ProfileList
              profiles={profiles}
              onActivate={(name) => activate.mutate(name)}
              onDeleteRequest={(name) => setPendingDelete(name)}
            />
          )}
        </CardBody>
      </Card>

      {pendingDelete && (
        <ConfirmDeleteModal
          name={pendingDelete}
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => remove.mutate(pendingDelete)}
          busy={remove.isPending}
          error={remove.error ? (remove.error as Error).message : null}
        />
      )}
    </div>
  );
}

function ProfileList({
  profiles,
  onActivate,
  onDeleteRequest,
}: {
  profiles: ProfileListResponse;
  onActivate: (name: string) => void;
  onDeleteRequest: (name: string) => void;
}) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-text-muted uppercase tracking-wide text-xs">
          <th className="text-left font-medium py-1.5 pr-2">Name</th>
          <th className="text-left font-medium py-1.5 pr-2">Status</th>
          <th className="text-right font-medium py-1.5"></th>
        </tr>
      </thead>
      <tbody>
        {profiles.profiles.map((name) => (
          <tr key={name} className="border-t border-border/60">
            <td className="py-2 pr-2 font-mono text-text-primary">{name}</td>
            <td className="py-2 pr-2">
              {name === profiles.active ? (
                <Badge tone="info">active</Badge>
              ) : (
                <span className="text-text-muted text-xs">—</span>
              )}
            </td>
            <td className="py-2 text-right">
              <div className="inline-flex items-center gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onActivate(name)}
                  disabled={name === profiles.active}
                >
                  Activate
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => onDeleteRequest(name)}
                  disabled={name === "default"}
                  aria-label={`Delete profile ${name}`}
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                </Button>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ConfirmDeleteModal({
  name,
  onCancel,
  onConfirm,
  busy,
  error,
}: {
  name: string;
  onCancel: () => void;
  onConfirm: () => void;
  busy: boolean;
  error: string | null;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      onClick={() => !busy && onCancel()}
    >
      <div
        className="card-surface max-w-md w-full p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="delete-title" className="text-base font-semibold text-text-primary">
          Delete profile <span className="font-mono">{name}</span>?
        </h2>
        <p className="mt-1 text-sm text-text-secondary">
          The overrides and audit log for this profile will be removed.
          This cannot be undone.
        </p>
        {error && (
          <p className="mt-2 text-sm text-danger" role="alert">
            {error}
          </p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" size="md" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant="danger" size="md" onClick={onConfirm} disabled={busy}>
            {busy ? "Deleting…" : "Delete"}
          </Button>
        </div>
      </div>
    </div>
  );
}
