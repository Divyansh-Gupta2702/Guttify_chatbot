# GutGPT Backend + Embeddable Shopify Widget

GutGPT is now a backend-only FastAPI application plus one embeddable JavaScript
widget. The existing diagnosis, recommendation, safety-checking, product data,
LLM, and conversation logic remain in the Python modules.

## Architecture

Shopify website → `gutgpt-widget.js` → AWS FastAPI → GutGPT logic → LLM/product data

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

- `http://localhost:8000/` → `GutGPT chatbot backend is running.`
- `http://localhost:8000/gutgpt-widget.js` → widget JavaScript

For a separate local test page, load:

```html
<script src="http://localhost:8000/gutgpt-widget.js"></script>
```

Set `ALLOWED_ORIGINS` to the origin serving that test page when it is hosted
separately.

## AWS

Run the same FastAPI application on the AWS server:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

If the AWS runtime supplies `PORT`, the application also supports that
environment variable.

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

The widget stores a signed JWT guest credential in browser `localStorage`. The
JWT expires after 30 days and is validated server-side for signature, issuer,
audience, expiry, token type, and revocation. No API keys or LLM secrets are
sent to the browser. The credential is a bearer secret, so protect the widget
against XSS and do not log or share it.

The backend keeps the existing in-memory conversation state. Therefore use a
single Uvicorn worker unless session state is moved to a shared store such as
Redis.

## Secrets

Never put `GROQ_API_KEY` or any other provider credential into
`gutgpt-widget.js`. Secrets belong only in the AWS server environment.

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
- `JWT_SECRET_KEY` — required; a unique random secret of at least 32 UTF-8 bytes.
- `JWT_ISSUER` — defaults to `gutgpt-api`.
- `JWT_AUDIENCE` — defaults to `gutgpt-guest-session`.
- `ALLOWED_ORIGINS` — comma-separated exact Shopify storefront origins. Do not leave this empty in production.
- `SESSION_TTL_SECONDS` — optional session expiry, default `3600`.
- `MAX_SESSIONS` — optional in-memory session cap, default `10000`.
- `PORT` — optional server port, default `8000`.

The production app fails startup if `GROQ_API_KEY` or `ALLOWED_ORIGINS` is missing.
Language input is restricted to the supported Indian-language codes, and translation failures are returned as a controlled `503` rather than silently returning an English diagnosis.

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


## Customer registration and JSON storage (v18.3)

- The Shopify widget asks for the customer's name, age, contact number or email, and city before enabling the assessment chat.
- The customer must tick the consent checkbox before submission.
- The backend saves each registration to `customer_data.json` in the application directory. The file is initialized as an empty JSON array and is excluded from Git by `.gitignore` because it contains personal information.
- The `/api/chat` endpoint rejects messages for sessions that have not completed registration.
- Registration retries for the same session are idempotent and do not create duplicate records.

**Storage limitation:** JSON-file storage is intended for this requested initial version. On hosting platforms with an ephemeral filesystem (including typical Render deployments without a persistent disk), records can be lost on redeploy/restart. It is also not suitable for multiple backend workers sharing one file. Use a persistent disk or a database before relying on this for production customer records. Restrict access to the file and follow the applicable privacy/data-retention requirements.


## Testing customer records on Render (admin-only)

For temporary testing, set a strong random `GUTGPT_ADMIN_TOKEN` in the Render service's Environment settings, then redeploy. Do not commit the token to Git or put it in the Shopify widget.

Browser dashboard:
- Open `https://YOUR-SERVICE.onrender.com/admin` after deployment. Enter the `GUTGPT_ADMIN_TOKEN` value to view customer records in a table, refresh the list, or download the JSON file. The token is sent in an Authorization header and is not placed in the URL.

Authenticated endpoints:
- `GET /api/admin/customers` — returns a JSON list and count.
- `GET /api/admin/customers/download` — downloads `customer_data.json`.

Send the token only in the HTTP `Authorization` header as `Bearer YOUR_TOKEN`. Do not append it to the URL. Example from a trusted terminal:

```bash
curl -H "Authorization: Bearer $GUTGPT_ADMIN_TOKEN" https://YOUR-SERVICE.onrender.com/api/admin/customers
curl -L -H "Authorization: Bearer $GUTGPT_ADMIN_TOKEN" https://YOUR-SERVICE.onrender.com/api/admin/customers/download -o customer_data.json
```

These endpoints are disabled with HTTP 503 until `GUTGPT_ADMIN_TOKEN` is configured, and reject requests without a valid token. The JSON file is stored on the service filesystem; on Render Free that filesystem is ephemeral, so records can disappear after restarts/redeploys. Use dummy data for testing and never expose these endpoints without authentication.

## Passwordless guest JWT sessions (30-day expiry)

After successful registration, the backend issues a signed HS256 guest-access JWT with a 30-day lifetime. Claims include `sub` (backend-generated customer ID), `typ=guest_access`, `iss`, `aud`, `iat`, `nbf`, `exp`, and a unique `jti`. The backend stores only a hash of the JTI for revocation and checks that hash against the customer record during restoration. A customer ID by itself is never accepted as proof of identity.

Required Render environment variables:

- `JWT_SECRET_KEY`: a unique, cryptographically random secret of at least 32 UTF-8 bytes. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Store it only in Render environment settings; do not commit it.
- `JWT_ISSUER`: normally `gutgpt-api`.
- `JWT_AUDIENCE`: normally `gutgpt-guest-session`.
- Keep `ALLOWED_ORIGINS` set to the exact Shopify storefront origin(s), without a wildcard.

`PyJWT` is installed through `requirements.txt`. Startup fails closed if `JWT_SECRET_KEY` is absent or shorter than 32 bytes. Changing the secret invalidates existing JWT sessions, so rotate it only with a planned re-registration/recovery path. The browser currently stores the credential in `localStorage`; this is compatible with the cross-origin widget but is exposed to successful same-origin script injection. Protect the widget against XSS and consider a carefully configured HttpOnly cookie/CSRF design in a future hardening pass.

For a smooth upgrade, the restore endpoint supports an unexpired legacy opaque token already stored by the prior release exactly once, then returns and persists a new JWT. The widget replaces the legacy token with the JWT. Legacy tokens that have expired or whose JSON records were lost cannot be upgraded and require registration again. The JWT expires 30 days after issue; this is not a sliding expiration.

## Assessment summary fields (temporary JSON mode)

When the deterministic flow completes an assessment, GutGPT updates two fields on the matching customer record in `customer_data.json`: `likely_assessment` (the likely assessment value from screening) and `final_symptom_summary` (the final summary of symptoms). It also records `assessment_updated_at`. There is no separate assessment table or `assessment_data.json` file. Intermediate questions do not overwrite these fields.

- Default file: `customer_data.json` beside `app.py`; optionally set `CUSTOMER_DATA_FILE` to another path.
- Admin dashboard: open `/admin`, enter `GUTGPT_ADMIN_TOKEN`, and view customer registration details and the two assessment fields in one table.
- Authenticated endpoints: `GET /api/admin/customers` and `GET /api/admin/customers/download`.
- Customer JSON download includes both assessment summary fields.
- The file contains personal and health-related information. Restrict access, do not commit real data, and follow applicable privacy and retention requirements.

**Temporary-storage warning:** This version intentionally uses JSON files and ignores `DATABASE_URL`. On Render Free, local files may disappear after restarts, redeploys, or instance replacement, and separate instances do not share files. Use dummy data for testing only. For reliable production storage, move to a persistent disk or managed database.

See `JSON_TEMPORARY_STORAGE.md` for deployment setup and limitations. The diagnosis engine, NLU, question flow, safety checks, and recommendation rules have not been changed.
