# Approvals (Task 19)

Sensitive agent actions never run straight away. They become **approval requests** that an
Owner or Admin answers on the Approvals page (`/b/{id}/approvals`). Product decisions:
agent-written follow-up messages are drafts the owner approves (PO 2026-10-21, option B). Each
request offers **Approve once** or **Always allow**, so owners aren't asked again and again
(PO 2026-10-22).

## Policy (`agentree/actions`, `APPROVALS`)
| Action | Agent | Expires after | "Always allow" |
|---|---|---|---|
| `send_follow_up_email` | Sales Agent | 3 days | yes |
| `set_agent_enabled`, `update_public_profile`, `update_lead_status`, `assign_lead` | Executive Assistant (Task 20, `EXECUTIVE.md`) | 1 day | yes |

- The gateway refuses to run a sensitive action directly (`claim` raises). Only
  `agentree.approvals` runs it, after a person decides or a rule allows it.
- The tool is **opt-in** (`OPT_IN`): it is off in an agent's default configuration, and the
  business turns it on in the AI team page ("Draft follow-up emails").

## Lifecycle (`agentree/approvals`)
`pending` → `approved` (once / always / rule) or `rejected`, or `expired` once its TTL passes →
`executing` → `executed`, `canceled` (no longer needed) or `failed`. A run that stops midway
(server restart) shows as `unknown` after 10 minutes and is **never retried**, because it may
already have taken effect.

- **Bound to the parameters.** A request stores its parameters and their hash. The approval
  records the hash of exactly what was approved (`approved_hash`). If the parameters differ at
  run time, the approval is void (`failed: params_changed`). A person may **edit** editable fields
  before approving (the follow-up's subject and body, never its recipient), and the approval then
  binds the edited version.
- **Exactly once.** Whoever runs it (the API right after the decision, or the worker every
  `AGENTREE_APPROVALS_INTERVAL_SECONDS`, default 60, as a safety net) first moves it from
  `approved` to `executing` in one conditional UPDATE, so only one runner wins. Retries and
  repeated decisions don't run it again. Requests are idempotent per key (one follow-up per lead).
- **Re-checked at run time.** The approver, or whoever created the rule, must still be an
  Owner or Admin (`canceled: approver_not_allowed`, since Task 20). The agent must still hold the
  tool (`canceled: tool_turned_off`).
  The action's own checks also apply (see below).
- **Always allow** creates a rule (business, agent, action). Later requests from that agent for
  that action are approved by the rule and run at once. Nobody is notified, and the history shows
  "Sent automatically". Owners and Admins can revoke a rule at any time. Requests the backend
  **flagged** always wait for a person, even under a rule, and can't be "always allowed".
- **Who:** Members can see requests. Only Owners and Admins can decide or revoke rules
  (backend-enforced, 403 otherwise).
- **Told:** a new pending request emails Owners and Admins and sends a push to their devices.
  Both name the agent and the action, never the draft or the lead (lock screens are public).
- **Audit:** `approval.requested`, `approval.decided` (once / always / rule / reject, edited),
  `approval.executed` (status, reason), `approval_rule.created`, `approval_rule.revoked`. The
  audit records action, agent and decision only, never parameters.
- **Retention:** requests hold a lead's address and a draft, so they are deleted 30 days after
  they were made (`agentree_purge_approvals`, SECURITY DEFINER, refuses a cutoff less than a day
  old). Parameters are never logged.

## The first sensitive action: follow-up emails (`agentree/leads/outreach.py`)
- **When:** a new lead's first-contact reminder falls due (24 h after the lead) while the lead is
  still *new* and left an email, and the business turned the tool on. The draft replaces that
  reminder email, because the approval request is the reminder. If drafting fails (no key,
  malformed output), the normal reminder goes out instead. At most one agent email per lead.
- **Draft:** the business's own AI key (BYOK, primary then backup) writes it from the lead's
  request and the Sales Agent's published knowledge. Both are untrusted data inside delimiters,
  and the output must be JSON, otherwise it is refused (never repaired).
- **Flag:** every number and link in the draft must appear in that knowledge, the request, the
  lead's name or the business name (`cited_numbers_ok`, link allowlist). Otherwise the request is
  flagged (`unverified_numbers` / `unverified_links`) and always waits for a person.
- **Send:** only if the lead still exists (`lead_deleted`), is still *new* (`lead_contacted`)
  and has the same address (`lead_changed`). Replies go to the member who approved it, or who
  created the rule (an owner if that person left). The footer tells the lead why they got it.
  If the mail server refuses, the request becomes `failed: send_failed` and the page asks the team
  to contact the lead themselves.

## API
| Method | Path | Who |
|---|---|---|
| GET | `/api/businesses/{id}/approvals?view=pending\|history&limit=` | member |
| GET | `/api/businesses/{id}/approvals/{approval_id}` | member |
| POST | `/api/businesses/{id}/approvals/{approval_id}/decision` `{decision: once\|always\|reject, edits?}` | admin+ |
| GET | `/api/businesses/{id}/approval-rules` | member |
| DELETE | `/api/businesses/{id}/approval-rules/{rule_id}` | admin+ |

Errors: 409 `not_pending`, `expired`, `always_not_allowed`; 422 with the field name for a bad
edit.

## Tests
`tests/test_approvals.py` covers:
- the tool is opt-in, and with the tool off the plain reminder goes out;
- every sensitive action has an executor, and the gateway never runs one directly;
- a draft waits, owners and admins are told without the draft, members can't decide, approve
  once sends exactly once (repeat decision, worker, concurrent runners), the audit trail;
- always allow sends later drafts without asking until it is revoked, and members can't revoke;
- flagged drafts ignore the rule and refuse "always";
- the draft checks, edits (the recipient is locked), rejection and expiry;
- voided approvals (changed parameters), lead contacted or tool turned off after approval;
- unknown outcomes are never retried, failed drafts fall back to the reminder, failed sends are
  recorded, and requests are purged after 30 days.

The isolation matrix covers the new routes with a real approval and rule in the other business.
E2E (`e2e/agents.spec.ts`) checks that the tool is off by default and can be turned on, and that
the Approvals page renders. A pending request needs a due lead (24 h), so deciding is covered by
the backend tests and was checked by hand in a browser.
