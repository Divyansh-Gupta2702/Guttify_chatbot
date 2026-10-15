# GutGPT v18.3 — Security and release audit (partial remediation)

## Scope and evidence

Audited the supplied `guttify_work` archive, focusing on `app.py`, the embedded Shopify widget, customer registration/restore routes, and existing pytest tests. The archive contains the deterministic diagnosis engine and existing regression tests. No production logs, Render credentials, database credentials, or live Shopify environment were supplied.

## Changes made

- Replaced insecure customer-ID-only restoration with a high-entropy opaque guest credential. The backend returns the credential after registration, persists only its SHA-256 hash with a 30-day expiry, and requires the credential to restore a profile. A customer ID alone cannot restore a profile.
- Updated the widget to save the guest credential and, on refresh/reopen, create a fresh diagnostic session and restore only the profile. Previous diagnostic answers are not copied into the new session. If the credential is missing/invalid/expired, the widget falls back to registration.
- Added backend contact validation that accepts a plausible email or international-style phone number without hardcoding one country's phone format; rejects control characters and obvious invalid strings.
- Removed the customer ID from registration log messages.
- Updated the widget's consent copy to clarify that no website account/password is needed and details are stored.
- Updated/added regression tests for guest-token restoration, invalid guest credentials, token-hash-only persistence, age reuse, fresh diagnostic state, and invalid contact input.

## Baseline and verification

- Runtime: Python 3.13.5.
- `python -m py_compile app.py guttify_agent.py nlu_extractor.py`: passed.
- Baseline `pytest -q`: collection failed before tests ran because `langchain_core` was not installed (`ModuleNotFoundError`).
- Attempted dependency installation from `requirements.txt` plus pytest/PyJWT; installation could not proceed because package index/network name resolution was unavailable.
- Therefore no pytest test count is claimed, and the new tests have not been executed. Full functional, integration, and security verification remains incomplete.

## Release blockers / unresolved requirements

This archive is **not production-ready for the full requested scope**. The following are not implemented in this remediation and must not be assumed present:

1. JWT issuance/verification, refresh/revocation, secure credential transport, token-type/audience/issuer validation, and authenticated API dependencies.
2. JWT issuance/verification is not implemented. Restoration currently uses a 30-day opaque bearer guest credential; the widget stores it in `localStorage`, which is accessible to same-origin JavaScript and therefore remains less protective than a compatible HttpOnly-cookie design. Evaluate XSS risk and Shopify third-party-cookie constraints before production hardening.
3. Persistent PostgreSQL storage, schema/migrations, transactional diagnosis history/answers, retention/deletion workflows, and production-safe storage abstraction. Customer profiles still use JSON, which may be ephemeral on Render.
4. `GET /api/customer/me`, history list/detail APIs, and history UI.
5. Shared durable sessions for multi-worker deployments, registration/session/recovery rate limits, and robust idempotency keys. Customer JSON remains local/ephemeral on Render; restoration works only while the profile JSON file persists.
6. Full CSRF/origin analysis for a selected credential transport, production CORS verification, dependency vulnerability scan, XSS/API dynamic testing, and Render/Shopify live deployment verification.
7. End-to-end verification of all diagnostic and clinical safety requirements. Existing tests are present but could not be collected in this environment due missing dependencies.

## Deployment notes

- The current patch enables profile restoration using an expiring opaque bearer guest credential, not JWT. For production, migrate JSON profiles to durable storage and consider HttpOnly cookies or a short-lived access token plus secure renewal. Never reintroduce customer-ID-only recovery.
- Do not use JSON on Render as production persistence. Configure PostgreSQL (or another durable supported store) and migrate records before relying on history.
- Keep `ALLOWED_ORIGINS` restricted to exact Shopify storefront origins. Do not use `*` with credentialed CORS.
- Keep `GROQ_API_KEY` and `GUTGPT_ADMIN_TOKEN` in Render environment variables; never commit actual values.
- Deploy backend/widget changes together. After this first deployment, customers who registered under the earlier disabled-restore build may need to register once to receive a guest credential; old records without a stored credential hash cannot be securely claimed based only on their customer ID. Once a token is issued and retained by the browser, normal refresh/reopen should restore the profile without re-registration until expiry.

## Architecture preserved

The existing deterministic diagnostic pipeline was not redesigned: user message → NLU extraction → contextual question resolver → state update → question/rule engine → diagnosis/recommendation. No diagnosis/product mappings were intentionally changed.

## JWT guest-session update (2026-10-15)

- Replaced newly issued opaque guest credentials with HS256 JWTs that expire exactly 30 days after issuance.
- JWT verification pins the algorithm and validates signature, issuer, audience, `exp`, `iat`, `nbf`, `sub`, `jti`, and the `typ=guest_access` token type.
- A SHA-256 hash of the unique JWT `jti` is stored in the customer JSON record. Restoration checks both the customer subject and JTI hash, so rotating the token revokes the old token.
- Added required `JWT_SECRET_KEY` startup validation (minimum 32 UTF-8 bytes), plus configurable issuer/audience variables. No signing secret is hardcoded.
- Existing unexpired opaque credentials from the immediately prior release are upgraded once to JWT during restore, avoiding unnecessary re-registration where the legacy token and JSON record still exist.
- Widget persists a returned upgraded token. PyJWT dependency and test coverage were added.
- Browser storage remains `localStorage`; JWT does not itself prevent XSS. Full PostgreSQL persistence, broader rate limiting, secure history APIs, and live Render/Shopify verification remain outside this patch.
