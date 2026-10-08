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

The widget stores only its generated session ID in browser `localStorage`.
No API keys or LLM secrets are sent to the browser.

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

- `GROQ_API_KEY` — required for multilingual input/output translation.
- `ALLOWED_ORIGINS` — comma-separated exact Shopify storefront origins. Do not leave this empty in production.
- `SESSION_TTL_SECONDS` — optional session expiry, default `3600`.
- `MAX_SESSIONS` — optional in-memory session cap, default `10000`.
- `PORT` — optional server port, default `8000`.

The production app fails startup if `GROQ_API_KEY` or `ALLOWED_ORIGINS` is missing.
Language input is restricted to the supported Indian-language codes, and translation failures are returned as a controlled `503` rather than silently returning an English diagnosis.

Session state is bounded by TTL and maximum-session limits. The production deployment should remain single-worker unless session state is moved to a shared store such as Redis.
