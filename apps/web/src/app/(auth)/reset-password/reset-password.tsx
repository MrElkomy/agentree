"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { AuthHeading } from "@/components/auth";
import { Alert, Button, TextField, buttonClass } from "@/components/ui";
import { api } from "@/lib/api";
import { MIN_PASSWORD, PASSWORD_HINT, messageFor } from "@/lib/messages";

export function ResetPassword() {
  const params = useSearchParams();
  const [token] = useState(() => params.get("token"));

  useEffect(() => {
    // Keep the single-use token out of the address bar and history.
    if (token) window.history.replaceState(null, "", "/reset-password");
  }, [token]);

  return token ? <NewPasswordForm token={token} /> : <RequestForm />;
}

function RequestForm() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/password-reset/request", "POST", { email });
      setDone(true);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <>
        <AuthHeading title="Check your email">
          If an account exists for <strong className="text-ink">{email}</strong>, we sent a link to
          reset the password. It expires in 60 minutes.
        </AuthHeading>
        <Link href="/login" className={`${buttonClass("secondary")} w-full`}>
          Back to sign in
        </Link>
      </>
    );
  }

  return (
    <>
      <AuthHeading title="Reset your password">
        Enter the email you use for Agentree and we&apos;ll send you a reset link.
      </AuthHeading>
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
          Send reset link
        </Button>
        <Link href="/login" className="text-center text-sm font-semibold text-brand underline-offset-4 hover:underline">
          Back to sign in
        </Link>
      </form>
    </>
  );
}

function NewPasswordForm({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD) return setFieldError(`Use at least ${MIN_PASSWORD} characters.`);
    if (password !== confirm) return setFieldError("The passwords don't match.");
    setFieldError(null);
    setBusy(true);
    try {
      await api("/api/auth/password-reset/confirm", "POST", { token, new_password: password });
      setDone(true);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <>
        <AuthHeading title="Password updated">
          You&apos;ve been signed out on all devices. Sign in with your new password.
        </AuthHeading>
        <Link href="/login" className={`${buttonClass()} w-full`}>
          Continue to sign in
        </Link>
      </>
    );
  }

  return (
    <>
      <AuthHeading title="Choose a new password" />
      <form onSubmit={onSubmit} className="flex flex-col gap-5">
        {error ? (
          <Alert tone="error">
            {error}{" "}
            <Link href="/reset-password" className="font-semibold underline">
              Request a new link
            </Link>
          </Alert>
        ) : null}
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD}
          maxLength={256}
          hint={PASSWORD_HINT}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <TextField
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          required
          error={fieldError}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <Button type="submit" busy={busy}>
          Update password
        </Button>
      </form>
    </>
  );
}
