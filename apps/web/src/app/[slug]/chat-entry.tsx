"use client";

import { useEffect, useRef, useState } from "react";
import { GuestChat } from "@/components/guest-chat";
import { hasGuestConversation } from "@/lib/guest-chat";
import { useClientValue } from "@/lib/use-client-value";

/** The page's main call to action: opens the Sales Agent chat right on this page. */
export function ChatEntry({ slug, displayName }: { slug: string; displayName: string }) {
  // A returning visitor finds their open conversation already expanded.
  const returning = useClientValue(() => hasGuestConversation(slug), false);
  const [toggled, setToggled] = useState<boolean | null>(null);
  const open = toggled ?? returning;
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (toggled) panelRef.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [toggled]);

  return (
    <div className="flex w-full flex-col gap-3">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="public-chat"
        onClick={() => setToggled(!open)}
        className="flex min-h-16 w-full items-center gap-4 rounded-xl bg-brand px-4 py-3 text-start text-white shadow-sm transition-colors hover:bg-brand-hover"
      >
        <span aria-hidden="true" className="flex size-10 shrink-0 items-center justify-center rounded-full bg-white/15">
          <svg viewBox="0 0 20 20" className="size-5">
            <path
              d="M4 4h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H9l-4 3v-3H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="font-semibold">Chat with our Sales Agent</span>
          <span className="text-sm text-white/80">
            {open ? "Hide the conversation" : "Questions about products or prices? Get an answer now."}
          </span>
        </span>
        <svg
          viewBox="0 0 20 20"
          aria-hidden="true"
          className={`size-5 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="m5 8 5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <div
        id="public-chat"
        ref={panelRef}
        hidden={!open}
        className="overflow-hidden rounded-xl border border-line bg-surface"
      >
        {open ? (
          <>
            <div className="border-b border-line px-4 py-3">
              <p dir="auto" className="font-semibold">
                {displayName} Sales Agent
              </p>
            </div>
            <GuestChat slug={slug} displayName={displayName} channel="public" className="h-[32rem] max-h-[75dvh]" />
          </>
        ) : null}
      </div>
    </div>
  );
}
