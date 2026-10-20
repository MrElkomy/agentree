/**
 * Server-side reads of the public (no login) API, used by the public page, the widget
 * iframe page and the widget framing policy. These calls go straight to FastAPI on the
 * private network (`AGENTREE_API_URL`, the same setting the `/api/*` rewrite uses) and never
 * carry a user's cookie. Only public, anonymous data is read here.
 */
import type { PublicPage } from "./api";

// Read at request time on the server; the container image sets it at runtime too.
const apiUrl = () => (process.env.AGENTREE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

// Same pattern the backend's validate_slug uses (reserved names are checked there).
const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$/;

export const isPublicSlug = (slug: string) => SLUG_RE.test(slug) && !slug.includes("--");

/** GET a public API path: the parsed body, null on 404, throws on any other failure. */
async function getJson<T>(path: string, timeoutMs: number): Promise<T | null> {
  const res = await fetch(`${apiUrl()}${path}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`public API answered ${res.status}`);
  return (await res.json()) as T;
}

/**
 * The enabled public page for `slug`, or null when it is unknown or disabled. Throws when
 * the API is unreachable, so visitors see an error instead of a misleading "not found".
 */
export async function fetchPublicPage(slug: string): Promise<PublicPage | null> {
  if (!isPublicSlug(slug)) return null;
  return getJson<PublicPage>(`/api/public/${encodeURIComponent(slug)}`, 5000);
}

/** Origins allowed to frame the widget; null on any failure (callers then deny framing). */
export async function fetchWidgetOrigins(slug: string): Promise<string[] | null> {
  if (!isPublicSlug(slug)) return null;
  try {
    const body = await getJson<{ widget_origins?: unknown }>(
      `/api/public/${encodeURIComponent(slug)}/widget-config`,
      2000,
    );
    if (!body || !Array.isArray(body.widget_origins)) return null;
    return body.widget_origins.filter((o): o is string => typeof o === "string");
  } catch {
    return null;
  }
}
