# GutGPT v18.3 — Security and release audit (partial remediation)

## Scope and evidence

Audited the supplied `guttify_work` archive, focusing on `app.py`, the embedded Shopify widget, customer registration/restore routes, and existing pytest tests. The archive contains the deterministic diagnosis engine and existing regression tests. No production logs, Render credentials, database credentials, or live Shopify environment were supplied.

## Changes made

- Disabled `POST /api/customer/restore` because it previously restored a profile using only a browser-supplied `customer_id`. That was an insecure direct-object-reference / identity-verification flaw. It now fails closed with HTTP 501 and a clear recovery-not-configured error rather than exposing a customer's profile to anyone who knows or obtains an identifier.
- Added backend contact validation that accepts a plausible email or international-style phone number without hardcoding one country's phone format; rejects control characters and obvious invalid strings.
- Removed the customer ID from registration log messages.
- Updated the widget's consent copy to clarify that no website account/password is needed and details are stored.
- Updated/added regression tests for the disabled insecure restore path and invalid contact input.

## Baseline and verification

- Runtime: Python 3.13.5.
- `python -m py_compile app.py guttify_agent.py nlu_extractor.py`: passed.
- Baseline `pytest -q`: collection failed before tests ran because `langchain_core` was not installed (`ModuleNotFoundError`).
- Attempted dependency installation from `requirements.txt` plus pytest/PyJWT; installation could not proceed because package index/network name resolution was unavailable.
- Therefore no pytest test count is claimed, and the new tests have not been executed. Full functional, integration, and security verification remains incomplete.

## Release blockers / unresolved requirements

This archive is **not production-ready for the full requested scope**. The following are not implemented in this remediation and must not be assumed present:

1. JWT issuance/verification, refresh/revocation, secure credential transport, token-type/audience/issuer validation, and authenticated API dependencies.
2. Secure returning-customer recovery. It is intentionally disabled until authentication is implemented; customer ID alone must never be treated as proof of identity.
3. Persistent PostgreSQL storage, schema/migrations, transactional diagnosis history/answers, retention/deletion workflows, and production-safe storage abstraction. Customer profiles still use JSON, which may be ephemeral on Render.
4. `GET /api/customer/me`, history list/detail APIs, and history UI.
5. Shared durable sessions for multi-worker deployments, secure session restoration across browser refresh/reopen, registration/session/recovery rate limits, and robust idempotency keys.
6. Full CSRF/origin analysis for a selected credential transport, production CORS verification, dependency vulnerability scan, XSS/API dynamic testing, and Render/Shopify live deployment verification.
7. End-to-end verification of all diagnostic and clinical safety requirements. Existing tests are present but could not be collected in this environment due missing dependencies.

## Deployment notes

- Do not enable customer restoration until a signed, expiring, revocable guest credential is issued by the backend and all profile/history endpoints enforce ownership from that credential.
- Do not use JSON on Render as production persistence. Configure PostgreSQL (or another durable supported store) and migrate records before relying on history.
- Keep `ALLOWED_ORIGINS` restricted to exact Shopify storefront origins. Do not use `*` with credentialed CORS.
- Keep `GROQ_API_KEY` and `GUTGPT_ADMIN_TOKEN` in Render environment variables; never commit actual values.
- Deploy backend/widget changes together. The disabled restore route is a deliberate behavior change for any client that called it; the currently supplied widget does not call that route.

## Architecture preserved

The existing deterministic diagnostic pipeline was not redesigned: user message → NLU extraction → contextual question resolver → state update → question/rule engine → diagnosis/recommendation. No diagnosis/product mappings were intentionally changed.
