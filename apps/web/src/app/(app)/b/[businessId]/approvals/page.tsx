"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useState } from "react";
import { useBusiness } from "@/components/business-shell";
import { useSession } from "@/components/session";
import { Alert, Button, Spinner, TextField } from "@/components/ui";
import { api, type Approval, type ApprovalRule } from "@/lib/api";
import { ACTION_LABEL, DECISION_LABEL, ERROR_LABEL, FLAG_LABEL, STATUS_LABEL } from "@/lib/approvals";
import { dateTime } from "@/lib/leads";
import { atLeast } from "@/lib/roles";

const AGENT_TITLE: Record<string, string> = {
  sales: "Sales Agent",
  customer_service: "Customer Service",
  technical_support: "Technical Support",
  data_analyst: "Data Analyst",
  executive: "Executive Assistant",
};

function agentTitle(role: string): string {
  return AGENT_TITLE[role] ?? role;
}

function when(iso: string): string {
  return dateTime.format(new Date(iso));
}

function actionLabel(action: string): string {
  return ACTION_LABEL[action] ?? action;
}

type Lists = { pending: Approval[]; history: Approval[]; rules: ApprovalRule[] };

/**
 * Approvals (Task 19): sensitive agent actions wait here for an owner or admin, who approves
 * once, always allows the agent that action, edits it first, or rejects it. The backend
 * enforces all of it; this page only shows and asks.
 */
export default function ApprovalsPage() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const base = `/api/businesses/${encodeURIComponent(business.id)}`;
  const canDecide = atLeast(business.role, "admin");
  const [lists, setLists] = useState<Lists | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async (): Promise<Lists> => {
    const [pending, history, rules] = await Promise.all([
      api<Approval[]>(`${base}/approvals?view=pending`),
      api<Approval[]>(`${base}/approvals?view=history&limit=30`),
      api<ApprovalRule[]>(`${base}/approval-rules`),
    ]);
    return { pending, history, rules };
  }, [base]);

  const load = useCallback(async () => {
    try {
      setLists(await fetchAll());
    } catch (err) {
      setError(handleError(err));
    }
  }, [fetchAll, handleError]);

  useEffect(() => {
    let cancelled = false;
    fetchAll().then(
      (l) => !cancelled && setLists(l),
      (err) => !cancelled && setError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [fetchAll, handleError]);

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <title>{`Approvals · ${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">Approvals</h1>
        <p className="max-w-prose text-ink-muted">
          Some things your AI agents may only do after an owner or admin says yes, such as emailing
          a lead. Approve a request once, or always allow it so the agent doesn&apos;t ask again. You
          can stop always allowing at any time. Requests you don&apos;t answer expire on their own.
        </p>
      </header>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {!canDecide ? <Alert tone="info">Only owners and admins can approve or reject requests.</Alert> : null}
      {lists === null && !error ? <Spinner label="Loading approvals…" /> : null}

      {lists ? (
        <>
          <section aria-labelledby="pending-heading" className="flex flex-col gap-4">
            <h2 id="pending-heading" className="text-lg font-semibold">
              Waiting for you {lists.pending.length ? `(${lists.pending.length})` : ""}
            </h2>
            {lists.pending.length === 0 ? (
              <p className="text-ink-muted">
                Nothing to approve. To let the Sales Agent draft follow-up emails, turn on
                &ldquo;Draft follow-up emails&rdquo; on the AI team page.
              </p>
            ) : null}
            <ul className="flex flex-col gap-4">
              {lists.pending.map((a) => (
                <PendingCard key={a.id} base={base} approval={a} canDecide={canDecide} onDone={load} />
              ))}
            </ul>
          </section>

          <section aria-labelledby="rules-heading" className="flex flex-col gap-3">
            <h2 id="rules-heading" className="text-lg font-semibold">
              Always allowed
            </h2>
            {lists.rules.length === 0 ? (
              <p className="text-ink-muted">Every request waits for a person.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {lists.rules.map((r) => (
                  <RuleRow key={r.id} base={base} rule={r} canDecide={canDecide} onDone={load} />
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="history-heading" className="flex flex-col gap-3">
            <h2 id="history-heading" className="text-lg font-semibold">
              History
            </h2>
            {lists.history.length === 0 ? (
              <p className="text-ink-muted">No requests yet. Requests are kept for 30 days.</p>
            ) : (
              <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
                {lists.history.map((a) => (
                  <HistoryRow key={a.id} approval={a} />
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}

function Draft({ approval }: { approval: Approval }) {
  const p = approval.params as Record<string, unknown>;
  if (approval.action !== "send_follow_up_email") return null;
  return (
    <div className="flex flex-col gap-2 rounded-md border border-line bg-canvas p-4 text-sm">
      <p>
        <span className="font-semibold">To:</span> {String(p.to ?? "")}
      </p>
      <p dir="auto">
        <span className="font-semibold">Subject:</span> {String(p.subject ?? "")}
      </p>
      <p dir="auto" className="whitespace-pre-wrap break-words" data-testid="approval-body">
        {String(p.body ?? "")}
      </p>
    </div>
  );
}

function PendingCard({
  base,
  approval,
  canDecide,
  onDone,
}: {
  base: string;
  approval: Approval;
  canDecide: boolean;
  onDone: () => Promise<void>;
}) {
  const { handleError } = useSession();
  const { business } = useBusiness();
  const p = approval.params as Record<string, unknown>;
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(String(p.subject ?? ""));
  const [body, setBody] = useState(String(p.body ?? ""));
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bodyId = useId();

  async function decide(decision: "once" | "always" | "reject") {
    setBusy(decision);
    setError(null);
    try {
      const edits = editing && decision !== "reject" ? { subject, body } : undefined;
      await api(`${base}/approvals/${approval.id}/decision`, "POST", { decision, edits });
      await onDone();
    } catch (err) {
      setError(handleError(err));
      setBusy(null);
    }
  }

  return (
    <li data-testid="approval-card" className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5">
      <div className="flex flex-col gap-1">
        <h3 className="font-semibold">
          {agentTitle(approval.agent)} wants to {actionLabel(approval.action)}
        </h3>
        <p className="text-sm text-ink-muted">
          {approval.summary} · asked {when(approval.requested_at)} · expires {when(approval.expires_at)}
          {approval.target_type === "lead" && approval.target_id ? (
            <>
              {" · "}
              <Link className="font-semibold text-brand underline" href={`/b/${business.id}/leads/${approval.target_id}`}>
                Open lead
              </Link>
            </>
          ) : null}
        </p>
      </div>
      {approval.flag ? <Alert tone="warning">{FLAG_LABEL[approval.flag] ?? "Check this request carefully."}</Alert> : null}
      {editing ? (
        <div className="flex flex-col gap-3">
          <TextField label="Subject" value={subject} maxLength={150} onChange={(e) => setSubject(e.target.value)} />
          <div className="flex flex-col gap-1.5">
            <label htmlFor={bodyId} className="text-sm font-semibold">
              Email
            </label>
            <textarea
              id={bodyId}
              dir="auto"
              value={body}
              maxLength={2000}
              rows={8}
              onChange={(e) => setBody(e.target.value)}
              className="rounded-md border border-line-strong bg-surface px-3 py-2 text-base focus-visible:border-brand"
            />
          </div>
        </div>
      ) : (
        <Draft approval={approval} />
      )}
      {error ? <Alert tone="error">{error}</Alert> : null}
      {canDecide ? (
        <div className="flex flex-wrap gap-2">
          <Button busy={busy === "once"} disabled={busy !== null} onClick={() => decide("once")}>
            {editing ? "Approve edited email" : "Approve once"}
          </Button>
          {approval.allow_always && !editing ? (
            <Button variant="secondary" busy={busy === "always"} disabled={busy !== null} onClick={() => decide("always")}>
              Always allow
            </Button>
          ) : null}
          {approval.editable ? (
            <Button variant="ghost" disabled={busy !== null} onClick={() => setEditing((e) => !e)}>
              {editing ? "Cancel editing" : "Edit"}
            </Button>
          ) : null}
          <Button variant="danger" busy={busy === "reject"} disabled={busy !== null} onClick={() => decide("reject")}>
            Reject
          </Button>
        </div>
      ) : null}
      {canDecide && approval.allow_always && !editing ? (
        <p className="text-sm text-ink-muted">
          &ldquo;Always allow&rdquo; sends this one and lets the {agentTitle(approval.agent)} {actionLabel(approval.action)} from now on
          without asking. Replies go to your email address. Drafts with a number or link that isn&apos;t in your
          knowledge base still wait for you.
        </p>
      ) : null}
    </li>
  );
}

function RuleRow({
  base,
  rule,
  canDecide,
  onDone,
}: {
  base: string;
  rule: ApprovalRule;
  canDecide: boolean;
  onDone: () => Promise<void>;
}) {
  const { handleError } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function revoke() {
    setBusy(true);
    setError(null);
    try {
      await api(`${base}/approval-rules/${rule.id}`, "DELETE");
      await onDone();
    } catch (err) {
      setError(handleError(err));
      setBusy(false);
    }
  }

  return (
    <li data-testid="approval-rule" className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p>
          <span className="font-semibold">{agentTitle(rule.agent)}</span> may {actionLabel(rule.action)} without asking
          <span className="text-sm text-ink-muted"> · since {when(rule.created_at)}</span>
        </p>
        {canDecide ? (
          <Button variant="secondary" size="sm" busy={busy} onClick={revoke}>
            Stop always allowing
          </Button>
        ) : null}
      </div>
      {error ? <Alert tone="error">{error}</Alert> : null}
    </li>
  );
}

function HistoryRow({ approval }: { approval: Approval }) {
  const reason = approval.error ? ERROR_LABEL[approval.error] : null;
  return (
    <li data-testid="approval-history" className="flex flex-col gap-1 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-semibold">{approval.summary}</p>
        <span data-testid="approval-status" className="text-sm font-semibold">
          {STATUS_LABEL[approval.status] ?? approval.status}
        </span>
      </div>
      <p className="text-sm text-ink-muted">
        {agentTitle(approval.agent)} · {when(approval.requested_at)}
        {approval.decision ? ` · ${DECISION_LABEL[approval.decision] ?? approval.decision}` : ""}
      </p>
      {reason ? <p className="text-sm text-ink-muted">{reason}</p> : null}
    </li>
  );
}
