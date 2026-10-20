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
      <main className="flex w-full max-w-xl flex-col items-center gap-8">
        <header className="flex flex-col items-center gap-4 text-center">
          <div
            aria-hidden="true"
            className="flex size-24 items-center justify-center rounded-full bg-canopy font-display text-3xl font-bold text-white shadow-[inset_0_-3px_0_rgb(0_0_0/0.18)]"
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

        {page.chat_enabled ? <ChatEntry slug={page.slug} displayName={page.display_name} /> : null}

        {page.links.length ? (
          <nav aria-label={`${page.display_name} links`} className="w-full">
            <ul className="flex flex-col gap-3">
              {page.links.map((link, i) => (
                <li key={`${i}-${link.url}`}>
                  <a
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    dir="auto"
                    className="flex min-h-12 w-full items-center justify-center rounded-lg border border-line-strong bg-surface px-4 py-3 text-center font-semibold text-ink transition-colors hover:border-canopy hover:text-canopy"
                  >
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        ) : null}
      </main>
      <footer className="mt-auto pt-12 text-center text-xs text-ink-muted">
        <p>
          Powered by <span className="font-semibold text-ink">Agentree</span>
        </p>
      </footer>
    </div>
  );
}
