import { expect, test } from "@playwright/test";
import { logIn, replyDone, runId, signUp, verifyFromEmail } from "./helpers";
import { emailText } from "./mailpit";

// Runs against the dev stack with AGENTREE_LLM_DEMO_MODE=true. The demo provider (see
// agentree/llm/fake.py) routes problems ("broken", "error") to Technical Support, service
// questions ("refund", "return") to Customer Service, and marks a conversation resolved when the
// visitor says "that worked" to an agent allowed to resolve.
test("support agents: routing, scoped knowledge, who may resolve; a visitor confirms their email", async ({
  page,
  browser,
}) => {
  test.setTimeout(120_000);
  const run = runId();
  const ownerEmail = `support-owner-${run}@example.com`;
  const businessName = `Comfy Chairs ${run}`;

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
  await primary.getByLabel("API key").fill("sk-e2e-demo-key-00006666");
  await primary.getByLabel("Test the key with a tiny request before saving").uncheck();
  await primary.getByRole("button", { name: "Save key" }).click();
  await expect(primary.getByText("•••• 6666")).toBeVisible();

  // --- AI team: turn on Customer Service ("Mona") and Technical Support ----------------------
  await page.getByRole("link", { name: "AI team", exact: true }).first().click();
  const cs = page.getByTestId("agent-customer_service");
  await expect(cs).toContainText("Customers can mark its conversations resolved.");
  await expect(cs.getByLabel("Mark conversations resolved")).toBeChecked();
  await cs.getByLabel("Turn on Customer Service").check();
  await cs.getByLabel("Name customers see").fill("Mona");
  await cs.getByRole("button", { name: "Save Customer Service" }).click();
  await expect(page.getByTestId("agent-status-customer_service")).toHaveText("On");
  const ts = page.getByTestId("agent-technical_support");
  await ts.getByLabel("Turn on Technical Support").check();
  await ts.getByRole("button", { name: "Save Technical Support" }).click();
  await expect(page.getByTestId("agent-status-technical_support")).toHaveText("On");

  // --- Knowledge only Technical Support may use ---------------------------------------------
  await page.getByRole("link", { name: "Knowledge" }).first().click();
  const form = page.getByRole("form", { name: "New entry" });
  await form.getByLabel("Title").fill("Wobbly chair fix");
  await form.getByLabel("Content").fill("Tighten the four base screws with the included hex key.");
  await form.getByLabel("Only these agents").check();
  await form.getByLabel("Technical Support").check();
  await form.getByLabel("Sales Agent").uncheck();
  await form.getByRole("button", { name: "Save as draft" }).click();
  const entry = page.getByTestId("knowledge-entry").filter({ hasText: "Wobbly chair fix" });
  await expect(entry.getByTestId("knowledge-scope")).toHaveText("Only Technical Support");
  await entry.getByRole("button", { name: "Publish" }).click();
  await expect(entry.getByText("Published")).toBeVisible();

  await page.getByRole("link", { name: "Public page & widget" }).first().click();
  const slug = new URL((await page.getByTestId("public-url").textContent())!.trim()).pathname.slice(1);
  await page.getByLabel("Public page is on").check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("public-status")).toHaveText("Live");

  // --- Visitor: Customer Service → Technical Support → Customer Service, then resolves ----------
  const visitorContext = await browser.newContext();
  const v = await visitorContext.newPage();
  await v.goto(`/${slug}`);
  await expect(v.getByRole("button", { name: "Chat with our Technical Support" })).toBeVisible();
  await v.getByRole("button", { name: "Chat with Mona" }).click();
  const input = v.getByLabel("Message", { exact: true });
  await input.fill("Hello, I have a question about my chair");
  await input.press("Enter");
  await expect(v.getByTestId("guest-assistant").last()).toContainText("Customer Service here.");
  await expect(v.getByTestId("guest-agent-name").last()).toHaveText("Mona");
  await replyDone(v);
  await expect(v.getByRole("button", { name: "My issue is resolved" })).toBeVisible();

  await input.fill("The chair arrived broken and wobbles");
  await input.press("Enter");
  await expect(v.getByTestId("guest-joined").last()).toHaveText("Technical Support joined the conversation");
  await expect(v.getByTestId("guest-assistant").last()).toContainText("Technical Support here.");
  await replyDone(v);
  // Only Customer Service conversations can be closed by the visitor.
  await expect(v.getByRole("button", { name: "My issue is resolved" })).toHaveCount(0);

  await input.fill("It still wobbles. I want a refund");
  await input.press("Enter");
  await expect(v.getByTestId("guest-joined").last()).toHaveText("Mona joined the conversation");
  await replyDone(v);
  await expect(v.getByText("<<")).toHaveCount(0);
  await v.getByRole("button", { name: "My issue is resolved" }).click();
  await expect(v.getByTestId("conversation-resolved")).toBeVisible();

  // --- A new conversation the agent itself marks resolved -------------------------------------
  await v.getByRole("button", { name: "New conversation" }).click();
  await input.fill("Where can I read your return policy?");
  await input.press("Enter");
  await expect(v.getByTestId("guest-agent-name").last()).toHaveText("Mona");
  await replyDone(v);
  await input.fill("That worked, thank you");
  await input.press("Enter");
  await expect(v.getByTestId("conversation-resolved")).toBeVisible();
  await expect(v.getByText("<<RESOLVED")).toHaveCount(0);
  await visitorContext.close();

  // --- A Sales conversation stays team-only for resolution -----------------------------------
  const salesContext = await browser.newContext();
  const s = await salesContext.newPage();
  await s.goto(`/${slug}`);
  await s.getByRole("button", { name: "Chat with our Sales Agent" }).click();
  const salesInput = s.getByLabel("Message", { exact: true });
  await salesInput.fill("How much is the Ergo chair?");
  await salesInput.press("Enter");
  await replyDone(s);
  await expect(s.getByRole("button", { name: "Talk to a person" })).toBeVisible();
  await expect(s.getByRole("button", { name: "My issue is resolved" })).toHaveCount(0);
  await salesContext.close();

  // --- Owner: who resolved what is in the activity log --------------------------------------
  await page.goto(`${businessPath}/activity`);
  const log = page.getByTestId("audit-event");
  await expect(log.filter({ hasText: "A visitor marked their conversation resolved" })).toHaveCount(1);
  await expect(log.filter({ hasText: "Customer Service marked a conversation resolved" })).toHaveCount(1);
  await expect(log.filter({ hasText: "Customer Service handed a conversation to Technical Support" })).toHaveCount(1);
  await expect(log.filter({ hasText: "Technical Support handed a conversation to Customer Service" })).toHaveCount(1);

  // --- Task 16: a visitor confirms their email with a code; the owner sees the customer -------
  // (Part of this test, which already has an owner and a live page: the E2E suite stays under
  // the sign-up limit of 10 per IP per hour.) Memory extraction runs in the worker and is
  // covered by backend tests (tests/test_customers.py).
  const visitorEmail = `visitor-${run}@example.com`;
  const idContext = await browser.newContext();
  const w = await idContext.newPage();
  await w.goto(`/${slug}`);
  await w.getByRole("button", { name: "Chat with our Sales Agent" }).click();
  await expect(w.getByTestId("retention-notice")).toContainText("are deleted after 30 days");
  const wInput = w.getByLabel("Message", { exact: true });
  await wInput.fill("Hi, I need chairs for my office");
  await wInput.press("Enter");
  await replyDone(w);
  await w.getByRole("button", { name: "Remember me next time" }).click();
  const remember = w.getByRole("form", { name: "Remember me" });
  await remember.getByLabel("Your email").fill(visitorEmail);
  await remember.getByRole("button", { name: "Send code" }).click();
  const code = /\b(\d{6})\b/.exec(await emailText(visitorEmail, "Enter this code"))?.[1];
  expect(code).toBeTruthy();
  // A wrong code is refused without saying why.
  await remember.getByLabel("Code from the email").fill(code === "000000" ? "111111" : "000000");
  await remember.getByRole("button", { name: "Confirm" }).click();
  await expect(remember.getByRole("alert")).toHaveText("That code didn't work. Check it, or ask for a new one.");
  await remember.getByLabel("Code from the email").fill(code!);
  await remember.getByRole("button", { name: "Confirm" }).click();
  const masked = `${visitorEmail[0]}***@example.com`;
  await expect(w.getByTestId("identity-verified")).toContainText(`Remembered as ${masked}`);
  await w.reload(); // the open conversation and the identity are restored
  await expect(w.getByTestId("identity-verified")).toContainText(masked);
  await idContext.close();

  await page.goto(`${businessPath}/customers`);
  await expect(page.getByRole("heading", { level: 1, name: "Customers" })).toBeVisible();
  await expect(page.getByTestId("customer").filter({ hasText: visitorEmail })).toContainText("Email confirmed");
  await page.goto(`${businessPath}/activity`);
  await expect(log.filter({ hasText: "A visitor confirmed their email in the chat" })).toHaveCount(1);
});
