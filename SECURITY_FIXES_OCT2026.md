# GutGPT security and persistence hardening — October 2026

This change set addresses five requested workstreams. It preserves the existing deterministic diagnosis, safety, questionnaire, and product-rule architecture.

## 1. Admin JSON export

- Corrected the download response to append a real newline rather than the two-character sequence `\n` outside the JSON document.
- Added a regression test that parses the downloaded body with `json.loads`.

## 2. Guest JWT browser storage

- Guest tokens are now read/written from `sessionStorage`, not persistent `localStorage`.
- The previous local-storage guest-token key is cleared on frontend/widget initialization.
- This reduces persistence after a tab's browsing session ends, but **does not eliminate XSS exposure**: same-origin JavaScript can still read `sessionStorage`. Keep strict output escaping, avoid unsafe script injection, and consider an HttpOnly cookie only after validating Shopify cross-origin/third-party-cookie behavior.

## 3. Persistence and session isolation

- Customer records now persist `bound_session_ids`, allowing session/customer binding checks to recover the binding from customer storage instead of relying exclusively on the in-memory map.
- The active diagnostic conversation itself remains in memory. Startup rejects `WEB_CONCURRENCY > 1` because this build does not yet have a shared Redis/session backend. Do not scale to multiple workers until session state, registration state, and conversation history are moved to a shared store.
- JSON fallback remains suitable for local/single-worker development only. Use PostgreSQL for production persistence; the current JSON read-modify-write flow is not safe for concurrent processes.

## 4. Rate limiting and admin authentication

- Replaced random 1%-per-request PostgreSQL rate-limit cleanup with a deterministic per-worker 10-minute cleanup schedule.
- Added an overall admin API request budget (120 requests/minute/IP) in addition to the existing failed-authentication budget (10 failures/15 minutes/IP).
- JWT configuration now requires a URL-safe secret of at least 43 characters, matching the representation length of 32 random bytes from `secrets.token_urlsafe(32)`. Length/character checks cannot prove entropy; configure a randomly generated secret, never a human-created phrase.

## 5. Dependency and frontend security checks

- Added the missing `python-dotenv` runtime dependency and bounded supported major versions for application dependencies.
- `requirements.txt` is **not a fully reproducible lockfile**. Before production release, resolve the ranges in the deployment's Python 3.12 environment, commit a generated lock/constraints file, and run `pip-audit` against that exact resolved set.
- Static frontend review: user-supplied chat text is inserted with `textContent`; bot markdown is HTML-escaped before controlled formatting, and the Bristol chart marker is replaced only with a fixed embedded image/template. No use of `eval` or `document.write` was found in the reviewed frontend files. Continue regression-testing these assumptions when editing rendering code.

## Verification limits

The source bundle was edited in an isolated working directory. Python syntax compilation succeeded. Pytest collection could not complete in this environment because `langchain_core` is not installed; therefore no test pass is claimed. PostgreSQL, browser, multi-worker, and live LLM behavior still require verification in the project's configured environment.
