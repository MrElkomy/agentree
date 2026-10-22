"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import { AgentAvailability } from "@/components/agent-availability";
import { useBusiness } from "@/components/business-shell";
import { BusinessHoursEditor } from "@/components/business-hours";
import { useSession } from "@/components/session";
import { Alert, Button, Spinner, buttonClass } from "@/components/ui";
import { TOOL_LABEL } from "@/lib/agents";
import { api, type AgentConfig, type AgentConfigIn, type BusinessHours } from "@/lib/api";
import { atLeast } from "@/lib/roles";

// What each customer-facing agent does beyond answering from your knowledge.
const ROLE_NOTE: Record<string, string> = {
  customer_service:
    "Answers questions about your policies and services from your knowledge, never promises refunds or order updates, and brings in your team for anything it can't settle. Customers can mark its conversations resolved.",
  data_analyst:
    "Answers your team's questions about your numbers: conversations, leads, handoffs and trends. It only states numbers Agentree computed, never estimates. Internal: visitors can never reach it.",
  executive:
    "Your operations manager: summarizes how the business and your agents are doing and suggests next steps, using only numbers Agentree computed. It can propose changes, but never makes them: an owner or admin approves each one on the Approvals page. Internal: visitors can never reach it.",
  technical_support:
    "Asks what's wrong, then suggests troubleshooting steps from your knowledge. It never claims to have changed anything and brings in your team when a fix needs account access. Customers can mark its conversations resolved.",
};

export default function AgentsPage() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const base = `/api/businesses/${encodeURIComponent(business.id)}/agents`;
  const canEdit = atLeast(business.role, "admin");
  const [agents, setAgents] = useState<AgentConfig[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hoursSet, setHoursSet] = useState(false);

  // Saving business hours can change which agents are answering right now.
  const reload = useCallback(async () => {
    setHoursSet(true);
    try {
      setAgents(await api<AgentConfig[]>(base));
    } catch (err) {
      setError(handleError(err));
    }
  }, [base, handleError]);

  useEffect(() => {
    let cancelled = false;
    api<BusinessHours>(base.replace(/\/agents$/, "/business-hours")).then(
      (h) => !cancelled && setHoursSet(Boolean(h.configured)),
      () => undefined, // the hours editor reports its own errors
    );
    api<AgentConfig[]>(base).then(
      (a) => !cancelled && setAgents(a),
      (err) => !cancelled && setError(handleError(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [base, handleError]);

  const onSaved = (saved: AgentConfig) =>
    setAgents((list) => list?.map((x) => (x.role === saved.role ? saved : x)) ?? list);
  const publicOnes = agents?.filter((a) => a.audience === "public") ?? [];
  const internalOnes = agents?.filter((a) => a.audience === "internal") ?? [];

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <title>{`AI team · ${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">AI team</h1>
        <p className="max-w-prose text-ink-muted">
          Choose which agents work for {business.name}, what they&apos;re called and what they may
          do. Agents hand a conversation to the right teammate on their own, and customers never
          have to repeat themselves.
        </p>
        <Link href={`/b/${business.id}/agents/sales`} className={`${buttonClass("secondary", "sm")} w-fit`}>
          Try them in the test chat
        </Link>
      </header>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {!canEdit ? <Alert tone="info">Only owners and admins can change the AI team.</Alert> : null}
      {agents === null && !error ? <Spinner label="Loading agents…" /> : null}

      {agents ? (
        <>
          <BusinessHoursEditor base={base} canEdit={canEdit} onSaved={reload} />
          <section aria-labelledby="public-agents" className="flex flex-col gap-4">
            <h2 id="public-agents" className="text-lg font-semibold">
              Customer-facing agents
            </h2>
            {publicOnes.map((a) => (
              <div key={a.role} className="flex flex-col gap-2">
                <AgentCard base={base} agent={a} canEdit={canEdit} onSaved={onSaved} />
                {a.enabled ? (
                  <AgentAvailability
                    key={`${a.role}-${a.availability.mode}-${a.availability.paused_from ?? ""}`}
                    base={base}
                    agent={a}
                    canEdit={canEdit}
                    hoursSet={hoursSet}
                    onSaved={onSaved}
                  />
                ) : null}
              </div>
            ))}
          </section>
          <section aria-labelledby="internal-agents" className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <h2 id="internal-agents" className="text-lg font-semibold">
                Internal agents
              </h2>
              <p className="text-sm text-ink-muted">
                Only your team can use them. Visitors can never reach internal agents.
              </p>
            </div>
            {internalOnes.map((a) => (
              <AgentCard key={a.role} base={base} agent={a} canEdit={canEdit} onSaved={onSaved} />
            ))}
          </section>
        </>
      ) : null}
    </div>
  );
}

function AgentCard({
  base,
  agent,
  canEdit,
  onSaved,
}: {
  base: string;
  agent: AgentConfig;
  canEdit: boolean;
  onSaved: (saved: AgentConfig) => void;
}) {
  const { handleError } = useSession();
  const id = useId();
  const [enabled, setEnabled] = useState(agent.enabled);
  const [name, setName] = useState(agent.display_name);
  const [isPublic, setIsPublic] = useState(agent.public);
  const [tools, setTools] = useState<string[]>(agent.tools);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const editable = canEdit && agent.available;
  const dirty =
    enabled !== agent.enabled ||
    name.trim() !== agent.display_name ||
    isPublic !== agent.public ||
    [...tools].sort().join() !== [...agent.tools].sort().join();

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setNotice(null);
    try {
      const body: AgentConfigIn = { enabled, display_name: name, public: isPublic, tools };
      const saved = await api<AgentConfig>(`${base}/${agent.role}`, "PUT", body);
      setName(saved.display_name);
      onSaved(saved);
      setNotice({ tone: "success", text: "Saved." });
    } catch (err) {
      setNotice({ tone: "error", text: handleError(err) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={save}
      aria-labelledby={`${id}-title`}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
      data-testid={`agent-${agent.role}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h3 id={`${id}-title`} className="text-base font-semibold">
            {agent.name}
            {agent.display_name ? <span className="font-normal text-ink-muted"> · {agent.title}</span> : null}
          </h3>
          <p className="text-sm text-ink-muted">Handles {agent.handles}.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
          <span className="rounded-full bg-paper px-2.5 py-0.5 ring-1 ring-line-strong">
            {agent.audience === "public" ? "Customer-facing" : "Internal"}
          </span>
          {!agent.available ? (
            <span className="rounded-full bg-paper px-2.5 py-0.5 text-ink-muted ring-1 ring-line">Coming soon</span>
          ) : null}
          {agent.available ? (
            <span
              className={`rounded-full px-2.5 py-0.5 ${agent.enabled ? "bg-brand text-white" : "bg-paper text-ink-muted ring-1 ring-line"}`}
              data-testid={`agent-status-${agent.role}`}
            >
              {agent.enabled ? "On" : "Off"}
            </span>
          ) : null}
        </div>
      </div>

      {!agent.available ? (
        <p className="text-sm text-ink-muted">This agent is being built and arrives in a later update.</p>
      ) : (
        <>
          {ROLE_NOTE[agent.role] ? <p className="text-sm text-ink-muted">{ROLE_NOTE[agent.role]}</p> : null}
          <label className="flex items-center gap-2 text-sm font-semibold">
            <input
              type="checkbox"
              checked={enabled}
              disabled={!editable}
              onChange={(e) => setEnabled(e.target.checked)}
              className="size-4 accent-brand"
            />
            Turn on {agent.title}
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-semibold">{agent.audience === "public" ? "Name customers see" : "Name your team sees"}</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={40}
                dir="auto"
                disabled={!editable}
                placeholder={agent.title}
                className="min-h-11 rounded-md border border-line-strong bg-surface px-3 text-base focus-visible:border-brand"
              />
              <span className="text-xs text-ink-muted">
                For example &quot;Sara from your brand&quot;. Only the name changes, never what the agent may do.
              </span>
            </label>
            {agent.audience === "public" ? (
              <label className="flex items-start gap-2 self-center text-sm">
                <input
                  type="checkbox"
                  checked={isPublic}
                  disabled={!editable}
                  onChange={(e) => setIsPublic(e.target.checked)}
                  className="mt-0.5 size-4 accent-brand"
                />
                <span>
                  <span className="font-semibold">Visitors can chat with this agent</span>
                  <span className="block text-xs text-ink-muted">
                    Off: only your team can use it, in the test chat.
                  </span>
                </span>
              </label>
            ) : null}
          </div>
          {agent.available_tools.length ? (
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-sm font-semibold">What this agent may do</legend>
              {agent.available_tools.map((tool) => (
                <label key={tool} className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={tools.includes(tool)}
                    disabled={!editable}
                    onChange={(e) =>
                      setTools((t) => (e.target.checked ? [...t, tool] : t.filter((x) => x !== tool)))
                    }
                    className="mt-0.5 size-4 accent-brand"
                  />
                  <span>
                    <span className="font-semibold">{TOOL_LABEL[tool]?.title ?? tool}</span>
                    <span className="block text-xs text-ink-muted">{TOOL_LABEL[tool]?.hint}</span>
                  </span>
                </label>
              ))}
            </fieldset>
          ) : null}
          {notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null}
          {editable ? (
            <div>
              <Button type="submit" size="sm" busy={saving} disabled={!dirty}>
                Save {agent.title}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </form>
  );
}
