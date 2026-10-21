"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useBusiness } from "@/components/business-shell";
import { LeadStatusBadge } from "@/components/lead-status-badge";
import { useSession } from "@/components/session";
import { Alert, Button, Spinner } from "@/components/ui";
import { api, type Lead, type LeadPage, type LeadStatus } from "@/lib/api";
import { CHANNEL_LABEL, LEAD_STATUSES, LEAD_STATUS_LABEL, dateTime, leadTitle } from "@/lib/leads";

const PAGE_SIZE = 50;

export default function LeadsPage() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const base = `/api/businesses/${encodeURIComponent(business.id)}/leads`;
  const [filter, setFilter] = useState<LeadStatus | "all">("all");
  const [leads, setLeads] = useState<Lead[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPage = useCallback(
    (before?: string) => {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
      if (filter !== "all") params.set("status", filter);
      if (before) params.set("before", before);
      return api<LeadPage>(`${base}?${params}`);
    },
    [base, filter],
  );

  useEffect(() => {
    let cancelled = false;
    fetchPage().then(
      (page) => {
        if (cancelled) return;
        setLeads(page.leads);
        setNext(page.next_before ?? null);
        setError(null);
      },
      (err) => !cancelled && setError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [fetchPage, handleError]);

  async function loadMore() {
    if (!next) return;
    setLoadingMore(true);
    try {
      const page = await fetchPage(next);
      setLeads((prev) => [...(prev ?? []), ...page.leads]);
      setNext(page.next_before ?? null);
    } catch (err) {
      setError(handleError(err));
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="flex max-w-5xl flex-col gap-8">
      <title>{`Leads · ${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">Leads</h1>
        <p className="max-w-prose text-ink-muted">
          Visitors who shared their contact details with your Sales Agent and agreed to be
          contacted. Follow up, then keep the status up to date.
        </p>
      </header>

      <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-2">
        {(["all", ...LEAD_STATUSES] as const).map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={filter === s}
            onClick={() => {
              setLeads(null);
              setFilter(s);
            }}
            className={[
              "min-h-9 rounded-full border px-3 text-sm font-semibold",
              filter === s ? "border-brand bg-brand text-white" : "border-line-strong bg-surface text-ink hover:border-brand",
            ].join(" ")}
          >
            {s === "all" ? "All" : LEAD_STATUS_LABEL[s]}
          </button>
        ))}
      </div>

      {error ? (
        <Alert tone="error">{error}</Alert>
      ) : leads === null ? (
        <Spinner label="Loading leads" />
      ) : leads.length === 0 ? (
        <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-6">
          <p className="font-semibold">{filter === "all" ? "No leads yet." : "No leads with this status."}</p>
          {filter === "all" ? (
            <p className="text-ink-muted">
              When a visitor on your public page or website chat shares their details and agrees to
              be contacted, they appear here and owners and admins get an email.
            </p>
          ) : null}
        </div>
      ) : (
        <section aria-label="Leads" className="flex flex-col gap-4">
          <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
            {leads.map((lead) => (
              <li key={lead.id} data-testid="lead-row">
                <Link
                  href={`/b/${business.id}/leads/${lead.id}`}
                  className="flex flex-col gap-1 px-4 py-3 hover:bg-brand-soft/50 focus-visible:bg-brand-soft/50 sm:flex-row sm:items-center sm:gap-6 sm:px-5"
                >
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span dir="auto" className="truncate font-semibold text-ink">
                      {leadTitle(lead)}
                    </span>
                    <span className="truncate text-sm text-ink-muted" dir="auto">
                      {[lead.email, lead.phone].filter(Boolean).join(" · ")}
                      {lead.need ? ` — ${lead.need}` : ""}
                    </span>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-3 text-sm text-ink-muted">
                    {lead.next_follow_up_at ? (
                      <FollowUpDue at={lead.next_follow_up_at} />
                    ) : null}
                    <span>{CHANNEL_LABEL[lead.channel] ?? lead.channel}</span>
                    <time dateTime={lead.created_at}>{dateTime.format(new Date(lead.created_at))}</time>
                    <LeadStatusBadge status={lead.status} />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          {next ? (
            <div>
              <Button variant="secondary" size="sm" busy={loadingMore} onClick={() => void loadMore()}>
                Load more
              </Button>
            </div>
          ) : null}
        </section>
      )}
    </div>
  );
}

function FollowUpDue({ at }: { at: string }) {
  const [now] = useState(() => Date.now()); // judged when the row first renders
  const overdue = new Date(at).getTime() < now;
  return (
    <span className={overdue ? "font-semibold text-danger" : undefined} data-testid="lead-follow-up">
      {overdue ? "Follow-up overdue" : `Follow up by ${dateTime.format(new Date(at))}`}
    </span>
  );
}
