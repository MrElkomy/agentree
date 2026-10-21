"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { useBusiness } from "@/components/business-shell";
import { Dialog } from "@/components/dialog";
import { LeadStatusBadge } from "@/components/lead-status-badge";
import { RichText, textDirection } from "@/components/rich-text";
import { useSession } from "@/components/session";
import { Alert, Button, SelectField, Spinner } from "@/components/ui";
import { api, isApiError, type Lead, type LeadDetail, type LeadStatus } from "@/lib/api";
import { CHANNEL_LABEL, LEAD_STATUSES, LEAD_STATUS_LABEL, dateTime, leadTitle } from "@/lib/leads";
import { atLeast } from "@/lib/roles";

const MAX_NOTES = 2000;

export default function LeadDetailPage() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const router = useRouter();
  const { leadId } = useParams<{ leadId: string }>();
  const path = `/api/businesses/${encodeURIComponent(business.id)}/leads/${encodeURIComponent(leadId)}`;
  const listHref = `/b/${business.id}/leads`;
  const isAdmin = atLeast(business.role, "admin");

  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState<"status" | "notes" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<LeadDetail>(path).then(
      (l) => {
        if (cancelled) return;
        setLead(l);
        setNotes(l.notes);
      },
      (err) => {
        if (cancelled) return;
        if (isApiError(err, 404)) setMissing(true);
        else setError(handleError(err));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [path, handleError]);

  async function save(patch: { status?: LeadStatus; notes?: string }, what: "status" | "notes") {
    setSaving(what);
    setError(null);
    setNotice(null);
    try {
      const updated = await api<Lead>(path, "PATCH", patch);
      setLead((prev) => (prev ? { ...prev, ...updated } : prev));
      setNotice(what === "status" ? "Status updated." : "Notes saved.");
    } catch (err) {
      setError(handleError(err));
    } finally {
      setSaving(null);
    }
  }

  async function remove() {
    setDeleting(true);
    try {
      await api(path, "DELETE");
      router.push(listHref);
    } catch (err) {
      setError(handleError(err));
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  if (missing) {
    return (
      <div className="flex max-w-3xl flex-col gap-4">
        <Alert tone="info">This lead doesn&apos;t exist or was deleted.</Alert>
        <Link href={listHref} className="font-semibold text-brand">
          Back to leads
        </Link>
      </div>
    );
  }
  if (!lead) return error ? <Alert tone="error">{error}</Alert> : <Spinner label="Loading lead" />;

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <title>{`${leadTitle(lead)} · Leads · ${business.name} · Agentree`}</title>
      <nav aria-label="Breadcrumb">
        <Link href={listHref} className="text-sm font-semibold text-brand">
          ← All leads
        </Link>
      </nav>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 dir="auto" className="text-2xl font-bold sm:text-3xl">
            {leadTitle(lead)}
          </h1>
          <p className="text-sm text-ink-muted">
            From {CHANNEL_LABEL[lead.channel] ?? lead.channel} ·{" "}
            <time dateTime={lead.created_at}>{dateTime.format(new Date(lead.created_at))}</time>
          </p>
        </div>
        <LeadStatusBadge status={lead.status} />
      </header>

      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {error ? <Alert tone="error">{error}</Alert> : null}

      <section aria-labelledby="contact-heading" className="grid gap-4 rounded-lg border border-line bg-surface p-5 sm:grid-cols-2">
        <h2 id="contact-heading" className="text-lg font-semibold sm:col-span-2">
          Contact
        </h2>
        <dl className="contents">
          <div className="flex flex-col gap-0.5">
            <dt className="text-sm text-ink-muted">Email</dt>
            <dd>{lead.email ? <a href={`mailto:${lead.email}`} className="font-semibold text-brand break-all">{lead.email}</a> : "—"}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-sm text-ink-muted">Phone</dt>
            <dd>{lead.phone ? <a href={`tel:${lead.phone.replace(/[^\d+]/g, "")}`} className="font-semibold text-brand">{lead.phone}</a> : "—"}</dd>
          </div>
          <div className="flex flex-col gap-0.5 sm:col-span-2">
            <dt className="text-sm text-ink-muted">What they need</dt>
            <dd dir="auto" className="whitespace-pre-wrap break-words">{lead.need || "—"}</dd>
          </div>
          <div className="flex flex-col gap-0.5 sm:col-span-2">
            <dt className="text-sm text-ink-muted">Consent</dt>
            <dd className="text-sm">
              Agreed to be contacted on {dateTime.format(new Date(lead.consent_at))}.
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="followup-heading" className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5">
        <h2 id="followup-heading" className="text-lg font-semibold">
          Follow-up
        </h2>
        <SelectField
          label="Status"
          value={lead.status}
          disabled={saving !== null}
          onChange={(e) => void save({ status: e.target.value as LeadStatus }, "status")}
          className="sm:max-w-xs"
        >
          {LEAD_STATUSES.map((s) => (
            <option key={s} value={s}>
              {LEAD_STATUS_LABEL[s]}
            </option>
          ))}
        </SelectField>
        <form
          className="flex flex-col gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            void save({ notes }, "notes");
          }}
        >
          <label htmlFor="lead-notes" className="text-sm font-semibold">
            Notes for your team
          </label>
          <textarea
            id="lead-notes"
            dir="auto"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={MAX_NOTES}
            rows={4}
            className="rounded-md border border-line-strong bg-surface px-3 py-2 text-base focus-visible:border-brand"
          />
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-ink-muted">
              Only your team sees notes. {notes.length}/{MAX_NOTES}
            </span>
            <Button type="submit" size="sm" variant="secondary" busy={saving === "notes"} disabled={notes === lead.notes}>
              Save notes
            </Button>
          </div>
        </form>
      </section>

      <section aria-labelledby="conversation-heading" className="flex flex-col gap-3">
        <h2 id="conversation-heading" className="text-lg font-semibold">
          Conversation
        </h2>
        {lead.messages.length === 0 ? (
          <p className="rounded-lg border border-line bg-surface p-5 text-ink-muted">
            The conversation is no longer available. Conversations are deleted after 30 days; the
            lead stays.
          </p>
        ) : (
          <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 sm:p-5">
            {lead.messages.map((m, i) =>
              m.role === "user" ? (
                <div key={i} className="ms-auto max-w-[85%] rounded-lg bg-brand px-4 py-2.5 text-white">
                  <p dir={textDirection(m.content)} className="whitespace-pre-wrap break-words">{m.content}</p>
                </div>
              ) : (
                <div key={i} className="me-auto max-w-[85%] rounded-lg border border-line bg-paper px-4 py-2.5">
                  <RichText text={m.content} />
                </div>
              ),
            )}
          </div>
        )}
      </section>

      {isAdmin ? (
        <section aria-labelledby="danger-heading" className="flex flex-col gap-2">
          <h2 id="danger-heading" className="text-lg font-semibold">
            Delete lead
          </h2>
          <p className="max-w-prose text-sm text-ink-muted">
            Permanently removes this person&apos;s contact details, for example when they ask you to
            delete their data. The activity log keeps a record that a lead was deleted.
          </p>
          <div>
            <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
              Delete lead
            </Button>
          </div>
        </section>
      ) : null}

      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Delete this lead?"
        description="Their contact details and your notes are removed. This can't be undone."
      >
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmDelete(false)} disabled={deleting}>
            Cancel
          </Button>
          <Button variant="danger" busy={deleting} onClick={() => void remove()}>
            Delete lead
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
