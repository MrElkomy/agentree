"use client";

import { useCallback, useEffect, useState } from "react";
import { useBusiness } from "@/components/business-shell";
import { useSession } from "@/components/session";
import { Alert, Button, Spinner } from "@/components/ui";
import { api, type AuditEvent, type AuditPage, type Role } from "@/lib/api";
import { ACTION_LABEL } from "@/lib/approvals";
import { CHANNEL_LABEL, LEAD_STATUS_LABEL } from "@/lib/leads";
import { ROLE_LABEL, atLeast } from "@/lib/roles";

const PAGE_SIZE = 50;

const timeFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" });

function roleLabel(value: unknown): string {
  return typeof value === "string" && value in ROLE_LABEL ? ROLE_LABEL[value as Role] : String(value ?? "");
}

function slotLabel(value: unknown): string {
  return value === "backup" ? "backup" : "primary";
}

function statusLabel(value: unknown): string {
  return typeof value === "string" && value in LEAD_STATUS_LABEL
    ? LEAD_STATUS_LABEL[value as keyof typeof LEAD_STATUS_LABEL]
    : String(value ?? "");
}

function actionLabel(value: unknown): string {
  return ACTION_LABEL[String(value)] ?? String(value ?? "act");
}

function actorName(e: AuditEvent): string {
  if (!e.actor) return "System";
  return e.actor.email ?? "A former user";
}

function targetName(e: AuditEvent): string {
  return e.target_email ?? "a former user";
}

/** One readable sentence per event. Unknown actions fall back to their code. */
function describe(e: AuditEvent): string {
  const who = actorName(e);
  const d = e.details as Record<string, unknown>;
  switch (e.action) {
    case "business.created":
      return `${who} created the business`;
    case "invitation.created":
      return `${who} invited ${String(d.email ?? "someone")} as ${roleLabel(d.role)}`;
    case "invitation.revoked":
      return `${who} canceled an invitation`;
    case "member.joined":
      return `${who} joined as ${roleLabel(d.role)}`;
    case "member.role_changed":
      return `${who} changed ${targetName(e)}'s role from ${roleLabel(d.from_role)} to ${roleLabel(d.to_role)}`;
    case "member.removed":
      return `${who} removed ${targetName(e)} (${roleLabel(d.role)})`;
    case "member.left":
      return `${who} left the business`;
    case "provider_key.saved":
      return `${who} ${d.replaced ? "replaced" : "added"} the ${slotLabel(d.slot)} AI provider key`;
    case "provider_key.removed":
      return `${who} removed the ${slotLabel(d.slot)} AI provider key`;
    case "lead.created":
      return `A visitor shared their contact details (${CHANNEL_LABEL[String(d.channel)] ?? "chat"})`;
    case "lead.updated":
      return "A visitor updated their contact details";
    case "lead.status_changed":
      return `${who} moved a lead from ${statusLabel(d.from_status)} to ${statusLabel(d.to_status)}`;
    case "lead.notes_updated":
      return `${who} updated the notes on a lead`;
    case "lead.deleted":
      return `${who} deleted a lead`;
    case "follow_up.created":
      return d.agent ? "Sales Agent added a follow-up reminder for a new lead" : `${who} added a follow-up reminder`;
    case "follow_up.updated":
      if (d.to_status === "done") return `${who} marked a follow-up done`;
      if (d.to_status === "canceled") return `${who} canceled a follow-up`;
      return `${who} updated a follow-up`;
    case "conversation.handoff_requested":
      return d.reason === "agent"
        ? "The AI asked for a person to take over a conversation"
        : "A visitor asked to talk to a person";
    case "conversation.handoff_canceled":
      return "A visitor chose to continue with the AI";
    case "conversation.taken_over":
      return `${who} took over a conversation`;
    case "conversation.assigned":
      return d.assigned ? `${who} assigned a conversation` : `${who} unassigned a conversation`;
    case "conversation.released":
      return `${who} handed a conversation back to the AI`;
    case "conversation.resolved":
      if (d.resolved_by === "agent") return `${agentTitle(d.agent)} marked a conversation resolved`;
      if (d.resolved_by === "visitor") return "A visitor marked their conversation resolved";
      return `${who} resolved a conversation`;
    case "knowledge_file.uploaded":
      return `${who} uploaded a knowledge file (${String(d.kind ?? "").toUpperCase()})`;
    case "knowledge_file.deleted":
      return `${who} deleted a knowledge file`;
    case "customer.verified":
      return "A visitor confirmed their email in the chat";
    case "customer.memory_updated":
      return `${who} corrected a customer note`;
    case "customer.memory_deleted":
      return `${who} deleted a customer note`;
    case "customer.deleted":
      return `${who} deleted a customer and their notes`;
    case "approval.requested":
      return `${agentTitle(d.agent)} asked for approval to ${actionLabel(d.kind)}${d.flagged ? " (flagged for review)" : ""}`;
    case "approval.decided":
      if (d.decision === "rule") return `${agentTitle(d.agent)} was allowed to ${actionLabel(d.kind)} by an "Always allow" rule`;
      if (d.decision === "reject") return `${who} rejected a request to ${actionLabel(d.kind)}`;
      return `${who} approved a request to ${actionLabel(d.kind)}${d.decision === "always" ? " and allowed it always" : ""}${d.edited ? " (edited)" : ""}`;
    case "approval.executed":
      return d.status === "executed"
        ? `${agentTitle(d.agent)} completed an approved request to ${actionLabel(d.kind)}`
        : `An approved request to ${actionLabel(d.kind)} didn't run (${String(d.status ?? "")})`;
    case "approval_rule.created":
      return `${who} always allowed ${agentTitle(d.agent)} to ${actionLabel(d.kind)}`;
    case "approval_rule.revoked":
      return `${who} stopped always allowing ${agentTitle(d.agent)} to ${actionLabel(d.kind)}`;
    case "report_settings.updated":
      return d.kind === "off" ? `${who} turned off email reports` : `${who} set email reports to ${String(d.kind)}`;
    case "business_hours.updated":
      return `${who} updated the business hours (${String(d.timezone ?? "")})`;
    case "agent.availability_updated":
      return `${who} changed when the ${agentTitle(d.agent)} answers visitors${d.paused ? " (paused for a period)" : ""}`;
    case "agent.handoff":
      return `${agentTitle(d.from_agent)} handed a conversation to ${agentTitle(d.to_agent)}`;
    case "agent.config_updated":
      return `${who} updated the ${agentTitle(d.agent)} settings${d.enabled === false ? " (turned off)" : ""}`;
    default:
      return `${who}: ${e.action}`;
  }
}

const AGENT_TITLE: Record<string, string> = {
  sales: "Sales Agent",
  customer_service: "Customer Service",
  technical_support: "Technical Support",
  data_analyst: "Data Analyst",
  executive: "Executive Assistant",
};

function agentTitle(role: unknown): string {
  return AGENT_TITLE[String(role)] ?? "An agent";
}

function detail(e: AuditEvent): string | null {
  const d = e.details as Record<string, unknown>;
  if (e.action === "provider_key.saved") {
    return [d.provider, d.model, d.verified ? "tested before saving" : "not tested"].filter(Boolean).join(" · ");
  }
  return null;
}

export default function ActivityPage() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const canView = atLeast(business.role, "admin");
  const path = `/api/businesses/${encodeURIComponent(business.id)}/audit-events`;
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPage = useCallback(
    (before?: string) =>
      api<AuditPage>(`${path}?limit=${PAGE_SIZE}${before ? `&before=${encodeURIComponent(before)}` : ""}`),
    [path],
  );

  useEffect(() => {
    if (!canView) return;
    let cancelled = false;
    fetchPage().then(
      (page) => {
        if (cancelled) return;
        setEvents(page.events);
        setNext(page.next_before ?? null);
      },
      (err) => !cancelled && setError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [canView, fetchPage, handleError]);

  async function loadMore() {
    if (!next) return;
    setLoadingMore(true);
    try {
      const page = await fetchPage(next);
      setEvents((prev) => [...(prev ?? []), ...page.events]);
      setNext(page.next_before ?? null);
    } catch (err) {
      setError(handleError(err));
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <title>{`Activity log · ${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">Activity log</h1>
        <p className="max-w-prose text-ink-muted">
          A permanent record of important changes in this business: team members, roles, invitations
          and AI provider keys. Entries can&apos;t be edited or deleted. Keys and passwords are never
          recorded.
        </p>
      </header>

      {!canView ? (
        <Alert tone="info">Only owners and admins can see the activity log.</Alert>
      ) : error ? (
        <Alert tone="error">{error}</Alert>
      ) : events === null ? (
        <Spinner label="Loading activity" />
      ) : events.length === 0 ? (
        <p className="rounded-lg border border-line bg-surface p-6 text-ink-muted">No activity yet.</p>
      ) : (
        <section aria-label="Activity" className="flex flex-col gap-4">
          <ol className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
            {events.map((e) => {
              const extra = detail(e);
              return (
                <li key={e.id} className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:gap-6 sm:px-5" data-testid="audit-event">
                  <time dateTime={e.created_at} className="shrink-0 text-sm text-ink-muted sm:w-44">
                    {timeFormat.format(new Date(e.created_at))}
                  </time>
                  <div className="flex min-w-0 flex-col">
                    <p className="break-words text-ink">{describe(e)}</p>
                    {extra ? <p className="text-sm text-ink-muted">{extra}</p> : null}
                  </div>
                </li>
              );
            })}
          </ol>
          {next ? (
            <div>
              <Button variant="secondary" size="sm" busy={loadingMore} onClick={() => void loadMore()}>
                Load older activity
              </Button>
            </div>
          ) : null}
        </section>
      )}
    </div>
  );
}
