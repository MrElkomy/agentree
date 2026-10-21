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
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  api,
  isApiError,
  type GuestChatReply,
  type GuestLeadIn,
  type GuestMessage,
  type GuestSession,
  type LeadSuggestion,
} from "./api";

export const MAX_GUEST_MESSAGE = 1000;

export type GuestChannel = "public" | "widget";
export type GuestTurn = { role: "user" | "assistant"; content: string };

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

async function chatOnce(slug: string, message: string, channel: GuestChannel): Promise<GuestChatReply> {
  let token = read(tokenKey(slug)) ?? (await newToken(slug));
  let conversationId = read(convKey(slug));
  let renewed = false;
  let restarted = false;
  for (;;) {
    try {
      const reply = await api<GuestChatReply>(
        `${base(slug)}/chat`,
        "POST",
        { message, conversation_id: conversationId, channel },
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
    const done = (restored: GuestTurn[]) => {
      if (cancelled) return;
      setTurns(restored);
      setRestoring(false);
    };
    if (!token || !conversationId) {
      void Promise.resolve().then(() => done([]));
    } else {
      api<GuestMessage[]>(
        `${base(slug)}/conversations/${encodeURIComponent(conversationId)}/messages`,
        "GET",
        undefined,
        opts(token),
      ).then(
        (messages) =>
          done(
            messages
              .filter((m) => m.role === "user" || m.role === "assistant")
              .map((m) => ({ role: m.role as GuestTurn["role"], content: m.content })),
          ),
        (err) => {
          if (isApiError(err, 401)) write(tokenKey(slug), null);
          if (isApiError(err, 401) || isApiError(err, 404)) write(convKey(slug), null);
          done([]);
        },
      );
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
      try {
        const reply = await chatOnce(slug, text, channel);
        setTurns((t) => [...t, { role: "assistant", content: reply.reply }]);
        if (reply.lead_suggestion) setSuggestion(reply.lead_suggestion);
        return true;
      } catch (err) {
        setTurns((t) => t.slice(0, -1)); // not answered: give the text back to the visitor
        setError(guestErrorMessage(err));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [slug, channel],
  );

  const reset = useCallback(() => {
    write(convKey(slug), null);
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

  return { turns, busy, restoring, error, send, reset, suggestion, submitLead, newIdempotencyKey };
}
