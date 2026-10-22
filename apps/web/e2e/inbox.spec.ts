import { expect, test } from "@playwright/test";
import { logIn, runId, signUp, verifyFromEmail } from "./helpers";
import { emailText } from "./mailpit";

// Runs against the dev stack with AGENTREE_LLM_DEMO_MODE=true: the demo provider adds the
// handoff marker when the visitor asks for a "person" or "human" (see agentree/llm/fake.py).
test("the AI hands a visitor to the team; the owner takes over, replies and hands back", async ({ page, browser }) => {
  test.setTimeout(90_000);
  const run = runId();
  const ownerEmail = `inbox-owner-${run}@example.com`;
  const businessName = `Pine Chairs ${run}`;

  // --- Owner: business, demo key, public page on --------------------------------------
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
  await primary.getByLabel("API key").fill("sk-e2e-demo-key-00008888");
  await primary.getByLabel("Test the key with a tiny request before saving").uncheck();
  await primary.getByRole("button", { name: "Save key" }).click();
  await expect(primary.getByText("•••• 8888")).toBeVisible();
  await page.getByRole("link", { name: "Public page & widget" }).first().click();
  const slug = new URL((await page.getByTestId("public-url").textContent())!.trim()).pathname.slice(1);
  await page.getByLabel("Public page is on").check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("public-status")).toHaveText("Live");

  // --- Visitor: asks for a person; the AI hands over and goes quiet --------------------
  const visitorContext = await browser.newContext();
  const v = await visitorContext.newPage();
  await v.goto(`/${slug}`);
  await v.getByRole("button", { name: "Chat with our Sales Agent" }).click();
  await v.getByLabel("Message", { exact: true }).fill("Can I talk to a person about a bulk order?");
  await v.keyboard.press("Enter");
  await expect(v.getByTestId("guest-assistant").last()).toContainText("connect you with the team");
  await expect(v.getByText("<<HANDOFF>>")).toHaveCount(0);
  await expect(v.getByTestId("handoff-waiting")).toContainText(`The ${businessName} team has been notified`);
  await v.getByLabel("Message", { exact: true }).fill("I need 40 chairs");
  await v.keyboard.press("Enter");
  await expect(v.getByTestId("guest-user").last()).toHaveText("I need 40 chairs");
  await expect(v.getByTestId("guest-assistant")).toHaveCount(1); // the AI stayed quiet

  // --- Owner: alerted by email, takes over from the inbox and replies ------------------
  const alert = await emailText(ownerEmail, "/inbox/");
  expect(alert).toContain(businessName);
  expect(alert).not.toContain("40 chairs"); // no visitor message content in emails
  await page.getByRole("link", { name: "Inbox", exact: true }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Inbox" })).toBeVisible();
  const row = page.getByTestId("inbox-row").first();
  await expect(row).toContainText("Waiting for a person");
  await expect(row).toContainText("I need 40 chairs");
  await row.getByRole("link").click();
  await expect(page.getByText("The AI asked for a person")).toBeVisible();
  await page.getByRole("button", { name: "Take over", exact: true }).click();
  await expect(page.getByTestId("inbox-status")).toHaveText("With the team");
  await expect(page.getByTestId("inbox-assignee")).toHaveText("You");
  // Task 21: the owner keeps this conversation past the 30-day deletion (and can release it).
  const hold = page.getByTestId("legal-hold");
  await hold.getByRole("button", { name: "Place legal hold" }).click();
  await expect(hold).toContainText("On legal hold: kept past the 30-day deletion");
  await hold.getByRole("button", { name: "Release legal hold" }).click();
  await expect(hold).toContainText("Deleted 30 days after the last message");
  await page.getByLabel(`Reply as the ${businessName} team`).fill("Hi! I can offer 10% off for 40 chairs.");
  await page.getByRole("button", { name: "Send reply" }).click();
  await expect(page.getByTestId("inbox-team")).toContainText("10% off");

  // --- Visitor: sees the team's reply ---------------------------------------------------
  await expect(v.getByTestId("guest-human")).toContainText("10% off", { timeout: 15_000 });
  await expect(v.getByTestId("guest-human")).toContainText(`${businessName} team`);
  await expect(v.getByTestId("handoff-active")).toBeVisible();

  // --- Owner hands back; the AI answers again -------------------------------------------
  await page.getByRole("button", { name: "Hand back to AI" }).click();
  await expect(page.getByTestId("inbox-status")).toHaveText("AI answering");
  await expect(v.getByTestId("handoff-active")).toHaveCount(0, { timeout: 15_000 });
  await v.getByLabel("Message", { exact: true }).fill("Thanks, what about delivery?");
  await v.keyboard.press("Enter");
  await expect(v.getByTestId("guest-assistant")).toHaveCount(2);
  await visitorContext.close();

  await page.goto(`${businessPath}/activity`);
  const log = page.getByTestId("audit-event");
  await expect(log.filter({ hasText: "The AI asked for a person to take over a conversation" })).toHaveCount(1);
  await expect(log.filter({ hasText: `${ownerEmail} took over a conversation` })).toHaveCount(1);
  await expect(log.filter({ hasText: `${ownerEmail} handed a conversation back to the AI` })).toHaveCount(1);
});
