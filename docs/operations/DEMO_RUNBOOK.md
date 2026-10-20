# Demo runbook: Sales Agent with a real customer-owned AI key

Goal: show the full flow (sign up → business → AI provider key → knowledge → Sales Agent chat)
on a real provider, using **your own** API key. Requires PRs #5, #6, #7 and #8 merged.

## Security rules for the demo (non-negotiable)
- Paste the real API key **only** into the Agentree "AI Providers" screen. Never into GitHub,
  chat, tickets, `.env` files committed to git, test fixtures, or command lines that are logged.
- Do not take screenshots or recordings of the key field while typing the key. After saving,
  the UI shows only `•••• last4` — that view is safe to show.
- Use a **dedicated demo key** with a low spending limit set in the provider console
  (OpenAI: project budget; Anthropic: workspace spend limit; Google AI Studio: quota). Revoke it
  after the demo.
- `AGENTREE_LLM_DEMO_MODE` must be **false** (default). With it on, no real provider is called.
- Generate a fresh master key for the demo environment (never reuse the dev compose key outside
  local dev): see `docs/operations/MASTER_KEY.md`.

## 1. Start an environment
**Option A — local machine with Docker** (fastest):
```bash
git clone https://github.com/MrElkomy/agentree && cd agentree
docker compose -f infra/docker-compose.yml up -d --build      # API :8000, Mailpit :8025
cd apps/web && npm ci && npm run build && AGENTREE_API_URL=http://127.0.0.1:8000 npm run start
```
Open http://localhost:3000. Emails (verification, invites) appear in Mailpit at http://localhost:8025.

**Option B — hosted staging**: not available yet (deployment is Phase 7). Until then, Option A
is the only way to run the demo with a real key.

## 2. Walk through the flow
1. **Sign up** at `/signup` → open the verification email in Mailpit → verify → sign in.
2. **Create a business** (e.g. "Ergo Chairs").
3. **AI Providers** → *Primary provider* → *Connect a key*:
   - Provider: OpenAI / Anthropic / Google Gemini / Groq; Model: e.g. `gpt-4o-mini`,
     `claude-haiku-4-5`, `gemini-2.5-flash`, `openai/gpt-oss-120b` (any model your account can
     use). **Groq has a free tier** (console.groq.com → API Keys; key starts with `gsk_`).
     Gemini keys must start with `AIza`: AI Studio `AQ.` keys are currently rejected by Google's
     REST API.
   - Paste the key, keep **"Test the key with a tiny request before saving"** checked → *Save key*.
   - Expected: "Key tested and saved securely", status *Working*, key shown as `•••• last4`.
   - Optional: add a **Backup provider** from a different provider account.
4. **Knowledge** → add 2–4 entries (prices, delivery, warranty/returns, contact) → *Publish* each.
5. **Sales Agent** → ask:
   - a covered question ("How much is the Ergo chair?") → answer uses your facts, footer shows
     your provider/model;
   - an uncovered question ("Do you ship to Mars?") → the agent should say it doesn't have that
     information and offer to connect you with the team; footer shows "No published knowledge
     matched this question";
   - a follow-up in the same conversation → context is kept.
6. **Failover (optional)**: with a backup configured, temporarily replace the primary with an
   invalid key (save with the test unchecked) → chat still answers, footer shows "answered by
   backup provider"; AI Providers shows the primary's last error. Restore the real key after.
7. **Roles (optional)**: invite a teammate as Member → they can chat and draft knowledge but
   cannot see or change keys beyond the masked status, or publish.

## Public page & widget
1. In the business sidebar open **Public page & widget** (Owner or Admin).
2. Tick **Public page is on**, add a bio and a few links (each `https://…`), set the daily reply
   limit (protects your AI credit; default 200), then **Save**. Until it is on and saved, the
   page answers "not found".
3. **Page address** shows `{origin}/{slug}` → *Open* it in a private window (no login) and chat
   with the Sales Agent. Reload: the conversation is still there. Another browser does not see it.
4. **Website chat**: list the exact website addresses that may show the chat (one per line, e.g.
   `https://www.example.com`), save, then paste the snippet before `</body>` on that website:
   ```html
   <script src="{origin}/widget.js" data-agentree="{slug}" async></script>
   ```
   On any website not in the list the browser refuses to show the chat.
5. **Staging note**: tryagentree.com is behind a basic-auth gate, and the gate also covers
   `/widget.js` and the chat iframe. Visitors on another website would get a login prompt or a
   broken chat, so on staging try the widget on tryagentree.com pages only (the iframe allows
   our own origin); real customer websites need the gate lifted for these paths first.

## 3. After the demo
- Remove the key in *AI Providers* (*Remove*) **and revoke it in the provider console**.
- Local: `docker compose -f infra/docker-compose.yml down -v` deletes all demo data.

## Known limitations (still open — see roadmap "Open requirements")
- Replies are not streamed (the full answer appears at once).
- No circuit breaker / automatic recovery: each message tries the primary first again.
- 30-day conversation retention is **not** enforced yet — do not use real customer conversations.
- Knowledge is typed entries only (no file upload). Only the Sales Agent exists; no branding of the public page
  or website widget customization (colours, logo) yet.
