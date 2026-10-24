import { expect, test } from "@playwright/test";
import { a11yScan as scan, logIn, logOut, runId, signUp, verifyFromEmail } from "./helpers";
import { linkFromEmail } from "./mailpit";

const run = runId();
const ownerEmail = `owner-${run}@example.com`;
const memberEmail = `member-${run}@example.com`;
const businessName = `Acme Plumbing ${run}`;

test("unauthenticated visit to /dashboard goes to sign in", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/);
  await expect(page.getByRole("heading", { name: "Sign in to Agentree" })).toBeVisible();
});

test("wrong password shows a generic error", async ({ page }) => {
  await page.goto("/login");
  await logIn(page, `nobody-${run}@example.com`);
  await expect(page.getByRole("alert").filter({ hasText: "don't match" })).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
  await scan(page, "/login (desktop)");
});

test("owner creates a business and invites a member who joins", async ({ browser }) => {
  // --- Owner: sign up, verify, sign in, create a business --------------------------------
  const ownerContext = await browser.newContext();
  const owner = await ownerContext.newPage();
  await owner.goto("/signup");
  await signUp(owner, ownerEmail);
  await verifyFromEmail(owner, ownerEmail);
  await logIn(owner, ownerEmail);
  await expect(owner).toHaveURL(/\/dashboard$/);
  await expect(owner.getByRole("heading", { name: "Set up your first business" })).toBeVisible();

  await owner.getByLabel("Business name").fill(businessName);
  await expect(owner.getByLabel("URL name")).toHaveValue(`acme-plumbing-${run}`);
  await owner.getByRole("button", { name: "Create business" }).click();
  await expect(owner).toHaveURL(/\/b\/[0-9a-f-]{36}$/);
  await expect(owner.getByRole("heading", { level: 1, name: businessName })).toBeVisible();
  await expect(owner.getByTestId("current-business")).toHaveText(businessName);

  // The new business appears in the switcher.
  await owner.getByRole("button", { name: /Switch business/ }).click();
  const switcher = owner.getByRole("list", { name: "Your businesses" });
  await expect(switcher.getByRole("link", { name: new RegExp(businessName) })).toBeVisible();
  await owner.keyboard.press("Escape");

  // --- Owner: invite a member ----------------------------------------------------------
  await owner.getByRole("link", { name: "Members" }).first().click();
  await expect(owner.getByRole("heading", { name: "Members", level: 1 })).toBeVisible();
  await expect(owner.getByTestId("member-row")).toHaveCount(1);
  await owner.getByLabel("Email", { exact: true }).fill(memberEmail);
  await owner.getByRole("button", { name: "Send invitation" }).click();
  await expect(owner.getByText(`Invitation sent to ${memberEmail}.`)).toBeVisible();
  await expect(owner.getByTestId("invitation-row")).toContainText(memberEmail);

  // --- Owner: the activity log records both changes, newest first ----------------------
  await owner.getByRole("link", { name: "Activity log" }).first().click();
  await expect(owner.getByRole("heading", { name: "Activity log", level: 1 })).toBeVisible();
  const events = owner.getByTestId("audit-event");
  await expect(events).toHaveCount(2);
  await expect(events.nth(0)).toContainText(`${ownerEmail} invited ${memberEmail} as Member`);
  await expect(events.nth(1)).toContainText(`${ownerEmail} created the business`);
  await logOut(owner);
  await ownerContext.close();

  // --- Member: open the invitation, sign up, verify, sign in, accept -------------------
  const memberContext = await browser.newContext();
  const member = await memberContext.newPage();
  const inviteLink = await linkFromEmail(memberEmail, "/invitations/accept");
  await member.goto(inviteLink);
  await expect(member).toHaveURL(/\/login\?next=%2Finvitations%2Faccept/);
  await member.getByRole("link", { name: "Create an account" }).click();
  await expect(member).toHaveURL(/\/signup\?next=/);
  await signUp(member, memberEmail);
  await verifyFromEmail(member, memberEmail);
  await logIn(member, memberEmail);

  await expect(member).toHaveURL(/\/invitations\/accept\?token=/);
  await expect(member.getByText(memberEmail)).toBeVisible();
  await member.getByRole("button", { name: "Accept invitation" }).click();
  await expect(member.getByRole("heading", { name: `You've joined ${businessName}` })).toBeVisible();
  await member.getByRole("link", { name: `Open ${businessName}` }).click();

  // --- Member: sees the business as a member, cannot invite ----------------------------
  await expect(member.getByRole("heading", { level: 1, name: businessName })).toBeVisible();
  await expect(member.getByText("Your role")).toBeVisible();
  await expect(member.locator("dd").getByText("Member", { exact: true })).toBeVisible();
  await member.getByRole("link", { name: "Members" }).first().click();
  await expect(member.getByRole("heading", { name: "Members", level: 1 })).toBeVisible();
  await expect(member.getByTestId("member-row")).toHaveCount(2);
  await expect(member.getByRole("heading", { name: "Invite someone" })).toHaveCount(0);
  await expect(member.getByRole("button", { name: "Send invitation" })).toHaveCount(0);
  await expect(member.getByRole("heading", { name: "Pending invitations" })).toHaveCount(0);
  await expect(member.getByRole("link", { name: "Activity log" })).toHaveCount(0);

  // The member's own dashboard lists the business with the member role.
  await member.goto("/dashboard");
  const row = member.getByRole("link", { name: new RegExp(businessName) });
  await expect(row).toContainText("Member");

  await logOut(member);
  // After logout the backend session is gone: protected pages send you to sign in.
  await member.goto("/dashboard");
  await expect(member).toHaveURL(/\/login\?next=%2Fdashboard$/);
  await memberContext.close();
});

test("sign-in never redirects to another site", async ({ page }) => {
  // Task 22 security review: browsers drop the tab, so "/\t/evil.example" would be "//evil.example".
  // Reuses the owner from above: sign-up is limited to 10 per IP per hour.
  await page.goto(`/login?next=${encodeURIComponent("/\t/evil.example/")}`);
  await logIn(page, ownerEmail);
  await expect(page).toHaveURL(/\/dashboard$/);
  expect(new URL(page.url()).host).not.toContain("evil.example");
});

test("each business stays private; dashboard pages fit a phone and pass an accessibility scan", async ({
  browser,
}) => {
  // Task 22 (B4): two tenants in the UI, a 390×844 phone and axe (WCAG 2 A/AA, serious+ issues).
  // Reuses the accounts above: sign-up is limited to 10 per IP per hour.
  const memberContext = await browser.newContext();
  const member = await memberContext.newPage();
  await member.goto("/login");
  await logIn(member, memberEmail);
  await expect(member).toHaveURL(/\/dashboard$/);
  await member.getByLabel("Business name").fill(`Second Shop ${run}`);
  await member.getByRole("button", { name: "Create business" }).click();
  await expect(member).toHaveURL(/\/b\/[0-9a-f-]{36}$/);
  const secondUrl = new URL(member.url()).pathname;
  await memberContext.close();

  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const owner = await phone.newPage();
  await owner.goto("/login");
  await scan(owner, "/login");
  await logIn(owner, ownerEmail);
  await expect(owner).toHaveURL(/\/dashboard$/);

  // The owner of the first business is not a member of the second: nothing of it is shown.
  for (const path of [secondUrl, `${secondUrl}/leads`, `${secondUrl}/inbox`, `${secondUrl}/analytics`]) {
    await owner.goto(path);
    await expect(owner.getByRole("heading", { name: "Business not available" })).toBeVisible();
    await expect(owner.getByText(`Second Shop ${run}`)).toHaveCount(0);
  }

  // Their own business, on a phone.
  await owner.goto("/dashboard");
  await owner.getByRole("link", { name: new RegExp(businessName) }).click();
  await expect(owner).toHaveURL(/\/b\/[0-9a-f-]{36}$/);
  const base = new URL(owner.url()).pathname;
  for (const path of ["", "/inbox", "/leads", "/knowledge", "/agents", "/approvals", "/analytics", "/members"]) {
    await owner.goto(`${base}${path}`);
    await expect(owner.getByRole("heading", { level: 1 }).first()).toBeVisible();
    await scan(owner, `${base}${path}`);
  }
  await phone.close();
});


test("privacy notice and terms are public and linked from sign-up", async ({ page }) => {
  // Task 22 (final gate 2): linked from sign-up, the public page and the chat.
  await page.goto("/signup");
  await page.getByRole("link", { name: "privacy notice" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Privacy notice" })).toBeVisible();
  await expect(page.getByText("You are talking to AI.")).toBeVisible();
  await scan(page, "/privacy");
  await page.goto("/signup");
  await page.getByRole("link", { name: "terms" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Terms" })).toBeVisible();
  await expect(page.getByText("Your AI keys and costs")).toBeVisible();
  await scan(page, "/terms");
});
