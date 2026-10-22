"use client";

import { useEffect, useId, useState, type FormEvent } from "react";
import { useSession } from "@/components/session";
import { Alert, Button } from "@/components/ui";
import { api, type BusinessHours } from "@/lib/api";

const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

type Day = { open: boolean; start: string; end: string };

function timeZones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC"];
  }
}

function toDays(h: BusinessHours): Day[] {
  return h.days.map((d) => (d ? { open: true, start: d.start, end: d.end } : { open: false, start: "09:00", end: "17:00" }));
}

/**
 * When the business is open (Task 20b). Agents can answer only during these hours, or only
 * outside them to cover the off time; each agent's choice is set below its card.
 */
export function BusinessHoursEditor({
  base,
  canEdit,
  onSaved,
}: {
  base: string;
  canEdit: boolean;
  onSaved: () => Promise<void>;
}) {
  const { handleError } = useSession();
  const url = `${base.replace(/\/agents$/, "")}/business-hours`;
  const id = useId();
  const [loaded, setLoaded] = useState<BusinessHours | null>(null);
  const [timezone, setTimezone] = useState("UTC");
  const [days, setDays] = useState<Day[]>([]);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<BusinessHours>(url).then(
      (h) => {
        if (cancelled) return;
        setLoaded(h);
        // A business that never saved its hours starts from the browser's time zone.
        setTimezone(h.configured ? h.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
        setDays(toDays(h));
      },
      (err) => !cancelled && setNotice({ tone: "error", text: handleError(err) }),
    );
    return () => {
      cancelled = true;
    };
  }, [url, handleError]);

  function patch(i: number, change: Partial<Day>) {
    setDays((list) => list.map((d, j) => (j === i ? { ...d, ...change } : d)));
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setNotice(null);
    try {
      const body: Omit<BusinessHours, "configured"> = {
        timezone,
        days: days.map((d) => (d.open ? { start: d.start, end: d.end } : null)),
      };
      const saved = await api<BusinessHours>(url, "PUT", body);
      setLoaded(saved);
      setNotice({ tone: "success", text: "Business hours saved." });
      await onSaved();
    } catch (err) {
      setNotice({ tone: "error", text: handleError(err) });
    } finally {
      setSaving(false);
    }
  }

  if (loaded === null) return notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null;

  return (
    <form
      onSubmit={save}
      aria-labelledby={`${id}-title`}
      data-testid="business-hours"
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex flex-col gap-1">
        <h2 id={`${id}-title`} className="text-lg font-semibold">
          Business hours
        </h2>
        <p className="text-sm text-ink-muted">
          Each customer-facing agent can answer always, only during these hours, or only outside them to cover the
          time your team is off. {loaded.configured ? null : "Not set yet: every agent answers always."}
        </p>
      </div>
      <label className="flex max-w-sm flex-col gap-1 text-sm">
        <span className="font-semibold">Time zone</span>
        <select
          value={timezone}
          disabled={!canEdit}
          onChange={(e) => setTimezone(e.target.value)}
          className="min-h-11 rounded-md border border-line-strong bg-surface px-3 text-base"
        >
          {[...new Set([timezone, ...timeZones()])].map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-semibold">Opening hours</legend>
        {days.map((d, i) => (
          <div key={DAY_NAMES[i]} className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex w-36 items-center gap-2">
              <input
                type="checkbox"
                checked={d.open}
                disabled={!canEdit}
                onChange={(e) => patch(i, { open: e.target.checked })}
                className="size-4 accent-brand"
              />
              <span className="font-semibold">{DAY_NAMES[i]}</span>
            </label>
            {d.open ? (
              <>
                <input
                  type="time"
                  aria-label={`${DAY_NAMES[i]} opens`}
                  value={d.start}
                  disabled={!canEdit}
                  onChange={(e) => patch(i, { start: e.target.value })}
                  className="min-h-10 rounded-md border border-line-strong bg-surface px-2"
                />
                <span aria-hidden="true">–</span>
                <input
                  type="time"
                  aria-label={`${DAY_NAMES[i]} closes`}
                  value={d.end}
                  disabled={!canEdit}
                  onChange={(e) => patch(i, { end: e.target.value })}
                  className="min-h-10 rounded-md border border-line-strong bg-surface px-2"
                />
              </>
            ) : (
              <span className="text-ink-muted">Closed</span>
            )}
          </div>
        ))}
      </fieldset>
      {notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null}
      {canEdit ? (
        <div>
          <Button type="submit" size="sm" busy={saving}>
            Save business hours
          </Button>
        </div>
      ) : null}
    </form>
  );
}
