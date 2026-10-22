"use client";

/**
 * Bot challenge (Cloudflare Turnstile, U-16) before a visitor's first chat session. The backend
 * decides: the page tells us the public site key only when the challenge is on, and the token is
 * verified server-side for our host and the `guest_session` action. Turnstile's script is loaded
 * only when needed. The widget shows itself only when Cloudflare wants an interaction; otherwise
 * the visitor never sees it.
 */

type Turnstile = {
  render: (container: HTMLElement, options: Record<string, unknown>) => string;
  remove: (widgetId: string) => void;
};

declare global {
  interface Window {
    turnstile?: Turnstile;
  }
}

const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
const TIMEOUT_MS = 120_000;
const siteKeys = new Map<string, string>();
let script: Promise<Turnstile> | null = null;

/** The public page or widget registers its site key (none when the challenge is off). */
export function registerChallenge(slug: string, siteKey: string | null | undefined) {
  if (siteKey) siteKeys.set(slug, siteKey);
  else siteKeys.delete(slug);
}

export class ChallengeError extends Error {}

function loadTurnstile(): Promise<Turnstile> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  script ??= new Promise<Turnstile>((resolve, reject) => {
    const el = document.createElement("script");
    el.src = SCRIPT_URL;
    el.async = true;
    el.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new ChallengeError("no turnstile")));
    el.onerror = () => {
      script = null;
      el.remove();
      reject(new ChallengeError("turnstile did not load"));
    };
    document.head.appendChild(el);
  });
  return script;
}

/** A fresh one-time token for opening a session, or undefined when the challenge is off. */
export async function challengeToken(slug: string): Promise<string | undefined> {
  const siteKey = siteKeys.get(slug);
  if (!siteKey) return undefined;
  const turnstile = await loadTurnstile();
  const box = document.createElement("div");
  box.setAttribute("data-testid", "bot-challenge");
  box.className = "fixed inset-x-0 bottom-4 z-50 flex justify-center";
  document.body.appendChild(box);
  let widgetId: string | undefined;
  try {
    return await new Promise<string>((resolve, reject) => {
      const timer = window.setTimeout(() => reject(new ChallengeError("timeout")), TIMEOUT_MS);
      const fail = () => {
        window.clearTimeout(timer);
        reject(new ChallengeError("challenge failed"));
      };
      widgetId = turnstile.render(box, {
        sitekey: siteKey,
        action: "guest_session",
        appearance: "interaction-only",
        callback: (token: string) => {
          window.clearTimeout(timer);
          resolve(token);
        },
        "error-callback": fail,
        "expired-callback": fail,
        "timeout-callback": fail,
      });
    });
  } finally {
    if (widgetId) turnstile.remove(widgetId);
    box.remove();
  }
}
