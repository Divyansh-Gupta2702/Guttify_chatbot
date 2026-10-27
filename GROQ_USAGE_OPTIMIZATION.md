# GutGPT v18.3 Groq usage optimization notes

## Changes in this build

- Added `groq_service.py` as the shared invocation/telemetry boundary for the Groq calls found in the supplied Python modules. It records reason, latency, known token usage, status category, and zero gateway retries without logging prompts or secrets.
- NLU model initialization now has explicit timeout, configurable output-token ceiling, and `max_retries=0`. Existing deterministic-first question resolution remains before NLU model use.
- Translation calls now use the shared boundary, have a lower default output-token ceiling, and no longer retry a failed/invalid output with a second translation prompt. Existing controlled translation-unavailable handling remains.
- Legacy `guttify_chatbot.py` invocation sites also use the shared boundary, so they are observable if invoked.

## Environment variables

- `GROQ_NLU_MODEL` (existing model selection; unchanged)
- `GROQ_TRANSLATION_MODEL` (existing model selection; unchanged)
- `GROQ_NLU_MAX_TOKENS=500`
- `GROQ_NLU_TIMEOUT_SECONDS=12`
- `GROQ_TRANSLATION_MAX_TOKENS=500`
- `GROQ_TRANSLATION_TIMEOUT_SECONDS=25` (existing default)
- `GROQ_TRANSLATION_MAX_RETRIES=0` (existing default; gateway itself never retries)
- `GROQ_RESPONSE_TIMEOUT_SECONDS=12`
- `GROQ_MAX_CONCURRENT_PER_WORKER=4`
- `GROQ_QUEUE_TIMEOUT_SECONDS=1.0`

Values are conservative starting points, not claims about the account's actual Groq limits. Check the configured model and account-level RPM/TPM/RPD in the Groq console before choosing production thresholds.

## Important limitations

The provided gateway's semaphore is **per Python worker**, not a shared distributed token/request limiter. The existing app has database-backed HTTP rate limiting, but this archive does not include a shared Groq token reservation/cooldown/circuit-breaker implementation. Those require a carefully tested shared PostgreSQL/Redis coordination design and should not be represented as complete by this patch. Also, the complete one-Groq-call budget across an entire chat request is not yet guaranteed: non-English messages can require input translation and output translation, and an unresolved NLU path may also use Groq. The changes here remove the obvious translation repair retry and expose the remaining call paths rather than silently claiming the strict global budget is achieved.

## Run tests

From the extracted project directory, in PowerShell:

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
```

No production database migration is included. Keep a source backup and a database backup before deployment.
