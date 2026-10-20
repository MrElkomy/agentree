"use client";

/**
 * Anonymous visitor chat with a business's Sales Agent, shared by the public page panel
 * and the website widget iframe. Both run on our own origin, so the public API's
 * same-origin check passes; customer websites only ever embed the iframe.
 *
 * The guest token is an opaque bearer credential for this browser and this business only.
 * It is kept in localStorage (`agentree:guest:{slug}`) because the widget runs in a
 * third-party iframe where cookies are unreliable; when storage is blocked it lives in
 * memory for this tab. It is never put in a URL. The backend decides everything: a token
 * only ever reaches its own conversations.
 */
import { useCallback, useEffect, useState } from "react";
import { ApiError, api, isApiError, type GuestChatReply, type GuestMessage, type GuestSession } from "./api";

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
const opts = (bearer?: string) => ({ bearer, credentials: "omit" as const });

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

export function useGuestChat(slug: string, channel: GuestChannel) {
  const [turns, setTurns] = useState<GuestTurn[]>([]);
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
    setError(null);
  }, [slug]);

  return { turns, busy, restoring, error, send, reset };
}
