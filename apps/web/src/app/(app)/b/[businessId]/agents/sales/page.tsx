"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useBusiness } from "@/components/business-shell";
import { RichText, textDirection } from "@/components/rich-text";
import { Alert, Button, buttonClass } from "@/components/ui";
import { api, isApiError, type ChatMessage, type ConsoleReply } from "@/lib/api";
import { messageFor } from "@/lib/messages";
import { StreamInterruptedError, streamApi } from "@/lib/stream";

type AssistantTurn = {
  role: "assistant";
  content: string;
  // meta exists only for replies received in this page session (restored history has none).
  meta?: Pick<ConsoleReply, "sources" | "fallback_used">;
  streaming?: boolean;
  failed?: boolean; // the reply broke off mid-way; nothing was saved
};
type Turn = { role: "user"; content: string } | AssistantTurn;

// The open conversation survives a page refresh (per business, this browser only).
const storageKey = (businessId: string) => `agentree:sales-conversation:${businessId}`;

function remember(businessId: string, id: string | null) {
  try {
    if (id) localStorage.setItem(storageKey(businessId), id);
    else localStorage.removeItem(storageKey(businessId));
  } catch {
    // storage unavailable (private mode): the chat simply isn't restored
  }
}

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

  useEffect(() => {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(storageKey(business.id));
    } catch {
      return;
    }
    if (!saved) return;
    let cancelled = false;
    api<ChatMessage[]>(`${base}/conversations/${encodeURIComponent(saved)}/messages`)
      .then((messages) => {
        if (cancelled) return;
        setConversationId(saved);
        setTurns(
          messages.map((m) =>
            m.role === "user" ? { role: "user", content: m.content } : { role: "assistant", content: m.content },
          ),
        );
      })
      .catch(() => remember(business.id, null)); // deleted (e.g. 30-day retention) or not ours
    return () => {
      cancelled = true;
    };
  }, [base, business.id]);

  // Updates the reply being streamed (always the last turn).
  function patchReply(fn: (a: AssistantTurn) => AssistantTurn) {
    setTurns((t) => {
      const last = t[t.length - 1];
      return last?.role === "assistant" ? [...t.slice(0, -1), fn(last)] : t;
    });
  }

  async function send(message: string) {
    const text = message.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setTurns((t) => [...t, { role: "user", content: text }, { role: "assistant", content: "", streaming: true }]);
    setDraft("");
    try {
      const r = await streamApi<ConsoleReply>(
        `${base}/agents/sales/console/stream`,
        { message: text, conversation_id: conversationId },
        {
          onDelta: (d) => patchReply((a) => ({ ...a, content: a.content + d })),
          onRestart: () => patchReply((a) => ({ ...a, content: "" })), // the backup answers instead
        },
      );
      setConversationId(r.conversation_id);
      remember(business.id, r.conversation_id);
      patchReply(() => ({
        role: "assistant",
        content: r.reply, // final text replaces the streamed one
        meta: { sources: r.sources, fallback_used: r.fallback_used },
      }));
    } catch (err) {
      if (err instanceof StreamInterruptedError) {
        patchReply((a) => ({ ...a, streaming: false, failed: true })); // keep the partial text
      } else {
        setTurns((t) => t.slice(0, -2)); // the message was not answered or saved
        setDraft(text);
        setError({
          text: messageFor(err),
          needsProvider:
            isApiError(err, 409, "no_ai_provider_configured") || isApiError(err, 503, "ai_unavailable"),
        });
      }
    } finally {
      setBusy(false);
    }
  }

  /** Sends the interrupted message again (it was not saved). */
  function retry() {
    const user = turns[turns.length - 2];
    if (!user || user.role !== "user" || busy) return;
    setTurns((t) => t.slice(0, -2));
    void send(user.content);
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
              remember(business.id, null);
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
        aria-busy={busy}
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
            <div key={i} className="ml-auto max-w-[85%] rounded-lg bg-brand px-4 py-3 text-white" data-testid="chat-user">
              <p dir={textDirection(t.content)} className="whitespace-pre-wrap break-words">{t.content}</p>
            </div>
          ) : (
            <div key={i} className="mr-auto flex max-w-[85%] flex-col gap-2" data-testid="chat-assistant">
              {t.content ? (
                <div className={`rounded-lg border border-line bg-paper px-4 py-3 ${t.failed ? "opacity-70" : ""}`}>
                  <RichText text={t.content} />
                </div>
              ) : t.streaming ? (
                <p className="text-sm text-ink-muted" role="status">
                  Sales Agent is typing…
                </p>
              ) : null}
              {t.failed ? (
                <p className="flex flex-wrap items-center gap-2 text-sm text-danger" role="alert" data-testid="chat-interrupted">
                  The reply was interrupted and nothing was saved.
                  <Button size="sm" variant="secondary" onClick={retry} disabled={busy}>
                    Retry
                  </Button>
                </p>
              ) : null}
              <p className="text-xs text-ink-muted">
                {business.name} Sales Agent
                {t.meta && !t.meta.sources.length ? (
                  <>
                    {" · "}
                    <span className="font-semibold text-warn">No published knowledge matched this question.</span>
                  </>
                ) : null}
                {t.meta?.fallback_used ? " · answered by backup provider" : ""}
              </p>
            </div>
          ),
        )}
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
          className="rounded-md border border-line-strong bg-surface px-3 py-2 text-base focus-visible:border-brand"
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
