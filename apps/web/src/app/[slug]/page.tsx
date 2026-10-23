import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import { fetchPublicPage } from "@/lib/public-api";
import { ChatEntry } from "./chat-entry";

// A business's public AI page: agentree.com/{slug} (PC-02). Server-rendered from the public
// API; unknown, reserved and disabled slugs are all "not found". Static routes such as
// /login or /dashboard take precedence over this dynamic segment.

type Props = { params: Promise<{ slug: string }> };

const loadPage = cache(fetchPublicPage);

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const page = await loadPage((await params).slug);
  if (!page) return { robots: { index: false, follow: false } };
  return {
    title: { absolute: page.display_name },
    description: page.bio.slice(0, 160) || `Chat with ${page.display_name}.`,
    // Staging: keep public pages out of search engines until launch.
    robots: { index: false, follow: false },
  };
}

function initials(name: string): string {
  const letters = name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => Array.from(w)[0] ?? "");
  return letters.join("").toUpperCase() || "?";
}

export default async function PublicBusinessPage({ params }: Props) {
  const page = await loadPage((await params).slug);
  if (!page) notFound();

  return (
    <div className="flex min-h-dvh flex-col items-center px-4 py-10 sm:py-16">
      <main className="flex w-full max-w-lg flex-col items-center gap-8">
        <header className="flex flex-col items-center gap-4 text-center">
          <div
            aria-hidden="true"
            className="flex size-24 items-center justify-center rounded-full bg-brand font-display text-3xl font-bold text-white shadow-[inset_0_-3px_0_rgb(0_0_0/0.18)]"
          >
            <span dir="auto">{initials(page.display_name)}</span>
          </div>
          <h1 dir="auto" className="text-2xl font-bold sm:text-3xl" data-testid="public-name">
            {page.display_name}
          </h1>
          {page.bio ? (
            <p dir="auto" className="max-w-prose whitespace-pre-line text-ink-muted" data-testid="public-bio">
              {page.bio}
            </p>
          ) : null}
        </header>

        {page.chat_enabled ? (
          <section aria-labelledby="agents-heading" className="flex w-full flex-col gap-3">
            <h2 id="agents-heading" className="text-sm font-semibold tracking-normal text-ink-muted">
              Talk to our team
            </h2>
            <ChatEntry
              slug={page.slug}
              displayName={page.display_name}
              agents={page.agents}
              leadCapture={page.lead_capture}
              retentionDays={page.retention_days ?? 30}
              customerMemory={page.customer_memory ?? true}
              challengeSiteKey={page.challenge_site_key ?? null}
            />
          </section>
        ) : null}

        {page.links.length ? (
          <section aria-labelledby="links-heading" className="flex w-full flex-col gap-3">
            <h2 id="links-heading" className="text-sm font-semibold tracking-normal text-ink-muted">
              Links
            </h2>
            <ul className="flex flex-col gap-3">
              {page.links.map((link, i) => (
                <li key={`${i}-${link.url}`}>
                  <a
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="group flex min-h-14 w-full items-center gap-4 rounded-xl border border-line bg-surface px-4 py-3 shadow-sm transition-colors hover:border-brand"
                  >
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span dir="auto" className="font-semibold text-ink group-hover:text-brand">
                        {link.label}
                      </span>
                      {link.description ? (
                        <span dir="auto" className="text-sm text-ink-muted">
                          {link.description}
                        </span>
                      ) : null}
                    </span>
                    <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4 shrink-0 text-ink-muted group-hover:text-brand">
                      <path
                        d="M8 4H4.5A.5.5 0 0 0 4 4.5v11a.5.5 0 0 0 .5.5h11a.5.5 0 0 0 .5-.5V12M11 4h5v5M16 4l-7 7"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                    <span className="sr-only">(opens in a new tab)</span>
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </main>
      <footer className="mt-auto pt-12 text-center text-xs text-ink-muted">
        <p className="inline-flex items-center gap-1.5">
          Powered by
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/agentree-wordmark.svg" alt="Agentree" className="h-3.5 w-auto" />
        </p>
      </footer>
    </div>
  );
}
