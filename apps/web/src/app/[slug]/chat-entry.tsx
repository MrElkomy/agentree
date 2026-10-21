"use client";

import { useEffect, useRef, useState } from "react";
import { GuestChat } from "@/components/guest-chat";
import type { PublicAgent } from "@/lib/api";
import { ENTRY_HINT, chatWith } from "@/lib/agents";
import { hasGuestConversation } from "@/lib/guest-chat";
import { useClientValue } from "@/lib/use-client-value";

/**
 * The page's main call to action: one button per agent open to visitors. The visitor picks who
 * to start with; the backend may then hand the conversation to a better-suited teammate.
 */
export function ChatEntry({
  slug,
  displayName,
  agents,
  leadCapture,
  retentionDays,
}: {
  slug: string;
  displayName: string;
  agents: PublicAgent[];
  leadCapture: boolean;
  retentionDays: number;
}) {
  // A returning visitor finds their open conversation already expanded.
  const returning = useClientValue(() => hasGuestConversation(slug), false);
  const [chosen, setChosen] = useState<string | null>(null);
  const [toggled, setToggled] = useState<boolean | null>(null);
  const open = toggled ?? returning;
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (toggled) panelRef.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [toggled]);

  return (
    <div className="flex w-full flex-col gap-3">
      {agents.map((agent) => {
        const active = open && (chosen ?? agents[0]?.role) === agent.role;
        return (
          <button
            key={agent.role}
            type="button"
            aria-expanded={active}
            aria-controls="public-chat"
            onClick={() => {
              if (active) {
                setToggled(false);
              } else {
                setChosen(agent.role);
                setToggled(true);
              }
            }}
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
              <span dir="auto" className="font-semibold">
                {chatWith(agent.name)}
              </span>
              <span className="text-sm text-white/80">
                {active ? "Hide the conversation" : (ENTRY_HINT[agent.role] ?? "Get an answer now.")}
              </span>
            </span>
            <svg
              viewBox="0 0 20 20"
              aria-hidden="true"
              className={`size-5 shrink-0 transition-transform ${active ? "rotate-180" : ""}`}
            >
              <path d="m5 8 5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        );
      })}
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
                {displayName}
              </p>
            </div>
            <GuestChat
              slug={slug}
              displayName={displayName}
              channel="public"
              entryAgent={chosen ?? undefined}
              leadCapture={leadCapture}
              retentionDays={retentionDays}
              className="h-[32rem] max-h-[75dvh]"
            />
          </>
        ) : null}
      </div>
    </div>
  );
}
