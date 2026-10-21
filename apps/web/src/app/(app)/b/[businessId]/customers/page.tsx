"use client";

import { useCallback, useEffect, useState } from "react";
import { useBusiness } from "@/components/business-shell";
import { useSession } from "@/components/session";
import { Alert, Button, Spinner } from "@/components/ui";
import { api, type Customer, type CustomerDetail, type MemoryItem } from "@/lib/api";
import { dateTime } from "@/lib/leads";
import { atLeast } from "@/lib/roles";

const CATEGORY_LABEL: Record<string, string> = {
  interest: "Interested in",
  owned: "Has",
  issue: "Open issue",
  preference: "Preference",
  constraint: "Constraint",
};

export default function CustomersPage() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const base = `/api/businesses/${encodeURIComponent(business.id)}/customers`;
  const canEdit = atLeast(business.role, "admin");
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setCustomers(await api<Customer[]>(base));
    } catch (err) {
      setError(handleError(err));
    }
  }, [base, handleError]);

  useEffect(() => {
    let cancelled = false;
    api<Customer[]>(base).then(
      (c) => !cancelled && setCustomers(c),
      (err) => !cancelled && setError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [base, handleError]);

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <title>{`Customers · ${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">Customers</h1>
        <p className="max-w-prose text-ink-muted">
          Short notes your AI agents keep about visitors, so returning customers don&apos;t repeat
          themselves. Agents only use them after the customer confirms their email with a code,
          and only what each agent&apos;s role needs. Everything is deleted after 30 days at the
          latest, and visitors are told so in the chat.
        </p>
      </header>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {!canEdit ? <Alert tone="info">Only owners and admins can correct or delete customer notes.</Alert> : null}
      {customers === null && !error ? <Spinner label="Loading customers…" /> : null}
      {customers?.length === 0 ? (
        <p className="text-ink-muted">
          No customers yet. Notes appear here a few minutes after a visitor&apos;s conversation ends.
        </p>
      ) : null}
      <ul className="flex flex-col gap-4">
        {customers?.map((c) => (
          <CustomerCard key={c.id} base={base} customer={c} canEdit={canEdit} onChanged={load} />
        ))}
      </ul>
    </div>
  );
}

function CustomerCard({
  base,
  customer,
  canEdit,
  onChanged,
}: {
  base: string;
  customer: Customer;
  canEdit: boolean;
  onChanged: () => Promise<void>;
}) {
  const { handleError } = useSession();
  const [detail, setDetail] = useState<CustomerDetail | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const url = `${base}/${customer.id}`;

  async function toggle() {
    if (!open && detail === null) {
      try {
        setDetail(await api<CustomerDetail>(url));
      } catch (err) {
        setError(handleError(err));
        return;
      }
    }
    setOpen((o) => !o);
  }

  async function reload() {
    setDetail(await api<CustomerDetail>(url));
    await onChanged();
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api(url, "DELETE");
      await onChanged();
    } catch (err) {
      setError(handleError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5" data-testid="customer">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="font-semibold break-words">{customer.email ?? "Visitor (email not confirmed)"}</h2>
          <p className="text-sm text-ink-muted">
            {customer.item_count} {customer.item_count === 1 ? "note" : "notes"} · last seen{" "}
            <time dateTime={customer.last_seen_at}>{dateTime.format(new Date(customer.last_seen_at))}</time>
          </p>
        </div>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
            customer.verified ? "bg-brand text-white" : "bg-paper text-ink-muted ring-1 ring-line"
          }`}
        >
          {customer.verified ? "Email confirmed" : "Not confirmed"}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => void toggle()} aria-expanded={open}>
          {open ? "Hide notes" : "Show notes"}
        </Button>
        {canEdit ? (
          <Button size="sm" variant="danger" busy={busy} onClick={() => void remove()}>
            Delete customer
          </Button>
        ) : null}
      </div>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {open && detail ? (
        detail.memory.length === 0 ? (
          <p className="text-sm text-ink-muted">No notes.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {detail.memory.map((m) => (
              <NoteRow key={m.id} url={`${url}/memory/${m.id}`} item={m} canEdit={canEdit} onChanged={reload} />
            ))}
          </ul>
        )
      ) : null}
    </li>
  );
}

function NoteRow({
  url,
  item,
  canEdit,
  onChanged,
}: {
  url: string;
  item: MemoryItem;
  canEdit: boolean;
  onChanged: () => Promise<void>;
}) {
  const { handleError } = useSession();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(item.value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setEditing(false);
      await onChanged();
    } catch (err) {
      setError(handleError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-col gap-2 rounded-md border border-line bg-paper p-3 text-sm" data-testid="memory-item">
      {editing ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void act(() => api(url, "PATCH", { value }));
          }}
          className="flex flex-wrap items-end gap-2"
        >
          <label className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="font-semibold">{CATEGORY_LABEL[item.category] ?? item.category}</span>
            <input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              maxLength={120}
              dir="auto"
              className="min-h-11 rounded-md border border-line-strong bg-surface px-3 text-base focus-visible:border-brand"
            />
          </label>
          <Button type="submit" size="sm" busy={busy}>
            Save
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={busy}>
            Cancel
          </Button>
        </form>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p dir="auto">
            <span className="font-semibold">{CATEGORY_LABEL[item.category] ?? item.category}:</span> {item.value}
          </p>
          {canEdit ? (
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
                Edit
              </Button>
              <Button size="sm" variant="danger" busy={busy} onClick={() => void act(() => api(url, "DELETE"))}>
                Delete
              </Button>
            </div>
          ) : null}
        </div>
      )}
      <p className="text-xs text-ink-muted">
        Deleted on <time dateTime={item.expires_at}>{dateTime.format(new Date(item.expires_at))}</time>
      </p>
      {error ? <Alert tone="error">{error}</Alert> : null}
    </li>
  );
}
