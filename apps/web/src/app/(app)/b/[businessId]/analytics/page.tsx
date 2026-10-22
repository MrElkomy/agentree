"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useBusiness } from "@/components/business-shell";
import { EmailReports } from "@/components/email-reports";
import { useSession } from "@/components/session";
import { Alert, SelectField, Spinner, buttonClass } from "@/components/ui";
import { api, type AnalyticsSummary } from "@/lib/api";
import { atLeast } from "@/lib/roles";

/** The current UTC month and the 12 before it, newest first ("YYYY-MM"). */
function lastMonths(): string[] {
  const now = new Date();
  let y = now.getUTCFullYear();
  let m = now.getUTCMonth() + 1;
  const out: string[] = [];
  for (let i = 0; i < 13; i++) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    if (--m === 0) {
      m = 12;
      y--;
    }
  }
  return out;
}

const monthName = (month: string) =>
  new Date(`${month}-01T00:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

export default function AnalyticsPage() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const months = lastMonths();
  const [month, setMonth] = useState(months[0] ?? "");
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = `/api/businesses/${encodeURIComponent(business.id)}/analytics`;

  useEffect(() => {
    let cancelled = false;
    api<AnalyticsSummary>(`${base}/summary?month=${encodeURIComponent(month)}`).then(
      (d) => !cancelled && setData(d),
      (err) => !cancelled && setError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [base, month, handleError]);

  const shown = data && data.start.startsWith(month) ? data : null;
  const labels = Object.fromEntries((shown?.totals ?? []).map((t) => [t.name, t.label]));

  return (
    <div className="flex max-w-5xl flex-col gap-8">
      <title>{`Analytics · ${business.name} · Agentree`}</title>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold sm:text-3xl">Analytics</h1>
          <p className="max-w-prose text-ink-muted">
            Your AI team&apos;s numbers, counted from your conversations and activity (UTC days,
            refreshed every hour). Ask the Data Analyst about them in the{" "}
            <Link href={`/b/${business.id}/agents/sales`} className="font-semibold text-brand">
              test chat
            </Link>
            .
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <SelectField label="Month" value={month} onChange={(e) => setMonth(e.target.value)} className="w-48">
            {months.map((m) => (
              <option key={m} value={m}>
                {monthName(m)}
              </option>
            ))}
          </SelectField>
          <a
            href={`${base}/export?month=${encodeURIComponent(month)}`}
            download
            className={buttonClass("primary")}
            data-testid="analytics-export"
          >
            Download Excel
          </a>
        </div>
      </header>
      {!atLeast(business.role, "admin") ? (
        <Alert tone="info">The Excel file includes your leads&apos; contact details for owners and admins only.</Alert>
      ) : null}
      {error ? <Alert tone="error">{error}</Alert> : null}
      {!shown && !error ? <Spinner label="Loading numbers…" /> : null}
      {shown ? (
        <>
          {shown.missing_days.length ? (
            <Alert tone="info">
              {shown.missing_days.length} day(s) of this month haven&apos;t been counted yet. Their numbers are
              unknown, not zero.
            </Alert>
          ) : null}
          <section aria-label="Totals" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {shown.totals.map((t) => (
              <div key={t.name} className="rounded-lg border border-line bg-surface p-4" data-testid={`metric-${t.name}`}>
                <p className="text-sm text-ink-muted">{t.label}</p>
                <p className="mt-1 text-2xl font-bold">{t.value.toLocaleString("en-US")}</p>
              </div>
            ))}
            {shown.rates.map((r) => (
              <div key={r.name} className="rounded-lg border border-line bg-paper p-4" data-testid={`rate-${r.name}`}>
                <p className="text-sm text-ink-muted">{r.label}</p>
                <p className="mt-1 text-2xl font-bold">{r.value === null ? "—" : `${r.value}%`}</p>
              </div>
            ))}
          </section>
          <section aria-labelledby="daily-heading" className="flex flex-col gap-3">
            <h2 id="daily-heading" className="text-lg font-semibold">
              Day by day
            </h2>
            {shown.days.length === 0 ? (
              <p className="text-ink-muted">No days counted yet for this month.</p>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-line bg-surface">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line text-left">
                      <th scope="col" className="px-3 py-2 font-semibold">
                        Date
                      </th>
                      {Object.entries(labels).map(([name, label]) => (
                        <th key={name} scope="col" className="px-3 py-2 font-semibold">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...shown.days].reverse().map((d) => (
                      <tr key={d.day} className="border-b border-line last:border-0">
                        <td className="px-3 py-2 whitespace-nowrap">{d.day}</td>
                        {Object.keys(labels).map((name) => (
                          <td key={name} className="px-3 py-2 tabular-nums">
                            {d.values[name] ?? 0}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}
      <EmailReports businessBase={base.replace(/\/analytics$/, "")} canEdit={atLeast(business.role, "admin")} />
    </div>
  );
}
