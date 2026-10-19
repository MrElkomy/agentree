# ADR-001: Authentication approach

Date: 2026-10-19 · Status: **Proposed — needs Product Owner approval** (U-17 / TD-04)

## Context
Agentree needs sign-up/login, email verification, password reset, Google sign-in soon, MFA before handling sensitive customer data at scale, and an enterprise SSO path later (excluded from MVP). Users belong to many businesses with different roles. Tenant isolation is enforced by Agentree's own memberships + PostgreSQL RLS (`TENANCY.md`), and that must not move to a vendor. Target: commercial launch in ~30 days.

## Options

| | A. Custom FastAPI auth | B. Managed identity (WorkOS AuthKit / Clerk / Auth0) | C. Self-hosted IdP (Keycloak, Ory, Zitadel) |
|---|---|---|---|
| Time to market | Slowest: we build & test signup, verify, reset, lockout, Google OAuth, MFA, email templates | Fastest: hosted flows, MFA, Google, bot/breach protection out of the box | Medium: setup is quick, hardening and operations are not |
| Security | Fully ours to get right; every flow is new attack surface | Specialist vendor handles credential storage, MFA, anomaly detection | Strong software, but patching/upgrades/backups are ours |
| Multi-business memberships | Ours (needed anyway) | Ours — vendor "organizations" not used as source of truth | Ours |
| Operating cost | No fee; engineering + email provider | Free tiers exist but differ and change; costs grow with users/features (SSO is usually a paid add-on). **Verify current pricing before choosing.** | Hosting + ops time |
| Operational burden | Medium (email deliverability, abuse) | Low | High (another stateful service) |
| Vendor dependency | None | Real: user records live with vendor; password-hash export varies by vendor. Mitigated by design below. | None (but Java/Go service to run) |
| Enterprise SSO later | Large build | Built-in (WorkOS strongest here) | Built-in |

## Decision (recommended)
**Option B, used for identity only, behind an Agentree boundary.** Primary candidate: **WorkOS AuthKit** (B2B-focused, standard OIDC, clean path to SSO/SCIM). Alternative: **Clerk** (best Next.js developer experience). Final pick after a 1-day spike verifying current pricing, FastAPI integration and data-export terms.

Design that limits lock-in:
1. **Vendor authenticates; Agentree authorizes.** FastAPI completes the OIDC code flow server-side, verifies the ID token (issuer, audience, signature via JWKS, expiry, nonce).
2. **Agentree issues its own session:** opaque, hashed, server-side session in an `HttpOnly; Secure; SameSite=Lax` cookie on our domain → instant revocation, same-origin CSRF model, no vendor token in the browser for API calls.
3. Local `users` table keyed by our UUID with `(provider, provider_subject)`; email verified flag copied from the provider.
4. Memberships, roles, business switching, invites (our own invite tokens) and RLS context stay 100% in Agentree.
5. One module (`agentree/identity/provider.py`) wraps the vendor; switching providers = new adapter + user re-link by verified email.

## Consequences
- Saves an estimated 1–2 weeks versus custom auth and removes the riskiest flows from our code — material for a 30-day launch.
- Requires a vendor account (Product Owner) and configured redirect URLs per environment.
- Public visitors (guests) are **not** vendor users; guest/customer identity stays in Agentree (email OTP per TD-08).
- Revisit if vendor pricing at projected scale exceeds the cost of owning auth.

## Needs approval
1. Option B with the boundary above.
2. Vendor: WorkOS AuthKit (recommended) or Clerk — after the spike confirms pricing/terms.
