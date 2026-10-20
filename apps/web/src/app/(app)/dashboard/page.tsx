"use client";

import Link from "next/link";
import { AccountMenu } from "@/components/account-menu";
import { Wordmark } from "@/components/brand";
import { CreateBusinessForm } from "@/components/create-business";
import { useSession } from "@/components/session";
import { RoleBadge } from "@/components/ui";

export default function DashboardPage() {
  const { businesses } = useSession();
  const empty = businesses.length === 0;

  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <Wordmark />
          <AccountMenu />
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <title>Your businesses · Agentree</title>
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_24rem]">
          <section aria-labelledby="businesses-heading" className="flex flex-col gap-6">
            <div className="flex flex-col gap-2">
              <h1 id="businesses-heading" className="text-2xl font-bold sm:text-3xl">
                Your businesses
              </h1>
              <p className="max-w-prose text-ink-muted">
                Each business is its own workspace with its own team, knowledge and agents.
              </p>
            </div>
            {empty ? (
              <div className="rounded-lg border border-dashed border-line-strong bg-surface px-6 py-10">
                <h2 className="text-lg font-semibold">Set up your first business</h2>
                <p className="mt-2 max-w-prose text-ink-muted">
                  Create a workspace for your business, then invite your team. If someone invited
                  you, open the link in their email to join their business.
                </p>
              </div>
            ) : (
              <ul className="flex flex-col divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
                {businesses.map((b) => (
                  <li key={b.id}>
                    <Link
                      href={`/b/${b.id}`}
                      className="flex items-center justify-between gap-4 px-5 py-4 hover:bg-brand-soft/60 focus-visible:bg-brand-soft/60"
                    >
                      <span className="flex min-w-0 flex-col">
                        <span className="truncate font-semibold">{b.name}</span>
                        <span className="truncate text-sm text-ink-muted">{b.slug}</span>
                      </span>
                      <RoleBadge role={b.role} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section
            aria-labelledby="create-heading"
            className="h-fit rounded-lg border border-line bg-surface p-6 lg:sticky lg:top-6"
          >
            <h2 id="create-heading" className="mb-5 text-lg font-semibold">
              {empty ? "Create your business" : "Add another business"}
            </h2>
            <CreateBusinessForm />
          </section>
        </div>
      </main>
    </div>
  );
}
