"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { AuthHeading, recallNext, withNext } from "@/components/auth";
import { Alert, Button, Spinner, TextField, buttonClass } from "@/components/ui";
import { api } from "@/lib/api";
import { messageFor } from "@/lib/messages";

type State = "verifying" | "verified" | "failed" | "no-token";

export function VerifyEmail() {
  const params = useSearchParams();
  const [token] = useState(() => params.get("token"));
  const [state, setState] = useState<State>(token ? "verifying" : "no-token");
  const [error, setError] = useState<string | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const submitted = useRef(false);

  useEffect(() => {
    if (!token || submitted.current) return;
    // Tokens are single-use: guard against double effects (React strict mode).
    submitted.current = true;
    // Keep the token out of the address bar and history once read.
    window.history.replaceState(null, "", "/verify-email");
    api("/api/auth/verify-email", "POST", { token })
      .then(() => {
        setNext(recallNext());
        setState("verified");
      })
      .catch((err: unknown) => {
        setError(messageFor(err));
        setState("failed");
      });
  }, [token]);

  if (state === "verifying") {
    return (
      <>
        <AuthHeading title="Verifying your email" />
        <Spinner label="Confirming your link…" />
      </>
    );
  }

  if (state === "verified") {
    return (
      <>
        <AuthHeading title="Email verified">Your account is ready. Sign in to continue.</AuthHeading>
        <Link href={withNext("/login", next)} className={`${buttonClass()} w-full`}>
          Continue to sign in
        </Link>
      </>
    );
  }

  return (
    <>
      <AuthHeading title={state === "failed" ? "We couldn't verify your email" : "Verify your email"}>
        Enter your email and we&apos;ll send a new verification link.
      </AuthHeading>
      {error ? (
        <div className="mb-5">
          <Alert tone="error">{error}</Alert>
        </div>
      ) : null}
      <ResendForm />
    </>
  );
}

function ResendForm() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/resend-verification", "POST", { email });
      setDone(true);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <Alert tone="success">
        If that account needs verifying, a new link is on its way. Check your inbox.
      </Alert>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5">
      {error ? <Alert tone="error">{error}</Alert> : null}
      <TextField
        label="Email"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <Button type="submit" busy={busy}>
        Send verification link
      </Button>
      <Link href="/login" className="text-center text-sm font-semibold text-brand underline-offset-4 hover:underline">
        Back to sign in
      </Link>
    </form>
  );
}
