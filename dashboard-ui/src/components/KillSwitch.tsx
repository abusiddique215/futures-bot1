import { useState } from "react";
import { AlertTriangle, Power } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";

interface Props {
  /**
   * Called when the user confirms the kill switch. Defaults to the live
   * REST endpoint; override in tests or storybook.
   */
  onConfirm?: () => Promise<unknown>;
}

/**
 * Always-reachable kill switch. Single click in the Topbar opens the modal;
 * a second confirmation triggers POST /api/bots/flatten_all.
 */
export function KillSwitch({ onConfirm }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      if (onConfirm) {
        await onConfirm();
      } else {
        await api.flattenAll();
      }
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to flatten");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button
        variant="danger"
        size="sm"
        onClick={() => setOpen(true)}
        aria-label="Flatten all positions (kill switch)"
      >
        <Power className="h-3.5 w-3.5" aria-hidden />
        Flatten All
      </Button>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="kill-switch-title"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
          onClick={() => !busy && setOpen(false)}
        >
          <div
            className="card-surface max-w-md w-full p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <AlertTriangle
                className="h-5 w-5 text-danger flex-shrink-0 mt-0.5"
                aria-hidden
              />
              <div className="flex-1">
                <h2
                  id="kill-switch-title"
                  className="text-base font-semibold text-text-primary"
                >
                  Flatten all open positions?
                </h2>
                <p className="mt-1 text-sm text-text-secondary">
                  This will market-close every open position across every bot.
                  Working orders will be cancelled. This action cannot be undone.
                </p>
                {error && (
                  <p className="mt-2 text-sm text-danger" role="alert">
                    {error}
                  </p>
                )}
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <Button
                variant="ghost"
                size="md"
                onClick={() => setOpen(false)}
                disabled={busy}
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                size="md"
                onClick={handleConfirm}
                disabled={busy}
              >
                {busy ? "Flattening…" : "Yes, flatten all"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
