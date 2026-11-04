# GutGPT v18.4.1 — Provider and safety-scope hardening

This is a targeted patch on top of `18.4-conversation-intelligence`.

## Changes

1. **Groq GPT-OSS JSON-mode compatibility**
   - NLU requests using `openai/gpt-oss-*` now set `reasoning_format="hidden"` alongside JSON Object Mode.
   - The parameter is model-specific and is not sent to other Groq models.
   - Existing prompt instructions, JSON parsing, field validation, deterministic fallback, call budgets, and circuit breaker remain unchanged.

2. **Safe provider error diagnostics**
   - Provider failures now log sanitized API error code, type, parameter, and a bounded message.
   - Bearer credentials, Groq API keys, Google API keys, and JWT-like strings are redacted.
   - Prompts, user messages, model outputs, and credentials are not logged.
   - No automatic retries were added.

3. **Safety-review scope correction**
   - `unanswered_safety_question` is now explicitly marked as assessment-scoped.
   - Persistent pregnancy/lactation product restrictions remain customer-scoped.
   - Confirmed urgent red flags remain assessment-scoped.
   - This corrects the misleading `scope=customer` log for an unanswered assessment safety question; it does not weaken or remove any safety restriction.

4. **Guest restore diagnostics**
   - Restore failures now identify whether the request-body credential or HttpOnly cookie was rejected, using source labels only.
   - No token, cookie, JWT, or credential value is logged.
   - JWT validation, customer-record matching, expiry checks, and session/customer binding are unchanged.

5. **Version**
   - Version updated to `18.4.1-provider-safety-hardening`.

## Validation

- Python syntax compilation: passed for all 73 Python files in the patched archive (including the new regression test).
- Focused regression run: 45 passed.
- Two tests could not execute in this audit environment because optional runtime packages are absent: `langchain_core` and `langchain_groq`. These are environment/dependency limitations, not test assertion failures.
- No live Groq API request was made. Deploy to staging first and verify that the new structured error fields no longer show HTTP 400 for GPT-OSS NLU requests.

## Explicitly unchanged

- Clinical diagnosis and rule engine
- Questionnaire flow and question schema
- Safety decision rules
- Product eligibility and recommendation rules
- PostgreSQL-only customer and assessment persistence
- Guest JWT validation and session/customer binding
- Provider budgets, concurrency controls, and no-hidden-retry behavior
