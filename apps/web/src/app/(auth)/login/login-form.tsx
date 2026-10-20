"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { AuthHeading, forgetNext, recallNext, rememberNext, withNext } from "@/components/auth";
import { Alert, Button, TextField } from "@/components/ui";
import { api, isApiError, safeNext, type Me } from "@/lib/api";
import { messageFor } from "@/lib/messages";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setUnverified(false);
    setResent(false);
    try {
      await api<Me>("/api/auth/login", "POST", { email, password });
      const target = next ?? recallNext() ?? "/dashboard";
      forgetNext();
      router.replace(target);
    } catch (err) {
      setUnverified(isApiError(err, 403, "email_not_verified"));
      setError(messageFor(err));
      setBusy(false);
    }
  }

  async function resend() {
    try {
      await api("/api/auth/resend-verification", "POST", { email });
      rememberNext(next);
      setResent(true);
    } catch (err) {
      setError(messageFor(err));
    }
  }

  return (
    <>
      <AuthHeading title="Sign in to Agentree">Welcome back. Use your work email.</AuthHeading>
      <form onSubmit={onSubmit} className="flex flex-col gap-5">
        {error ? (
          <Alert tone={unverified ? "warning" : "error"}>
            <p>{error}</p>
            {unverified && !resent ? (
              <Button variant="secondary" size="sm" className="mt-3" onClick={resend}>
                Send a new verification email
              </Button>
            ) : null}
          </Alert>
        ) : null}
        {resent ? (
          <Alert tone="success">If that account needs verifying, a new link is on its way.</Alert>
        ) : null}
        <TextField
          label="Email"
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
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <div className="-mt-2 flex justify-end">
          <Link href="/reset-password" className="text-sm font-semibold text-brand underline-offset-4 hover:underline">
            Forgot your password?
          </Link>
        </div>
        <Button type="submit" busy={busy}>
          Sign in
        </Button>
      </form>
      <p className="mt-8 text-sm text-ink-muted">
        New to Agentree?{" "}
        <Link
          href={withNext("/signup", next)}
          className="font-semibold text-brand underline-offset-4 hover:underline"
        >
          Create an account
        </Link>
      </p>
    </>
  );
}
