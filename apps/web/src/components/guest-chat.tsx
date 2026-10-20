"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { RichText, textDirection } from "@/components/rich-text";
import { Button } from "@/components/ui";
import { MAX_GUEST_MESSAGE, useGuestChat, type GuestChannel } from "@/lib/guest-chat";

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
  const { turns, busy, restoring, error, send, reset } = useGuestChat(slug, channel);
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputId = useId();
  const counterId = `${inputId}-counter`;
  const agentName = `${displayName} Sales Agent`;

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [turns, busy]);

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
              className="ms-auto max-w-[85%] rounded-lg bg-canopy px-4 py-2.5 text-white"
              data-testid="guest-user"
            >
              <p dir={textDirection(t.content)} className="break-words whitespace-pre-wrap">
                {t.content}
              </p>
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
        {busy ? (
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
            className="min-h-11 flex-1 resize-none rounded-md border border-line-strong bg-surface px-3 py-2 text-base focus-visible:border-canopy"
          />
          <Button type="submit" busy={busy} disabled={!draft.trim() || over}>
            Send
          </Button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-ink-muted">
          <p>You&apos;re chatting with an AI assistant.</p>
          <div className="flex items-center gap-3">
            {turns.length && !busy ? (
              <button type="button" onClick={reset} className="font-semibold underline-offset-2 hover:underline">
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
