import { ApiError } from "./api";

/**
 * User-facing copy for backend error codes. Auth messages stay deliberately generic,
 * matching the backend's no-enumeration behaviour.
 */
const MESSAGES: Record<string, string> = {
  invalid_credentials: "That email and password don't match. Check them and try again.",
  email_not_verified:
    "Verify your email before signing in. Use the link we sent, or send a new one below.",
  rate_limited: "Too many attempts. Wait a few minutes, then try again.",
  invalid_or_expired_token: "This link is invalid or has expired. Request a new one.",
  invalid_or_expired_invitation:
    "This invitation is invalid, expired, or was sent to a different email address.",
  invalid_current_password: "Your current password is incorrect.",
  slug_taken: "That URL name is already in use. Try another one.",
  invalid_slug:
    "Use 3–63 lowercase letters, digits or single hyphens, starting and ending with a letter or digit. Some names are reserved.",
  insufficient_role: "Your role doesn't allow this action.",
  last_owner: "A business needs at least one owner. Make someone else an owner first.",
  not_found: "We couldn't find that. It may have been removed, or you no longer have access.",
  origin_not_allowed: "This request was blocked for security reasons. Reload the page and retry.",
  not_authenticated: "Your session has ended. Sign in again.",
  network_error: "Can't reach Agentree right now. Check your connection and try again.",
  validation_error: "Some fields are invalid. Check them and try again.",
};

export function messageFor(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code.startsWith("password must")) {
      // Backend password-policy messages are safe, fixed strings.
      return `Your password ${err.code.slice("password ".length)}.`;
    }
    const known = MESSAGES[err.code];
    if (known) return known;
    if (err.status >= 500) return "Something went wrong on our side. Try again in a moment.";
  }
  return "Something went wrong. Try again.";
}

export const PASSWORD_HINT = "At least 12 characters. A short phrase works well.";
export const MIN_PASSWORD = 12;

export const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$/;

export function slugProblem(slug: string): string | null {
  if (!slug) return null;
  if (slug.length < 3) return "At least 3 characters.";
  if (slug.length > 63) return "At most 63 characters.";
  if (/[^a-z0-9-]/.test(slug)) return "Only lowercase letters, digits and hyphens.";
  if (slug.startsWith("-") || slug.endsWith("-")) return "Start and end with a letter or digit.";
  if (slug.includes("--")) return "No double hyphens.";
  return SLUG_RE.test(slug) ? null : "Use lowercase letters, digits and hyphens.";
}

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 63)
    .replace(/-$/, "");
}
