# GutGPT v18.3 — Groq Translation Budget and Customer Restore Fix

## Changes

1. **Language-aware Groq budget**
   - Non-English/Hinglish chat turns are allowed up to the two calls needed for input and output translation, even if an older deployment still sets `GROQ_MAX_CALLS_PER_MESSAGE=1`.
   - English turns continue to honor the configured cap (minimum one).
   - Larger configured caps are preserved.
   - The existing shared PostgreSQL RPM/TPM/concurrency limiter and circuit breaker remain in place. This does not remove the global rate controls.

2. **Customer restore token fallback**
   - Restore validates both a supplied request-body token and the HttpOnly cookie when both are present.
   - If one token is stale, malformed, revoked, or does not match a stored customer record, the other candidate can still be validated.
   - Tokens are still verified and matched against persisted customer identity/JTI hashes; no authentication check is bypassed.
   - Session-to-customer binding, expiry checks, and legacy-token upgrade behavior remain in place.

3. **Regression coverage**
   - Added tests for the two-call translation round trip and bounded third-call rejection.
   - Added a customer restore regression test for a stale body token with a valid cookie.

## Verification

- `py_compile` passed for modified Python modules and tests.
- `tests/test_groq_service.py` and `tests/test_groq_output_fallback.py`: 10 passed.
- The customer-restore test could not be executed in the current build environment because `langchain_core` is not installed. Run the full test suite in the project's normal environment before deployment.

## Deployment notes

- No database schema or production data was changed.
- Keep `GROQ_SHARED_LIMITER_ENABLED=true` and configure shared RPM/TPM/concurrency values according to the actual Groq account limits.
- Deploy the updated source and run the complete regression suite before promoting to production.
