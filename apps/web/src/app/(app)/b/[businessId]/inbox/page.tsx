"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useBusiness } from "@/components/business-shell";
import { InboxStatusBadge } from "@/components/inbox-status-badge";
import { useSession } from "@/components/session";
import { Alert, Button, Spinner } from "@/components/ui";
import { api, type InboxItem, type InboxPage, type Member } from "@/lib/api";
import { INBOX_POLL_MS, INBOX_STATUSES, INBOX_STATUS_LABEL, type InboxStatus } from "@/lib/inbox";
import { CHANNEL_LABEL, dateTime } from "@/lib/leads";

const PAGE_SIZE = 50;

export default function InboxPageView() {
  const { business } = useBusiness();
  const { handleError, me } = useSession();
  const base = `/api/businesses/${encodeURIComponent(business.id)}`;
  const [filter, setFilter] = useState<InboxStatus | "all">("all");
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [next, setNext] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [members, setMembers] = useState<Member[]>([]);

  const fetchPage = useCallback(
    (before?: string) => {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
      if (filter !== "all") params.set("status", filter);
      if (before) params.set("before", before);
      return api<InboxPage>(`${base}/inbox?${params}`);
    },
    [base, filter],
  );

  useEffect(() => {
    let cancelled = false;
    api<Member[]>(`${base}/members`).then(
      (m) => !cancelled && setMembers(m),
      () => {
        // names are a convenience; the list still works without them
      },
    );
    return () => {
      cancelled = true;
    };
  }, [base]);

  // Load, then refresh the first page while the inbox is open (no push channel yet).
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchPage().then(
        (page) => {
          if (cancelled) return;
          setItems(page.items);
          setCounts(page.counts);
          setNext(page.next_before ?? null);
          setError(null);
        },
        (err) => !cancelled && setError(handleError(err)),
      );
    void load();
    const timer = setInterval(() => void load(), INBOX_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [fetchPage, handleError]);

  async function loadMore() {
    if (!next) return;
    setLoadingMore(true);
    try {
      const page = await fetchPage(next);
      setItems((prev) => [...(prev ?? []), ...page.items]);
      setNext(page.next_before ?? null);
    } catch (err) {
      setError(handleError(err));
    } finally {
      setLoadingMore(false);
    }
  }

  const memberName = (id: string | null | undefined) =>
    !id ? null : id === me.id ? "You" : (members.find((m) => m.user_id === id)?.email ?? "A member");
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="flex max-w-5xl flex-col gap-8">
      <title>{`Inbox · ${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">Inbox</h1>
        <p className="max-w-prose text-ink-muted">
          Conversations from your public page and website chat. When a visitor asks for a person, or
          the AI can&apos;t help, the conversation waits here for your team and owners and admins get
          an email. Take it over to reply yourself; the AI stays quiet until you hand it back.
        </p>
      </header>

      <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-2">
        {(["all", ...INBOX_STATUSES] as const).map((s) => {
          const n = s === "all" ? total : (counts[s] ?? 0);
          return (
            <button
              key={s}
              type="button"
              aria-pressed={filter === s}
              onClick={() => {
                setItems(null);
                setFilter(s);
              }}
              className={[
                "inline-flex min-h-9 items-center gap-2 rounded-full border px-3 text-sm font-semibold",
                filter === s
                  ? "border-brand bg-brand text-white"
                  : "border-line-strong bg-surface text-ink hover:border-brand",
              ].join(" ")}
            >
              {s === "all" ? "All" : INBOX_STATUS_LABEL[s]}
              <span
                className={[
                  "rounded-full px-1.5 text-xs",
                  filter === s ? "bg-white/20" : s === "needs_human" && n ? "bg-warn-soft text-warn" : "bg-paper",
                ].join(" ")}
              >
                {n}
              </span>
            </button>
          );
        })}
      </div>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {items === null ? (
        error ? null : <Spinner label="Loading conversations" />
      ) : items.length === 0 ? (
        <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-6">
          <p className="font-semibold">
            {filter === "all" ? "No conversations yet." : "No conversations with this status."}
          </p>
          {filter === "all" ? (
            <p className="text-ink-muted">
              Share your public page or add the website chat. Visitor conversations show up here.
            </p>
          ) : null}
        </div>
      ) : (
        <section aria-label="Conversations" className="flex flex-col gap-4">
          <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
            {items.map((item) => (
              <li key={item.id} data-testid="inbox-row">
                <Link
                  href={`/b/${business.id}/inbox/${item.id}`}
                  className="flex flex-col gap-1 px-4 py-3 hover:bg-brand-soft/50 focus-visible:bg-brand-soft/50 sm:flex-row sm:items-center sm:gap-6 sm:px-5"
                >
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="font-semibold text-ink">
                      Visitor on {CHANNEL_LABEL[item.channel] ?? item.channel}
                    </span>
                    <span className="truncate text-sm text-ink-muted" dir="auto">
                      {item.preview_role === "user"
                        ? ""
                        : item.preview_role === "human"
                          ? "Team: "
                          : "AI: "}
                      {item.preview || "No messages"}
                    </span>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-3 text-sm text-ink-muted">
                    {memberName(item.assignee_user_id) ? (
                      <span className="max-w-48 truncate">{memberName(item.assignee_user_id)}</span>
                    ) : null}
                    <time dateTime={item.last_message_at}>
                      {dateTime.format(new Date(item.last_message_at))}
                    </time>
                    <InboxStatusBadge status={item.status} />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          {next ? (
            <div>
              <Button variant="secondary" size="sm" busy={loadingMore} onClick={() => void loadMore()}>
                Load more
              </Button>
            </div>
          ) : null}
        </section>
      )}
    </div>
  );
}
