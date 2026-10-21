import { expect, test } from "@playwright/test";
import { logIn, replyDone, runId, signUp, verifyFromEmail } from "./helpers";

// Runs against the dev stack with AGENTREE_LLM_DEMO_MODE=true: the backend replaces AI
// providers with a canned reply, so no real AI key or network call is needed.
const DEMO_REPLY_START = "This is a demo reply";

test("owner connects a key, publishes knowledge and chats with the Sales Agent", async ({ page }) => {
  const run = runId();
  const email = `agent-owner-${run}@example.com`;
  const businessName = `Ergo Chairs ${run}`;

  await page.goto("/signup");
  await signUp(page, email);
  await verifyFromEmail(page, email);
  await logIn(page, email);
  await page.getByLabel("Business name").fill(businessName);
  await page.getByRole("button", { name: "Create business" }).click();
  await expect(page.getByRole("heading", { level: 1, name: businessName })).toBeVisible();

  // Chat before setup: the agent explains a provider is needed.
  await page.getByRole("link", { name: "Sales Agent" }).first().click();
  await page.getByLabel("Message", { exact: true }).fill("Hello");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Connect an AI provider key first" })).toBeVisible();

  // 1. Connect a provider key (saved without a live test call).
  await page.getByRole("link", { name: "Open AI Providers" }).click();
  await expect(page.getByRole("heading", { name: "AI Providers", level: 1 })).toBeVisible();
  const primary = page.getByTestId("slot-primary");
  await primary.getByRole("button", { name: "Connect a key" }).click();
  await primary.getByLabel("API key").fill("sk-e2e-demo-key-00001234");
  await primary.getByLabel("Test the key with a tiny request before saving").uncheck();
  await primary.getByRole("button", { name: "Save key" }).click();
  await expect(primary.getByText("Key saved securely (not tested).")).toBeVisible();
  await expect(primary.getByText("•••• 1234")).toBeVisible();
  await expect(page.getByText("sk-e2e-demo-key-00001234")).toHaveCount(0); // never shown again

  // 2. Add and publish knowledge.
  await page.getByRole("link", { name: "Knowledge" }).first().click();
  await page.getByLabel("Title").fill("Pricing");
  await page.getByLabel("Content").fill("The Ergo chair costs $299 and ships in 5 days.");
  await page.getByRole("button", { name: "Save as draft" }).click();
  const entry = page.getByTestId("knowledge-entry").filter({ hasText: "Pricing" });
  await expect(entry.getByText("Draft")).toBeVisible();
  await entry.getByRole("button", { name: "Publish" }).click();
  await expect(entry.getByText("Published")).toBeVisible();

  // 3. Chat with the Sales Agent.
  await page.getByRole("link", { name: "Sales Agent" }).first().click();
  await page.getByLabel("Message", { exact: true }).fill("How much is the Ergo chair?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("chat-user")).toHaveText("How much is the Ergo chair?");
  const answer = page.getByTestId("chat-assistant");
  await expect(answer).toContainText(DEMO_REPLY_START);
  // Published knowledge was used: no "nothing matched" warning under the reply.
  await expect(answer).not.toContainText("No published knowledge matched");
  // The reply is labelled "<business> Sales Agent", not with provider internals.
  await expect(answer).toContainText(`${businessName} Sales Agent`);

  // The conversation survives a page refresh.
  await replyDone(page);
  await page.reload();
  await expect(page.getByTestId("chat-user")).toHaveText("How much is the Ergo chair?");
  await expect(page.getByTestId("chat-assistant")).toContainText(DEMO_REPLY_START);
});
