# GutGPT v18.3 Production Log Fixes

## Fixes driven by 2026-10-10 Render logs

1. **Eliminated duplicate NLU/LLM calls for active questions**
   - `/api/chat` already computes contextual NLU in `_run_nlu`.
   - `_apply_answer` now consumes those precomputed facts instead of calling `extract_natural_facts()` a second time.
   - This removes the observed two-Groq-call pattern and reduces latency.

2. **Deterministic food-trigger answers**
   - Active `food_trigger`/`triggers`/`trigger` questions now resolve common answers such as `dairy`, `milk`, `paneer`, `wheat`, `bread`, `beans`, `spicy`, `coffee`, etc. without an LLM call.
   - Explicit no-trigger responses resolve as `food_related=False`.

3. **Optional Bristol stool question**
   - `"I don't know"`, `"not sure"`, `"no idea"`, and equivalent answers are treated as a valid skip for the question wording `if you know it`.
   - State uses `stool_form="unknown"`, which is non-clinical and cannot satisfy numeric Bristol comparisons.
   - Questionnaire readiness recognizes the skip and advances instead of looping.
   - Numeric Bristol values and consistency descriptions continue to resolve normally.

4. **Question-aware NLU schema completeness**
   - Added `stool_form`, `food_trigger`, and `food_related` to validated NLU fields so deterministic contextual answers are not silently discarded before state resolution.

## Regression result

233 tests passed, 18 subtests passed.
