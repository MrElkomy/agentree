"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useBusiness } from "@/components/business-shell";
import { useSession } from "@/components/session";
import { Alert, Button, Spinner, TextField } from "@/components/ui";
import { PUBLIC_ROLES } from "@/lib/agents";
import { api, type KnowledgeEntry } from "@/lib/api";
import { messageFor } from "@/lib/messages";
import { atLeast } from "@/lib/roles";

const MAX_BODY = 20000;

const roleTitle = (role: string) => PUBLIC_ROLES.find((r) => r.role === role)?.title ?? role;

export default function KnowledgePage() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const canPublish = atLeast(business.role, "admin");
  const base = `/api/businesses/${encodeURIComponent(business.id)}/knowledge`;
  const [entries, setEntries] = useState<KnowledgeEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setEntries(await api<KnowledgeEntry[]>(base));
    } catch (err) {
      setError(handleError(err));
    }
  }, [base, handleError]);

  useEffect(() => {
    let cancelled = false;
    api<KnowledgeEntry[]>(base).then(
      (e) => !cancelled && setEntries(e),
      (err) => !cancelled && setError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [base, handleError]);

  const published = entries?.filter((e) => e.status === "published").length ?? 0;

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <title>{`Knowledge · ${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">Knowledge</h1>
        <p className="max-w-prose text-ink-muted">
          What your agents may tell customers: products, prices, policies, FAQs. Agents only use
          <strong className="text-ink"> published</strong> entries; edits go back to draft until
          an owner or admin publishes them again.
        </p>
      </header>
      {error ? <Alert tone="error">{error}</Alert> : null}

      <section aria-labelledby="new-entry-heading" className="rounded-lg border border-line bg-surface p-6">
        <h2 id="new-entry-heading" className="mb-4 text-lg font-semibold">
          Add an entry
        </h2>
        <EntryForm base={base} onSaved={load} />
      </section>

      <section aria-labelledby="entries-heading" className="flex flex-col gap-4">
        <h2 id="entries-heading" className="text-lg font-semibold">
          Entries
          {entries ? (
            <span className="ml-2 text-base font-normal text-ink-muted">
              ({published} published of {entries.length})
            </span>
          ) : null}
        </h2>
        {entries === null && !error ? <Spinner label="Loading knowledge…" /> : null}
        {entries?.length === 0 ? (
          <p className="text-ink-muted">No entries yet. Start with your prices and your most common questions.</p>
        ) : null}
        <ul className="flex flex-col gap-4">
          {entries?.map((e) => (
            <EntryItem key={e.id} entry={e} base={base} canPublish={canPublish} onChanged={load} />
          ))}
        </ul>
      </section>
    </div>
  );
}

function EntryForm({
  base,
  initial,
  onSaved,
  onCancel,
}: {
  base: string;
  initial?: KnowledgeEntry;
  onSaved: () => Promise<void>;
  onCancel?: () => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [body, setBody] = useState(initial?.body ?? "");
  // Empty: every agent may use the entry.
  const [roles, setRoles] = useState<string[]>(initial?.agent_roles ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (initial) {
        await api(`${base}/${initial.id}`, "PATCH", { title, body, agent_roles: roles });
      } else {
        await api(base, "POST", { title, body, agent_roles: roles });
        setTitle("");
        setBody("");
        setRoles([]);
      }
      await onSaved();
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label={initial ? "Edit entry" : "New entry"}>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <TextField label="Title" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} />
      <div className="flex flex-col gap-1.5">
        <label htmlFor={initial ? `body-${initial.id}` : "body-new"} className="text-sm font-semibold">
          Content
        </label>
        <textarea
          id={initial ? `body-${initial.id}` : "body-new"}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          required
          maxLength={MAX_BODY}
          rows={6}
          className="rounded-md border border-line-strong bg-surface px-3 py-2 text-base focus-visible:border-brand"
        />
        <p className="text-sm text-ink-muted">
          {body.length.toLocaleString()} / {MAX_BODY.toLocaleString()} characters
        </p>
      </div>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-semibold">Which agents use this entry</legend>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="radio"
            name={initial ? `scope-${initial.id}` : "scope-new"}
            checked={roles.length === 0}
            onChange={() => setRoles([])}
            className="size-4 accent-brand"
          />
          All agents
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="radio"
            name={initial ? `scope-${initial.id}` : "scope-new"}
            checked={roles.length > 0}
            onChange={() => setRoles((r) => (r.length ? r : ["sales"]))}
            className="size-4 accent-brand"
          />
          Only these agents
        </label>
        {roles.length > 0 ? (
          <div className="flex flex-wrap gap-x-5 gap-y-2 ps-6">
            {PUBLIC_ROLES.map(({ role, title }) => (
              <label key={role} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={roles.includes(role)}
                  disabled={roles.length === 1 && roles.includes(role)}
                  onChange={(e) =>
                    setRoles((r) => (e.target.checked ? [...r, role] : r.filter((x) => x !== role)))
                  }
                  className="size-4 accent-brand"
                />
                {title}
              </label>
            ))}
          </div>
        ) : null}
        <p className="text-sm text-ink-muted">
          For example, troubleshooting steps only for Technical Support. Other agents never see it.
        </p>
      </fieldset>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" busy={busy}>
          {initial ? "Save changes" : "Save as draft"}
        </Button>
        {onCancel ? (
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        ) : null}
      </div>
    </form>
  );
}

function EntryItem({
  entry,
  base,
  canPublish,
  onChanged,
}: {
  entry: KnowledgeEntry;
  base: string;
  canPublish: boolean;
  onChanged: () => Promise<void>;
}) {
  const { handleError } = useSession();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isPublished = entry.status === "published";

  async function act(action: "publish" | "unpublish" | "delete") {
    setBusy(action);
    setError(null);
    try {
      if (action === "delete") await api(`${base}/${entry.id}`, "DELETE");
      else await api(`${base}/${entry.id}/${action}`, "POST");
      await onChanged();
    } catch (err) {
      setError(handleError(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="rounded-lg border border-line bg-surface p-5" data-testid="knowledge-entry">
      {editing ? (
        <EntryForm
          base={base}
          initial={entry}
          onCancel={() => setEditing(false)}
          onSaved={async () => {
            setEditing(false);
            await onChanged();
          }}
        />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="font-semibold break-words">{entry.title}</h3>
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                isPublished ? "bg-brand text-white" : "bg-warn-soft text-warn ring-1 ring-warn/30"
              }`}
            >
              {isPublished ? "Published" : "Draft"}
            </span>
            <span className="text-xs text-ink-muted" data-testid="knowledge-scope">
              {entry.agent_roles.length ? `Only ${entry.agent_roles.map(roleTitle).join(", ")}` : "All agents"}
            </span>
          </div>
          <p className="line-clamp-4 text-sm whitespace-pre-wrap text-ink-muted">{entry.body}</p>
          {error ? <Alert tone="error">{error}</Alert> : null}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
              Edit
            </Button>
            {canPublish ? (
              <>
                <Button
                  size="sm"
                  variant={isPublished ? "secondary" : "primary"}
                  busy={busy === "publish" || busy === "unpublish"}
                  onClick={() => void act(isPublished ? "unpublish" : "publish")}
                >
                  {isPublished ? "Unpublish" : "Publish"}
                </Button>
                <Button size="sm" variant="danger" busy={busy === "delete"} onClick={() => void act("delete")}>
                  Delete
                </Button>
              </>
            ) : null}
          </div>
        </div>
      )}
    </li>
  );
}
