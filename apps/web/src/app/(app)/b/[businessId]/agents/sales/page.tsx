"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useBusiness } from "@/components/business-shell";
import { RichText } from "@/components/rich-text";
import { Alert, Button, buttonClass } from "@/components/ui";
import { api, isApiError, type ConsoleReply } from "@/lib/api";
import { messageFor } from "@/lib/messages";

type Turn =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; meta: Pick<ConsoleReply, "sources" | "provider" | "model" | "slot" | "fallback_used"> };

const SUGGESTIONS = ["What do you sell?", "How much does it cost?", "Do you offer a warranty?"];

export default function SalesAgentPage() {
  const { business } = useBusiness();
  const base = `/api/businesses/${encodeURIComponent(business.id)}`;
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ text: string; needsProvider: boolean } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [turns, busy]);

  async function send(message: string) {
    const text = message.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setTurns((t) => [...t, { role: "user", content: text }]);
    setDraft("");
    try {
      const r = await api<ConsoleReply>(`${base}/agents/sales/console`, "POST", {
        message: text,
        conversation_id: conversationId,
      });
      setConversationId(r.conversation_id);
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          content: r.reply,
          meta: { sources: r.sources, provider: r.provider, model: r.model, slot: r.slot, fallback_used: r.fallback_used },
        },
      ]);
    } catch (err) {
      setTurns((t) => t.slice(0, -1)); // the message was not answered or saved
      setDraft(text);
      setError({
        text: messageFor(err),
        needsProvider: isApiError(err, 409, "no_ai_provider_configured") || isApiError(err, 503, "ai_unavailable"),
      });
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(draft);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(draft);
    }
  }

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <title>{`Sales Agent · ${business.name} · Agentree`}</title>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold sm:text-3xl">Sales Agent</h1>
          <p className="max-w-prose text-ink-muted">
            Talk to your Sales Agent the way a customer would. It answers only from your published
            knowledge, using your own AI provider.
          </p>
        </div>
        {turns.length ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setTurns([]);
              setConversationId(null);
              setError(null);
            }}
          >
            New conversation
          </Button>
        ) : null}
      </header>

      <section
        aria-label="Conversation"
        aria-live="polite"
        className="flex min-h-80 flex-col gap-4 rounded-lg border border-line bg-surface p-4 sm:p-6"
      >
        {turns.length === 0 ? (
          <div className="flex flex-col gap-3">
            <p className="text-ink-muted">Try a question your customers ask:</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <Button key={s} variant="secondary" size="sm" onClick={() => void send(s)} disabled={busy}>
                  {s}
                </Button>
              ))}
            </div>
          </div>
        ) : null}
        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="ml-auto max-w-[85%] rounded-lg bg-canopy px-4 py-3 text-white" data-testid="chat-user">
              <p dir="auto" className="whitespace-pre-wrap break-words">{t.content}</p>
            </div>
          ) : (
            <div key={i} className="mr-auto flex max-w-[85%] flex-col gap-2" data-testid="chat-assistant">
              <div className="rounded-lg border border-line bg-paper px-4 py-3">
                <RichText text={t.content} />
              </div>
              <p className="text-xs text-ink-muted">
                {t.meta.sources.length ? null : (
                  <>
                    <span className="font-semibold text-warn">No published knowledge matched this question.</span>
                    {" · "}
                  </>
                )}
                {t.meta.provider} {t.meta.model}
                {t.meta.fallback_used ? " · answered by backup provider" : ""}
              </p>
            </div>
          ),
        )}
        {busy ? (
          <p className="mr-auto text-sm text-ink-muted" role="status">
            Sales Agent is typing…
          </p>
        ) : null}
        <div ref={endRef} />
      </section>

      {error ? (
        <Alert tone="error">
          <span>{error.text}</span>
          {error.needsProvider ? (
            <Link href={`/b/${business.id}/ai-providers`} className={`${buttonClass("secondary", "sm")} ml-3`}>
              Open AI Providers
            </Link>
          ) : null}
        </Alert>
      ) : null}

      <form onSubmit={onSubmit} className="flex flex-col gap-2" aria-label="Send a message">
        <label htmlFor="chat-input" className="sr-only">
          Message
        </label>
        <textarea
          id="chat-input"
          dir="auto"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          rows={3}
          maxLength={4000}
          placeholder="Ask about your products, prices or policies…"
          className="rounded-md border border-line-strong bg-surface px-3 py-2 text-base focus-visible:border-canopy"
        />
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-ink-muted">Enter to send · Shift+Enter for a new line</p>
          <Button type="submit" busy={busy} disabled={!draft.trim()}>
            Send
          </Button>
        </div>
      </form>
    </div>
  );
}
