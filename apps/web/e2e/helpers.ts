import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { linkFromEmail } from "./mailpit";

export const PASSWORD = "correct horse battery staple";

export const runId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

export async function signUp(page: Page, email: string) {
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
}

export async function verifyFromEmail(page: Page, email: string) {
  await page.goto(await linkFromEmail(email, "/verify-email"));
  await expect(page.getByRole("heading", { name: "Email verified" })).toBeVisible();
  await page.getByRole("link", { name: "Continue to sign in" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to Agentree" })).toBeVisible();
}

export async function logIn(page: Page, email: string) {
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function logOut(page: Page) {
  await page.getByRole("button", { name: "Account menu" }).first().click();
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
}

/** Waits until no chat on the page is still streaming a reply (it is saved only at the end). */
export async function replyDone(page: Page) {
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
}

/** No horizontal scrolling and no serious or critical WCAG 2 A/AA violations. */
export async function a11yScan(page: Page, label: string) {
  await page.waitForLoadState("networkidle");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `${label} scrolls sideways`).toBeLessThanOrEqual(1);
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect(serious, `${label} accessibility`).toEqual([]);
}
