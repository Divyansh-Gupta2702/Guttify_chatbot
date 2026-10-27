# GutGPT v18.3 Groq optimization — Phase 2 implementation report

## Implemented in this iteration

- Enforced a request-scoped `GROQ_MAX_CALLS_PER_MESSAGE` budget (default 2: one input and one output translation) across the shared invocation boundary, including translation, NLU, and legacy model helpers.
- Added a circuit breaker with configurable failure threshold and cooldown. The local breaker protects each worker; a shared PostgreSQL cooldown is also applied when an HTTP 429 is observed.
- Added PostgreSQL-backed shared request-per-minute, estimated-token-per-minute, and active-request lease reservations. Reservations use a PostgreSQL advisory transaction lock, and provider calls happen after the reservation transaction closes. If the shared limiter/database is unavailable, calls fail closed rather than becoming unlimited.
- Added bounded lease expiry so a crashed worker does not hold a concurrency slot forever.
- Added Shopify widget `message_id` generation and backend PostgreSQL idempotency records scoped to the session. Completed duplicate messages return the stored response; concurrent duplicates receive HTTP 409 with Retry-After; stale/failed reservations can be retried.
- Added tests for message budget enforcement and isolation.

## Important behavior and limitations

- The one-call budget is strict. A non-English turn that needs both input translation and output translation cannot complete both through Groq under a one-call budget. The implementation intentionally fails safely rather than making a second call; fully preserving multilingual quality under this constraint requires consolidating translation/NLU or adding deterministic translations for the supported output templates. This is an architectural constraint, not a provider bug.
- PostgreSQL shared RPM/TPM/concurrency limits are estimates and must be configured against the actual Groq model/account limits. TPM reservation uses prompt-length estimation plus a configurable output-token reserve, and it is conservative for the remainder of the minute. It does not claim exact provider token accounting.
- The local circuit breaker is process-local. A shared cooldown is stored in PostgreSQL for 429 responses, but non-429 breaker failures are not yet aggregated into a distributed circuit state.
- Widget message IDs deduplicate requests from the current widget implementation. Other API clients must also send a stable `message_id` to benefit from idempotency.
- The existing API rate limiter and customer/session ownership checks are unchanged. No diagnosis, safety, recommendation, or database business schema was intentionally modified.

## Validation performed in this environment

- `python -m py_compile app.py groq_service.py multilingual.py nlu_extractor.py guttify_chatbot.py`: passed.
- `python -m pytest -q tests/test_groq_service.py`: 5 passed.
- `python -m pytest -q`: collection blocked by missing `langchain_core` in this execution environment. Install `requirements.txt` in the project environment and rerun; this is not evidence that the full suite passes or fails.
- No live PostgreSQL concurrency test, multi-worker load test, Groq account-limit verification, live deployment, or Shopify browser test was run here.

## Required production configuration

Set `GROQ_SHARED_LIMITER_ENABLED=true`, use the same PostgreSQL `DATABASE_URL` for all workers, and tune `GROQ_SHARED_RPM_LIMIT`, `GROQ_SHARED_TPM_LIMIT`, and `GROQ_SHARED_MAX_CONCURRENT` based on the lowest applicable Groq account/model limit with headroom. The tables are created additively on first use; no existing customer or assessment data is dropped or migrated.

## Windows PowerShell validation commands

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m py_compile app.py groq_service.py multilingual.py nlu_extractor.py guttify_chatbot.py
python -m pytest -q tests/test_groq_service.py
python -m pytest -q
```

Before production, take a PostgreSQL backup and keep the previous application release. Roll back by redeploying the previous application code/configuration only; do not restore an older database backup over newer customer data unless a separately reviewed recovery decision explicitly requires it.
