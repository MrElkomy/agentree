# ADR-001: Authentication approach

Date: 2026-10-19 · Status: **Accepted** (Product Owner decision, 2026-10-19) · Resolves U-17 / TD-04

## Decision
Authentication is built and operated **inside Agentree** (FastAPI + PostgreSQL) with established, maintained libraries. **No managed/paid auth provider** (WorkOS, Clerk, Auth0 or similar). No custom cryptography or homemade protocols.

## Requirements
- Email/password registration and login.
- Password hashing: **Argon2id** via `argon2-cffi` (library defaults, rehash on parameter change).
- **Server-side sessions:** random opaque token (`secrets.token_urlsafe`, ≥256 bits) sent in an `HttpOnly; Secure; SameSite=Lax` cookie; only its SHA-256 hash is stored. Idle + absolute expiry; revocation of one session, all sessions, and on password change/reset.
- **Email verification and password reset:** single-use, expiring tokens, stored hashed, invalidated on use.
- **CSRF:** SameSite cookie + Origin/Referer check on every state-changing request.
- **Rate limiting:** login, registration, reset and verification endpoints, per IP and per account; generic responses (no account enumeration).
- **Accounts, multi-business memberships, roles (Owner/Admin/Member), invitations** — authorization server-side, tenant context derived from membership (`TENANCY.md`).
- Email: **Mailpit** in development; production provider configurable via SMTP settings (provider choice open, U-05).
- Full tenant-isolation and authorization tests.

## Options considered
| | Custom FastAPI auth (chosen) | Managed identity (WorkOS / Clerk / Auth0) | Self-hosted IdP (Keycloak / Ory) |
|---|---|---|---|
| Cost | No vendor fee | Usage-based fees, SSO usually paid | Hosting + operations |
| Vendor dependency | None | User records with vendor | None, but another stateful service |
| Time to market | Slower (flows built and tested by us) | Fastest | Medium |
| Security burden | Ours: must follow the requirements above strictly | Vendor carries most | Ours to patch and operate |

## Consequences
- Every flow above is new attack surface: covered by dedicated tests (enumeration, token reuse/expiry, session fixation, CSRF, rate limits) and reviewed before launch.
- Adds roughly one week of backend work versus a managed provider; accepted for cost and independence.
- MFA (TOTP) and Google sign-in are post-MVP additions using the same session model. Enterprise SSO would need SAML/OIDC work later.
- Public visitors (guests) are not platform users; customer identity stays separate (TD-08).
