import { expect, test } from "@playwright/test";
import { logIn, replyDone, runId, signUp, verifyFromEmail } from "./helpers";

// Runs against the dev stack with AGENTREE_LLM_DEMO_MODE=true: the demo provider streams its
// reply word by word, and cuts off the first reply to a message asking to "simulate an
// interruption" (see agentree/llm/fake.py).
test("replies stream in; an interrupted reply can be retried; key health is shown", async ({ page, browser }) => {
  const run = runId();
  const ownerEmail = `reliability-owner-${run}@example.com`;
  const businessName = `Birch Lamps ${run}`;

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
  await primary.getByLabel("API key").fill("sk-e2e-demo-key-00007777");
  await primary.getByLabel("Test the key with a tiny request before saving").uncheck();
  await primary.getByRole("button", { name: "Save key" }).click();
  await expect(primary.getByText("•••• 7777")).toBeVisible();
  await expect(page.getByTestId("health-primary")).toHaveText("Not tested yet");

  // --- Console: streamed reply, then an interruption and a retry ------------------------
  await page.getByRole("link", { name: "Sales Agent" }).first().click();
  const input = page.getByLabel("Message", { exact: true });
  await input.fill("What do you sell?");
  await input.press("Enter");
  await expect(page.getByTestId("chat-assistant").last()).toContainText("local demo mode");
  await replyDone(page);
  await input.fill("Please simulate an interruption");
  await input.press("Enter");
  const interrupted = page.getByTestId("chat-interrupted");
  await expect(interrupted).toContainText("nothing was saved");
  await interrupted.getByRole("button", { name: "Retry" }).click();
  await expect(interrupted).toHaveCount(0);
  await expect(page.getByTestId("chat-assistant")).toHaveCount(2);
  await expect(page.getByTestId("chat-assistant").last()).toContainText("local demo mode");
  // Only completed turns were saved: a reload restores two questions and two answers.
  await replyDone(page);
  await page.reload();
  await expect(page.getByTestId("chat-user")).toHaveCount(2);
  await expect(page.getByTestId("chat-assistant")).toHaveCount(2);

  // Successful calls are the key's health signal.
  await page.getByRole("link", { name: "AI Providers" }).first().click();
  await expect(page.getByTestId("health-primary")).toContainText("Working · last success");

  // --- Visitor: the same on the public page -----------------------------------------------
  await page.getByRole("link", { name: "Public page & widget" }).first().click();
  const slug = new URL((await page.getByTestId("public-url").textContent())!.trim()).pathname.slice(1);
  await page.getByLabel("Public page is on").check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("public-status")).toHaveText("Live");

  const visitorContext = await browser.newContext();
  const v = await visitorContext.newPage();
  await v.goto(`/${slug}`);
  await v.getByRole("button", { name: "Chat with our Sales Agent" }).click();
  await v.getByLabel("Message", { exact: true }).fill("Can you simulate an interruption?");
  await v.keyboard.press("Enter");
  const cut = v.getByTestId("guest-interrupted");
  await expect(cut).toContainText("interrupted");
  await cut.getByRole("button", { name: "Try again" }).click();
  await expect(cut).toHaveCount(0);
  await expect(v.getByTestId("guest-assistant")).toHaveCount(1);
  await expect(v.getByTestId("guest-assistant")).toContainText("local demo mode");
  // New messages scroll the chat box, never the message field out of the screen.
  await expect(v.getByLabel("Message", { exact: true })).toBeInViewport();
  await visitorContext.close();
});
