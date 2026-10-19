"use client";

import type { ReactNode } from "react";
import { safeNext } from "@/lib/api";

export function AuthHeading({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-col gap-2">
      <h1 className="text-2xl font-bold sm:text-3xl">{title}</h1>
      {children ? <p className="text-ink-muted">{children}</p> : null}
    </div>
  );
}

export function AuthFallback() {
  return <div className="h-64" aria-hidden="true" />;
}

/*
  Where to go after sign-in. Remembered across the email-verification round trip (the link
  in the email opens a new tab without our query string). Holds a local path only — never a
  credential — and is validated as a same-origin path on every read.
*/
const NEXT_KEY = "agentree.next";

export function rememberNext(next: string | null) {
  const safe = safeNext(next);
  try {
    if (safe) window.localStorage.setItem(NEXT_KEY, safe);
  } catch {
    // Storage unavailable (private mode): the user lands on the dashboard instead.
  }
}

export function recallNext(): string | null {
  try {
    return safeNext(window.localStorage.getItem(NEXT_KEY));
  } catch {
    return null;
  }
}

export function forgetNext() {
  try {
    window.localStorage.removeItem(NEXT_KEY);
  } catch {
    // ignore
  }
}

export function withNext(path: string, next: string | null): string {
  const safe = safeNext(next);
  return safe ? `${path}?next=${encodeURIComponent(safe)}` : path;
}
