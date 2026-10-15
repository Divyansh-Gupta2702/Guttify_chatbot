# Guest-session restoration diagnostics patch

Version: `18.3-jwt-guest-30d-diag`

## What changed

- Logs the JWT validation exception class (for example `ExpiredSignatureError`, `InvalidAudienceError`, or `InvalidSignatureError`) without logging the JWT or any customer claims/contact information.
- Logs a generic reason category when a cryptographically valid JWT does not match the stored customer credential, when a legacy credential is not found, or when the stored token expiry has passed.
- Stops a malformed/invalid JWT-shaped value from silently falling through to the legacy opaque-token path. Legacy opaque credentials without the three JWT segments retain the compatibility path.
- Keeps public error messages generic and does not change the diagnostic/question engine.

## What to do after deployment

1. Deploy this archive to the same Render backend service.
2. In Render Environment, keep `JWT_SECRET_KEY` stable and identical for every instance of this service. It must be at least 32 UTF-8 bytes. Keep `JWT_ISSUER=gutgpt-api` and `JWT_AUDIENCE=gutgpt-guest-session` unless you intentionally configure matching values before issuing tokens.
3. Clear the stale browser token once, register again, and then reload:
   `localStorage.removeItem("gutgpt_guest_token_v1"); location.reload();`
4. Inspect Render logs for `Guest JWT validation failed reason=...` or `Guest restore rejected reason=...`.

Do not share the JWT, customer JSON, contact information, or the value of `JWT_SECRET_KEY`.

## Validation performed

- Python syntax compilation of `app.py` passed.
- JavaScript syntax check of `gutgpt-widget.js` passed.
- Full backend/integration tests were not run in this environment because `langchain_core` is not installed here. Do not interpret syntax checks as proof of a live Render restoration success.
