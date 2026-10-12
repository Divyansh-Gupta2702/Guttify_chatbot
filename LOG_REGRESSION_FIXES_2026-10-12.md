# GutGPT log-driven regression fixes — 2026-10-12

## Changes

- Expanded deterministic bleeding phrase normalization to recognize colloquial variants including `bloody poops`, `bloody stool`, `blood in my poop`, `poop with blood`, `stool with blood`, and `blood while pooping`.
- Grounded the bleeding fact and symptom label in explicit wording and preserved explicit negation.
- Applied the same bleeding vocabulary to active-question symptom filtering and LLM evidence validation.
- Added regression tests ensuring bloody-stool language starts the assessment flow and is not classified as irrelevant or sent straight to product recommendation.
- Changed NLU logs to distinguish `current_message_symptoms` from accumulated `session_symptoms`, avoiding the misleading impression that a bare answer such as `yes` re-extracted a previous symptom.

## Validation

- Targeted log regressions and active-question tests: 14 passed.
- Full test suite: 260 passed, 18 subtests passed.

## Deployment note

This patch preserves the deterministic question/rule engine and the existing safety gates. Deploy to staging first and replay the provided log scenarios before promoting to production. This is a software regression fix, not a clinical validation of the screening rules.
