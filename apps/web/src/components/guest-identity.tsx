"use client";

import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui";
import { useGuestIdentity } from "@/lib/guest-chat";

/**
 * "Remember me" for visitors (Task 16): email → one-time code → verified. Also states how long
 * the chat and what the assistants remember are kept (PO decision U-12: the visitor is told).
 */
export function GuestIdentity({ slug, displayName, retentionDays }: {
  slug: string;
  displayName: string;
  retentionDays: number;
}) {
  const { identity, busy, error, start, confirm, forget, clearError } = useGuestIdentity(slug);
  const [step, setStep] = useState<"closed" | "email" | "code">("closed");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const id = useId();

  async function onEmail(e: FormEvent) {
    e.preventDefault();
    if (await start(email.trim())) setStep("code");
  }

  async function onCode(e: FormEvent) {
    e.preventDefault();
    if (await confirm(code.trim())) {
      setStep("closed");
      setCode("");
    }
  }

  const close = () => {
    setStep("closed");
    setCode("");
    clearError();
  };

  return (
    <div className="flex flex-col gap-2 text-xs text-ink-muted" data-testid="guest-identity">
      <p data-testid="retention-notice">
        Chats, and what {displayName}&apos;s assistants remember about you, are deleted after {retentionDays} days.
      </p>
      {identity.verified ? (
        <p className="flex flex-wrap items-center gap-x-2" data-testid="identity-verified">
          <span>
            Remembered as <span className="font-semibold text-ink">{identity.email_hint}</span>
          </span>
          <button
            type="button"
            onClick={() => void forget()}
            disabled={busy}
            className="font-semibold underline-offset-2 hover:underline"
          >
            Not you?
          </button>
        </p>
      ) : step === "closed" ? (
        <p>
          <button
            type="button"
            onClick={() => setStep("email")}
            className="font-semibold underline-offset-2 hover:underline"
          >
            Remember me next time
          </button>
        </p>
      ) : (
        <form
          onSubmit={step === "email" ? onEmail : onCode}
          className="flex flex-col gap-2 rounded-md border border-line bg-paper p-3"
          aria-label="Remember me"
        >
          <label htmlFor={`${id}-input`} className="font-semibold text-ink">
            {step === "email" ? "Your email" : "Code from the email"}
          </label>
          <p>
            {step === "email"
              ? "We'll email you a code. Once you enter it, the assistants can use what you told us before."
              : `We sent a 6-digit code to ${email.trim()}. It expires in 10 minutes.`}
          </p>
          <div className="flex flex-wrap items-end gap-2">
            {step === "email" ? (
              <input
                id={`${id}-input`}
                type="email"
                autoComplete="email"
                required
                maxLength={254}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="min-h-11 min-w-0 flex-1 basis-48 rounded-md border border-line-strong bg-surface px-3 text-base text-ink focus-visible:border-brand"
              />
            ) : (
              <input
                id={`${id}-input`}
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                required
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                className="min-h-11 w-32 rounded-md border border-line-strong bg-surface px-3 text-base tracking-widest text-ink focus-visible:border-brand"
              />
            )}
            <Button type="submit" size="sm" busy={busy}>
              {step === "email" ? "Send code" : "Confirm"}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={close} disabled={busy}>
              Cancel
            </Button>
          </div>
          {error ? (
            <p role="alert" className="text-danger">
              {error}
            </p>
          ) : null}
        </form>
      )}
    </div>
  );
}
