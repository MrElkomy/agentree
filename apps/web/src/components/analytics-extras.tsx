"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSession } from "@/components/session";
import { api, type AnalyticsSummary, type Credential } from "@/lib/api";
import { dateTime } from "@/lib/leads";

const AGENT_TITLE: Record<string, string> = {
  sales: "Sales Agent",
  customer_service: "Customer Service",
  technical_support: "Technical Support",
  data_analyst: "Data Analyst",
  executive: "Executive Assistant",
};

const HEALTH: Record<string, { label: string; tone: string }> = {
  healthy: { label: "Working", tone: "bg-brand-soft text-brand" },
  degraded: { label: "Some errors", tone: "bg-warn-soft text-warn" },
  recovering: { label: "Recovering", tone: "bg-warn-soft text-warn" },
  down: { label: "Down: the other key answers", tone: "bg-danger-soft text-danger" },
};

/** Per-agent outcomes for the month (Task 21), counted from stored messages and activity. */
export function AgentOutcomes({ summary }: { summary: AnalyticsSummary }) {
  const outcomes = Object.entries(summary.agent_outcome_labels);
  return (
    <section aria-labelledby="agent-outcomes" className="flex flex-col gap-3">
      <h2 id="agent-outcomes" className="text-lg font-semibold">
        Agent outcomes
      </h2>
      {summary.agents.length === 0 ? (
        <p className="text-ink-muted">No visitor conversations answered by an agent this month yet.</p>
      ) : (
        <div
          role="region"
          aria-labelledby="agent-outcomes"
          tabIndex={0}
          className="overflow-x-auto rounded-lg border border-line bg-surface"
        >
          <table className="w-full text-sm" data-testid="agent-outcomes">
            <thead>
              <tr className="border-b border-line text-left">
                <th scope="col" className="px-3 py-2 font-semibold">
                  Agent
                </th>
                {outcomes.map(([name, label]) => (
                  <th key={name} scope="col" className="px-3 py-2 font-semibold">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {summary.agents.map((a) => (
                <tr key={a.role} className="border-b border-line last:border-0">
                  <th scope="row" className="px-3 py-2 text-left font-semibold whitespace-nowrap">
                    {AGENT_TITLE[a.role] ?? a.role}
                  </th>
                  {outcomes.map(([name]) => (
                    <td key={name} className="px-3 py-2 tabular-nums">
                      {a.outcomes[name] ?? 0}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Current health of the business's AI keys and how long raw conversations are kept. */
export function KeysAndRetention({ businessBase, businessId }: { businessBase: string; businessId: string }) {
  const { handleError } = useSession();
  const [keys, setKeys] = useState<Credential[] | null>(null);
  const [retention, setRetention] = useState<{ retention_days: number; last_run_at?: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Credential[]>(`${businessBase}/ai-providers`).then(
      (k) => !cancelled && setKeys(k),
      (err) => !cancelled && setError(handleError(err)),
    );
    api<{ retention_days: number; last_run_at?: string | null }>(`${businessBase}/analytics/retention`).then(
      (r) => !cancelled && setRetention(r),
      (err) => !cancelled && setError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [businessBase, handleError]);

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <section aria-labelledby="key-health" className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5">
        <h2 id="key-health" className="text-lg font-semibold">
          AI keys
        </h2>
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        {keys?.length === 0 ? (
          <p className="text-sm text-ink-muted">
            No AI key yet. <Link className="font-semibold text-brand underline" href={`/b/${businessId}/ai-providers`}>Add one</Link>.
          </p>
        ) : null}
        <ul className="flex flex-col gap-2">
          {keys?.map((k) => (
            <li key={k.slot} className="flex flex-wrap items-center justify-between gap-2 text-sm" data-testid={`key-health-${k.slot}`}>
              <span>
                <span className="font-semibold">{k.slot === "primary" ? "Primary" : "Backup"}</span> · {k.provider} · …{k.key_hint}
              </span>
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${HEALTH[k.health]?.tone ?? ""}`}>
                {HEALTH[k.health]?.label ?? k.health}
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="retention" className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-5 text-sm">
        <h2 id="retention" className="text-lg font-semibold">
          Data retention
        </h2>
        {retention ? (
          <>
            <p>
              Conversations are deleted {retention.retention_days} days after their last message, unless an owner placed
              them on legal hold. Daily counts on this page are kept for 13 months.
            </p>
            <p className="text-ink-muted" data-testid="retention-last-run">
              {retention.last_run_at
                ? `The deletion job last ran ${dateTime.format(new Date(retention.last_run_at))}.`
                : "The deletion job hasn't run yet."}
            </p>
          </>
        ) : null}
      </section>
    </div>
  );
}
