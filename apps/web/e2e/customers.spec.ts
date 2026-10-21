import { expect, test } from "@playwright/test";
import { logIn, replyDone, runId, signUp, verifyFromEmail } from "./helpers";
import { emailText } from "./mailpit";

// Task 16: a visitor is told how long chats and notes are kept, confirms their email with a
// one-time code ("Remember me next time"), and the owner sees the confirmed customer. Memory
// extraction itself runs in the worker and is covered by backend tests (tests/test_customers.py).
test("visitor confirms their email with a code; the owner sees the customer", async ({ page, browser }) => {
  test.setTimeout(90_000);
  const run = runId();
  const ownerEmail = `customers-owner-${run}@example.com`;
  const visitorEmail = `visitor-${run}@example.com`;
  const businessName = `Desk Depot ${run}`;

  await page.goto("/signup");
  await signUp(page, ownerEmail);
  await verifyFromEmail(page, ownerEmail);
  await logIn(page, ownerEmail);
  await page.getByLabel("Business name").fill(businessName);
  await page.getByRole("button", { name: "Create business" }).click();
  await expect(page.getByRole("heading", { level: 1, name: businessName })).toBeVisible();
  const businessPath = new URL(page.url()).pathname;
  await page.getByRole("link", { name: "AI Providers" }).first().click();
  const primary = page.getByTestId("slot-primary");
  await primary.getByRole("button", { name: "Connect a key" }).click();
  await primary.getByLabel("API key").fill("sk-e2e-demo-key-00007777");
  await primary.getByLabel("Test the key with a tiny request before saving").uncheck();
  await primary.getByRole("button", { name: "Save key" }).click();
  await expect(primary.getByText("•••• 7777")).toBeVisible();
  await page.getByRole("link", { name: "Public page & widget" }).first().click();
  const slug = new URL((await page.getByTestId("public-url").textContent())!.trim()).pathname.slice(1);
  await page.getByLabel("Public page is on").check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("public-status")).toHaveText("Live");

  // --- Visitor ------------------------------------------------------------------------------
  const visitorContext = await browser.newContext();
  const v = await visitorContext.newPage();
  await v.goto(`/${slug}`);
  await v.getByRole("button", { name: "Chat with our Sales Agent" }).click();
  await expect(v.getByTestId("retention-notice")).toContainText("are deleted after 30 days");
  const input = v.getByLabel("Message", { exact: true });
  await input.fill("Hi, I need desks for my office");
  await input.press("Enter");
  await replyDone(v);

  await v.getByRole("button", { name: "Remember me next time" }).click();
  const form = v.getByRole("form", { name: "Remember me" });
  await form.getByLabel("Your email").fill(visitorEmail);
  await form.getByRole("button", { name: "Send code" }).click();
  const body = await emailText(visitorEmail, "Enter this code");
  const code = /\b(\d{6})\b/.exec(body)?.[1];
  expect(code).toBeTruthy();

  // A wrong code is refused without saying why.
  await form.getByLabel("Code from the email").fill(code === "000000" ? "111111" : "000000");
  await form.getByRole("button", { name: "Confirm" }).click();
  await expect(form.getByRole("alert")).toHaveText("That code didn't work. Check it, or ask for a new one.");
  await form.getByLabel("Code from the email").fill(code!);
  await form.getByRole("button", { name: "Confirm" }).click();
  const masked = `${visitorEmail[0]}***@example.com`;
  await expect(v.getByTestId("identity-verified")).toContainText(`Remembered as ${masked}`);

  // Remembered across a reload.
  await v.reload(); // the open conversation is restored
  await expect(v.getByTestId("identity-verified")).toContainText(masked);
  await visitorContext.close();

  // --- Owner: the confirmed customer is listed -----------------------------------------------
  await page.goto(`${businessPath}/customers`);
  await expect(page.getByRole("heading", { level: 1, name: "Customers" })).toBeVisible();
  const customer = page.getByTestId("customer").filter({ hasText: visitorEmail });
  await expect(customer).toContainText("Email confirmed");
  await page.goto(`${businessPath}/activity`);
  await expect(
    page.getByTestId("audit-event").filter({ hasText: "A visitor confirmed their email in the chat" }),
  ).toHaveCount(1);
});
