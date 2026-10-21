"use client";

/**
 * Anonymous visitor chat with a business's Sales Agent, shared by the public page panel
 * and the website widget iframe. Both run on our own origin, so the public API's
 * same-origin check passes; customer websites only ever embed the iframe.
 *
 * The guest token is an opaque credential for this browser and this business only, sent in
 * the X-Agentree-Guest header. Same-origin requests also carry the browser's HTTP basic auth
 * for a gate in front of the app (staging); the public API ignores the dashboard cookie.
 * It is kept in localStorage (`agentree:guest:{slug}`) because the widget runs in a
 * third-party iframe where cookies are unreliable; when storage is blocked it lives in
 * memory for this tab. It is never put in a URL. The backend decides everything: a token
 * only ever reaches its own conversations.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  api,
  isApiError,
  type GuestChatReply,
  type GuestConversation,
  type GuestLeadIn,
  type GuestSession,
  type LeadSuggestion,
} from "./api";
import { StreamInterruptedError, streamApi, type StreamHandlers } from "./stream";

export const MAX_GUEST_MESSAGE = 1000;

export type GuestChannel = "public" | "widget";
/** `human` is a team member of the business replying after a handoff. */
export type GuestTurn = {
  role: "user" | "assistant" | "human";
  content: string;
  failed?: boolean; // an assistant reply that broke off mid-way (nothing was saved)
};
export type ConversationStatus = GuestConversation["status"];

/** While a person is (or will be) answering, the AI stays quiet and the chat polls for replies. */
export const isPaused = (status: ConversationStatus) =>
  status === "needs_human" || status === "human_active";
const POLL_MS = 5000;

const tokenKey = (slug: string) => `agentree:guest:${slug}`;
const convKey = (slug: string) => `agentree:guest-conv:${slug}`;

// Fallback when localStorage is unavailable (private mode, blocked third-party storage).
const memory = new Map<string, string>();

function read(key: string): string | null {
  try {
    return localStorage.getItem(key) ?? memory.get(key) ?? null;
  } catch {
    return memory.get(key) ?? null;
  }
}

function write(key: string, value: string | null) {
  if (value === null) memory.delete(key);
  else memory.set(key, value);
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // storage unavailable: the in-memory copy keeps the chat working for this tab
  }
}

/** True when this browser has an open conversation with this business. */
export const hasGuestConversation = (slug: string) =>
  read(tokenKey(slug)) !== null && read(convKey(slug)) !== null;

const GUEST_MESSAGES: Record<string, string> = {
  busy: "We're getting a lot of messages — please try again in a moment.",
  agent_unavailable: "The assistant is unavailable right now.",
  not_found: "This chat isn't available right now.",
  network_error: "Can't connect right now. Check your connection and try again.",
  validation_error: "That message can't be sent. Keep it under 1,000 characters.",
  invalid_email: "Check the email address.",
  invalid_phone: "Check the phone number (digits, spaces, + and dashes).",
  invalid_contact: "Add an email address or a phone number so the team can reach you.",
  idempotency_conflict: "Please send the form again.",
};

function toTurns(conversation: GuestConversation): GuestTurn[] {
  return conversation.messages
    .filter((m) => m.role === "user" || m.role === "assistant" || m.role === "human")
    .map((m) => ({ role: m.role as GuestTurn["role"], content: m.content }));
}

/** Visitor-facing copy: short, neutral, and never mentions providers, models or keys. */
export function guestErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const known = GUEST_MESSAGES[err.code];
    if (known) return known;
  }
  return "Something went wrong. Please try again.";
}

const base = (slug: string) => `/api/public/${encodeURIComponent(slug)}`;
// Public calls never send the dashboard cookie; the guest token is the only credential.
const opts = (guestToken?: string) => ({ guestToken });

async function newToken(slug: string): Promise<string> {
  const s = await api<GuestSession>(`${base(slug)}/sessions`, "POST", undefined, opts());
  write(tokenKey(slug), s.token);
  return s.token;
}

function fetchConversation(slug: string, token: string, conversationId: string) {
  return api<GuestConversation>(
    `${base(slug)}/conversations/${encodeURIComponent(conversationId)}`,
    "GET",
    undefined,
    opts(token),
  );
}

async function chatOnce(
  slug: string,
  message: string,
  channel: GuestChannel,
  handlers: StreamHandlers,
): Promise<GuestChatReply> {
  let token = read(tokenKey(slug)) ?? (await newToken(slug));
  let conversationId = read(convKey(slug));
  let renewed = false;
  let restarted = false;
  for (;;) {
    try {
      const reply = await streamApi<GuestChatReply>(
        `${base(slug)}/chat/stream`,
        { message, conversation_id: conversationId, channel },
        handlers,
        opts(token),
      );
      write(convKey(slug), reply.conversation_id);
      return reply;
    } catch (err) {
      if (isApiError(err, 401) && !renewed) {
        // Expired or unknown session: start a fresh one once. Its conversations are new too.
        renewed = true;
        write(convKey(slug), null);
        conversationId = null;
        token = await newToken(slug);
        continue;
      }
      if (isApiError(err, 404) && conversationId && !restarted) {
        // The conversation is gone (retention) or not ours: continue in a new one.
        restarted = true;
        write(convKey(slug), null);
        conversationId = null;
        continue;
      }
      throw err;
    }
  }
}

export type LeadDraft = Omit<GuestLeadIn, "conversation_id" | "consent" | "idempotency_key">;

function newIdempotencyKey(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }
}

export function useGuestChat(slug: string, channel: GuestChannel) {
  const [turns, setTurns] = useState<GuestTurn[]>([]);
  const [status, setStatus] = useState<ConversationStatus>("open");
  // Prefill offered by the agent after the visitor shared contact details (never sent as-is).
  const [suggestion, setSuggestion] = useState<LeadSuggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Restore this visitor's open conversation (same browser, same business).
  useEffect(() => {
    let cancelled = false;
    const token = read(tokenKey(slug));
    const conversationId = read(convKey(slug));
    const done = (restored: GuestConversation | null) => {
      if (cancelled) return;
      setTurns(restored ? toTurns(restored) : []);
      setStatus(restored?.status ?? "open");
      setRestoring(false);
    };
    if (!token || !conversationId) {
      void Promise.resolve().then(() => done(null));
    } else {
      fetchConversation(slug, token, conversationId).then(done, (err) => {
        if (isApiError(err, 401)) write(tokenKey(slug), null);
        if (isApiError(err, 401) || isApiError(err, 404)) write(convKey(slug), null);
        done(null);
      });
    }
    return () => {
      cancelled = true;
    };
  }, [slug]);

  /** Sends one message; resolves false (and keeps the text for a retry) when it failed. */
  const send = useCallback(
    async (message: string): Promise<boolean> => {
      const text = message.trim();
      if (!text || text.length > MAX_GUEST_MESSAGE) return false;
      setBusy(true);
      setError(null);
      setTurns((t) => [...t, { role: "user", content: text }]);
      // The reply streams into an assistant turn after the visitor's message.
      const setReply = (fn: (current: string) => string | null) =>
        setTurns((t) => {
          const last = t[t.length - 1];
          const current = last?.role === "assistant" ? last.content : null;
          const next = fn(current ?? "");
          const base = current === null ? t : t.slice(0, -1);
          return next === null ? base : [...base, { role: "assistant", content: next }];
        });
      try {
        const reply = await chatOnce(slug, text, channel, {
          onDelta: (d) => setReply((c) => c + d),
          onRestart: () => setReply(() => null), // the backup provider answers instead
        });
        // Final text replaces the streamed one. Empty: a person is answering, the AI stayed quiet.
        setReply(() => reply.reply || null);
        setStatus(reply.status);
        if (reply.lead_suggestion) setSuggestion(reply.lead_suggestion);
        return true;
      } catch (err) {
        if (err instanceof StreamInterruptedError) {
          // Keep what arrived, marked as interrupted; the visitor can send the message again.
          setTurns((t) => {
            const last = t[t.length - 1];
            return last?.role === "assistant" ? [...t.slice(0, -1), { ...last, failed: true }] : t;
          });
          return true;
        }
        setTurns((t) => t.slice(0, -1)); // not answered: give the text back to the visitor
        setError(guestErrorMessage(err));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [slug, channel],
  );

  // While paused, poll for the team's replies and for the hand-back to the assistant.
  const busyRef = useRef(false);
  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);
  useEffect(() => {
    if (!isPaused(status)) return;
    const timer = setInterval(() => {
      const token = read(tokenKey(slug));
      const conversationId = read(convKey(slug));
      if (!token || !conversationId || busyRef.current) return;
      fetchConversation(slug, token, conversationId).then(
        (conversation) => {
          if (busyRef.current) return;
          setTurns(toTurns(conversation));
          setStatus(conversation.status);
        },
        () => {
          // transient: the next tick retries
        },
      );
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [slug, status]);

  /** The visitor asks for a person (`true`) or chooses to continue with the assistant. */
  const setHandoff = useCallback(
    async (wanted: boolean): Promise<void> => {
      const token = read(tokenKey(slug));
      const conversationId = read(convKey(slug));
      if (!token || !conversationId) return;
      setError(null);
      try {
        const conversation = await api<GuestConversation>(
          `${base(slug)}/conversations/${encodeURIComponent(conversationId)}/handoff`,
          wanted ? "POST" : "DELETE",
          undefined,
          opts(token),
        );
        setTurns(toTurns(conversation));
        setStatus(conversation.status);
      } catch (err) {
        setError(guestErrorMessage(err));
      }
    },
    [slug],
  );

  /** Sends an interrupted message again (it was not saved). */
  const retry = useCallback(async (): Promise<void> => {
    const user = turns[turns.length - 2];
    if (busy || turns[turns.length - 1]?.failed !== true || user?.role !== "user") return;
    setTurns((t) => t.slice(0, -2));
    await send(user.content);
  }, [busy, send, turns]);

  const reset = useCallback(() => {
    write(convKey(slug), null);
    setStatus("open");
    setTurns([]);
    setSuggestion(null);
    setError(null);
  }, [slug]);

  /**
   * Sends the details the visitor reviewed, with their explicit consent. The key is fixed per
   * form attempt, so a network retry records the lead once. Throws a visitor-facing message.
   */
  const submitLead = useCallback(
    async (draft: LeadDraft, idempotencyKey: string): Promise<void> => {
      const token = read(tokenKey(slug));
      const conversationId = read(convKey(slug));
      if (!token || !conversationId) throw new Error(GUEST_MESSAGES.not_found);
      const body: GuestLeadIn = {
        ...draft,
        email: draft.email?.trim() || null,
        phone: draft.phone?.trim() || null,
        conversation_id: conversationId,
        consent: true,
        idempotency_key: idempotencyKey,
      };
      try {
        await api(`${base(slug)}/leads`, "POST", body, opts(token));
      } catch (err) {
        throw new Error(guestErrorMessage(err));
      }
    },
    [slug],
  );

  return {
    turns,
    status,
    busy,
    restoring,
    error,
    send,
    retry,
    reset,
    setHandoff,
    suggestion,
    submitLead,
    newIdempotencyKey,
  };
}
