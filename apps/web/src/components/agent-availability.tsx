"use client";

import { useId, useState, type FormEvent } from "react";
import { useSession } from "@/components/session";
import { Alert, Button } from "@/components/ui";
import { api, type AgentConfig, type AvailabilityIn } from "@/lib/api";

const MODES: { value: AvailabilityIn["mode"]; title: string; hint: string }[] = [
  { value: "always", title: "Always", hint: "Answers visitors at any time." },
  { value: "business_hours", title: "During business hours", hint: "Your team covers the rest." },
  {
    value: "outside_business_hours",
    title: "Outside business hours",
    hint: "Covers evenings, nights and days off while your team is away.",
  },
];

/** ISO time -> value for <input type="datetime-local"> in the viewer's time zone. */
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

/**
 * When one customer-facing agent answers visitors (Task 20b). Outside that time, or while
 * paused, visitors get its fixed message instead of an AI reply.
 */
export function AgentAvailability({
  base,
  agent,
  canEdit,
  hoursSet,
  onSaved,
}: {
  base: string;
  agent: AgentConfig;
  canEdit: boolean;
  hoursSet: boolean;
  onSaved: (saved: AgentConfig) => void;
}) {
  const { handleError } = useSession();
  const id = useId();
  const a = agent.availability;
  const [mode, setMode] = useState(a.mode);
  const [awayMessage, setAwayMessage] = useState(a.away_message);
  const [pauseFrom, setPauseFrom] = useState(toLocalInput(a.paused_from));
  const [pauseUntil, setPauseUntil] = useState(toLocalInput(a.paused_until));
  const [pauseMessage, setPauseMessage] = useState(a.pause_message);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  async function save(e: FormEvent, clearPause = false) {
    e.preventDefault();
    setSaving(true);
    setNotice(null);
    try {
      const body: AvailabilityIn = {
        mode,
        away_message: awayMessage,
        paused_from: clearPause ? null : fromLocalInput(pauseFrom),
        paused_until: clearPause ? null : fromLocalInput(pauseUntil),
        pause_message: pauseMessage,
      };
      const saved = await api<AgentConfig>(`${base}/${agent.role}/availability`, "PUT", body);
      if (clearPause) {
        setPauseFrom("");
        setPauseUntil("");
      }
      onSaved(saved);
      setNotice({ tone: "success", text: clearPause ? "Pause removed." : "Saved." });
    } catch (err) {
      setNotice({ tone: "error", text: handleError(err) });
    } finally {
      setSaving(false);
    }
  }

  const disabled = !canEdit;
  return (
    <form
      onSubmit={save}
      aria-labelledby={`${id}-title`}
      data-testid={`availability-${agent.role}`}
      className="flex flex-col gap-4 rounded-lg border border-dashed border-line-strong bg-surface p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 id={`${id}-title`} className="font-semibold">
          When {agent.name} answers visitors
        </h4>
        <span
          data-testid={`answering-${agent.role}`}
          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${agent.answering_now ? "bg-brand-soft text-brand" : "bg-warn-soft text-warn"}`}
        >
          {agent.answering_now ? "Answering now" : "Away now"}
        </span>
      </div>
      <fieldset className="flex flex-col gap-2">
        <legend className="sr-only">When it answers</legend>
        {MODES.map((m) => (
          <label key={m.value} className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              name={`${id}-mode`}
              value={m.value}
              checked={mode === m.value}
              disabled={disabled || (m.value !== "always" && !hoursSet)}
              onChange={() => setMode(m.value)}
              className="mt-0.5 size-4 accent-brand"
            />
            <span>
              <span className="font-semibold">{m.title}</span>
              <span className="block text-xs text-ink-muted">{m.hint}</span>
            </span>
          </label>
        ))}
        {!hoursSet ? <p className="text-xs text-ink-muted">Set your business hours above to use a schedule.</p> : null}
      </fieldset>
      {mode !== "always" ? (
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold">Message outside its hours</span>
          <textarea
            dir="auto"
            rows={2}
            maxLength={500}
            value={awayMessage}
            disabled={disabled}
            onChange={(e) => setAwayMessage(e.target.value)}
            placeholder="Thanks for your message! We're not available right now…"
            className="rounded-md border border-line-strong bg-surface px-3 py-2 text-base"
          />
        </label>
      ) : null}
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-semibold">Pause (for example a holiday)</legend>
        <div className="flex flex-wrap gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span>From</span>
            <input
              type="datetime-local"
              value={pauseFrom}
              disabled={disabled}
              onChange={(e) => setPauseFrom(e.target.value)}
              className="min-h-10 rounded-md border border-line-strong bg-surface px-2"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span>Until</span>
            <input
              type="datetime-local"
              value={pauseUntil}
              disabled={disabled}
              onChange={(e) => setPauseUntil(e.target.value)}
              className="min-h-10 rounded-md border border-line-strong bg-surface px-2"
            />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span>Message during the pause</span>
          <textarea
            dir="auto"
            rows={2}
            maxLength={500}
            value={pauseMessage}
            disabled={disabled}
            onChange={(e) => setPauseMessage(e.target.value)}
            placeholder="Eid Mubarak! We're back on Sunday…"
            className="rounded-md border border-line-strong bg-surface px-3 py-2 text-base"
          />
        </label>
        <p className="text-xs text-ink-muted">
          Times are in your browser&apos;s time zone. Visitors get this message instead of an AI reply, and their messages
          wait for your team in the Inbox.
        </p>
      </fieldset>
      {notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null}
      {canEdit ? (
        <div className="flex flex-wrap gap-2">
          <Button type="submit" size="sm" busy={saving}>
            Save availability
          </Button>
          {a.paused_from ? (
            <Button type="button" size="sm" variant="secondary" disabled={saving} onClick={(e) => save(e, true)}>
              Remove pause
            </Button>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}
