import { expect, test } from "@playwright/test";
import { logIn, runId, signUp, verifyFromEmail } from "./helpers";

// The dev stack has no VAPID key, so Web Push is "not set up": the page must say so and email
// alerts keep working. Delivery itself is covered by the API tests (tests/test_push.py).
test("owner sees the notifications page; the service worker and manifest are served", async ({ page, request }) => {
  const email = `push-owner-${runId()}@example.com`;
  await page.goto("/signup");
  await signUp(page, email);
  await verifyFromEmail(page, email);
  await logIn(page, email);
  await page.getByLabel("Business name").fill(`Cedar Clocks ${runId()}`);
  await page.getByRole("button", { name: "Create business" }).click();
  await page.getByRole("link", { name: "Notifications" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Notifications" })).toBeVisible();
  await expect(page.getByText("A visitor shares their contact details (new lead)")).toBeVisible();
  await expect(page.getByText("Push notifications aren't set up on this server yet.")).toBeVisible();

  const sw = await request.get("/push-sw.js");
  expect(sw.ok()).toBe(true);
  expect(sw.headers()["content-type"]).toContain("javascript");
  expect(await sw.text()).toContain("showNotification");
  const manifest = await request.get("/manifest.webmanifest");
  expect(manifest.ok()).toBe(true);
  expect((await manifest.json()).display).toBe("standalone");
});
