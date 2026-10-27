# GutGPT v18.3 — Groq test isolation fix

## What changed

Added `tests/conftest.py` with an autouse pytest fixture that resets the process-wide Groq circuit-breaker counters before and after each test. The production breaker remains shared across real requests; only test boundaries are isolated.

## Verification

Passed in this environment:

```text
python -m pytest -q tests/test_groq_service.py tests/test_nlu_production_regressions.py tests/test_v18_3_production_log_regressions.py tests/test_production_nlu_question_resolution_v19.py
55 passed in 0.26s
```

The full suite could not be collected in this environment because `langchain_core` is not installed. This is an environment/dependency issue, not a reported test assertion failure. Run the full suite in the project's virtual environment after installing `requirements.txt`.
