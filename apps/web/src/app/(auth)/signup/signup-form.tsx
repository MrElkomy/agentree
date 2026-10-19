"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { AuthHeading, rememberNext, withNext } from "@/components/auth";
import { Alert, Button, TextField } from "@/components/ui";
import { api, safeNext } from "@/lib/api";
import { MIN_PASSWORD, PASSWORD_HINT, messageFor } from "@/lib/messages";

export function SignupForm() {
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [resent, setResent] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD) {
      setPasswordError(`Use at least ${MIN_PASSWORD} characters.`);
      return;
    }
    setPasswordError(null);
    setBusy(true);
    try {
      await api("/api/auth/register", "POST", { email, password });
      rememberNext(next);
      setSentTo(email);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    if (!sentTo) return;
    try {
      await api("/api/auth/resend-verification", "POST", { email: sentTo });
      setResent(true);
    } catch (err) {
      setError(messageFor(err));
    }
  }

  if (sentTo) {
    return (
      <>
        <AuthHeading title="Check your email">
          We sent a verification link to <strong className="text-ink">{sentTo}</strong>. Open it to
          activate your account. The link expires in 24 hours.
        </AuthHeading>
        <div className="flex flex-col gap-4">
          {error ? <Alert tone="error">{error}</Alert> : null}
          {resent ? <Alert tone="success">A new link is on its way.</Alert> : null}
          <Button variant="secondary" onClick={resend} disabled={resent}>
            Send the link again
          </Button>
          <Link
            href={withNext("/login", next)}
            className="text-center text-sm font-semibold text-canopy underline-offset-4 hover:underline"
          >
            Back to sign in
          </Link>
        </div>
      </>
    );
  }

  return (
    <>
      <AuthHeading title="Create your Agentree account">
        Start with your account. You&apos;ll set up your business next.
      </AuthHeading>
      <form onSubmit={onSubmit} className="flex flex-col gap-5">
        {error ? <Alert tone="error">{error}</Alert> : null}
        <TextField
          label="Work email"
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <TextField
          label="Password"
          type="password"
          name="new-password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD}
          maxLength={256}
          hint={PASSWORD_HINT}
          error={passwordError}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Button type="submit" busy={busy}>
          Create account
        </Button>
      </form>
      <p className="mt-8 text-sm text-ink-muted">
        Already have an account?{" "}
        <Link
          href={withNext("/login", next)}
          className="font-semibold text-canopy underline-offset-4 hover:underline"
        >
          Sign in
        </Link>
      </p>
    </>
  );
}
