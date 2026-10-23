# GutGPT v18.3 — Frontend-to-Widget Migration Audit (Incremental)

## Scope and safety

Audited the uploaded `Code_Base.zip` in an isolated working copy. The archive does not contain a `.git` directory, so Git status, branch creation, and existing user changes cannot be inspected from this artifact. No production endpoint was contacted, no deployment was performed, and no customer data or backup contents were printed. The original uploaded ZIP remains unchanged.

## Code inventory

- Backend/API: `app.py`
- Customer-facing standalone surfaces: `index.html`, `chat.html`
- Shopify embed: `gutgpt-widget.js`
- Approved Bristol chart: `Bristol Stool Chart Infographic.png`
- Deterministic diagnosis/question/safety/recommendation modules: `guttify_agent.py`, `guttify_chatbot.py`, `clinical_rule_engine.py`, `nlu_extractor.py`, `intent_parser.py`, `question_schema.py`, `symptom_questionnaire.py`, `safety_checker.py`, `recommendation_engine.py`, `product_concern_router.py`, `multilingual.py`, `language_service.py`, `support_footer.py`
- Deployment: `Dockerfile`, `docker-compose.yaml`, `.dockerignore`, `.env.example`, `requirements.txt`, `README.md`
- Regression suite: `tests/` (including registration/restoration, persistence, security, diagnosis, bleeding priority, NLU, and recommendation tests)

## Feature parity matrix

| Feature | Existing frontend implementation | Backend endpoint/module | Widget behavior in source | Migration / verification |
|---|---|---|---|---|
| Registration details and consent | `index.html` form | `POST /api/customer`, `CustomerRegistrationRequest` | Present | Verify live field validation, duplicate submissions, failure recovery |
| New session | `index.html` | `POST /api/session` | Present | Fresh session is created before restore; test live sequence |
| Returning customer | `index.html` restoration flow | `POST /api/customer/restore` | Present, cookie dependent | CHIPS cookie improvement added; verify real browser/storefront |
| JWT authentication | Cookie + legacy sessionStorage migration | `_issue_guest_jwt`, `_decode_guest_jwt`, restore route | Cookie credentials included; no new token persisted in JS storage | Preserve HttpOnly design; verify expiry and browser policy |
| Diagnostic conversation | Frontend chat renderer | `POST /api/chat`, `ConversationManager` | Present | Regression-test exact question order and session lifecycle |
| Bristol chart/types 1–7 | Marker and chart renderer in `index.html` | Backend marker; chart asset route | Embedded chart data URI and type buttons | Confirm visual parity and accessible controls on storefront |
| Diagnosis/safety messages | Frontend response renderer | Rule engine and safety modules | Present | Verify no backend rule changes and exact output handling |
| Product recommendations | Frontend product cards | Recommendation modules and chat response | Present | Test optional fields, URLs, and duplicate rendering |
| Language/multilingual | `chat.html`, `multilingual.py`, `language_service.py` | Module/API usage needs tracing | No verified equivalent selector in widget source | Resolve whether feature is active/current before removal |
| Accessibility/responsive behavior | Standalone CSS and labels | N/A | Shadow DOM responsive widget | Manual keyboard/screen-reader/mobile verification required |
| Admin dashboard/export | Admin HTML served by `app.py` and admin routes | Authenticated `/admin` and `/api/admin/*` | Not public widget functionality | Retain separately; do not remove admin APIs |
| Standalone hosting | `/` returns `index.html`; chart route serves image | `app.py` | Widget served by `/gutgpt-widget.js` | Do not remove standalone files/routes until parity and deployment tests pass |

## Restoration defect analysis

The widget creates a fresh `/api/session` before calling `/api/customer/restore`, which matches the backend requirement that `session_id` exists in in-memory session state. The backend prefers the `gutgpt_guest_token` HttpOnly cookie, with `guest_token` in the request body as a legacy migration path. The widget reads only the legacy `gutgpt_guest_token_v1` from `sessionStorage`; after registration or successful restore it clears that legacy token and relies on the HttpOnly cookie.

The likely Shopify-specific failure is browser cookie policy: the standalone frontend is first-party to the API host, while a widget loaded on Shopify makes cross-site API requests. `SameSite=None; Secure` and `credentials: "include"` do not override browser blocking of unpartitioned third-party cookies. This is a code-supported likely cause, not proof of the exact production failure; the actual storefront, browser devtools, response `Set-Cookie`, request `Cookie`, and CORS response headers still need manual verification.

## Incremental change made

- `app.py`: Added secure-request detection and CHIPS `Partitioned` cookie attribute for allowlisted, HTTPS, cross-host storefront requests. Cookie deletion receives the same partition attribute. The cookie remains `HttpOnly`, host-only, and server-authenticated; no JWT is written to JavaScript-readable storage.
- `tests/test_phase2b_security_basics.py`: Added tests for partitioning on allowlisted cross-host HTTPS requests, not partitioning first-party/untrusted requests, and matching partitioned-cookie deletion.
- `README.md`: Documented the CHIPS behavior and browser limitation.

This is a compatibility improvement, not a universal fix. CHIPS availability varies by browser and privacy settings. Existing customers whose credential exists only as an unpartitioned API-host cookie may still be unable to restore in a browser that blocks that cookie in the embedded context. Do not force a new registration or weaken token security without a deliberate migration design.

## Test execution status

- `node --check gutgpt-widget.js`: passed (JavaScript syntax check).
- `python -m py_compile app.py tests/test_phase2b_security_basics.py`: passed (Python syntax/bytecode compilation).
- `python -m pytest -q --disable-warnings --maxfail=1`: blocked during collection because `langchain_core` is missing from the execution environment.
- `python -m pip install -r requirements.txt`: could not install dependencies because package index DNS/network access is unavailable.
- No full test pass count can honestly be reported. Tests requiring imports/runtime dependencies remain unverified.

## Widget-only migration change

The user reports that the full regression suite and manual Shopify widget checks now pass. Based on that confirmation, this working copy removes the standalone customer-facing frontend while preserving the backend API, Shopify widget, admin dashboard/API, deterministic diagnosis and recommendation logic, safety checks, customer storage code, and test suite. The user-reported checks have not been independently rerun in this environment.

Changes in the widget-only package:

- Removed `index.html`, `chat.html`, and the unused standalone Bristol chart image asset.
- Removed the root route that served `index.html` and removed the frontend-only `/bristol-stool-chart.png` route.
- The root route now returns JSON service metadata; `/api/health` remains the health endpoint and `/gutgpt-widget.js` continues serving the Shopify widget.
- Updated the security regression test to assert that standalone frontend files are absent and the widget does not persist guest JWTs in JavaScript-readable storage.
- Updated README deployment guidance.

The original uploaded archive and the previous debug-fixes archive remain unchanged. No production endpoint was contacted, no deployment was performed, and no customer data was modified.

## Remaining release checks

1. Run the full regression suite against this widget-only package in the project's normal environment and confirm all tests pass after the route and artifact removals.
2. Re-run a Docker build and container smoke test, confirming `/`, `/api/health`, and `/gutgpt-widget.js` respond correctly.
3. Confirm Shopify registration, refresh, returning-customer restoration, and multi-customer isolation on the production storefront after deploying this package.
4. Confirm the production environment variables and persistent database configuration before deployment. Keep a rollback copy of the current deployed image/package.

Admin dashboard `/admin` and `/api/admin/*` are intentionally retained; this change removes only the standalone customer-facing frontend.

## Rollback

The original uploaded ZIP and the previous debug-fixes ZIP remain unchanged. Restore the previous deployed package/image if the widget-only release fails verification. No production deployment or customer-data mutation has been performed by this change.
