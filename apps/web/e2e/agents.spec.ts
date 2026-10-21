import { expect, test } from "@playwright/test";
import { logIn, replyDone, runId, signUp, verifyFromEmail } from "./helpers";

// Runs against the dev stack with AGENTREE_LLM_DEMO_MODE=true: the demo provider routes problems
// ("error", "not working") to Technical Support and buying questions back to Sales when that
// teammate is enabled (see agentree/llm/fake.py).
test("owner sets up the AI team; a visitor is handed Sales → Technical Support → Sales", async ({ page, browser }) => {
  test.setTimeout(90_000);
  const run = runId();
  const ownerEmail = `team-owner-${run}@example.com`;
  const businessName = `Pixel Printers ${run}`;

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
  await primary.getByLabel("API key").fill("sk-e2e-demo-key-00005555");
  await primary.getByLabel("Test the key with a tiny request before saving").uncheck();
  await primary.getByRole("button", { name: "Save key" }).click();
  await expect(primary.getByText("•••• 5555")).toBeVisible();

  // --- AI team: name the Sales Agent, turn on Technical Support ---------------------------
  await page.getByRole("link", { name: "AI team", exact: true }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "AI team" })).toBeVisible();
  const sales = page.getByTestId("agent-sales");
  await sales.getByLabel("Name customers see").fill("Sara");
  await sales.getByRole("button", { name: "Save Sales Agent" }).click();
  await expect(sales.getByText("Saved.")).toBeVisible();
  const support = page.getByTestId("agent-technical_support");
  await expect(page.getByTestId("agent-status-technical_support")).toHaveText("Off");
  await support.getByLabel("Turn on Technical Support").check();
  await support.getByLabel("Name customers see").fill("Tariq");
  await support.getByRole("button", { name: "Save Technical Support" }).click();
  await expect(page.getByTestId("agent-status-technical_support")).toHaveText("On");
  // Internal agents cannot be turned on yet, and never by visitors.
  await expect(page.getByTestId("agent-data_analyst")).toContainText("Coming soon");
  await expect(page.getByTestId("agent-executive").getByRole("checkbox")).toHaveCount(0);

  await page.getByRole("link", { name: "Public page & widget" }).first().click();
  const slug = new URL((await page.getByTestId("public-url").textContent())!.trim()).pathname.slice(1);
  await page.getByLabel("Public page is on").check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("public-status")).toHaveText("Live");

  // --- Visitor: Sales → Technical Support → Sales ------------------------------------------
  const visitorContext = await browser.newContext();
  const v = await visitorContext.newPage();
  await v.goto(`/${slug}`);
  await expect(v.getByRole("button", { name: "Chat with Tariq" })).toBeVisible();
  await v.getByRole("button", { name: "Chat with Sara" }).click();
  const input = v.getByLabel("Message", { exact: true });
  await input.fill("Hi, I bought the P200 printer");
  await input.press("Enter");
  await expect(v.getByTestId("guest-agent-name").last()).toHaveText("Sara");
  await replyDone(v);

  await input.fill("It shows an error after the update");
  await input.press("Enter");
  await expect(v.getByTestId("guest-joined").last()).toHaveText("Tariq joined the conversation");
  await expect(v.getByTestId("guest-assistant").last()).toContainText("Technical Support here.");
  await expect(v.getByTestId("guest-agent-name").last()).toHaveText("Tariq");
  await expect(v.getByText("<<ROUTE")).toHaveCount(0);
  await replyDone(v);

  await input.fill("Fixed! What's the price to buy another one?");
  await input.press("Enter");
  await expect(v.getByTestId("guest-joined").last()).toHaveText("Sara joined the conversation");
  await expect(v.getByTestId("guest-agent-name").last()).toHaveText("Sara");
  await replyDone(v);

  // A reload restores who said what.
  await v.reload();
  await expect(v.getByTestId("guest-agent-name")).toHaveText(["Sara", "Sara", "Tariq", "Tariq", "Sara"]);
  await visitorContext.close();

  // --- Owner: handoffs are in the activity log -------------------------------------------
  await page.goto(`${businessPath}/activity`);
  const log = page.getByTestId("audit-event");
  await expect(log.filter({ hasText: "Sales Agent handed a conversation to Technical Support" })).toHaveCount(1);
  await expect(log.filter({ hasText: "Technical Support handed a conversation to Sales Agent" })).toHaveCount(1);
  await expect(log.filter({ hasText: `${ownerEmail} updated the Technical Support settings` })).toHaveCount(1);
});
