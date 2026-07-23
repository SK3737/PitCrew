# ADR 0001: Argon2id password hashing with rotating, reuse-detecting refresh tokens

## Status

Accepted. Implemented in Phase 2, reviewed clean after one fix-loop.

## Context

PitCrew needs real authentication and role-based access control (admin, mechanic, owner, demo), and the design spec calls out security awareness as a deliberate secondary CV signal (`docs/superpowers/specs/2026-07-23-pitcrew-design.md`, section 4.2).
The spec is explicit that this subsystem should stay concrete rather than delegated wholesale to a black-box library, because a legible, checkable implementation is itself the demonstration.

Two sub-decisions were needed: how to hash passwords, and how to issue and invalidate session tokens.

## Decision

**Password hashing**: Argon2id via `argon2-cffi`'s `PasswordHasher` (`backend/app/auth/hashing.py`), not `passlib` or `bcrypt`.
`passlib` is effectively unmaintained, and `bcrypt` silently truncates passwords past 72 bytes, which is a real footgun for a security-signal feature.
Argon2id is the current OWASP-recommended variant and is the library's own default.

**Tokens**: a short-lived JWT access token (HS256 via PyJWT, 15-minute lifetime, carrying `sub`, `role`, `jti`, and a `type: access` claim) sent in the `Authorization` header, plus a separate refresh token in an HttpOnly, Secure, `SameSite=strict` cookie, never in a JSON response body.
Refresh tokens are tracked server-side (`RefreshTokenRepository`) so they can be rotated on every use and revoked before their natural expiry, which a bare stateless JWT cannot do.
Presenting an already-rotated (or revoked) refresh token is treated as evidence of token theft: the entire refresh chain for that user is revoked, not just the one token.
Authorization is expressed once, as `require_permission(...)` FastAPI dependencies on routes (`backend/app/auth/rbac.py`), rather than as scattered per-route checks.

The rotation-plus-reuse-detection logic is hand-written rather than delegated to an auth-as-a-service library, matching the spec's stated rationale: it is small enough to read end to end and is exactly the kind of implementation detail a reviewer evaluating security awareness would want to see, not just take on faith.

## Consequences

**Positive**:
Two real vulnerabilities were caught and fixed during this feature's own development, which is itself evidence the design works as intended.
The implementer self-found and fixed a self-registration privilege-escalation bug (role was client-supplied at first, now server-side allowlisted to `owner`/`demo` only) before first review.
Code review then caught a second, more serious issue the implementer had missed: `get_current_user` never checked the `type` claim, so a refresh token could be replayed as a Bearer access token and be accepted with the user's real role - a genuine auth bypass in the opposite direction from the first fix.
The fix (stamping `type: access` on access tokens and rejecting any other or missing type in `get_current_user`) was verified by reproducing the bypass before the fix and confirming it was closed after, plus a full regression run.

**Negative**:
Hand-writing rotation and reuse detection is more maintenance surface than depending on a mature library, and it is only as strong as this project's own review process, which is a real tradeoff for a demo project accepted deliberately.
`RegisterRequest`/`LoginRequest.email` is a plain `str` today, with no email-format validation - low risk, data-quality only, not yet fixed.
No route yet lets an owner claim or create a vehicle (nothing sets `owner_id`), which was deliberately scoped out until a phase actually needs owner-scoped vehicle creation.
The frontend BFF's own session cookie (`frontend/lib/session.ts`) uses `SameSite=lax`, not `strict` - this is fine because the spec's strict requirement was scoped to the backend's refresh cookie specifically, but it is a slightly weaker CSRF posture worth naming rather than leaving implicit.
