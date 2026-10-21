# GutGPT Phase 2A – targeted bug fixes

## Changes made

1. **Summary confirmation no longer invokes NLU/Groq.** A confirmed summary is treated as a deterministic control action. The existing deterministic assessment pipeline and question-completeness checks still run afterward.
2. **Asked is no longer treated as answered.** `asked_fields` is historical metadata only. A required field that remains unanswered can be asked again even if its ID is already in `asked_fields`. Explicitly accepted unknown answers remain tracked separately.
3. **Bleeding assessment cannot skip a missing discriminator solely because it was asked before.** In particular, bright-red blood with no `blood_location` answer keeps `blood_location` pending.
4. **Assessment persistence has a final guard.** It will not write an assessment if the session is still awaiting summary confirmation, the diagnosis is not marked complete, or the questionnaire still has a pending required question.
5. **Regression tests added/updated** for no-NLU summary confirmation, re-asking missing blood location, and preventing bleeding completion while that discriminator is missing. The summary test fixture now represents previously asked but unanswered fields as explicitly accepted unknowns.

## Validation

- `python -m compileall -q .`: passed.
- Focused regression tests: `50 passed` across `test_v18_3_production_log_regressions.py`, `test_bleeding_priority_v20.py`, and `test_phase1_symptom_summary.py`.
- The assessment persistence test module could not be collected in this environment because `langchain_core` is not installed. The persistence guard compiles, but a live PostgreSQL integration test remains necessary.

## Preserved architecture

The existing NLU extraction → contextual resolution → state update → deterministic question/rule engine → assessment/recommendation pipeline remains in place. No diagnosis rules or product routing rules were replaced with an LLM.
