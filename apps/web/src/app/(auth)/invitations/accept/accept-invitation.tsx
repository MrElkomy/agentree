"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthHeading } from "@/components/auth";
import { Alert, Button, RoleBadge, Spinner, buttonClass } from "@/components/ui";
import { api, isApiError, loginHref, type Business, type Me } from "@/lib/api";
import { messageFor } from "@/lib/messages";

export function AcceptInvitation() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token");
  const [me, setMe] = useState<Me | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [joined, setJoined] = useState<Business | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api<Me>("/api/auth/me")
      .then((user) => !cancelled && setMe(user))
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isApiError(err, 401)) {
          router.replace(loginHref(`/invitations/accept?token=${encodeURIComponent(token)}`));
        } else {
          setError(messageFor(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, router]);

  async function accept() {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      setJoined(await api<Business>("/api/invitations/accept", "POST", { token }));
    } catch (err) {
      if (isApiError(err, 401)) {
        router.replace(loginHref(`/invitations/accept?token=${encodeURIComponent(token)}`));
        return;
      }
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <>
        <AuthHeading title="Invitation link incomplete">
          Open the link from your invitation email again, or ask the person who invited you to send
          a new one.
        </AuthHeading>
        <Link href="/dashboard" className={`${buttonClass("secondary")} w-full`}>
          Go to your dashboard
        </Link>
      </>
    );
  }

  if (joined) {
    return (
      <>
        <AuthHeading title={`You've joined ${joined.name}`}>
          You can now work in this business with the role below.
        </AuthHeading>
        <div className="mb-6 flex items-center justify-between rounded-lg border border-line bg-surface px-4 py-3">
          <span className="font-semibold">{joined.name}</span>
          <RoleBadge role={joined.role} />
        </div>
        <Link href={`/b/${joined.id}`} className={`${buttonClass()} w-full`}>
          Open {joined.name}
        </Link>
      </>
    );
  }

  if (!me) {
    return error ? <Alert tone="error">{error}</Alert> : <Spinner label="Checking your session…" />;
  }

  return (
    <>
      <AuthHeading title="Join a business on Agentree">
        You&apos;re signed in as <strong className="text-ink">{me.email}</strong>. Invitations
        only work for the email address they were sent to.
      </AuthHeading>
      <div className="flex flex-col gap-4">
        {error ? <Alert tone="error">{error}</Alert> : null}
        <Button onClick={accept} busy={busy}>
          Accept invitation
        </Button>
        <Link href="/dashboard" className={`${buttonClass("ghost")} w-full`}>
          Not now
        </Link>
      </div>
    </>
  );
}
