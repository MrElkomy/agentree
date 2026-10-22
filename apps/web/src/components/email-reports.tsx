"use client";

import { useEffect, useId, useState, type FormEvent } from "react";
import { useSession } from "@/components/session";
import { Alert, Button } from "@/components/ui";
import { api, type ReportSettings } from "@/lib/api";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/**
 * Email reports for owners and admins (Task 20c): off, daily or weekly, from 08:00 in the
 * business's time zone. The Executive Assistant can add short notes; their numbers are checked.
 */
export function EmailReports({ businessBase, canEdit }: { businessBase: string; canEdit: boolean }) {
  const { handleError } = useSession();
  const url = `${businessBase}/report-settings`;
  const id = useId();
  const [loaded, setLoaded] = useState<ReportSettings | null>(null);
  const [frequency, setFrequency] = useState<ReportSettings["frequency"]>("off");
  const [weekday, setWeekday] = useState(0);
  const [notes, setNotes] = useState(false);
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<ReportSettings>(url).then(
      (s) => {
        if (cancelled) return;
        setLoaded(s);
        setFrequency(s.frequency);
        setWeekday(s.weekday ?? 0);
        setNotes(Boolean(s.include_notes));
      },
      (err) => !cancelled && setNotice({ tone: "error", text: handleError(err) }),
    );
    return () => {
      cancelled = true;
    };
  }, [url, handleError]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy("save");
    setNotice(null);
    try {
      setLoaded(await api<ReportSettings>(url, "PUT", { frequency, weekday, include_notes: notes }));
      setNotice({ tone: "success", text: frequency === "off" ? "Email reports are off." : "Saved." });
    } catch (err) {
      setNotice({ tone: "error", text: handleError(err) });
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    setBusy("test");
    setNotice(null);
    try {
      await api(`${url}/test`, "POST");
      setNotice({ tone: "success", text: "A report is on its way to your email." });
    } catch (err) {
      setNotice({ tone: "error", text: handleError(err) });
    } finally {
      setBusy(null);
    }
  }

  if (loaded === null) return notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null;

  return (
    <form
      onSubmit={save}
      aria-labelledby={`${id}-title`}
      data-testid="email-reports"
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex flex-col gap-1">
        <h2 id={`${id}-title`} className="text-lg font-semibold">
          Email reports
        </h2>
        <p className="max-w-prose text-sm text-ink-muted">
          Owners and admins get these numbers by email from 08:00 in your business hours&apos; time zone (UTC if you
          haven&apos;t set them), with what&apos;s waiting for your team now. No customer messages or names.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold">Send</span>
          <select
            value={frequency}
            disabled={!canEdit}
            onChange={(e) => setFrequency(e.target.value as ReportSettings["frequency"])}
            className="min-h-11 rounded-md border border-line-strong bg-surface px-3 text-base"
          >
            <option value="off">Never (off)</option>
            <option value="daily">Every day</option>
            <option value="weekly">Every week</option>
          </select>
        </label>
        {frequency === "weekly" ? (
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-semibold">On</span>
            <select
              aria-label="Weekday"
              value={weekday}
              disabled={!canEdit}
              onChange={(e) => setWeekday(Number(e.target.value))}
              className="min-h-11 rounded-md border border-line-strong bg-surface px-3 text-base"
            >
              {WEEKDAYS.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={notes}
          disabled={!canEdit}
          onChange={(e) => setNotes(e.target.checked)}
          className="mt-0.5 size-4 accent-brand"
        />
        <span>
          <span className="font-semibold">Add notes from the Executive Assistant</span>
          <span className="block text-xs text-ink-muted">
            A few observations and suggestions, written with your AI key when the Executive Assistant is on. Notes with
            a number that isn&apos;t in the report are left out.
          </span>
        </span>
      </label>
      {notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null}
      {canEdit ? (
        <div className="flex flex-wrap gap-2">
          <Button type="submit" size="sm" busy={busy === "save"} disabled={busy !== null}>
            Save email reports
          </Button>
          <Button type="button" size="sm" variant="secondary" busy={busy === "test"} disabled={busy !== null} onClick={test}>
            Send me a report now
          </Button>
        </div>
      ) : null}
    </form>
  );
}
