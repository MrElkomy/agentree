"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { RichText, textDirection } from "@/components/rich-text";
import { Button } from "@/components/ui";
import type { LeadSuggestion } from "@/lib/api";
import {
  MAX_GUEST_MESSAGE,
  isPaused,
  useGuestChat,
  type GuestChannel,
  type LeadDraft,
} from "@/lib/guest-chat";

/**
 * Visitor chat with a business's Sales Agent (public page panel and website widget).
 * Replies are untrusted model output: RichText renders them as plain React nodes.
 * Visitors never see provider, model or knowledge details.
 */
export function GuestChat({
  slug,
  displayName,
  channel,
  className = "",
}: {
  slug: string;
  displayName: string;
  channel: GuestChannel;
  className?: string;
}) {
  const {
    turns,
    status,
    busy,
    restoring,
    error,
    send,
    reset,
    setHandoff,
    suggestion,
    submitLead,
    newIdempotencyKey,
  } = useGuestChat(slug, channel);
  const paused = isPaused(status);
  const teamName = `${displayName} team`;
  const [draft, setDraft] = useState("");
  // The details form opens when the agent offers it (a new suggestion) or when the visitor asks.
  const [manualOpen, setManualOpen] = useState(false);
  const [dismissed, setDismissed] = useState<LeadSuggestion | null>(null);
  const [leadSent, setLeadSent] = useState(false);
  const showForm = !leadSent && (manualOpen || (suggestion !== null && suggestion !== dismissed));
  const closeForm = () => {
    setManualOpen(false);
    setDismissed(suggestion);
  };
  const endRef = useRef<HTMLDivElement>(null);
  const keyRef = useRef("");
  const inputId = useId();
  const counterId = `${inputId}-counter`;
  const agentName = `${displayName} Sales Agent`;

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [turns, busy, showForm, leadSent, status]);

  async function submit() {
    const text = draft.trim();
    if (!text || busy || text.length > MAX_GUEST_MESSAGE) return;
    setDraft("");
    const ok = await send(text);
    if (!ok) setDraft(text);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit();
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  }

  const over = draft.length > MAX_GUEST_MESSAGE;

  return (
    <div className={`flex min-h-0 flex-col ${className}`} data-testid="guest-chat">
      <section
        aria-label={`Conversation with ${agentName}`}
        aria-live="polite"
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4"
      >
        {restoring ? (
          <p className="text-sm text-ink-muted" role="status">
            Loading your conversation…
          </p>
        ) : turns.length === 0 ? (
          <div className="me-auto max-w-[85%] rounded-lg border border-line bg-paper px-4 py-3">
            <p dir="auto">
              Hi! Ask {displayName} about products, prices or anything else — I&apos;ll answer from
              their information.
            </p>
          </div>
        ) : null}
        {turns.map((t, i) =>
          t.role === "user" ? (
            <div
              key={i}
              className="ms-auto max-w-[85%] rounded-lg bg-brand px-4 py-2.5 text-white"
              data-testid="guest-user"
            >
              <p dir={textDirection(t.content)} className="break-words whitespace-pre-wrap">
                {t.content}
              </p>
            </div>
          ) : t.role === "human" ? (
            <div key={i} className="me-auto flex max-w-[85%] flex-col gap-1" data-testid="guest-human">
              <div className="rounded-lg border border-brand/30 bg-brand-soft px-4 py-2.5">
                <p dir={textDirection(t.content)} className="break-words whitespace-pre-wrap">
                  {t.content}
                </p>
              </div>
              <p className="text-xs font-semibold text-brand-deep">{teamName}</p>
            </div>
          ) : (
            <div key={i} className="me-auto flex max-w-[85%] flex-col gap-1" data-testid="guest-assistant">
              <div className="rounded-lg border border-line bg-paper px-4 py-2.5">
                <RichText text={t.content} />
              </div>
              <p className="text-xs text-ink-muted">{agentName}</p>
            </div>
          ),
        )}
        {showForm ? (
          <LeadForm
            key={suggestion && !manualOpen ? JSON.stringify(suggestion) : "manual"}
            businessName={displayName}
            prefill={suggestion}
            onCancel={closeForm}
            onSubmit={async (lead) => {
              await submitLead(lead, keyRef.current);
              setLeadSent(true);
              setManualOpen(false);
            }}
            idempotencyKeyRef={keyRef}
            newKey={newIdempotencyKey}
          />
        ) : null}
        {leadSent ? (
          <p
            className="me-auto max-w-[85%] rounded-lg border border-brand/30 bg-brand-soft px-4 py-2.5 text-sm text-ink"
            role="status"
            data-testid="lead-sent"
          >
            Thanks! {displayName} has your details and will contact you soon.
          </p>
        ) : null}
        {status === "needs_human" ? (
          <div
            className="flex flex-col items-start gap-2 rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-sm"
            role="status"
            data-testid="handoff-waiting"
          >
            <p>
              You asked to talk to a person. The {teamName} has been notified and will reply here.
              You can keep writing in the meantime.
            </p>
            <button
              type="button"
              onClick={() => void setHandoff(false)}
              className="font-semibold underline-offset-2 hover:underline"
            >
              Continue with the assistant
            </button>
          </div>
        ) : status === "human_active" ? (
          <p
            className="rounded-lg border border-brand/30 bg-brand-soft px-4 py-3 text-sm"
            role="status"
            data-testid="handoff-active"
          >
            You&apos;re now chatting with the {teamName}.
          </p>
        ) : null}
        {busy && paused ? (
          <p className="me-auto text-sm text-ink-muted" role="status">
            Sending…
          </p>
        ) : busy ? (
          <p className="me-auto flex items-center gap-2 text-sm text-ink-muted" role="status">
            <span aria-hidden="true" className="flex gap-1">
              <span className="size-1.5 animate-bounce rounded-full bg-current" />
              <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:150ms]" />
              <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:300ms]" />
            </span>
            {agentName} is typing…
          </p>
        ) : null}
        <div ref={endRef} />
      </section>

      <form
        onSubmit={onSubmit}
        aria-label="Send a message"
        className="flex flex-col gap-2 border-t border-line bg-surface p-3"
      >
        {error ? (
          <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
            {error}
          </p>
        ) : null}
        <label htmlFor={inputId} className="sr-only">
          Message
        </label>
        <div className="flex items-end gap-2">
          <textarea
            id={inputId}
            dir="auto"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
            placeholder="Type your message…"
            aria-describedby={counterId}
            aria-invalid={over || undefined}
            className="min-h-11 flex-1 resize-none rounded-md border border-line-strong bg-surface px-3 py-2 text-base focus-visible:border-brand"
          />
          <Button type="submit" busy={busy} disabled={!draft.trim() || over}>
            Send
          </Button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-ink-muted">
          <p>
            {status === "human_active"
              ? `You're chatting with the ${teamName}.`
              : "You're chatting with an AI assistant."}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            {turns.length && !busy && !paused ? (
              <button
                type="button"
                onClick={() => void setHandoff(true)}
                className="font-semibold underline-offset-2 hover:underline"
              >
                Talk to a person
              </button>
            ) : null}
            {turns.length && !busy && !showForm && !leadSent ? (
              <button
                type="button"
                onClick={() => setManualOpen(true)}
                className="font-semibold underline-offset-2 hover:underline"
              >
                Leave your details
              </button>
            ) : null}
            {turns.length && !busy ? (
              <button
                type="button"
                onClick={() => {
                  reset();
                  setLeadSent(false);
                  setManualOpen(false);
                }}
                className="font-semibold underline-offset-2 hover:underline"
              >
                New conversation
              </button>
            ) : null}
            <span id={counterId} className={over ? "font-semibold text-danger" : undefined}>
              {draft.length}/{MAX_GUEST_MESSAGE}
            </span>
          </div>
        </div>
      </form>
    </div>
  );
}

/**
 * The visitor reviews the details the agent picked up (or types them), and must tick consent
 * before anything is sent. Nothing is saved until they press "Send my details".
 */
function LeadForm({
  businessName,
  prefill,
  onCancel,
  onSubmit,
  idempotencyKeyRef,
  newKey,
}: {
  businessName: string;
  prefill: LeadSuggestion | null;
  onCancel: () => void;
  onSubmit: (lead: LeadDraft) => Promise<void>;
  idempotencyKeyRef: { current: string };
  newKey: () => string;
}) {
  const id = useId();
  const [name, setName] = useState(prefill?.name ?? "");
  const [email, setEmail] = useState(prefill?.email ?? "");
  const [phone, setPhone] = useState(prefill?.phone ?? "");
  const [need, setNeed] = useState(prefill?.need ?? "");
  const [consent, setConsent] = useState(false);
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const hasContact = email.trim() !== "" || phone.trim() !== "";

  useEffect(() => {
    // One key per form: retries of the same submission are recorded once.
    idempotencyKeyRef.current = newKey();
  }, [idempotencyKeyRef, newKey]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!consent || !hasContact || sending) return;
    setSending(true);
    setProblem(null);
    try {
      await onSubmit({ name: name.trim(), email: email.trim(), phone: phone.trim(), need: need.trim() });
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "Something went wrong. Please try again.");
      // Changed details need a new key; an unchanged retry may reuse it.
      idempotencyKeyRef.current = newKey();
    } finally {
      setSending(false);
    }
  }

  const field = "min-h-10 rounded-md border border-line-strong bg-surface px-3 text-sm focus-visible:border-brand";
  return (
    <form
      onSubmit={submit}
      aria-labelledby={`${id}-title`}
      className="me-auto flex w-full max-w-[92%] flex-col gap-3 rounded-lg border border-line bg-surface p-4 shadow-sm"
      data-testid="lead-form"
    >
      <div className="flex flex-col gap-0.5">
        <p id={`${id}-title`} className="font-semibold">
          Share your details with {businessName}
        </p>
        <p className="text-xs text-ink-muted">Check them below. Nothing is sent until you confirm.</p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs font-semibold">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} dir="auto" className={field} autoComplete="name" />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold">
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} dir="ltr" className={field} autoComplete="email" />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold">
          Phone
          <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={32} dir="ltr" className={field} autoComplete="tel" />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold sm:col-span-2">
          What do you need?
          <textarea value={need} onChange={(e) => setNeed(e.target.value)} maxLength={500} rows={2} dir="auto" className={`${field} py-2`} />
        </label>
      </div>
      {!hasContact ? <p className="text-xs text-ink-muted">Add an email address or a phone number.</p> : null}
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1 size-4 accent-brand" />
        <span>I agree that {businessName} may contact me about my request.</span>
      </label>
      {problem ? (
        <p role="alert" className="text-sm font-medium text-danger">
          {problem}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" busy={sending} disabled={!consent || !hasContact}>
          Send my details
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={sending}>
          Not now
        </Button>
      </div>
    </form>
  );
}
