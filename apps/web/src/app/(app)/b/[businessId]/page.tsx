"use client";

import Link from "next/link";
import { useBusiness } from "@/components/business-shell";
import { RoleBadge, buttonClass } from "@/components/ui";
import { atLeast } from "@/lib/roles";

const ROLE_SUMMARY = {
  owner: "You have full control of this business, including its owners.",
  admin: "You can invite people and manage members.",
  member: "You can work in this business. Owners and admins manage the team.",
} as const;

export default function BusinessOverviewPage() {
  const { business } = useBusiness();
  const canInvite = atLeast(business.role, "admin");

  return (
    <div className="flex max-w-3xl flex-col gap-10">
      <title>{`${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-3">
        <h1 className="text-2xl font-bold break-words sm:text-3xl">{business.name}</h1>
        <dl className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <div className="flex items-center gap-2">
            <dt className="text-ink-muted">URL name</dt>
            <dd className="font-semibold">{business.slug}</dd>
          </div>
          <div className="flex items-center gap-2">
            <dt className="text-ink-muted">Your role</dt>
            <dd>
              <RoleBadge role={business.role} />
            </dd>
          </div>
        </dl>
        <p className="text-ink-muted">{ROLE_SUMMARY[business.role]}</p>
      </header>

      <section aria-labelledby="team-heading" className="rounded-lg border border-line bg-surface p-6">
        <h2 id="team-heading" className="text-lg font-semibold">
          Your team
        </h2>
        <p className="mt-2 max-w-prose text-ink-muted">
          {canInvite
            ? "Invite the people who'll work alongside your agents, and choose what each of them can manage."
            : "See who else works in this business."}
        </p>
        <Link href={`/b/${business.id}/members`} className={`${buttonClass("secondary")} mt-5`}>
          {canInvite ? "Manage members" : "View members"}
        </Link>
      </section>

      <section aria-labelledby="next-heading" className="flex flex-col gap-4">
        <h2 id="next-heading" className="text-lg font-semibold">
          Get your Sales Agent answering
        </h2>
        <ol className="grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-3">
          {[
            ["1. Connect a provider", "Add your own AI key (and a backup).", "ai-providers"],
            ["2. Add knowledge", "Write and publish what customers ask about.", "knowledge"],
            ["3. Try the agent", "Chat with it like a customer would.", "agents/sales"],
          ].map(([title, text, path]) => (
            <li key={title} className="bg-surface p-5">
              <Link href={`/b/${business.id}/${path}`} className="font-semibold text-brand-deep hover:underline">
                {title}
              </Link>
              <p className="mt-1 text-sm text-ink-muted">{text}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
