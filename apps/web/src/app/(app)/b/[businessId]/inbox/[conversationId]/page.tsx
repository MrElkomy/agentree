"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useBusiness } from "@/components/business-shell";
import { InboxStatusBadge } from "@/components/inbox-status-badge";
import { RichText, textDirection } from "@/components/rich-text";
import { useSession } from "@/components/session";
import { Alert, Button, SelectField, Spinner } from "@/components/ui";
import { api, isApiError, type InboxConversation, type InboxMessage, type Member } from "@/lib/api";
import { INBOX_POLL_MS } from "@/lib/inbox";
import { CHANNEL_LABEL, dateTime } from "@/lib/leads";

const MAX_REPLY = 4000;

type Action = "take-over" | "release" | "resolve" | "assign" | "reply";

export default function InboxConversationPage() {
  const { business } = useBusiness();
  const { handleError, me } = useSession();
  const { conversationId } = useParams<{ conversationId: string }>();
  const base = `/api/businesses/${encodeURIComponent(business.id)}`;
  const path = `${base}/inbox/${encodeURIComponent(conversationId)}`;
  const listHref = `/b/${business.id}/inbox`;

  const [data, setData] = useState<InboxConversation | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Action | null>(null);
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const lastCount = useRef(0);

  const load = useCallback(async () => {
    try {
      setData(await api<InboxConversation>(path));
    } catch (err) {
      if (isApiError(err, 404)) setMissing(true);
      else setError(handleError(err));
    }
  }, [path, handleError]);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      if (!cancelled) void load();
    };
    tick();
    const timer = setInterval(tick, INBOX_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    api<Member[]>(`${base}/members`).then(
      (m) => !cancelled && setMembers(m),
      () => {
        // the assign control is hidden without the member list
      },
    );
    return () => {
      cancelled = true;
    };
  }, [base]);

  const count = data?.messages.length ?? 0;
  useEffect(() => {
    if (count > lastCount.current) endRef.current?.scrollIntoView?.({ block: "end" });
    lastCount.current = count;
  }, [count]);

  async function act(action: Action, body?: unknown) {
    setPending(action);
    setError(null);
    try {
      await api(`${path}/${action}`, "POST", body);
      if (action === "reply") setDraft("");
      await load();
    } catch (err) {
      setError(handleError(err));
      if (isApiError(err, 409)) await load();
    } finally {
      setPending(null);
    }
  }

  function onReply(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || text.length > MAX_REPLY || pending) return;
    void act("reply", { content: text });
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) onReply(e);
  }

  if (missing) {
    return (
      <div className="flex max-w-3xl flex-col gap-4">
        <Alert tone="info">This conversation doesn&apos;t exist or was deleted.</Alert>
        <Link href={listHref} className="font-semibold text-brand">
          Back to the inbox
        </Link>
      </div>
    );
  }
  if (!data) return error ? <Alert tone="error">{error}</Alert> : <Spinner label="Loading conversation" />;

  const conv = data.conversation;
  const assigneeLabel = (id: string | null | undefined) =>
    !id ? "Nobody" : id === me.id ? "You" : (members.find((m) => m.user_id === id)?.email ?? "A member");
  const authorLabel = (m: InboxMessage) =>
    m.author_user_id === me.id ? "You" : (members.find((x) => x.user_id === m.author_user_id)?.email ?? "Team member");
  const active = conv.status === "human_active";
  const over = draft.length > MAX_REPLY;

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <title>{`Conversation · Inbox · ${business.name} · Agentree`}</title>
      <nav aria-label="Breadcrumb">
        <Link href={listHref} className="text-sm font-semibold text-brand">
          ← Inbox
        </Link>
      </nav>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-bold sm:text-3xl">
            Visitor on {CHANNEL_LABEL[conv.channel] ?? conv.channel}
          </h1>
          <p className="text-sm text-ink-muted">
            Started <time dateTime={conv.created_at}>{dateTime.format(new Date(conv.created_at))}</time>
            {conv.handoff_requested_at ? (
              <>
                {" · "}
                {conv.handoff_reason === "agent" ? "The AI asked for a person" : "The visitor asked for a person"}{" "}
                <time dateTime={conv.handoff_requested_at}>
                  {dateTime.format(new Date(conv.handoff_requested_at))}
                </time>
              </>
            ) : null}
          </p>
        </div>
        <InboxStatusBadge status={conv.status} />
      </header>

      {error ? <Alert tone="error">{error}</Alert> : null}

      <section
        aria-label="Conversation controls"
        className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-4 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between sm:p-5"
      >
        <div className="flex flex-col gap-1 text-sm">
          <span className="text-ink-muted">Assigned to</span>
          <span className="font-semibold" data-testid="inbox-assignee">
            {assigneeLabel(conv.assignee_user_id)}
          </span>
        </div>
        {members.length ? (
          <SelectField
            label="Assign to"
            value={conv.assignee_user_id ?? ""}
            disabled={pending !== null}
            onChange={(e) => void act("assign", { assignee_user_id: e.target.value || null })}
            className="sm:w-64"
          >
            <option value="">Nobody</option>
            {members.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.user_id === me.id ? `${m.email} (you)` : m.email}
              </option>
            ))}
          </SelectField>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {!(active && conv.assignee_user_id === me.id) ? (
            <Button size="sm" busy={pending === "take-over"} disabled={pending !== null} onClick={() => void act("take-over")}>
              {active ? "Take over from teammate" : "Take over"}
            </Button>
          ) : null}
          {conv.status === "needs_human" || active ? (
            <Button
              size="sm"
              variant="secondary"
              busy={pending === "release"}
              disabled={pending !== null}
              onClick={() => void act("release")}
            >
              Hand back to AI
            </Button>
          ) : null}
          {conv.status !== "resolved" ? (
            <Button
              size="sm"
              variant="secondary"
              busy={pending === "resolve"}
              disabled={pending !== null}
              onClick={() => void act("resolve")}
            >
              Resolve
            </Button>
          ) : null}
        </div>
      </section>

      <section aria-label="Messages" aria-live="polite" className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 sm:p-5">
        {data.messages.length === 0 ? <p className="text-ink-muted">No messages yet.</p> : null}
        {data.messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="me-auto flex max-w-[85%] flex-col gap-1" data-testid="inbox-visitor">
              <div className="rounded-lg border border-line bg-paper px-4 py-2.5">
                <p dir={textDirection(m.content)} className="whitespace-pre-wrap break-words">{m.content}</p>
              </div>
              <p className="text-xs text-ink-muted">
                Visitor · <time dateTime={m.created_at}>{dateTime.format(new Date(m.created_at))}</time>
              </p>
            </div>
          ) : m.role === "human" ? (
            <div key={m.id} className="ms-auto flex max-w-[85%] flex-col items-end gap-1" data-testid="inbox-team">
              <div className="rounded-lg bg-brand px-4 py-2.5 text-white">
                <p dir={textDirection(m.content)} className="whitespace-pre-wrap break-words">{m.content}</p>
              </div>
              <p className="text-xs text-ink-muted">
                {authorLabel(m)} · <time dateTime={m.created_at}>{dateTime.format(new Date(m.created_at))}</time>
              </p>
            </div>
          ) : (
            <div key={m.id} className="ms-auto flex max-w-[85%] flex-col items-end gap-1" data-testid="inbox-ai">
              <div className="rounded-lg border border-brand/30 bg-brand-soft px-4 py-2.5">
                <RichText text={m.content} />
              </div>
              <p className="text-xs text-ink-muted">
                AI agent · <time dateTime={m.created_at}>{dateTime.format(new Date(m.created_at))}</time>
              </p>
            </div>
          ),
        )}
        <div ref={endRef} />
      </section>

      {active ? (
        <form onSubmit={onReply} aria-label="Reply to the visitor" className="flex flex-col gap-2">
          <label htmlFor="inbox-reply" className="text-sm font-semibold">
            Reply as the {business.name} team
          </label>
          <textarea
            id="inbox-reply"
            dir="auto"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            rows={3}
            aria-invalid={over || undefined}
            className="rounded-md border border-line-strong bg-surface px-3 py-2 text-base focus-visible:border-brand"
          />
          <div className="flex items-center justify-between gap-3">
            <span className={`text-xs ${over ? "font-semibold text-danger" : "text-ink-muted"}`}>
              The visitor sees your reply as the {business.name} team. {draft.length}/{MAX_REPLY}
            </span>
            <Button type="submit" size="sm" busy={pending === "reply"} disabled={!draft.trim() || over}>
              Send reply
            </Button>
          </div>
        </form>
      ) : (
        <p className="rounded-lg border border-line bg-paper p-4 text-sm text-ink-muted">
          {conv.status === "needs_human"
            ? "The visitor is waiting for a person and the AI is paused. Take over to reply."
            : conv.status === "resolved"
              ? "This conversation is resolved. If the visitor writes again, the AI answers."
              : "The AI is answering this conversation. Take over to reply yourself."}
        </p>
      )}
    </div>
  );
}
