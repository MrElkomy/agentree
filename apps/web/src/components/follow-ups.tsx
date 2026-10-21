"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useSession } from "@/components/session";
import { Alert, Button, SelectField, TextField } from "@/components/ui";
import { api, type FollowUp, type FollowUpCreate, type Member } from "@/lib/api";
import { dateTime } from "@/lib/leads";

/** Local "YYYY-MM-DDTHH:mm" for <input type="datetime-local">. */
function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Follow-up tasks of one lead: reminders for the team (people contact the customer). The Sales
 * Agent adds a first-contact task for every new lead; members add their own, assign, and mark
 * them done. The backend enforces limits and dates; this only shapes the UI.
 */
export function FollowUps({ businessId, leadId }: { businessId: string; leadId: string }) {
  const { handleError } = useSession();
  const base = `/api/businesses/${encodeURIComponent(businessId)}`;
  const [tasks, setTasks] = useState<FollowUp[] | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState(() => toLocalInput(new Date(Date.now() + 24 * 3600 * 1000)));
  const [assignee, setAssignee] = useState("");
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [now] = useState(() => Date.now()); // "overdue" is judged at page load

  const listPath = `${base}/leads/${encodeURIComponent(leadId)}/follow-ups`;

  useEffect(() => {
    let cancelled = false;
    Promise.all([api<FollowUp[]>(listPath), api<Member[]>(`${base}/members`)]).then(
      ([t, m]) => {
        if (cancelled) return;
        setTasks(t);
        setMembers(m);
      },
      (err) => !cancelled && setError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [base, listPath, handleError]);

  const emailOf = (id: string | null | undefined) => members.find((m) => m.user_id === id)?.email;

  async function add(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setAdding(true);
    setError(null);
    try {
      const body: FollowUpCreate = {
        title: title.trim(),
        due_at: new Date(due).toISOString(),
        assignee_user_id: assignee || null,
      };
      const task = await api<FollowUp>(listPath, "POST", body);
      setTasks((prev) => [...(prev ?? []), task].sort(order));
      setTitle("");
    } catch (err) {
      setError(handleError(err));
    } finally {
      setAdding(false);
    }
  }

  async function setStatus(task: FollowUp, status: "open" | "done") {
    setBusyId(task.id);
    setError(null);
    try {
      const updated = await api<FollowUp>(`${base}/follow-ups/${task.id}`, "PATCH", { status });
      setTasks((prev) => (prev ?? []).map((t) => (t.id === task.id ? updated : t)).sort(order));
    } catch (err) {
      setError(handleError(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section aria-labelledby="followups-heading" className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5">
      <div className="flex flex-col gap-1">
        <h2 id="followups-heading" className="text-lg font-semibold">
          Follow-up reminders
        </h2>
        <p className="text-sm text-ink-muted">
          Your Sales Agent adds a reminder to contact every new lead within 24 hours. You get an
          email if a reminder is overdue.
        </p>
      </div>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {tasks === null ? null : tasks.length === 0 ? (
        <p className="text-sm text-ink-muted">No reminders.</p>
      ) : (
        <ul className="divide-y divide-line rounded-md border border-line">
          {tasks.map((t) => {
            const overdue = t.status === "open" && new Date(t.due_at).getTime() < now;
            return (
              <li key={t.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5" data-testid="follow-up">
                <div className="flex min-w-0 flex-1 flex-col">
                  <span dir="auto" className={t.status === "open" ? "font-semibold" : "text-ink-muted line-through"}>
                    {t.title}
                  </span>
                  <span className={`text-xs ${overdue ? "font-semibold text-danger" : "text-ink-muted"}`}>
                    {t.status === "open"
                      ? `${overdue ? "Overdue since" : "Due"} ${dateTime.format(new Date(t.due_at))}`
                      : t.status === "done"
                        ? `Done ${t.completed_at ? dateTime.format(new Date(t.completed_at)) : ""}`
                        : "Canceled"}
                    {" · "}
                    {t.assignee_user_id ? (emailOf(t.assignee_user_id) ?? "Former member") : "Owners and admins"}
                    {t.created_by_agent ? " · added by Sales Agent" : ""}
                  </span>
                </div>
                {t.status === "open" ? (
                  <Button size="sm" variant="secondary" busy={busyId === t.id} onClick={() => void setStatus(t, "done")}>
                    Mark done
                  </Button>
                ) : t.status === "done" ? (
                  <Button size="sm" variant="ghost" busy={busyId === t.id} onClick={() => void setStatus(t, "open")}>
                    Reopen
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      <form onSubmit={add} className="flex flex-wrap items-end gap-3" aria-label="Add a reminder">
        <TextField
          label="New reminder"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
          placeholder="Send the price list"
          dir="auto"
          className="min-w-48 flex-1"
        />
        <TextField
          label="Due"
          type="datetime-local"
          value={due}
          onChange={(e) => setDue(e.target.value)}
          className="w-full sm:w-56"
        />
        <SelectField
          label="Remind"
          value={assignee}
          onChange={(e) => setAssignee(e.target.value)}
          className="w-full sm:w-56"
        >
          <option value="">Owners and admins</option>
          {members.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.email}
            </option>
          ))}
        </SelectField>
        <Button type="submit" variant="secondary" busy={adding} disabled={!title.trim()}>
          Add reminder
        </Button>
      </form>
    </section>
  );
}

function order(a: FollowUp, b: FollowUp): number {
  if ((a.status === "open") !== (b.status === "open")) return a.status === "open" ? -1 : 1;
  return new Date(a.due_at).getTime() - new Date(b.due_at).getTime();
}
