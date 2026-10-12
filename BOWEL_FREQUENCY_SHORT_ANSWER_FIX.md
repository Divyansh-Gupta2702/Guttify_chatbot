# GutGPT — Bowel Frequency Short Answer Fix

## Bug
When GutGPT asked:

> How many bowel movements do you usually have per week?

The answer `3 times` was incorrectly treated as unresolved, while `3 times per week` worked.

## Fix
The deterministic active-question resolver for `bowel_frequency` now accepts:

- `3 times`
- `3`
- `about 3 times`
- `around 4 bowel movements`
- `roughly 2`
- Existing forms such as `3 times per week`

Because the active question already establishes the unit as **per week**, the resolver can safely interpret the numeric answer in that context.

## Scope
Only the `bowel_frequency` question resolver was changed. Diagnosis, recommendation, safety logic, session architecture, and other question flows were not redesigned.

## Validation
- Targeted tests: 71 passed
- Full regression suite: **262 passed, 18 subtests passed**
- Short numeric answers are resolved deterministically and do not call the LLM.
