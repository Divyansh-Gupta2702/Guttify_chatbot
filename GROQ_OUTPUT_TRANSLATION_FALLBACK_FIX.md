# GutGPT v18.3 — Groq budget / output translation fallback fix

## Problem observed
Logs showed deterministic assessment state updates completing, followed by output translation being rejected because the request had already consumed its one-call Groq budget. `app.py` then raised HTTP 503 before appending history and persisting the assessment checkpoint. This could cause the widget to retry a turn whose in-memory state had already changed.

## Change
- `app.py`: output translation failure no longer raises HTTP 503 after the rule engine has processed a message. It emits a localized temporary-translation notice followed by the exact original rule-engine response. The normal history and checkpoint persistence path can continue.
- `tests/test_groq_output_fallback.py`: tests that the fallback keeps the original question/safety text unchanged and adds the correct localized notice.

## Safety properties
- Does not change diagnosis or recommendation rules.
- Does not infer or modify clinical facts.
- Does not issue another Groq call.
- Preserves the exact English rule-engine response when translation is unavailable, including safety instructions.
- Avoids converting a translation-only failure into a 503 after state mutation.

## Verification in this environment
- `python -m py_compile app.py multilingual.py groq_service.py tests/test_groq_output_fallback.py`: passed.
- `python -m pytest -q tests/test_groq_output_fallback.py tests/test_groq_service.py`: 8 passed.
- Full regression suite was not rerun here because this execution environment lacks `langchain_core` / `langchain_groq` dependencies. User reported the full suite had passed previously, but this specific patch should be tested in their normal project environment.

## Suggested test commands (PowerShell)
```powershell
python -m py_compile app.py multilingual.py groq_service.py tests/test_groq_output_fallback.py
python -m pytest -q tests/test_groq_output_fallback.py tests/test_groq_service.py
python -m pytest -q
```

## Expected behavior
When input translation uses the single allowed model call and output translation is blocked by the budget, `/api/chat` should still return a normal chat response containing a Hinglish notice and the exact English rule-engine question/reply, and continue through normal history/checkpoint persistence. It should not return HTTP 503 solely because output translation was blocked.
