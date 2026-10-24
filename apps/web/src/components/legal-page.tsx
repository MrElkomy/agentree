import Link from "next/link";
import { Wordmark } from "@/components/brand";

export const LEGAL_UPDATED = "October 23, 2026";
export const CONTACT_EMAIL = "support@tryagentree.com";

/** Shared layout for the privacy notice and the terms (plain, readable, no app chrome). */
export function LegalPage({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col items-center gap-10 bg-paper px-4 py-10">
      <Link href="/" aria-label="Agentree home">
        <Wordmark />
      </Link>
      <article className="flex w-full max-w-prose flex-col gap-4 text-ink [&_h2]:mt-4 [&_h2]:text-lg [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc [&_a]:font-semibold [&_a]:text-brand [&_a]:underline">
        <h1 className="text-3xl font-bold">{title}</h1>
        <p className="text-sm text-ink-muted">Last updated {LEGAL_UPDATED}</p>
        {children}
      </article>
    </div>
  );
}
