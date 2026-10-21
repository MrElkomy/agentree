"use client";

import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { useBusiness } from "@/components/business-shell";
import { useSession } from "@/components/session";
import { Alert, Button, Spinner, TextField } from "@/components/ui";
import { api, type PublicProfile, type PublicProfileIn } from "@/lib/api";
import { atLeast } from "@/lib/roles";
import { useClientValue } from "@/lib/use-client-value";

// Mirrors the backend limits (agentree/public/service.py); the backend validates everything.
const MAX_DISPLAY_NAME = 80;
const MAX_BIO = 500;
const MAX_LINKS = 10;
const MAX_LABEL = 60;
const MAX_URL = 500;
const MAX_DESCRIPTION = 160;
const MAX_ORIGINS = 10;
const MAX_BUDGET = 5000;

// Hint only: exact https origin (host and optional port, no path). The backend decides,
// and also accepts http://localhost:<port> in development.
const ORIGIN_HINT_RE = /^https:\/\/[a-z0-9-]+(\.[a-z0-9-]+)+(:\d{1,5})?\/?$/i;
const LOCAL_RE = /^http:\/\/localhost:\d{1,5}\/?$/i;

type LinkRow = { key: number; label: string; url: string; description: string };
type Form = {
  enabled: boolean;
  displayName: string;
  bio: string;
  links: LinkRow[];
  origins: string;
  budget: string;
  memory: boolean;
};

let nextKey = 1;
const row = (label = "", url = "", description = ""): LinkRow => ({ key: nextKey++, label, url, description });

function toForm(p: PublicProfile): Form {
  return {
    enabled: p.enabled,
    displayName: p.display_name ?? "",
    bio: p.bio,
    links: p.links.map((l) => row(l.label, l.url, l.description)),
    origins: p.widget_origins.join("\n"),
    budget: String(p.daily_reply_budget),
    memory: p.customer_memory,
  };
}

const originLines = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

function originProblem(line: string): string | null {
  if (LOCAL_RE.test(line)) return null;
  if (ORIGIN_HINT_RE.test(line)) return null;
  if (/^http:\/\//i.test(line)) return "Use https:// (secure websites only).";
  if (!/^https:\/\//i.test(line)) return "Start with https://, for example https://www.example.com";
  return "Only the website address — no page path, query or wildcard.";
}

export default function PublicPageSettings() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const canEdit = atLeast(business.role, "admin");
  const path = `/api/businesses/${encodeURIComponent(business.id)}/public-profile`;

  const [profile, setProfile] = useState<PublicProfile | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const origin = useClientValue(() => window.location.origin, "");

  useEffect(() => {
    let cancelled = false;
    api<PublicProfile>(path).then(
      (p) => {
        if (cancelled) return;
        setProfile(p);
        setForm(toForm(p));
      },
      (err) => !cancelled && setLoadError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [path, handleError]);

  const update = (patch: Partial<Form>) => {
    setForm((f) => (f ? { ...f, ...patch } : f));
    setNotice(null);
  };

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form || !canEdit) return;
    const body: PublicProfileIn = {
      enabled: form.enabled,
      display_name: form.displayName.trim() || null,
      bio: form.bio.trim(),
      links: form.links
        .filter((l) => l.label.trim() || l.url.trim())
        .map((l) => ({ label: l.label.trim(), url: l.url.trim(), description: l.description.trim() })),
      widget_origins: originLines(form.origins),
      daily_reply_budget: Number(form.budget),
      customer_memory: form.memory,
    };
    setSaving(true);
    setNotice(null);
    try {
      const saved = await api<PublicProfile>(path, "PUT", body);
      setProfile(saved);
      setForm(toForm(saved));
      setNotice({
        tone: "success",
        text: saved.enabled ? "Saved. Your public page is live." : "Saved. Your public page is off.",
      });
    } catch (err) {
      setNotice({ tone: "error", text: handleError(err) });
    } finally {
      setSaving(false);
    }
  }

  const publicUrl = profile && origin ? `${origin}/${profile.slug}` : "";
  const snippet =
    profile && origin
      ? `<script src="${origin}/widget.js" data-agentree="${profile.slug}" async></script>`
      : "";

  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <title>{`Public page & widget · ${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">Public page &amp; widget</h1>
        <p className="max-w-prose text-ink-muted">
          Give customers a page where they can find your links and chat with your Sales Agent, and
          add the same chat to your own website. The page stays off until you turn it on, and
          the website chat only works on the websites you list below.
        </p>
      </header>

      {loadError ? <Alert tone="error">{loadError}</Alert> : null}
      {!form && !loadError ? <Spinner label="Loading public page settings…" /> : null}

      {profile ? (
        <section
          aria-labelledby="share-heading"
          className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-6"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="share-heading" className="text-lg font-semibold">
              Your public page
            </h2>
            <span
              data-testid="public-status"
              className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                profile.enabled ? "bg-brand-soft text-brand-deep" : "bg-paper text-ink-muted ring-1 ring-line-strong"
              }`}
            >
              {profile.enabled ? "Live" : "Off"}
            </span>
          </div>
          <CopyRow label="Page address" value={publicUrl} testId="public-url">
            {profile.enabled && publicUrl ? (
              <a href={publicUrl} target="_blank" rel="noopener noreferrer" className="text-sm font-semibold text-brand underline-offset-2 hover:underline">
                Open
              </a>
            ) : null}
          </CopyRow>
          {!profile.enabled ? (
            <p className="text-sm text-ink-muted">
              The page is off: visitors see &ldquo;not found&rdquo; until you turn it on and save.
            </p>
          ) : null}
          <CopyRow label="Website chat code" value={snippet} testId="embed-snippet" multiline />
          <p className="text-sm text-ink-muted">
            Paste this code before <code>&lt;/body&gt;</code> on your website. The chat button
            appears only on the websites listed under &ldquo;Websites allowed to show the
            chat&rdquo;, and only while the page is on.
          </p>
        </section>
      ) : null}

      {form ? (
        <form onSubmit={onSubmit} className="flex flex-col gap-6" aria-label="Public page settings">
          {!canEdit ? (
            <Alert tone="info">Only owners and admins can change the public page and widget.</Alert>
          ) : null}
          <fieldset disabled={!canEdit || saving} className="flex flex-col gap-6">
            <label className="flex items-start gap-3 rounded-lg border border-line bg-surface p-4">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => update({ enabled: e.target.checked })}
                className="mt-1 size-4"
              />
              <span className="flex flex-col gap-0.5">
                <span className="font-semibold">Public page is on</span>
                <span className="text-sm text-ink-muted">
                  Anyone with the link can see the page and chat with your Sales Agent. Replies use
                  your AI provider key and count toward the daily reply limit.
                </span>
              </span>
            </label>

            <TextField
              label="Display name"
              value={form.displayName}
              onChange={(e) => update({ displayName: e.target.value })}
              maxLength={MAX_DISPLAY_NAME}
              placeholder={business.name}
              hint={`Shown at the top of the page. Leave empty to use “${business.name}”.`}
              dir="auto"
            />

            <TextArea
              label="Bio"
              value={form.bio}
              onChange={(v) => update({ bio: v })}
              max={MAX_BIO}
              rows={4}
              hint="A short introduction: what you offer and who you help."
            />

            <LinksEditor links={form.links} onChange={(links) => update({ links })} canEdit={canEdit} />

            <OriginsField value={form.origins} onChange={(origins) => update({ origins })} />

            <TextField
              label="Daily reply limit"
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_BUDGET}
              required
              value={form.budget}
              onChange={(e) => update({ budget: e.target.value })}
              hint={`Most AI calls the public page and widget may make per day (UTC), 1–${MAX_BUDGET}: replies and customer notes. Protects your AI provider credit; visitors are asked to try later once it's reached.`}
              className="max-w-xs"
            />
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.memory}
                disabled={!canEdit}
                onChange={(e) => update({ memory: e.target.checked })}
                className="mt-0.5 size-4 accent-brand"
              />
              <span>
                <span className="font-semibold">Remember customers</span>
                <span className="block text-xs text-ink-muted">
                  After each conversation, one small AI call on your key saves short notes about the
                  customer (it counts toward the daily limit). Visitors can confirm their email so
                  your agents use those notes next time. Everything is deleted after 30 days.
                </span>
              </span>
            </label>
          </fieldset>

          {notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null}
          {canEdit ? (
            <div>
              <Button type="submit" busy={saving}>
                Save
              </Button>
            </div>
          ) : null}
        </form>
      ) : null}
    </div>
  );
}

function CopyRow({
  label,
  value,
  testId,
  multiline = false,
  children,
}: {
  label: string;
  value: string;
  testId: string;
  multiline?: boolean;
  children?: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-semibold">{label}</span>
      <div className="flex flex-wrap items-center gap-3">
        <code
          data-testid={testId}
          dir="ltr"
          className={`min-w-0 flex-1 rounded-md border border-line bg-paper px-3 py-2 text-sm ${
            multiline ? "break-all whitespace-pre-wrap" : "truncate"
          }`}
        >
          {value || "…"}
        </code>
        <div className="flex items-center gap-3">
          {children}
          <Button variant="secondary" size="sm" onClick={() => void copy()} disabled={!value}>
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function TextArea({
  label,
  value,
  onChange,
  max,
  rows,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  max: number;
  rows: number;
  hint: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      <textarea
        id={id}
        dir="auto"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={max}
        rows={rows}
        aria-describedby={`${id}-hint`}
        className="rounded-md border border-line-strong bg-surface px-3 py-2 text-base focus-visible:border-brand"
      />
      <div id={`${id}-hint`} className="flex justify-between gap-3 text-sm text-ink-muted">
        <span>{hint}</span>
        <span aria-label={`${value.length} of ${max} characters`}>
          {value.length}/{max}
        </span>
      </div>
    </div>
  );
}

function LinksEditor({
  links,
  onChange,
  canEdit,
}: {
  links: LinkRow[];
  onChange: (links: LinkRow[]) => void;
  canEdit: boolean;
}) {
  const set = (i: number, patch: Partial<LinkRow>) =>
    onChange(links.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const move = (i: number, by: -1 | 1) => {
    const next = [...links];
    const [item] = next.splice(i, 1);
    if (!item) return;
    next.splice(i + by, 0, item);
    onChange(next);
  };
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="text-sm font-semibold">Links</legend>
      <p className="-mt-1 text-sm text-ink-muted">
        Shown under your agents, in this order — your website, menu, booking or social profiles.
        Up to {MAX_LINKS}; each must start with https://. A short description is optional.
      </p>
      {links.length === 0 ? <p className="text-sm text-ink-muted">No links yet.</p> : null}
      <ol className="flex flex-col gap-3">
        {links.map((l, i) => {
          const urlBad = l.url.trim() !== "" && !/^https:\/\/\S+$/i.test(l.url.trim());
          return (
            <li
              key={l.key}
              className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
              data-testid="link-row"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
                <TextField
                  label={`Link ${i + 1} label`}
                  value={l.label}
                  onChange={(e) => set(i, { label: e.target.value })}
                  maxLength={MAX_LABEL}
                  placeholder="Our website"
                  dir="auto"
                  className="sm:w-48"
                />
                <TextField
                  label={`Link ${i + 1} address`}
                  type="url"
                  value={l.url}
                  onChange={(e) => set(i, { url: e.target.value })}
                  maxLength={MAX_URL}
                  placeholder="https://www.example.com"
                  dir="ltr"
                  error={urlBad ? "Must start with https://" : null}
                  className="min-w-0 flex-1"
                />
              </div>
              <TextField
                label={`Link ${i + 1} description (optional)`}
                value={l.description}
                onChange={(e) => set(i, { description: e.target.value })}
                maxLength={MAX_DESCRIPTION}
                placeholder="Browse our packages and prices"
                dir="auto"
              />
              {canEdit ? (
                <div className="flex justify-end gap-1">
                  <Button variant="ghost" size="sm" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move link ${i + 1} up`}>
                    ↑
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => move(i, 1)}
                    disabled={i === links.length - 1}
                    aria-label={`Move link ${i + 1} down`}
                  >
                    ↓
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => onChange(links.filter((_, j) => j !== i))} aria-label={`Remove link ${i + 1}`}>
                    Remove
                  </Button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
      {canEdit ? (
        <div>
          <Button variant="secondary" size="sm" onClick={() => onChange([...links, row()])} disabled={links.length >= MAX_LINKS}>
            Add link
          </Button>
        </div>
      ) : null}
    </fieldset>
  );
}

function OriginsField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const id = useId();
  const lines = originLines(value);
  const problems = lines
    .map((line) => ({ line, problem: originProblem(line) }))
    .filter((p): p is { line: string; problem: string } => p.problem !== null);
  const tooMany = lines.length > MAX_ORIGINS;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold">
        Websites allowed to show the chat
      </label>
      <textarea
        id={id}
        dir="ltr"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        spellCheck={false}
        autoCapitalize="off"
        placeholder={"https://www.example.com\nhttps://shop.example.com"}
        aria-describedby={`${id}-hint${problems.length || tooMany ? ` ${id}-problems` : ""}`}
        aria-invalid={problems.length || tooMany ? true : undefined}
        className={`rounded-md border bg-surface px-3 py-2 font-mono text-sm focus-visible:border-brand ${
          problems.length || tooMany ? "border-danger" : "border-line-strong"
        }`}
      />
      <p id={`${id}-hint`} className="text-sm text-ink-muted">
        One website address per line, exactly as it appears in the browser (with or without
        &ldquo;www&rdquo; counts as a different website). Up to {MAX_ORIGINS}. Leave empty to keep
        the chat on your Agentree page only.
      </p>
      {problems.length || tooMany ? (
        <ul id={`${id}-problems`} className="flex flex-col gap-0.5 text-sm font-medium text-danger">
          {tooMany ? <li>At most {MAX_ORIGINS} websites.</li> : null}
          {problems.map((p) => (
            <li key={p.line}>
              <span dir="ltr" className="font-mono">
                {p.line}
              </span>
              : {p.problem}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
