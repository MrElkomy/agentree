"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Wordmark } from "@/components/brand";
import { Alert, Button, Spinner, buttonClass } from "@/components/ui";
import { api, isApiError, loginHref, type Business, type Me } from "@/lib/api";
import { messageFor } from "@/lib/messages";

type Session = {
  me: Me;
  businesses: Business[];
  refreshBusinesses: () => Promise<void>;
  /** Turns an API error into a message; sends the user to sign in on 401. */
  handleError: (err: unknown) => string;
};

const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}

type Load =
  | { state: "loading" }
  | { state: "ready"; me: Me; businesses: Business[] }
  | { state: "unverified"; me: Me }
  | { state: "error"; message: string };

async function loadSession(): Promise<Load | "login"> {
  try {
    const me = await api<Me>("/api/auth/me");
    if (!me.email_verified) return { state: "unverified", me };
    const businesses = await api<Business[]>("/api/businesses");
    return { state: "ready", me, businesses };
  } catch (err) {
    if (isApiError(err, 401)) return "login";
    return { state: "error", message: messageFor(err) };
  }
}

/**
 * Loads the signed-in user from the backend (the only authority). No session token is ever
 * visible here: the cookie is HttpOnly and sent automatically on same-origin requests.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [load, setLoad] = useState<Load>({ state: "loading" });

  const toLogin = useCallback(() => {
    router.replace(loginHref(window.location.pathname + window.location.search));
  }, [router]);

  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void loadSession().then((result) => {
      if (cancelled) return;
      if (result === "login") toLogin();
      else setLoad(result);
    });
    return () => {
      cancelled = true;
    };
  }, [toLogin, attempt]);

  const handleError = useCallback(
    (err: unknown) => {
      if (isApiError(err, 401)) toLogin();
      return messageFor(err);
    },
    [toLogin],
  );

  const refreshBusinesses = useCallback(async () => {
    try {
      const businesses = await api<Business[]>("/api/businesses");
      setLoad((prev) => (prev.state === "ready" ? { ...prev, businesses } : prev));
    } catch (err) {
      handleError(err);
    }
  }, [handleError]);

  const value = useMemo<Session | null>(
    () =>
      load.state === "ready"
        ? { me: load.me, businesses: load.businesses, refreshBusinesses, handleError }
        : null,
    [load, refreshBusinesses, handleError],
  );

  if (load.state === "loading") {
    return (
      <div className="grid min-h-dvh place-items-center">
        <Spinner label="Loading your workspace…" />
      </div>
    );
  }

  if (load.state === "error") {
    return (
      <CenteredCard title="We couldn't load your workspace">
        <Alert tone="error">{load.message}</Alert>
        <Button
          onClick={() => {
            setLoad({ state: "loading" });
            setAttempt((n) => n + 1);
          }}
        >
          Try again
        </Button>
      </CenteredCard>
    );
  }

  if (load.state === "unverified") {
    return <UnverifiedNotice email={load.me.email} />;
  }

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

function CenteredCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col items-center gap-10 px-4 py-10">
      <Wordmark href="/login" />
      <div className="flex w-full max-w-md flex-col gap-5 rounded-lg border border-line bg-surface p-6">
        <h1 className="text-xl font-bold">{title}</h1>
        {children}
      </div>
    </div>
  );
}

function UnverifiedNotice({ email }: { email: string }) {
  const router = useRouter();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function resend() {
    try {
      await api("/api/auth/resend-verification", "POST", { email });
      setSent(true);
    } catch (err) {
      setError(messageFor(err));
    }
  }
  async function logout() {
    try {
      await api("/api/auth/logout", "POST");
    } finally {
      router.replace("/login");
    }
  }
  return (
    <CenteredCard title="Verify your email to continue">
      <p className="text-ink-muted">
        We sent a verification link to <strong className="text-ink">{email}</strong>.
      </p>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {sent ? <Alert tone="success">A new link is on its way.</Alert> : null}
      <Button variant="secondary" onClick={resend} disabled={sent}>
        Send the link again
      </Button>
      <button type="button" onClick={logout} className={buttonClass("ghost")}>
        Log out
      </button>
    </CenteredCard>
  );
}
