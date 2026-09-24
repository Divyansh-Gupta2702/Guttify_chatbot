# GutGPT V8 — Clinical Context Product Matching

## Fix in V8

V7 correctly classified a bright-red bleeding + sharp anal pain flow as a **Possible anal fissure pattern**, and it correctly allowed Piloease. The remaining bug was in the hand-off to the recommendation engine: the raw primary symptom was still `bleeding`, while Piloease's general product aliases intentionally do not include generic bleeding. The recommendation engine therefore returned no product.

V8 fixes this without weakening the safety gate.

### New clinical-context bridge

The recommendation engine now accepts an optional `match_context` supplied only after the deterministic clinical rule engine has produced a pattern. Contextual mappings include:

- Possible anal fissure pattern → Piloease Anal Care Spray
- Possible hemorrhoid pattern → Piles Pure + Piloease Anal Care Spray
- Dyspepsia/indigestion pattern → Acid Ease
- Upper-abdominal meal-related dyspepsia pattern → Acid Ease

A generic `bleeding` message still cannot directly retrieve Piloease. The user must first complete the bleeding screening and reach the appropriate clinical pattern.

## Product coverage audit

The active `products.json` contains 10 product entries. Product-specific entry points were checked for:

- GloLux → dull/dry/uneven skin and skin-health concerns
- Boost Vitamin B12 → B12 deficiency, low energy, fatigue, brain fog, focus and plant-based nutrient gaps
- Boost Vitamin D3+ → vitamin D deficiency, low immunity, weak bones, low sun exposure and low mood
- Apple Active → weight management and metabolism support
- Liver Lift → liver support, sluggishness and digestion-support concerns
- Guttify Poopie → low fibre, hard/irregular stools and constipation-related concerns
- Digest Boost → constipation/bloating/irregular digestion
- Acid Ease → acidity/heartburn/reflux, plus contextual dyspepsia patterns
- Piles Pure → hemorrhoid/piles pattern and bleeding-related hemorrhoid support
- Piloease → piles/anal fissure/anal discomfort/itching/irritation, plus contextual fissure/hemorrhoid patterns

Products are still filtered by clinical eligibility before recommendation. No generic symptom alias was added for Piloease's `bleeding`, specifically to prevent unassessed rectal bleeding from bypassing the screening flow.

## Verification

- `python -m compileall -q .` — passed
- `python -m pytest -q` — **53 passed, 6 subtests passed**
- Manual reproduction of the screenshot flow — Piloease returned
- Generic unassessed `bleeding` → Piloease — no match
- Black/tarry stool → urgent medical evaluation, no product
