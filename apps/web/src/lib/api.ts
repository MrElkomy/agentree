/**
 * Same-origin API client. The browser only talks to the Next.js origin; `/api/*` is
 * rewritten to FastAPI. The session lives in an HttpOnly cookie set by the backend and is
 * never readable here. The backend is the only authority for authentication and roles.
 */
import type { components } from "./api-types";

export type Schemas = components["schemas"];
export type Role = Schemas["Role"];
export type Me = Schemas["MeOut"];
export type Business = Schemas["BusinessOut"];
export type Member = Schemas["MemberOut"];
export type Invitation = Schemas["InvitationOut"];
export type Credential = Schemas["CredentialOut"];
export type ProviderName = Schemas["ProviderName"];
export type Slot = Schemas["Slot"];
export type KnowledgeEntry = Schemas["EntryOut"];
export type ConsoleReply = Schemas["ConsoleReplyOut"];
export type ChatMessage = Schemas["MessageOut"];
export type PublicProfile = Schemas["PublicProfileOut"];
export type PublicProfileIn = Schemas["PublicProfileIn"];
export type PublicPage = Schemas["PublicPageOut"];
export type GuestSession = Schemas["GuestSessionOut"];
export type GuestChatReply = Schemas["GuestChatOut"];
export type GuestMessage = Schemas["GuestMessageOut"];
export type LeadSuggestion = Schemas["LeadSuggestionOut"];
export type GuestLeadIn = Schemas["GuestLeadIn"];
export type Lead = Schemas["LeadOut"];
export type LeadDetail = Schemas["LeadDetailOut"];
export type LeadPage = Schemas["LeadPageOut"];
export type LeadStatus = Schemas["LeadStatus"];
export type AuditEvent = Schemas["AuditEventOut"];
export type AuditPage = Schemas["AuditPageOut"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(`${status} ${code}`);
    this.name = "ApiError";
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

function codeFrom(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // FastAPI request validation errors are a list.
    if (Array.isArray(detail)) return "validation_error";
    // Structured errors, e.g. {"code": "ai_unavailable", "errors": [...]}.
    if (detail && typeof detail === "object" && "code" in detail) {
      const code = (detail as { code: unknown }).code;
      if (typeof code === "string") return code;
    }
  }
  return "unknown_error";
}

type Options = {
  /** Guest session token for the public chat API (its own header, never a cookie). */
  guestToken?: string;
};

export async function api<T>(
  path: string,
  method: Method = "GET",
  body?: unknown,
  options: Options = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  // Not `Authorization`: that header carries HTTP basic auth of a gate in front of the app.
  if (options.guestToken) headers["X-Agentree-Guest"] = options.guestToken;
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network_error");
  }
  if (res.status === 204) return undefined as T;
  let parsed: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!res.ok) throw new ApiError(res.status, codeFrom(parsed));
  return parsed as T;
}

export const isApiError = (e: unknown, status?: number, code?: string): e is ApiError =>
  e instanceof ApiError &&
  (status === undefined || e.status === status) &&
  (code === undefined || e.code === code);

/** Path to the login page that returns to `next` afterwards (same-origin paths only). */
export function loginHref(next?: string): string {
  const safe = safeNext(next);
  return safe ? `/login?next=${encodeURIComponent(safe)}` : "/login";
}

/** Only allow local absolute paths as post-login redirects (no open redirects). */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return null;
  }
  return next;
}
