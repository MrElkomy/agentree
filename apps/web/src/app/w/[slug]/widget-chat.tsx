"use client";

import { useEffect } from "react";
import { GuestChat } from "@/components/guest-chat";
import { registerChallenge } from "@/lib/bot-challenge";
import { useClientValue } from "@/lib/use-client-value";

function close() {
  // Carries no data, so any target origin is safe; the loader only accepts this message
  // from our iframe's own origin and window.
  window.parent.postMessage({ type: "agentree:close" }, "*");
}

/** Compact chat-only layout that fills the widget iframe. */
export function WidgetChat({
  slug,
  displayName,
  leadCapture,
  retentionDays,
  customerMemory,
  challengeSiteKey,
}: {
  slug: string;
  displayName: string;
  leadCapture: boolean;
  retentionDays: number;
  customerMemory: boolean;
  challengeSiteKey: string | null;
}) {
  registerChallenge(slug, challengeSiteKey);
  const framed = useClientValue(() => window.parent !== window, false);

  useEffect(() => {
    if (!framed) return;
    // Escape inside the iframe closes the widget too (the host page never sees our keys).
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [framed]);

  return (
    <div className="flex h-dvh flex-col bg-surface">
      <header className="flex items-center justify-between gap-3 bg-brand px-4 py-3 text-white">
        <div className="flex min-w-0 flex-col">
          <h1 dir="auto" className="truncate text-base font-semibold" data-testid="widget-name">
            {displayName}
          </h1>
          <p className="text-xs opacity-85">AI assistant</p>
        </div>
        {framed ? (
          <button
            type="button"
            onClick={close}
            aria-label="Close chat"
            className="flex size-9 shrink-0 items-center justify-center rounded-md hover:bg-white/15"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true" className="size-4">
              <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        ) : null}
      </header>
      <GuestChat
        slug={slug}
        displayName={displayName}
        channel="widget"
        leadCapture={leadCapture}
        retentionDays={retentionDays}
        customerMemory={customerMemory}
        className="flex-1"
      />
    </div>
  );
}
