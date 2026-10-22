# Executive Assistant (Task 20a)

The business's operational manager, inside the test chat. It is internal: members only, and
guests can never reach it or be routed to it. It is off until an Owner or Admin turns it on in
the AI team page.

## What it knows (`agentree/executive/service.py`)
Each turn, its prompt gets two delimited blocks of data (not instructions):
- **Computed numbers**: the same block as the Data Analyst (`analytics.analyst_numbers`: last 7
  and 30 days, this month, last month).
- **Business state**: the AI team (on/off, open to visitors), the public page (on/off and its
  description), the 15 most recent leads (label `L-xxxxxx`, name, status, date received, next
  follow-up, need), the team (emails and roles) and the number of requests waiting for approval.
  It never sees itself in the team list.

Every number in its reply must appear in those blocks or in the question (`cited_numbers_ok`).
Otherwise the reply is replaced by the computed numbers, as for the Data Analyst.

## What it may do: propose, never perform
It may propose these changes, as `<<ACTION {...}>>` lines after its answer (at most 3 per reply):

| Action | Parameters | Runs |
|---|---|---|
| `set_agent_enabled` | `agent` (a role, never `executive`), `enabled` | `agents.configs.update_config` |
| `update_public_profile` | `enabled` and/or `bio` (≤ 500 characters) | `public.save_profile` (other fields kept) |
| `update_lead_status` | `lead` (label), `status` | `leads.update_lead` |
| `assign_lead` | `lead` (label), `member` (email) | open follow-ups reassigned, or a new one due in 1 day |

- Markers are untrusted model output. Each proposal is validated against this business's real
  agents, leads and members. A lead label must match exactly one recent lead. Invalid proposals
  become a plain status line ("I couldn't prepare that change: unknown lead") and nothing else
  happens. Markers are stripped from every agent's reply, and only the Executive's are read.
- A valid proposal becomes an **approval request** (`APPROVALS.md`, TTL 1 day, "Always allow"
  offered). The reply ends with a status line, which is stored with the message: "Waiting for
  approval: …", or under a rule "Done (always allowed): …" / "Couldn't do it: …".
- The business can take tools away from it on the AI team page: proposals for a tool that is off
  are refused ("I'm not allowed to make that change in this business").
- Changes run as the approver (the audit trail shows that person), and only if the approver (or
  whoever created the rule) is still an Owner or Admin. Otherwise `canceled: approver_not_allowed`
  (this check applies to every approval since Task 20).
- It never acts outside Agentree.

## Design note
The agents module must not import leads or public. So the Executive's context and its proposal
handling reach the agent turn as a `RoleExtension` (`agents.service`), built in the app's
lifespan (`app.state.agent_extensions`) and passed to the console turn. Import-linter enforces
that no feature module depends on `agentree.executive`.

## Not in 20a
- **Task 20c:** scheduled reports (daily or weekly email) and alerts.
- **Agent working hours:** approved by the PO 2026-10-22 and built in Task 20b (`AGENTS.md`). The
  Executive cannot change them yet; that comes as it is developed further.

## Tests
`tests/test_executive.py` covers:
- it is internal and off by default, and visitors are refused;
- the prompt holds the state blocks and computed numbers, and invented numbers are replaced;
- a proposal waits for approval and then runs as the approver, with the status line stored;
- "always allow" runs later proposals at once, and a demoted rule creator no longer authorizes;
- lead status and assignment, and the public page update;
- invalid, disallowed and over-limit proposals never become requests;
- other agents' markers are dropped.

The isolation matrix covers the routes. E2E (`agents.spec.ts`): turn it on, ask it to turn off
Technical Support, approve on the Approvals page, and see Technical Support off.
