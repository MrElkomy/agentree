"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useBusiness } from "@/components/business-shell";
import { useSession } from "@/components/session";
import { Alert, Button, SelectField, Spinner, TextField } from "@/components/ui";
import { api, type Credential, type ProviderName, type Slot } from "@/lib/api";
import { messageFor, messageForCode } from "@/lib/messages";
import { atLeast } from "@/lib/roles";

const PROVIDERS: { value: ProviderName; label: string; model: string; keyHint: string }[] = [
  { value: "openai", label: "OpenAI", model: "gpt-4o-mini", keyHint: "Starts with sk-" },
  { value: "anthropic", label: "Anthropic", model: "claude-haiku-4-5", keyHint: "Starts with sk-ant-" },
  { value: "gemini", label: "Google Gemini", model: "gemini-2.5-flash", keyHint: "From Google AI Studio (starts with AIza)" },
  { value: "groq", label: "Groq (free tier)", model: "openai/gpt-oss-120b", keyHint: "Starts with gsk_" },
];
const LABEL = Object.fromEntries(PROVIDERS.map((p) => [p.value, p.label])) as Record<ProviderName, string>;

const SLOTS: { slot: Slot; title: string; text: string }[] = [
  { slot: "primary", title: "Primary provider", text: "Used for every answer while it works." },
  {
    slot: "backup",
    title: "Backup provider",
    text: "Used automatically when the primary is down, rate-limited or out of credit.",
  },
];

export default function AiProvidersPage() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const canEdit = atLeast(business.role, "admin");
  const base = `/api/businesses/${encodeURIComponent(business.id)}/ai-providers`;
  const [creds, setCreds] = useState<Credential[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setCreds(await api<Credential[]>(base));
    } catch (err) {
      setError(handleError(err));
    }
  }, [base, handleError]);

  useEffect(() => {
    let cancelled = false;
    api<Credential[]>(base).then(
      (c) => !cancelled && setCreds(c),
      (err) => !cancelled && setError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [base, handleError]);

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <title>{`AI Providers · ${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">AI Providers</h1>
        <p className="max-w-prose text-ink-muted">
          Your agents run on your own AI provider account. Keys are encrypted before they are
          stored and are never shown again — only the last 4 characters.
        </p>
      </header>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {!canEdit ? (
        <Alert tone="info">Only owners and admins can add or change provider keys.</Alert>
      ) : null}
      {creds === null && !error ? <Spinner label="Loading providers…" /> : null}
      {creds ? (
        <div className="grid gap-6 lg:grid-cols-2">
          {SLOTS.map((s) => (
            <SlotCard
              key={s.slot}
              {...s}
              base={base}
              credential={creds.find((c) => c.slot === s.slot) ?? null}
              canEdit={canEdit}
              onChanged={load}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SlotCard({
  slot,
  title,
  text,
  base,
  credential,
  canEdit,
  onChanged,
}: {
  slot: Slot;
  title: string;
  text: string;
  base: string;
  credential: Credential | null;
  canEdit: boolean;
  onChanged: () => Promise<void>;
}) {
  const { handleError } = useSession();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<"test" | "delete" | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "error" | "warning"; text: string } | null>(null);

  async function test() {
    setBusy("test");
    setNotice(null);
    try {
      const r = await api<{ ok: boolean; error_kind: string | null }>(`${base}/${slot}/test`, "POST");
      setNotice(
        r.ok
          ? { tone: "success", text: "The key works." }
          : { tone: "error", text: messageForCode(`provider_${r.error_kind}`) },
      );
      await onChanged();
    } catch (err) {
      setNotice({ tone: "error", text: handleError(err) });
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    setBusy("delete");
    try {
      await api(`${base}/${slot}`, "DELETE");
      await onChanged();
    } catch (err) {
      setNotice({ tone: "error", text: handleError(err) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <section
      aria-labelledby={`${slot}-heading`}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-6"
      data-testid={`slot-${slot}`}
    >
      <div>
        <h2 id={`${slot}-heading`} className="text-lg font-semibold">
          {title}
        </h2>
        <p className="mt-1 text-sm text-ink-muted">{text}</p>
      </div>
      {notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null}
      {credential && !editing ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-ink-muted">Provider</dt>
          <dd className="font-semibold">{LABEL[credential.provider]}</dd>
          <dt className="text-ink-muted">Model</dt>
          <dd className="font-mono break-all">{credential.model}</dd>
          <dt className="text-ink-muted">Key</dt>
          <dd className="font-mono">{credential.key_hint ? `•••• ${credential.key_hint}` : "••••"}</dd>
          <dt className="text-ink-muted">Status</dt>
          <dd>
            {credential.last_error_kind ? (
              <span className="font-semibold text-danger">Last call failed ({credential.last_error_kind})</span>
            ) : credential.last_verified_at ? (
              <span className="font-semibold text-canopy-deep">
                Working · checked {new Date(credential.last_verified_at).toLocaleString()}
              </span>
            ) : (
              <span className="text-ink-muted">Not tested yet</span>
            )}
          </dd>
        </dl>
      ) : null}
      {!credential && !editing ? <p className="text-sm text-ink-muted">No key connected.</p> : null}
      {editing ? (
        <KeyForm
          slot={slot}
          base={base}
          initial={credential}
          onCancel={() => setEditing(false)}
          onSaved={async (t) => {
            setEditing(false);
            setNotice({ tone: "success", text: t });
            await onChanged();
          }}
        />
      ) : canEdit ? (
        <div className="flex flex-wrap gap-2">
          <Button variant={credential ? "secondary" : "primary"} onClick={() => setEditing(true)}>
            {credential ? "Replace key" : "Connect a key"}
          </Button>
          {credential ? (
            <>
              <Button variant="secondary" busy={busy === "test"} onClick={() => void test()}>
                Test key
              </Button>
              <Button variant="danger" busy={busy === "delete"} onClick={() => void remove()}>
                Remove
              </Button>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function KeyForm({
  slot,
  base,
  initial,
  onCancel,
  onSaved,
}: {
  slot: Slot;
  base: string;
  initial: Credential | null;
  onCancel: () => void;
  onSaved: (text: string) => Promise<void>;
}) {
  const [provider, setProvider] = useState<ProviderName>(initial?.provider ?? "openai");
  const [model, setModel] = useState(initial?.model ?? "gpt-4o-mini");
  const [apiKey, setApiKey] = useState("");
  const [verify, setVerify] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const meta = PROVIDERS.find((p) => p.value === provider)!;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`${base}/${slot}`, "PUT", { provider, model: model.trim(), api_key: apiKey.trim(), verify });
      setApiKey("");
      await onSaved(verify ? "Key tested and saved securely." : "Key saved securely (not tested).");
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label={`${slot} provider key`}>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <SelectField
        label="Provider"
        value={provider}
        onChange={(e) => {
          const next = e.target.value as ProviderName;
          setProvider(next);
          setModel(PROVIDERS.find((p) => p.value === next)!.model);
        }}
      >
        {PROVIDERS.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </SelectField>
      <TextField
        label="Model"
        value={model}
        onChange={(e) => setModel(e.target.value)}
        required
        maxLength={100}
        hint="The model ID from your provider account."
        autoComplete="off"
        spellCheck={false}
      />
      <TextField
        label="API key"
        type="password"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        required
        minLength={8}
        maxLength={512}
        hint={meta.keyHint}
        autoComplete="off"
        spellCheck={false}
      />
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} className="size-4" />
        Test the key with a tiny request before saving
      </label>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" busy={busy}>
          Save key
        </Button>
        <Button variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
