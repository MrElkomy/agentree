import { NextResponse, type NextRequest } from "next/server";
import { fetchWidgetOrigins } from "@/lib/public-api";

/**
 * Framing policy for the website widget iframe (`/w/{slug}`) — and nothing else.
 *
 * This is NOT authorization: it only tells browsers which websites may embed the widget
 * (CSP `frame-ancestors`, TD-17). The backend remains the only authority for every API call.
 * Every other route keeps `X-Frame-Options: DENY` from next.config.ts.
 *
 * The allowlist comes from the business's public page settings
 * (`GET /api/public/{slug}/widget-config`). On any failure (unknown or disabled page, API
 * unreachable, unexpected value) framing is denied entirely.
 */

// Defence in depth: the backend already normalizes origins; re-check before building a header.
const ORIGIN_RE = /^https?:\/\/[a-z0-9.-]+(?::\d{1,5})?$/;

export async function proxy(request: NextRequest) {
  // Slugs are plain [a-z0-9-]; anything encoded or malformed is rejected by fetchWidgetOrigins.
  const slug = request.nextUrl.pathname.split("/")[2] ?? "";
  const origins = await fetchWidgetOrigins(slug);
  const ancestors =
    origins === null ? "'none'" : ["'self'", ...origins.filter((o) => ORIGIN_RE.test(o))].join(" ");
  const response = NextResponse.next();
  response.headers.set("Content-Security-Policy", `frame-ancestors ${ancestors}`);
  return response;
}

export const config = {
  matcher: "/w/:path*",
};
