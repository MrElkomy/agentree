# AI reliability (Task 13a)

Replies stream as the model writes them, a failing AI key is taken out of rotation by a circuit
breaker, the backup key answers meanwhile, and traffic returns to the primary on its own once it
recovers. Owners see each key's health; operators get counters.

## Circuit breaker (per stored key)

State lives on the key's `provider_credentials` row (migration 0013), so every API process shares
it and replacing a key (a new row) starts closed.

| Column | Meaning |
|---|---|
| `failure_count` | Consecutive availability failures (reset by any success) |
| `last_failure_at` | Time of the last availability failure |
| `breaker_open_until` | Set while open: the key is skipped until this time |
| `probe_until` | Lease of the single half-open probe in flight |

- **Closed → open:** after 3 consecutive availability failures (`unavailable`, `transient`,
  `rate_limit`), or at once for `auth` / `quota` (the key itself needs attention).
  `bad_request` (our request is wrong, e.g. the model name) never trips the breaker.
- **Open:** calls skip the key (no wasted request, no added latency) and use the other key.
  Cooldown: 30 s, doubling after each failed probe up to 10 min; 5 min for auth/quota.
- **Half-open:** when the cooldown ends, the next real request is the probe; `admit()` claims it
  under a row lock with a 90 s lease, so only one request probes at a time.
- **Recovery:** a successful probe closes the breaker; because the primary is always tried
  first, traffic returns to it without any background job. A successful **Test** in AI Providers
  also closes it at once.

Code: `agentree/providers/service.py` (`admit`, `record_outcome`, `record_check`) and
`agentree/agents/service.py` (`_stream_with_fallback`).

## Streamed replies (SSE)

| Endpoint | Who |
|---|---|
| `POST /api/businesses/{id}/agents/sales/console/stream` | Members (test console) |
| `POST /api/public/{slug}/chat/stream` | Visitors (public page and website widget) |

Same body and the same checks, rate limits and daily reply budget as the JSON endpoints, which
remain. The server pulls the first item before answering, so errors before any text (not found,
no provider, every key down, guest token) are ordinary HTTP errors. After that the response is
`200 text/event-stream`:

| Event | Data |
|---|---|
| `delta` | `{"text": "…"}`: the next piece of visible text |
| `restart` | `{}`: the primary broke off mid-reply and the backup now answers; drop the partial text |
| `done` | Same body as the JSON endpoint; its `reply` is final and replaces the streamed text |
| `error` | `{"code": …}` (`agent_unavailable` for visitors; `ai_unavailable` + `errors` in the console) |

- Lead and handoff markers are never streamed: text from the first `<<` on is held back and the
  final reply (markers removed) arrives in `done`.
- Both messages are stored only when the turn completes. After `error` nothing was saved, so the
  chat keeps the partial text marked as interrupted and offers **Retry** / **Try again**, which
  sends the same message again. A visitor or member who leaves mid-reply also stores nothing.
- `restart` is sent only when the backup actually starts answering; if no key answers, the partial
  text stays for the error.
- Responses carry `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`. Verified
  locally through the Next.js `/api` rewrite and through Caddy 2.11 with the staging site block
  (`basic_auth` + `encode zstd gzip`): events arrive one by one and uncompressed, so the host
  Caddy config needs no change.

Adapters stream from each vendor's own SSE API (OpenAI/Groq chat completions with `stream`,
Anthropic Messages events, Gemini `streamGenerateContent?alt=sse`); the response body is never
logged or propagated.

## Health for owners

`GET /api/businesses/{id}/ai-providers` returns per key `health` (`healthy`, `degraded` = recent
errors but in use, `down` = breaker open, `recovering` = cooldown over, next call tests it),
`last_failure_at` and `breaker_open_until`. The AI Providers page shows it with the reason in
plain words, and a banner when a key is down (with or without a working backup).
`last_verified_at` is now the time of the key's last successful call.

## Monitoring

- **Logs:** `provider call failed` (slot, provider, error kind, `mid_stream`) and
  `provider breaker opened|reopened|closed` (business id, slot, provider, error kind). Never keys
  or message content.
- **Metrics:** `GET /api/internal/metrics` in Prometheus text format, only with the header
  `X-Agentree-Metrics-Token: $AGENTREE_METRICS_TOKEN` (unset: 404). Counters per API process:
  `agentree_llm_calls_total{provider,slot,outcome}`,
  `agentree_breaker_transitions_total{transition}`. Gauge `agentree_provider_keys{state}` from the
  SECURITY DEFINER function `agentree_provider_health_counts` (platform-wide counts only, no ids).
  No paid alerting service (out of scope); Task 13b adds owner alerts (email + Web Push) when a
  key goes down.

## Demo mode

With `AGENTREE_LLM_DEMO_MODE=true` the demo provider streams word by word and cuts off the first
reply to a message containing "simulate an interruption", for browser tests of the retry path.
