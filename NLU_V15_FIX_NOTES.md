# GutGPT NLU / Question Flow v15 Fixes

Based on production v14 logs.

## Fixed

- Defensive Groq JSON extraction: fenced JSON, preambles, and trailing text no longer cause avoidable JSON parsing failures when a valid JSON object is present.
- Natural yes/affirmative answers in question context: `absolutely`, `yes sometimes`, `it does`, `pretty much`, `of course`, etc.
- Natural negative answers in question context: `not really`, `nope`, `it does not`, etc.
- `incomplete_evacuation` now consumes natural affirmative/negative answers without falling into clarification loops.
- `bloating_pain` understands variants such as `it does improve after a bowel movement`.
- Hard-stool language now includes `hard poops`, `hard poos`, `poops are hard`, `stool is hard`, and `poop is hard`.
- Hard-stool detections are promoted into the normalized symptom list so the existing rule engine can establish the correct assessment branch.
- Water intake accepts `litres`, `liters`, and common typo `litters`, plus simple number words.
- Medication answers such as `no medicines` remain contextual facts and are consumed by the active question.
- Numeric answers to non-severity questions are no longer incorrectly interpreted as severity scores (for example, `around 3 litters` no longer becomes severity 3).

## Architecture preserved

User message -> NLU extraction -> state update -> existing question/rule engine -> diagnosis/recommendation.

No diagnosis rules, safety checks, questionnaire branches, or product recommendation rules were removed or replaced with an LLM-only system.

## Validation

160 tests passed, with 18 subtests passed.
