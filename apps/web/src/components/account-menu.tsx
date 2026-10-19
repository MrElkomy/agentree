"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Dialog } from "@/components/dialog";
import { Popover, menuItemClass } from "@/components/popover";
import { useSession } from "@/components/session";
import { Alert, Button, TextField } from "@/components/ui";
import { api } from "@/lib/api";
import { MIN_PASSWORD, PASSWORD_HINT } from "@/lib/messages";

export function AccountMenu({
  align = "end",
  side = "bottom",
}: {
  align?: "start" | "end";
  side?: "top" | "bottom";
}) {
  const router = useRouter();
  const { me, handleError } = useSession();
  const [changing, setChanging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function logout(everywhere: boolean) {
    setError(null);
    try {
      await api(everywhere ? "/api/auth/logout-all" : "/api/auth/logout", "POST");
      // Leaving the (app) layout unmounts the session state.
      router.replace("/login");
    } catch (err) {
      setError(handleError(err));
    }
  }

  const initial = me.email.slice(0, 1).toUpperCase();

  return (
    <>
      <Popover
        label="Account menu"
        align={align}
        side={side}
        buttonClassName="flex size-10 items-center justify-center rounded-full bg-canopy font-display text-base font-bold text-white hover:bg-canopy-hover"
        button={<span aria-hidden="true">{initial}</span>}
      >
        {(close) => (
          <div className="flex flex-col">
            <div className="border-b border-line px-3 pt-2 pb-3">
              <p className="text-xs text-ink-muted">Signed in as</p>
              <p className="truncate text-sm font-semibold" data-testid="account-email">
                {me.email}
              </p>
            </div>
            {error ? (
              <div className="p-2">
                <Alert tone="error">{error}</Alert>
              </div>
            ) : null}
            <div className="flex flex-col py-1">
              <button
                type="button"
                className={menuItemClass}
                onClick={() => {
                  close();
                  setChanging(true);
                }}
              >
                Change password
              </button>
              <button type="button" className={menuItemClass} onClick={() => void logout(false)}>
                Log out
              </button>
              <button type="button" className={menuItemClass} onClick={() => void logout(true)}>
                Log out everywhere
              </button>
            </div>
          </div>
        )}
      </Popover>
      <Dialog
        open={changing}
        onClose={() => setChanging(false)}
        title="Change password"
        description="Your other devices will be signed out. This one stays signed in."
      >
        <ChangePasswordForm onDone={() => setChanging(false)} />
      </Dialog>
    </>
  );
}

function ChangePasswordForm({ onDone }: { onDone: () => void }) {
  const { handleError } = useSession();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (next.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters for the new password.`);
      return;
    }
    setBusy(true);
    try {
      await api("/api/auth/password/change", "POST", {
        current_password: current,
        new_password: next,
      });
      setDone(true);
    } catch (err) {
      setError(handleError(err));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="flex flex-col gap-4">
        <Alert tone="success">Password changed. Other devices have been signed out.</Alert>
        <Button onClick={onDone}>Done</Button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      {error ? <Alert tone="error">{error}</Alert> : null}
      <TextField
        label="Current password"
        type="password"
        autoComplete="current-password"
        required
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
      />
      <TextField
        label="New password"
        type="password"
        autoComplete="new-password"
        required
        minLength={MIN_PASSWORD}
        maxLength={256}
        hint={PASSWORD_HINT}
        value={next}
        onChange={(e) => setNext(e.target.value)}
      />
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" busy={busy}>
          Change password
        </Button>
      </div>
    </form>
  );
}
