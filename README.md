# GutGPT Backend + Embeddable Shopify Widget

GutGPT is a backend-only FastAPI application plus one embeddable JavaScript
widget. There is no standalone customer-facing HTML frontend or frontend dev
server in this project. The existing diagnosis, recommendation, safety-checking,
product data, LLM, and conversation logic remain in the Python modules.

## Architecture

Shopify website → `gutgpt-widget.js` → FastAPI backend → GutGPT logic → LLM/product data


## Widget-only local architecture

This repository does not start a service on port `3000`. The backend runs on
port `8000` by default and serves the widget script at
`http://localhost:8000/gutgpt-widget.js`. If something is still listening on
port `3000`, it is a separately started process or an old container outside
this Compose configuration; stop that process/container separately. The backend
root route returns JSON status only and never serves a customer-facing page.

## Shopify installation

The website administrator only needs to add this script in the Shopify footer:

```html
<script src="https://api.yourdomain.com/gutgpt-widget.js"></script>
```

No HTML, CSS, or additional JavaScript is required.

The widget uses Shadow DOM so its styles and markup are isolated from the
Shopify theme.

## Local run

Set the required environment variables, then:

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Check:

- `http://localhost:8000/` → backend status JSON (not a chat UI).
- `http://localhost:8000/gutgpt-widget.js` → widget JavaScript

For a separate local test page, load:

```html
<script src="http://localhost:8000/gutgpt-widget.js"></script>
```

Set `ALLOWED_ORIGINS` to the origin serving that test page when it is hosted
separately.

## Direct Ubuntu server deployment

Run the same FastAPI application on your Ubuntu server (for example, a DigitalOcean droplet):

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

The application also supports the optional `PORT` environment variable.

Put the public API behind HTTPS, for example:

`https://api.yourdomain.com`

Then the Shopify site can use the single script tag shown above.

## CORS

Configure the production Shopify domain(s) in:

```text
ALLOWED_ORIGINS=https://www.yourshopifydomain.com,https://yourshopifydomain.com
```

Do not use `allow_origins=["*"]` for the production storefront.

## Session behavior

The API stores the signed JWT guest credential in a persistent, host-only
`HttpOnly` cookie (`gutgpt_guest_token`) with a 30-day maximum age. The JWT is
validated server-side for signature, issuer, audience, expiry, token type, and
revocation. The widget sends credentials with API requests and does not persist
newly issued guest tokens in JavaScript-readable storage. For allowlisted HTTPS
cross-host storefront requests, the backend additionally marks the cookie
`Partitioned` (CHIPS) while keeping it `HttpOnly`; this can help supported
browsers retain a storefront-partitioned credential when unpartitioned
third-party cookies are blocked. First-party requests retain a normal host-only
cookie. CHIPS is not supported uniformly by every browser/privacy setting, and
it cannot recover an old first-party cookie when that browser refuses to send it
in the embedded context. Test the actual Shopify storefront in supported
browsers before considering restoration complete. No API keys or LLM secrets
are sent to the browser. Protect the widget against XSS and do not log or share
guest credentials.

The backend keeps the existing in-memory conversation state. Therefore use a
single Uvicorn worker unless session state is moved to a shared store such as
Redis.

## Secrets

Never put `GROQ_API_KEY` or any other provider credential into
`gutgpt-widget.js`. Secrets belong only in the backend server environment.

## Files

The important runtime files are:

- `app.py` — FastAPI API and widget hosting
- `gutgpt-widget.js` — standalone Shopify widget
- `guttify_agent.py` — conversation/session/diagnosis flow
- `clinical_rule_engine.py` — clinical rules
- `recommendation_engine.py` — product matching
- `safety_checker.py` — safety checks
- `guttify_chatbot.py` — LLM response layer
- `products.json` — product data
- `.env.example` — environment variable template

## Final production configuration

The final website deployment requires these backend environment variables:

- `GROQ_API_KEY` — required by the GutGPT backend where applicable.
- `JWT_SECRET_KEY` — required; a unique URL-safe secret generated from at least 32 random bytes (43 or more characters).
- `JWT_ISSUER` — defaults to `gutgpt-api`.
- `JWT_AUDIENCE` — defaults to `gutgpt-guest-session`.
- `ALLOWED_ORIGINS` — comma-separated exact Shopify storefront origins. Do not leave this empty in production.
- `SESSION_TTL_SECONDS` — optional session expiry, default `3600`.
- `MAX_SESSIONS` — optional in-memory session cap, default `10000`.
- `PORT` — optional server port, default `8000`.
- `DATABASE_URL` — required PostgreSQL connection URL; for native PostgreSQL on Ubuntu the default port is usually `5432` (verify the actual server configuration).
- `GUTGPT_ADMIN_TOKEN` — a unique random secret of at least 32 bytes for protected admin endpoints.

The production app fails startup if required production configuration, including `GROQ_API_KEY`, `DATABASE_URL`, a valid `JWT_SECRET_KEY`, or `ALLOWED_ORIGINS`, is missing or invalid. Admin endpoints fail closed unless `GUTGPT_ADMIN_TOKEN` is configured with at least 32 bytes of random secret material. The application accepts English only; non-English input receives a fixed English notice and does not enter the clinical rule engine.

Session state is bounded by TTL and maximum-session limits. The production deployment should remain single-worker unless session state is moved to a shared store such as Redis.

## Business product-routing map (updated)

The supplied `Liver= Liver lift + Poopie.txt` mapping is reflected in the
product concern router and clinical product eligibility rules:

- Liver support: Liver Lift + Guttify Poopie
- Weight management: Apple Active + Guttify Poopie + Liver Lift
- Acidity: Acid Ease + Liver Lift
- Constipation: Guttify Poopie + Digest Boost
- Digestion concerns: Digest Boost + Liver Lift
- Bleeding piles: Guttify Poopie + Piles Pure (only after the existing safety and clinical screening permits recommendations)
- Fissure / anal swelling / burning concerns: Piles Pure + Piloease Anal Care Spray + Guttify Poopie (only after safety and clinical screening)
- Initial piles symptoms: Piles Pure
- Dark/patchy/uneven skin tone, hyperpigmentation, glow/youthfulness concerns: GloLux

These are business-defined product-routing preferences, not medical diagnoses
or proof that supplements treat a condition. Red-flag checks and the clinical
questionnaire must not be bypassed, particularly for blood in stool/rectal
bleeding. The source file also requests collecting name, age, contact details,
and city, followed by asking whether the user wants a free gut-health expert
consultation. That lead-capture/consent workflow is not implemented by this
routing change; it should be added as a separate explicit opt-in flow before
collecting or storing personal contact information.


### Customer Support Contact After Assessment

After a completed screening/diagnosis result (including a product recommendation), GutGPT appends a customer-support message with `guttify01@gmail.com` and `+91 9818693589`. The footer is not added to intermediate questions, greetings, safety-review messages, or subsequent acknowledgements.


## Customer registration and admin inspection (v18.3)

- The Shopify widget collects the customer's name, age, contact number, city, and consent before enabling assessment chat.
- Registration and assessment/checkpoint records are stored in PostgreSQL only. The backend refuses to start if `DATABASE_URL` is missing.
- Registration retries for the same session are idempotent and do not create duplicate records.
- `/api/chat` rejects sessions that have not completed registration.

Admin dashboard and authenticated endpoints:
- Open `/admin` on your configured backend and enter `GUTGPT_ADMIN_TOKEN` to inspect customer records.
- `GET /api/admin/customers` returns a JSON response containing customer records.
- `GET /api/admin/customers/download` exports records as JSON. This is an export response, not a JSON-file storage backend.

Send the admin token only in the HTTP `Authorization` header as `Bearer YOUR_TOKEN`; never append it to a URL. Customer and assessment information is sensitive. Restrict admin access and follow applicable privacy and data-retention requirements.

## Passwordless guest JWT sessions (30-day expiry)

After successful registration, the backend issues a signed HS256 guest-access JWT with a 30-day lifetime. Claims include `sub` (backend-generated customer ID), `typ=guest_access`, `iss`, `aud`, `iat`, `nbf`, `exp`, and a unique `jti`. The backend stores only a hash of the JTI for revocation and checks that hash against the customer record during restoration. A customer ID by itself is never accepted as proof of identity.

Required environment variables:

- `JWT_SECRET_KEY`: a unique, cryptographically random secret of at least 32 UTF-8 bytes. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Store it only in the hosting environment settings; do not commit it.
- `JWT_ISSUER`: normally `gutgpt-api`.
- `JWT_AUDIENCE`: normally `gutgpt-guest-session`.
- Keep `ALLOWED_ORIGINS` set to the exact Shopify storefront origin(s), without a wildcard.

`PyJWT` is installed through `requirements.txt`. Startup fails closed if `JWT_SECRET_KEY` is absent or is not a URL-safe secret of at least 43 characters. Changing the secret invalidates existing JWT sessions, so rotate it only with a planned re-registration/recovery path. HTTPS uses `Secure; SameSite=None` for the Shopify-embedded widget, and allowlisted cross-host storefront responses additionally use `Partitioned` where applicable. Local HTTP development uses `SameSite=Lax`. The widget sends credentials with API requests and uses tab-scoped storage only to migrate older tokens. Browser third-party-cookie restrictions may still affect cross-site embeds; verify registration and returning-customer restoration on the real storefront and each supported browser.

For a smooth upgrade, the restore endpoint accepts an unexpired legacy token from a prior release once, then upgrades it to a signed JWT in the HttpOnly cookie. The frontend clears the old tab-scoped token after successful restoration. Legacy tokens that have expired or whose customer records were lost cannot be upgraded and require registration again. The JWT expires 30 days after issue; this is not a sliding expiration.

## PostgreSQL-only persistence

PostgreSQL is mandatory for customer registration, customer assessment/checkpoint persistence, and shared API rate limiting. The service refuses to start if `DATABASE_URL` is missing or PostgreSQL is unavailable. Customer data is not stored in a JSON file, and the `customers` table has only these profile columns: `customer_id`, `name`, `age`, `contact`, `location`, `created_at`, `updated_at`, and `likely_assessment`. The separate `customer_chat_state` table stores registration/session bindings, consent, guest-token metadata, and other authentication/session metadata. Per-assessment chat history and resumable checkpoints are stored in `assessment_messages` and `assessment_state`, linked directly to `customer_assessments`, which is the single canonical assessment and lifecycle table. `customer_chat_state.active_assessment_id` identifies the customer’s currently resumable assessment; the browser session ID is not modeled in a redundant binding table. On startup, legacy `record_json` data is migrated before that column and other legacy columns are removed from `customers`.

For Docker Compose, set a strong `POSTGRES_PASSWORD` in `.env`. The Compose configuration supplies the backend with the internal PostgreSQL service URL and persists database files in the named `gutgpt_postgres_data` volume. Do not delete that volume when rebuilding or updating the backend: it may contain customer and assessment records. Back up the database before schema or deployment changes.

Admin download endpoints may still return JSON as an export format; that is an API response, not a JSON storage backend. The product catalog file (for example `products.json`) is static application content and is not customer-record storage.

The database tables are separated by purpose:

- `customers`: `customer_id`, `name`, `age`, `contact`, `location`, `created_at`, `updated_at`, `likely_assessment` only.
- `customer_chat_state`: customer/session binding, consent, guest-token hash/expiry, bound session IDs, last session, and other session metadata. Legacy `active_checkpoint` and `chat_history` columns are retained for compatibility but are cleared after normalized persistence.
- `customer_assessments`: one row per assessment, including ownership, lifecycle status, timestamps, and the completed assessment label when available.
- `assessment_messages`: individual user/assistant messages ordered by sequence number and grouped by assessment.
- `assessment_state`: the latest serialized rule-engine/session checkpoint for each assessment.
- `customer_assessments`: compatibility summary for completed assessment outcomes.
- `api_rate_limits`: shared rate-limit counters.

The startup migration is designed to copy old `record_json` profile/session/checkpoint fields and embedded assessment history into the dedicated tables before dropping the legacy column. Back up your PostgreSQL database before deploying the schema migration, and verify a returning customer's restore flow after startup.

The diagnosis engine, NLU, question flow, safety checks, and recommendation rules are unchanged by the PostgreSQL-only storage configuration.

See `CUSTOMER_CHAT_STATE_MIGRATION.md` for the final schema and migration behavior.
