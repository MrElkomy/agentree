/*
 * Agentree service worker: shows Web Push alerts (new lead, visitor waiting, AI key down) and
 * opens the related page on click. Payloads are decrypted by the browser; they carry only a
 * title, a short text and a same-origin path. It caches nothing and never touches requests.
 */
"use strict";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

function safePath(value) {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/\\")
    ? value
    : "/dashboard";
}

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }
  const title = typeof data.title === "string" && data.title ? data.title.slice(0, 120) : "Agentree";
  const options = {
    body: typeof data.body === "string" ? data.body.slice(0, 240) : "",
    tag: typeof data.tag === "string" ? data.tag.slice(0, 120) : undefined,
    icon: "/apple-icon.png",
    data: { url: safePath(data.url) },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(safePath(event.notification.data && event.notification.data.url), self.location.origin);
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const w of windows) {
        if (new URL(w.url).origin === target.origin && "focus" in w) {
          return w.focus().then((focused) => (focused && "navigate" in focused ? focused.navigate(target.href) : focused));
        }
      }
      return self.clients.openWindow(target.href);
    }),
  );
});
