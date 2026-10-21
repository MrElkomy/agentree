/**
 * Web Push opt-in for this browser/device. The backend stores the subscription for the signed-in
 * Owner/Admin and sends alerts through the browser's push service (see public/push-sw.js).
 */
import { api } from "./api";

const SW_PATH = "/push-sw.js";

export function pushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** iPhone/iPad only allow Web Push for sites added to the home screen (iOS 16.4+). */
export function needsHomeScreenInstall(): boolean {
  if (typeof window === "undefined") return false;
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const standalone =
    window.matchMedia?.("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return ios && !standalone;
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = base64url.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function registration(): Promise<ServiceWorkerRegistration> {
  await navigator.serviceWorker.register(SW_PATH, { scope: "/" });
  return navigator.serviceWorker.ready;
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  return reg ? reg.pushManager.getSubscription() : null;
}

export class PermissionDeniedError extends Error {}

/** Asks for permission, subscribes this device and stores it for the business. */
export async function enablePush(base: string, publicKey: string): Promise<void> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new PermissionDeniedError(permission);
  const reg = await registration();
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) }));
  await api(`${base}/subscriptions`, "POST", sub.toJSON());
}

/** Stops alerts for this business on this device. */
export async function disablePush(base: string): Promise<void> {
  const sub = await currentSubscription();
  if (!sub) return;
  await api(`${base}/subscriptions/remove`, "POST", { endpoint: sub.endpoint });
}
