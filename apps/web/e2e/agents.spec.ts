import { expect, test } from "@playwright/test";
import { logIn, replyDone, runId, signUp, verifyFromEmail } from "./helpers";
import { emailText } from "./mailpit";

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
  // Internal agents can never be opened to visitors.
  await expect(page.getByTestId("agent-executive")).toContainText("Internal");
  await expect(page.getByTestId("agent-executive").getByText("Visitors can chat with this agent")).toHaveCount(0);

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

  // --- Task 18a: Analytics page, Excel export, and the Data Analyst (team only) ------------------
  await page.goto(`${businessPath}/agents`);
  const analyst = page.getByTestId("agent-data_analyst");
  await analyst.getByLabel("Turn on Data Analyst").check();
  await analyst.getByRole("button", { name: "Save Data Analyst" }).click();
  await expect(page.getByTestId("agent-status-data_analyst")).toHaveText("On");
  await page.getByRole("link", { name: "Analytics" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Analytics" })).toBeVisible();
  await expect(page.getByTestId("metric-conversations")).toBeVisible();
  const href = await page.getByTestId("analytics-export").getAttribute("href");
  const xlsx = await page.request.get(href!);
  expect(xlsx.status()).toBe(200);
  expect(xlsx.headers()["content-type"]).toContain("spreadsheetml");

  await page.getByRole("link", { name: "Test chat" }).first().click();
  await page.getByLabel("Start with").selectOption({ label: "Data Analyst" });
  await page.getByLabel("Message", { exact: true }).fill("How many conversations did we have?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("chat-assistant").last()).toContainText("In the last 30 days you had");

  // --- Task 18b: an uploaded table, queried by the Data Analyst in the sandbox ------------------
  await page.goto(`${businessPath}/knowledge`);
  await page.locator("#knowledge-upload").setInputFiles({
    name: "orders.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("product,units\nChair,4\nDesk,2\nLamp,9\n"),
  });
  const table = page.getByTestId("knowledge-file").filter({ hasText: "orders.csv" });
  await expect(table.getByTestId("knowledge-file-status")).toHaveText(
    "Ready for the Data Analyst · 3 rows, 2 columns",
  );
  // Start a fresh test chat: forget the saved one, so no restore races the "Start with" choice.
  await page.evaluate(() => {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith("agentree:sales-conversation:")) localStorage.removeItem(key);
    }
  });
  await page.getByRole("link", { name: "Test chat" }).first().click();
  await page.getByLabel("Start with").selectOption({ label: "Data Analyst" });
  await page.getByLabel("Message", { exact: true }).fill("How many rows does my orders table have?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("chat-assistant").last()).toHaveText(/Your table has 3 rows\./);
  await expect(page.getByText("<<SQL")).toHaveCount(0);

  // --- Task 19: follow-up email drafts are opt-in and wait on the Approvals page --------------
  await page.goto(`${businessPath}/agents`);
  const salesAgent = page.getByTestId("agent-sales");
  const drafts = salesAgent.getByLabel(/Draft follow-up emails/);
  await expect(drafts).not.toBeChecked(); // off until the business turns it on
  await drafts.check();
  await salesAgent.getByRole("button", { name: "Save Sales Agent" }).click();
  await expect(salesAgent.getByText("Saved.")).toBeVisible();
  await page.getByRole("link", { name: "Approvals" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Approvals" })).toBeVisible();
  await expect(page.getByText("Nothing to approve.")).toBeVisible();
  await expect(page.getByText("Every request waits for a person.")).toBeVisible();

  // --- Task 20: the Executive Assistant proposes, a person approves -------------------------
  await page.goto(`${businessPath}/agents`);
  const exec = page.getByTestId("agent-executive");
  await exec.getByLabel("Turn on Executive Assistant").check();
  await exec.getByRole("button", { name: "Save Executive Assistant" }).click();
  await expect(page.getByTestId("agent-status-executive")).toHaveText("On");
  await page.evaluate(() => {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith("agentree:sales-conversation:")) localStorage.removeItem(key);
    }
  });
  await page.getByRole("link", { name: "Test chat" }).first().click();
  await page.getByLabel("Start with").selectOption({ label: "Executive Assistant" });
  await page.getByLabel("Message", { exact: true }).fill("Please turn off Technical Support");
  await page.keyboard.press("Enter");
  const proposal = page.getByTestId("chat-assistant").last();
  await expect(proposal).toContainText("Waiting for approval: Turn off the Technical Support.");
  await expect(page.getByText("<<ACTION")).toHaveCount(0);
  await page.getByRole("link", { name: "Approvals" }).first().click();
  const card = page.getByTestId("approval-card").filter({ hasText: "Executive Assistant wants to turn an agent on or off" });
  await expect(card).toContainText("Turn off the Technical Support");
  await card.getByRole("button", { name: "Approve once" }).click();
  await expect(page.getByTestId("approval-history").first().getByTestId("approval-status")).toHaveText("Done");
  await page.goto(`${businessPath}/agents`);
  await expect(page.getByTestId("agent-status-technical_support")).toHaveText("Off");

  // --- Task 20b: business hours and a pause with a fixed message ------------------------------
  const hoursForm = page.getByTestId("business-hours");
  await expect(hoursForm.getByText("Not set yet: every agent answers always.")).toBeVisible();
  await hoursForm.getByRole("button", { name: "Save business hours" }).click();
  await expect(hoursForm.getByText("Business hours saved.")).toBeVisible();
  const salesHours = page.getByTestId("availability-sales");
  await expect(page.getByTestId("answering-sales")).toHaveText("Answering now");
  const [from, until] = await page.evaluate(() => {
    const local = (d: Date) => {
      const p = (n: number) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
    };
    const now = Date.now();
    return [local(new Date(now - 3600_000)), local(new Date(now + 86400_000))];
  });
  await salesHours.getByLabel("From").fill(from);
  await salesHours.getByLabel("Until").fill(until);
  await salesHours.getByLabel("Message during the pause").fill("Eid Mubarak! We're back on Sunday.");
  await salesHours.getByRole("button", { name: "Save availability" }).click();
  await expect(page.getByTestId("answering-sales")).toHaveText("Away now");

  const holidayContext = await browser.newContext();
  const h = await holidayContext.newPage();
  await h.goto(`/${slug}`);
  await h.getByRole("button", { name: "Chat with Sara" }).click();
  await h.getByLabel("Message", { exact: true }).fill("Are you open?");
  await h.keyboard.press("Enter");
  await expect(h.getByTestId("guest-assistant").last()).toHaveText(/Eid Mubarak! We're back on Sunday\./);
  await holidayContext.close();

  // --- Task 20c: email reports (a real email, checked in Mailpit) --------------------------------
  await page.getByRole("link", { name: "Analytics" }).first().click();
  const reportsForm = page.getByTestId("email-reports");
  await reportsForm.getByLabel("Send").selectOption("weekly");
  await reportsForm.getByLabel("Weekday").selectOption("Friday");
  await reportsForm.getByRole("button", { name: "Save email reports" }).click();
  await expect(reportsForm.getByText("Saved.")).toBeVisible();
  await reportsForm.getByRole("button", { name: "Send me a report now" }).click();
  await expect(reportsForm.getByText("A report is on its way to your email.")).toBeVisible();
  const report = await emailText(ownerEmail, "Weekly report for");
  expect(report).toContain("Visitor conversations:");
  expect(report).toContain("Leads still new:");
});
