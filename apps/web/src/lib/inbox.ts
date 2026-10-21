import type { InboxItem } from "./api";

export type InboxStatus = InboxItem["status"];

export const INBOX_STATUSES: InboxStatus[] = ["needs_human", "human_active", "open", "resolved"];

export const INBOX_STATUS_LABEL: Record<InboxStatus, string> = {
  needs_human: "Waiting for a person",
  human_active: "With the team",
  open: "AI answering",
  resolved: "Resolved",
};

// Text labels carry the meaning; colour only reinforces it.
export const INBOX_STATUS_STYLE: Record<InboxStatus, string> = {
  needs_human: "bg-warn-soft text-warn ring-1 ring-warn/30",
  human_active: "bg-brand text-white",
  open: "bg-brand-soft text-brand-deep ring-1 ring-brand/30",
  resolved: "bg-surface text-ink-muted ring-1 ring-line-strong",
};

/** How often open inbox pages refresh (no push channel yet). */
export const INBOX_POLL_MS = 5000;

