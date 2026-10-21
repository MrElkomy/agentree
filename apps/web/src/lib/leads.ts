import type { Lead, LeadStatus } from "./api";

export const LEAD_STATUSES: LeadStatus[] = ["new", "contacted", "qualified", "won", "lost"];

export const LEAD_STATUS_LABEL: Record<LeadStatus, string> = {
  new: "New",
  contacted: "Contacted",
  qualified: "Qualified",
  won: "Won",
  lost: "Lost",
};

// Text labels carry the meaning; colour only reinforces it.
export const LEAD_STATUS_STYLE: Record<LeadStatus, string> = {
  new: "bg-brand text-white",
  contacted: "bg-brand-soft text-brand-deep ring-1 ring-brand/30",
  qualified: "bg-warn-soft text-warn ring-1 ring-warn/30",
  won: "bg-ink text-white",
  lost: "bg-surface text-ink-muted ring-1 ring-line-strong",
};

export const CHANNEL_LABEL: Record<string, string> = {
  public: "Public page",
  widget: "Website chat",
};

export function leadTitle(lead: Pick<Lead, "name" | "email" | "phone">): string {
  return lead.name || lead.email || lead.phone || "Visitor";
}

export const dateTime = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" });
