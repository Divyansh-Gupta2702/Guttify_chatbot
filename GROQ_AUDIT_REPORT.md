# GutGPT v18.3 Groq audit and implementation report

## Scope inspected

Inspected the supplied archive's `app.py`, `nlu_extractor.py`, `multilingual.py`, `guttify_chatbot.py`, `guttify_agent.py`, existing test files, requirements, Dockerfile, Compose configuration, and widget JavaScript. No diagnosis, recommendation, question-schema, authentication, PostgreSQL persistence, or session-ownership rules were intentionally changed.

## Groq call paths found in the supplied source

| Location | Trigger | Original possible calls | Change in this build |
|---|---|---:|---|
| `nlu_extractor.py::_llm_extract` | Deterministic extraction and active-question resolution do not resolve the input and `_needs_llm(...)` permits model use | 1 attempt, potentially SDK-managed retry depending on defaults | Uses central gateway; explicit 12-second timeout, 500 output-token default, `max_retries=0` |
| `multilingual.py::translate_to_english` | Non-English/Hinglish input is not covered by the exact short-answer map | 1 | Uses central gateway; no retry in gateway |
| `multilingual.py::translate_from_english` | Non-English response needs rendering | Previously up to 2 | Uses central gateway; removed the second translation/repair call; controlled `TranslationUnavailableError` remains |
| `guttify_chatbot.py` legacy response generation | Direct invocation of legacy response/product-generation helpers | Up to 1 per invoked helper | Both invocation sites use central gateway; client configured for timeout and zero retries. The current `/api/chat` route uses deterministic response formatting for its listed statuses, so these are not normally part of that route's successful response path. |
| `app.py::chat` | Incoming widget message | Can combine input translation + unresolved NLU + output translation for a non-English message | No model call is added to the deterministic response formatting path. Existing DB-backed HTTP request limits remain. |

### Root causes of avoidable usage

1. Output translation made a second Groq request whenever the first translation looked unchanged or unusable. That is now removed; translation failure returns the existing controlled error instead of trying again.
2. NLU, input translation, output translation, and legacy response helpers had separate direct `.invoke()` sites, so there was no single place for common telemetry and concurrency protection. All discovered application `.invoke()` calls now route through `groq_service.invoke_groq`.
3. NLU client configuration did not explicitly set a timeout or `max_retries=0`; it now does.
4. Translation's default output-token ceiling was 1200, high for translation of short widget responses; it is now 500 and configurable.
5. There is still a multi-call path for some non-English incoming messages (input translation + possible NLU + output translation). This build does **not** claim the requested hard maximum of one Groq call for the entire HTTP message has been achieved. Enforcing that globally without breaking language behavior needs a product decision about which stage gets the sole call, or a deterministic/local translation strategy for supported languages.

## Existing protections observed

- `nlu_extractor.py::extract_natural_facts` already performs deterministic context resolution first and returns early when the active question is answered/unknown.
- NLU code handles empty/malformed model output by returning fallback data rather than re-asking the model for JSON repair.
- `app.py` has HTTP request rate limits for chat session and client IP, using its existing enforcement path.
- The route uses deterministic screening/product response formatting for the listed result statuses.
- The provided source already has a PostgreSQL-oriented persistence design and customer/session validation; this patch does not modify storage or migrations.

## New shared gateway behavior

`groq_service.py` provides a single application invocation boundary, bounded per-worker concurrent calls, a short bounded wait for a free slot, structured latency/token/error-category logs, and no gateway retries. It never logs prompt content. Token counts are emitted only when the provider response exposes them.

## Limits and items not completed

- The local semaphore is per Python worker. It is not a shared multi-worker quota and must not be mistaken for a distributed limiter.
- The archive's current database-backed HTTP rate limiting is not equivalent to shared Groq RPM/TPM reservations. A shared PostgreSQL/Redis token bucket, shared cooldown, retry budget, and circuit breaker are not implemented in this patch.
- The strict global one-call-per-message budget and idempotency keyed to a stable widget message ID are not implemented here. The supplied chat request schema/widget lifecycle must be changed and regression-tested together before safely claiming this acceptance criterion.
- The configured model name is left unchanged (`openai/gpt-oss-20b` in the inspected modules). Account-specific RPM/TPM/RPD limits cannot be read from source code and were not verifiable from the supplied files. Confirm them in the Groq console before selecting production thresholds.
- Before/after actual token or 429 rates cannot be measured offline without production telemetry or authorized provider access. The gateway logs can begin capturing latency and token counts when the provider returns usage metadata.
- No production deployment, Shopify live test, or production database operation was performed.

## Tests run

- `python -m compileall -q app.py nlu_extractor.py multilingual.py guttify_chatbot.py groq_service.py`: passed.
- `python -m pytest -q tests/test_groq_service.py`: 3 passed.
- Full `python -m pytest -q --disable-warnings --maxfail=1`: blocked during collection because the environment does not have `langchain_core` installed (`ModuleNotFoundError`). No existing tests were deleted. Install `requirements.txt` in the target virtual environment and rerun the full suite.
