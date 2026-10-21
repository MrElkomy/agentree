"use client";

import { useCallback, useEffect, useState } from "react";
import { useBusiness } from "@/components/business-shell";
import { useSession } from "@/components/session";
import { Alert, Button, Spinner } from "@/components/ui";
import { api, type PushConfig } from "@/lib/api";
import {
  PermissionDeniedError,
  currentSubscription,
  disablePush,
  enablePush,
  needsHomeScreenInstall,
  pushSupported,
} from "@/lib/push";
import { atLeast } from "@/lib/roles";

type DeviceState = "checking" | "unsupported" | "install" | "denied" | "on" | "off";

const ALERTS = [
  "A visitor shares their contact details (new lead)",
  "A visitor asks for a person, or the AI hands a conversation to your team",
  "One of your AI provider keys goes down",
];

export default function NotificationsPage() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const base = `/api/businesses/${encodeURIComponent(business.id)}/notifications/push`;
  const isAdmin = atLeast(business.role, "admin");
  const [config, setConfig] = useState<PushConfig | null>(null);
  const [device, setDevice] = useState<DeviceState>("checking");
  const [busy, setBusy] = useState<"on" | "off" | "test" | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "error" | "info"; text: string } | null>(null);

  const refresh = useCallback(async () => {
    const cfg = await api<PushConfig>(base);
    setConfig(cfg);
    if (!pushSupported()) return setDevice(needsHomeScreenInstall() ? "install" : "unsupported");
    if (Notification.permission === "denied") return setDevice("denied");
    const sub = await currentSubscription();
    if (!sub) return setDevice("off");
    const r = await api<{ subscribed: boolean }>(`${base}/subscriptions/check`, "POST", { endpoint: sub.endpoint });
    setDevice(r.subscribed ? "on" : "off");
  }, [base]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve()
      .then(refresh)
      .catch((err) => !cancelled && setNotice({ tone: "error", text: handleError(err) }));
    return () => {
      cancelled = true;
    };
  }, [refresh, handleError]);

  async function run(kind: "on" | "off" | "test") {
    setBusy(kind);
    setNotice(null);
    try {
      if (kind === "on") {
        await enablePush(base, config?.public_key ?? "");
        setNotice({ tone: "success", text: "Alerts are on for this device." });
      } else if (kind === "off") {
        await disablePush(base);
        setNotice({ tone: "info", text: "Alerts are off for this device. Email alerts continue." });
      } else {
        const r = await api<{ sent: number }>(`${base}/test`, "POST");
        setNotice(
          r.sent
            ? { tone: "success", text: "Test notification sent. It should appear in a few seconds." }
            : { tone: "error", text: "No device received it. Turn alerts on for this device first." },
        );
      }
      await refresh();
    } catch (err) {
      if (err instanceof PermissionDeniedError) {
        setDevice("denied");
      } else {
        setNotice({ tone: "error", text: handleError(err) });
      }
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <title>{`Notifications · ${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">Notifications</h1>
        <p className="max-w-prose text-ink-muted">
          Get instant alerts on your phone or computer, even when Agentree isn&apos;t open. Owners and
          admins always get these alerts by email too.
        </p>
      </header>

      {notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null}

      <section aria-labelledby="alerts-heading" className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5">
        <h2 id="alerts-heading" className="text-lg font-semibold">
          You&apos;re alerted when
        </h2>
        <ul className="flex list-disc flex-col gap-1 pl-5 text-sm">
          {ALERTS.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
        <p className="text-xs text-ink-muted">
          Alerts name your business only — never a visitor&apos;s name, contact details or messages.
        </p>
      </section>

      <section aria-labelledby="device-heading" className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5">
        <div className="flex flex-col gap-1">
          <h2 id="device-heading" className="text-lg font-semibold">
            This device
          </h2>
          {config ? (
            <p className="text-sm text-ink-muted">
              {config.devices === 0
                ? "Alerts aren't on for any of your devices yet."
                : config.devices === 1
                  ? "Alerts are on for 1 of your devices."
                  : `Alerts are on for ${config.devices} of your devices.`}
            </p>
          ) : null}
        </div>
        {!isAdmin ? (
          <Alert tone="info">Only owners and admins receive these alerts.</Alert>
        ) : config === null || device === "checking" ? (
          <Spinner label="Checking this device…" />
        ) : !config.available ? (
          <Alert tone="info">Push notifications aren&apos;t set up on this server yet. Email alerts still work.</Alert>
        ) : device === "install" ? (
          <Alert tone="info">
            On iPhone and iPad, add Agentree to your Home Screen first (Share → Add to Home Screen), open it from
            there, then turn alerts on. Requires iOS 16.4 or later.
          </Alert>
        ) : device === "unsupported" ? (
          <Alert tone="info">This browser can&apos;t receive push notifications. Try Chrome, Edge, Firefox or Safari.</Alert>
        ) : device === "denied" ? (
          <Alert tone="error">
            Notifications are blocked for this site in your browser settings. Allow them there, then reload this page.
          </Alert>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <span data-testid="push-device-status" className="text-sm font-semibold">
              {device === "on" ? "Alerts are on for this device" : "Alerts are off for this device"}
            </span>
            {device === "on" ? (
              <>
                <Button size="sm" variant="secondary" busy={busy === "test"} disabled={busy !== null} onClick={() => void run("test")}>
                  Send a test notification
                </Button>
                <Button size="sm" variant="ghost" busy={busy === "off"} disabled={busy !== null} onClick={() => void run("off")}>
                  Turn off
                </Button>
              </>
            ) : (
              <Button size="sm" busy={busy === "on"} disabled={busy !== null} onClick={() => void run("on")}>
                Turn on alerts
              </Button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
