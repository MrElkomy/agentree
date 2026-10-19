import { expect } from "@playwright/test";

const MAILPIT = process.env.MAILPIT_URL ?? "http://127.0.0.1:8025";

type Summary = { ID: string; Subject: string; To: { Address: string }[] };

/**
 * Waits for the newest email to `to` whose body contains a link to `path` and returns that
 * link as a path relative to the web origin (e.g. "/verify-email?token=...").
 */
export async function linkFromEmail(to: string, path: string): Promise<string> {
  const pattern = new RegExp(`https?://[^\\s/]+(${path.replace(/[/?]/g, "\\$&")}\\?token=[A-Za-z0-9_-]+)`);
  const found: { link?: string } = {};
  await expect
    .poll(
      async () => {
        const res = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}`);
        if (!res.ok) return null;
        const { messages } = (await res.json()) as { messages: Summary[] };
        for (const m of messages) {
          const full = await fetch(`${MAILPIT}/api/v1/message/${m.ID}`);
          if (!full.ok) continue;
          const { Text } = (await full.json()) as { Text: string };
          const match = pattern.exec(Text);
          if (match?.[1]) {
            found.link = match[1];
            return found.link;
          }
        }
        return null;
      },
      { message: `email to ${to} with a ${path} link`, timeout: 30_000, intervals: [500, 1000] },
    )
    .not.toBeNull();
  if (!found.link) throw new Error(`no ${path} link for ${to}`);
  return found.link;
}
