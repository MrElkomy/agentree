# ADR-002: BYOK key vault and LLM provider adapters

Date: 2026-10-19 · Status: **Implemented (Task 05)** — LiteLLM evaluation outcome recorded below for Product Owner visibility.

## Key vault (envelope encryption)
- Each stored provider key gets a random 256-bit data key (DEK). Key encrypted with the DEK, DEK wrapped with the master key, both **AES-256-GCM** (`cryptography` library). No custom crypto.
- **Associated data** `agentree:provider-credential:{business_id}:{credential_id}` binds each ciphertext to its tenant and row: copying it to another business or row fails decryption (tested).
- Master key from `AGENTREE_MASTER_KEY` (never in the DB, never committed). Custody, backup, recovery and rotation procedure: `docs/operations/MASTER_KEY.md`. Required in staging/production (startup fails closed). **Rotation:** new `AGENTREE_MASTER_KEY`/`_ID`, old key in `AGENTREE_PREVIOUS_MASTER_KEYS`; secrets re-wrap lazily on next use. A KMS can replace the env key behind `core/vault.py` later.
- Keys are **write-only** for clients: API returns provider, model, last 4 characters, verification status. Plaintext exists only in memory when saving and when a model call needs it; never logged.
- Table `provider_credentials` (tenant RLS), one row per `primary` / `backup` slot. Replacing a slot creates a new row id. Admin+ manage; members can view status.

## LLM adapters
- Agentree-owned interface `agentree/llm/base.py` (`LLMProvider.chat(api_key, ChatRequest) -> ChatResult`), error taxonomy `ErrorKind` (auth, quota, rate_limit, unavailable, transient, bad_request) for later failover decisions.
- Implementations: thin `httpx` adapters for **OpenAI, Anthropic, Gemini** against fixed vendor endpoints (no customer-supplied URLs → no SSRF surface). Key sent in headers only (never URLs); model names validated; provider error bodies never propagated or logged.
- `FakeProvider` for tests; automated tests never call real providers.

## LiteLLM evaluation (approved as "evaluated implementation")
Decision for MVP: **not adopted now**; revisit when we need many more providers.
- We need 3 providers and one call shape; thin adapters are ~200 lines we fully control and test.
- LiteLLM is a large, fast-moving dependency tree; for a component that handles customer API keys, a smaller supply-chain surface is preferable.
- Per-call key injection, error classification and failover policy are ours anyway (ADR/architecture §10).
- The interface allows adding a LiteLLM-backed `LLMProvider` without touching business logic.

## Not in this task
Streaming responses (with the Sales Agent, slice 2.4), automatic failover/circuit breaker (slice 2.5), usage accounting.

## Addendum (2026-10-20): Groq added (Product Owner decision)
- **Why:** a free option for demos. Google AI Studio now issues `AQ.` keys for this account,
  and those keys return `401 ACCESS_TOKEN_TYPE_UNSUPPORTED` on the REST API (an open issue on
  Google's side). Groq has a free tier with no card required.
- **How:** `GroqProvider` reuses the OpenAI adapter against Groq's fixed OpenAI-compatible
  endpoint `https://api.groq.com/openai/v1/chat/completions`. It is still a fixed vendor URL,
  so there is no SSRF surface. Migration `0007` extends the provider check constraint.
- **Also fixed:** Gemini answers an invalid key with HTTP 400 `API_KEY_INVALID`. This is now
  classified as `auth` ("key rejected") instead of `bad_request` ("model rejected").
