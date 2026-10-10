# GutGPT V16 — Multi-Symptom Product Routing Fix

## What changed

The recommendation layer now evaluates independently eligible product clusters for all explicitly reported symptoms, instead of allowing the primary symptom to suppress products for secondary symptoms.

Examples:

- bleeding + constipation + hard stools → anorectal recommendation(s) + constipation recommendation(s)
- constipation + hard stools + acidity → constipation recommendation(s) + Acid Ease
- more than two eligible product matches are retained instead of being silently truncated by `TOP_K=2`

## Safety and architecture preserved

- Existing clinical questionnaire remains unchanged.
- Existing deterministic clinical rule engine remains the safety gate.
- Red-flag and urgent-medical-evaluation paths are unchanged.
- Products are only added through an explicit product eligibility map; arbitrary product.json keyword overlap cannot create a recommendation.
- Existing ambiguity handling remains in place. When multiple products are valid, the UI can present the options instead of forcing one.
- No LLM-only recommendation logic was introduced.

## Recommendation scoring change

A product can now receive a direct eligibility score from an explicitly reported secondary symptom after the clinical layer has already allow-listed that product cluster. This allows a secondary symptom such as `acidity` to reach Acid Ease even when `constipation` is the primary symptom.

## Validation

Full test suite:

`162 passed, 18 subtests passed`
