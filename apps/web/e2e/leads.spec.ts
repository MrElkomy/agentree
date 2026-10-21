import { expect, test } from "@playwright/test";
import { logIn, runId, signUp, verifyFromEmail } from "./helpers";

// Runs against the dev stack with AGENTREE_LLM_DEMO_MODE=true: the demo provider adds the lead
// marker when the visitor writes an email address (see agentree/llm/fake.py).
test("visitor confirms their details in the chat; the owner follows up on the lead", async ({ page, browser }) => {
  const run = runId();
  const ownerEmail = `lead-owner-${run}@example.com`;
  const visitorEmail = `visitor-${run}@example.com`;
  const businessName = `Oak Tables ${run}`;

  // --- Owner: business, demo key, public page on --------------------------------------
  await page.goto("/signup");
  await signUp(page, ownerEmail);
  await verifyFromEmail(page, ownerEmail);
  await logIn(page, ownerEmail);
  await page.getByLabel("Business name").fill(businessName);
  await page.getByRole("button", { name: "Create business" }).click();
  await expect(page.getByRole("heading", { level: 1, name: businessName })).toBeVisible();
  await page.getByRole("link", { name: "AI Providers" }).first().click();
  const primary = page.getByTestId("slot-primary");
  await primary.getByRole("button", { name: "Connect a key" }).click();
  await primary.getByLabel("API key").fill("sk-e2e-demo-key-00009999");
  await primary.getByLabel("Test the key with a tiny request before saving").uncheck();
  await primary.getByRole("button", { name: "Save key" }).click();
  await expect(primary.getByText("•••• 9999")).toBeVisible();
  await page.getByRole("link", { name: "Public page & widget" }).first().click();
  const slug = new URL((await page.getByTestId("public-url").textContent())!.trim()).pathname.slice(1);
  await page.getByLabel("Public page is on").check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("public-status")).toHaveText("Live");

  // --- Visitor: shares an email; reviews the prefilled form; consents ------------------
  const visitorContext = await browser.newContext();
  const v = await visitorContext.newPage();
  await v.goto(`/${slug}`);
  await v.getByRole("button", { name: "Chat with our Sales Agent" }).click();
  await v.getByLabel("Message", { exact: true }).fill(`I'd like a quote for 6 tables. Email me at ${visitorEmail}`);
  await v.keyboard.press("Enter");
  const form = v.getByTestId("lead-form");
  await expect(form).toBeVisible();
  await expect(form.getByLabel("Email")).toHaveValue(visitorEmail);
  const send = form.getByRole("button", { name: "Send my details" });
  await expect(send).toBeDisabled(); // consent is required
  await form.getByLabel("Name").fill("Sara Ahmed");
  await form.getByLabel(`I agree that ${businessName} may contact me about my request.`).check();
  await send.click();
  await expect(v.getByTestId("lead-sent")).toContainText(`${businessName} has your details`);
  await expect(v.getByTestId("lead-form")).toHaveCount(0);
  await visitorContext.close();

  // --- Owner: sees the lead, opens it, updates the status ------------------------------
  await page.getByRole("link", { name: "Leads", exact: true }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Leads" })).toBeVisible();
  const row = page.getByTestId("lead-row").filter({ hasText: "Sara Ahmed" });
  await expect(row).toContainText(visitorEmail);
  await expect(row).toContainText("New");
  await expect(row.getByTestId("lead-follow-up")).toContainText("Follow up by");
  await row.getByRole("link").click();
  await expect(page.getByRole("heading", { level: 1, name: "Sara Ahmed" })).toBeVisible();
  await expect(page.getByRole("link", { name: visitorEmail })).toHaveAttribute("href", `mailto:${visitorEmail}`);
  await expect(page.getByText(`Email me at ${visitorEmail}`)).toBeVisible(); // the conversation
  // The Sales Agent's first-contact reminder; contacting the lead closes it.
  const reminder = page.getByTestId("follow-up").filter({ hasText: "Contact Sara Ahmed" });
  await expect(reminder).toContainText("added by Sales Agent");
  await expect(reminder.getByRole("button", { name: "Mark done" })).toBeVisible();
  await page.getByLabel("Status").selectOption("contacted");
  await expect(page.getByText("Status updated.")).toBeVisible();
  await expect(reminder.getByRole("button", { name: "Reopen" })).toBeVisible();

  // A reminder of the team's own.
  await page.getByLabel("New reminder").fill("Send the price list");
  await page.getByRole("button", { name: "Add reminder" }).click();
  await expect(page.getByTestId("follow-up").filter({ hasText: "Send the price list" })).toContainText(
    "Owners and admins",
  );

  await page.getByRole("link", { name: "Activity log" }).first().click();
  const log = page.getByTestId("audit-event");
  await expect(log.filter({ hasText: `${ownerEmail} moved a lead from New to Contacted` })).toHaveCount(1);
  await expect(log.filter({ hasText: `${ownerEmail} marked a follow-up done` })).toHaveCount(1);
  await expect(log.filter({ hasText: `${ownerEmail} added a follow-up reminder` })).toHaveCount(1);
  await expect(log.filter({ hasText: "Sales Agent added a follow-up reminder for a new lead" })).toHaveCount(1);
  await expect(log.filter({ hasText: "A visitor shared their contact details (Public page)" })).toHaveCount(1);
});
