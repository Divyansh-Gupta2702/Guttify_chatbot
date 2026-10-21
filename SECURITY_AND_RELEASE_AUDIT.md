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

## Phase 2B — initial security hardening (2026-10-21)

### Changes made in this increment

- Added strict `ALLOWED_ORIGINS` validation at startup: rejects wildcard origins, malformed/non-HTTP(S) origins, credentials/path/query/fragment, and non-local HTTP origins. HTTPS is required for non-local storefront origins.
- Added baseline response headers: `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and a restrictive `Permissions-Policy` disabling camera, microphone, and geolocation APIs.
- Added `Cache-Control: no-store` and `Pragma: no-cache` to API responses and the admin dashboard response so sensitive customer/chat data is not cached by browser or shared HTTP caches.
- Added regression tests for allowed and rejected CORS origin values.

### Verification status

- `python -m py_compile app.py guttify_agent.py nlu_extractor.py`: passed.
- Full pytest collection is currently blocked in this environment because `langchain_core` is not installed and package-index access is unavailable. Do not interpret unexecuted tests as passing.

### Still open in Phase 2B

- Shared/distributed rate limiting for session creation, registration, restore, and chat (must account for Render proxy and multi-worker deployment).
- Full route-by-route authorization and customer/session isolation audit.
- Admin secret rotation and brute-force controls.
- Dependency vulnerability scan and dynamic XSS/API testing.
- Live Render/Shopify verification and deployment configuration review.

### Superseding note on earlier partial-audit text

The earlier report above predates the Phase 2A PostgreSQL integration changes in this archive. The current `app.py` contains PostgreSQL customer/assessment persistence when `DATABASE_URL` is configured, with JSON fallback when it is not. Production must explicitly configure `DATABASE_URL` and verify the active backend; the presence of PostgreSQL code alone does not prove production is using it. The remaining database-related Phase 2B work is to verify configuration, least-privilege database credentials, access isolation, retention/deletion, and failure behavior.

### Phase 2B — route authorization follow-up (2026-10-21)

- **Session/profile binding guard:** guest restore now refuses to switch an in-memory session that is already bound to a different customer profile. This returns `409 SESSION_CUSTOMER_MISMATCH`; a fresh session can still restore a valid profile, and restoring the same profile to its existing session remains allowed.
- **Admin secret minimum:** the admin customer-list/export endpoints now fail closed with HTTP 503 unless `GUTGPT_ADMIN_TOKEN` is at least 32 UTF-8 bytes. Configure a randomly generated secret of at least 32 bytes before using the admin dashboard.
- **Regression tests added:** session/profile mismatch, unbound/same-customer restore, and weak/strong admin token behavior. These tests have been syntax-checked but are not confirmed executed because the current environment is missing `langchain_core` during test collection.

**Still open before production:** shared/distributed rate limiting for session creation, registration, restore, and chat; brute-force/rotation controls for admin access; full dependency audit; dynamic API/XSS checks; review of browser `localStorage` guest-token exposure; and live Render/Shopify verification. In-memory rate limiting is not being represented as production-grade because it would not coordinate across multiple workers/instances and proxy IP handling must be configured carefully.


### Phase 2B — rate limiting and registration isolation follow-up (2026-10-21)

- Added fixed-window rate limiting to session creation (20/10 minutes per client), registration (10/10 minutes per client and 5/10 minutes per session), guest restore (30/10 minutes per client and 10/10 minutes per session), and chat (30/minute per session and 120/minute per client).
- When `DATABASE_URL` is configured, counters are atomically updated in PostgreSQL `api_rate_limits`, so the limits are shared across workers/instances using the same database. Keys are SHA-256 hashes rather than raw client/session identifiers; stale counter rows are opportunistically removed. If PostgreSQL rate-limit storage fails, requests fail closed with a service error.
- When `DATABASE_URL` is not configured, a bounded in-process limiter is used for local development only. It does **not** coordinate across workers or instances and must not be described as distributed protection.
- Rate limits use the ASGI peer address and intentionally do not trust arbitrary `X-Forwarded-For` headers. A reverse-proxy deployment must ensure the ASGI peer address is correctly configured/understood; otherwise per-client limits may be too broad. No live Render/Shopify checks were performed in this increment.
- Admin brute-force protection now counts failed token attempts only (10 failures per 15 minutes per client), so normal successful admin refreshes do not consume the failure budget.
- Registration now rejects a request that would rebind an already customer-bound session to a different/new profile (`409 SESSION_CUSTOMER_MISMATCH`).
- Added unit-test cases for rate-limit rejection and registration binding checks. Syntax compilation passed; pytest still cannot collect in this environment because `langchain_core` is missing. No tests are claimed as passing.

### Remaining Phase 2B work (excluding live deployment verification)

- Review browser `localStorage` guest-token exposure and evaluate practical XSS defenses for the Shopify-embedded deployment.
- Run a dependency vulnerability scan and dynamic API/XSS/security regression tests in an environment with the project's dependencies installed.
- Review database permissions, retention/deletion, and rate-limit table maintenance policies. Configure `DATABASE_URL` to use shared PostgreSQL rate limiting; do not rely on the process-local fallback for multi-worker production.
- Rotate the admin secret using a securely generated value (at least 32 UTF-8 bytes) and keep it only in deployment secrets/environment configuration.

### Phase 2B — unit-test direct-call compatibility fix (2026-10-21)

- Made the `request` parameter optional at the Python-call level for `new_session` and `register_customer`, while keeping the `Request` annotation so FastAPI injects the request for actual HTTP calls.
- Rate limiting still runs for HTTP requests. Direct Python calls used by legacy unit tests may omit `request`; they are not network requests and skip the HTTP request-based limiter.
- This addresses test failures caused by direct calls raising `TypeError` before assertions could run. Syntax compilation passed. Targeted pytest execution is currently blocked at collection because `langchain_core` is not installed in the environment; the tests have not yet been confirmed passing.
