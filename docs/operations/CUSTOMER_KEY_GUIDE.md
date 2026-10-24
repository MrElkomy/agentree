# Connecting your AI keys (customer guide)

Agentree uses AI accounts that **you** own. Your provider bills you directly; Agentree never
resells AI tokens. You add two keys: a **primary** and a **backup** from a different provider, so
your assistants keep answering if one provider has an outage.

## 1. Create an account and a key with a provider
Pick two of these (different companies for the primary and the backup):

| Provider | Where to create a key | Good default model |
|---|---|---|
| OpenAI | platform.openai.com → API keys → Create new secret key | gpt-4o-mini |
| Anthropic | console.anthropic.com → API Keys → Create Key | a current Claude Haiku/Sonnet model |
| Google Gemini | aistudio.google.com → Get API key | a current Gemini Flash model |

Add a payment method with the provider; free tiers are not guaranteed and can stop at any time.

## 2. Set a spending limit with the provider
Every provider lets you set a monthly budget or usage limit. Set one before going live. In
Agentree, also set the **daily reply limit** (Public page & widget → Daily reply limit) so a busy
day or abuse cannot run up your bill.

## 3. Add the keys in Agentree
1. Open your business → **AI keys**.
2. **Primary** → Connect a key → choose the provider, paste the key, pick the model.
3. Keep "Test the key with a tiny request before saving" on (it costs a fraction of a cent).
4. Do the same for **Backup** with the other provider.

After saving, Agentree shows only the last 4 characters. The full key is encrypted and never shown
again, not even to us.

## 4. What happens when a key fails
- Agentree switches to the backup automatically and keeps answering.
- Owners and Admins get an email (and a push alert if turned on) that the key is down.
- Agentree tries the primary again after a short wait (30 seconds, growing up to 10 minutes while
  it keeps failing) and returns to it as soon as it works.
- The AI keys card on the Analytics page shows each key's health.

## 5. Replacing or removing a key
AI keys → **Replace key** (paste the new key) or remove it. Revoke the old key at the provider afterwards.
Only Owners and Admins can change keys; every change is in the Activity log (without the key).

## Never
- Never send your key by email or chat, not even to Agentree support. Paste it only into the AI
  keys page.
- Never reuse a key you also use in other apps; create one just for Agentree.
