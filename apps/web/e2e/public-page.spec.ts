import { createServer } from "node:http";
import { expect, test, type Page } from "@playwright/test";
import { logIn, runId, signUp, verifyFromEmail } from "./helpers";

// Runs against the dev stack with AGENTREE_LLM_DEMO_MODE=true (canned replies, no real key).
const DEMO_REPLY_START = "This is a demo reply";

async function ownerSetup(page: Page, run: string) {
  const email = `public-owner-${run}@example.com`;
  const businessName = `Cedar Desks ${run}`;
  await page.goto("/signup");
  await signUp(page, email);
  await verifyFromEmail(page, email);
  await logIn(page, email);
  await page.getByLabel("Business name").fill(businessName);
  await page.getByRole("button", { name: "Create business" }).click();
  await expect(page.getByRole("heading", { level: 1, name: businessName })).toBeVisible();

  // Demo key + published knowledge, so the public Sales Agent can answer.
  await page.getByRole("link", { name: "AI Providers" }).first().click();
  const primary = page.getByTestId("slot-primary");
  await primary.getByRole("button", { name: "Connect a key" }).click();
  await primary.getByLabel("API key").fill("sk-e2e-demo-key-00005678");
  await primary.getByLabel("Test the key with a tiny request before saving").uncheck();
  await primary.getByRole("button", { name: "Save key" }).click();
  await expect(primary.getByText("•••• 5678")).toBeVisible();

  await page.getByRole("link", { name: "Knowledge" }).first().click();
  await page.getByLabel("Title").fill("Pricing");
  await page.getByLabel("Content").fill("The Cedar desk costs $499.");
  await page.getByRole("button", { name: "Save as draft" }).click();
  const entry = page.getByTestId("knowledge-entry").filter({ hasText: "Pricing" });
  await entry.getByRole("button", { name: "Publish" }).click();
  await expect(entry.getByText("Published")).toBeVisible();
  return businessName;
}

test("owner publishes a public page; visitors chat privately; widget is framable only by allowlist", async ({
  page,
  browser,
  request,
}) => {
  const run = runId();
  const businessName = await ownerSetup(page, run);

  // Public page settings.
  await page.getByRole("link", { name: "Public page & widget" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Public page & widget" })).toBeVisible();
  await expect(page.getByTestId("public-status")).toHaveText("Off");
  const url = (await page.getByTestId("public-url").textContent())!.trim();
  const slug = new URL(url).pathname.slice(1);
  expect(slug).toMatch(/^cedar-desks-/);
  await expect(page.getByTestId("embed-snippet")).toContainText(`data-agentree="${slug}"`);

  // Before enabling, the page does not exist for visitors.
  expect((await request.get(`/${slug}`)).status()).toBe(404);

  await page.getByLabel("Public page is on").check();
  await page.getByLabel("Bio").fill("Handmade standing desks from Cairo.");
  await page.getByRole("button", { name: "Add link" }).click();
  await page.getByLabel("Link 1 label").fill("Our shop");
  await page.getByLabel("Link 1 address").fill("https://shop.example.com/desks");
  // localhost origins are accepted only in dev/test (the CI stack runs AGENTREE_ENVIRONMENT=dev).
  await page.getByLabel("Websites allowed to show the chat").fill("https://www.example.com\nhttp://localhost:4000");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved. Your public page is live.")).toBeVisible();
  await expect(page.getByTestId("public-status")).toHaveText("Live");

  // Visitor 1: a fresh browser context with no login.
  const visitor1 = await browser.newContext();
  const v1 = await visitor1.newPage();
  await v1.goto(`/${slug}`);
  await expect(v1.getByTestId("public-name")).toHaveText(businessName);
  await expect(v1.getByTestId("public-bio")).toHaveText("Handmade standing desks from Cairo.");
  const link = v1.getByRole("link", { name: "Our shop" });
  await expect(link).toHaveAttribute("href", "https://shop.example.com/desks");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");

  await v1.getByRole("button", { name: "Chat with our Sales Agent" }).click();
  await expect(v1.getByText("You're chatting with an AI assistant.")).toBeVisible();
  await v1.getByLabel("Message", { exact: true }).fill("How much is the Cedar desk?");
  await v1.keyboard.press("Enter");
  await expect(v1.getByTestId("guest-user")).toHaveText("How much is the Cedar desk?");
  await expect(v1.getByTestId("guest-assistant")).toContainText(DEMO_REPLY_START);
  await expect(v1.getByTestId("guest-assistant")).toContainText(`${businessName} Sales Agent`);

  // The conversation survives a reload (same browser).
  await v1.reload();
  await expect(v1.getByTestId("guest-user")).toHaveText("How much is the Cedar desk?");
  await expect(v1.getByTestId("guest-assistant")).toContainText(DEMO_REPLY_START);

  // Visitor 2 (another browser) does not see visitor 1's conversation.
  const visitor2 = await browser.newContext();
  const v2 = await visitor2.newPage();
  await v2.goto(`/${slug}`);
  await v2.getByRole("button", { name: "Chat with our Sales Agent" }).click();
  await expect(v2.getByTestId("guest-chat")).toBeVisible();
  await expect(v2.getByTestId("guest-user")).toHaveCount(0);
  await expect(v2.getByText("How much is the Cedar desk?")).toHaveCount(0);

  // Widget iframe page: compact chat; framing allowed only for the listed websites.
  const widgetResponse = await v2.goto(`/w/${slug}`);
  const csp = widgetResponse!.headers()["content-security-policy"] ?? "";
  expect(csp).toBe("frame-ancestors 'self' https://www.example.com http://localhost:4000");
  expect(widgetResponse!.headers()["x-frame-options"]).toBeUndefined();
  await expect(v2.getByTestId("widget-name")).toHaveText(businessName);
  await expect(v2.getByTestId("guest-chat")).toBeVisible();

  // The embed snippet on an allowed website: launcher opens the chat iframe; it closes from
  // inside the iframe (postMessage) and with Escape.
  // A real local http server: an https page could not load the http dev server's script, and
  // Chrome's local-network rules block scripts on intercepted (route-fulfilled) pages.
  const hostHtml = `<!doctype html><html><body><h1>Example shop</h1><script src="${new URL(url).origin}/widget.js" data-agentree="${slug}" async></script></body></html>`;
  const hostServer = createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(hostHtml);
  });
  await new Promise<void>((resolve) => hostServer.listen(4000, resolve));
  const host = await visitor2.newPage();
  await host.goto("http://localhost:4000/");
  const launcher = host.getByRole("button", { name: "Open chat" });
  await launcher.click();
  const widget = host.frameLocator(`iframe[src$="/w/${slug}"]`);
  await expect(widget.getByTestId("widget-name")).toHaveText(businessName);
  await widget.getByLabel("Message", { exact: true }).fill("Do you deliver?");
  await widget.getByLabel("Message", { exact: true }).press("Enter");
  await expect(widget.getByTestId("guest-assistant")).toContainText(DEMO_REPLY_START);
  await widget.getByRole("button", { name: "Close chat" }).click();
  await expect(host.locator("iframe")).toBeHidden();
  await host.getByRole("button", { name: "Open chat" }).click();
  await expect(host.locator("iframe")).toBeVisible();
  await host.keyboard.press("Escape");
  await expect(host.locator("iframe")).toBeHidden();

  // A website that is not on the list: the browser refuses to show the chat.
  const otherServer = createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(hostHtml);
  });
  await new Promise<void>((resolve) => otherServer.listen(4001, resolve));
  const other = await visitor2.newPage();
  await other.goto("http://localhost:4001/");
  const refused = other.waitForEvent("console", (m) => m.text().includes("frame-ancestors"));
  await other.getByRole("button", { name: "Open chat" }).click();
  await refused;
  await expect(other.frameLocator("iframe").getByTestId("widget-name")).toHaveCount(0);
  await new Promise((resolve) => hostServer.close(resolve));
  await new Promise((resolve) => otherServer.close(resolve));

  // Every other page stays unframable.
  const dashboard = await request.get("/dashboard");
  expect(dashboard.headers()["x-frame-options"]).toBe("DENY");

  // Turning the page off makes it disappear for visitors, and the widget unframable.
  await page.getByLabel("Public page is on").uncheck();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved. Your public page is off.")).toBeVisible();
  await v1.goto(`/${slug}`);
  await expect(v1.getByRole("heading", { name: "Page not found" })).toBeVisible();
  const off = await request.get(`/w/${slug}`);
  expect(off.status()).toBe(404);
  expect(off.headers()["content-security-policy"]).toBe("frame-ancestors 'none'");

  await visitor1.close();
  await visitor2.close();
});
