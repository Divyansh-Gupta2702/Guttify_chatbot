# GutGPT v18.3 — Hinglish short-answer patch

## Change
`multilingual.py` now normalizes exact short Hinglish answers locally before any Groq translation call. Examples: `nahi` / `nahin` / `nhi` -> `no`; `haan` / `ji` -> `yes`; `raat ko` -> `at night`. This means these exact answers do not depend on Groq being available.

The mapping is exact-match only and does not alter longer sentences. The existing question resolver still determines which active field the normalized answer applies to; safety logic is not changed.

## Files
- `multilingual.py`
- `tests/test_hinglish_auto_detection_patch.py`

## Verification
Focused tests: 4 passed.
Full project regression suite and live Shopify test: not run.

## Integration note
This patch updates the `multilingual.py` from the uploaded language patch ZIP, not your full application. It only helps if your `app.py` detects the message as `hi-latn` and calls `translate_to_english()` before invoking the NLU/contextual resolver. Verify that wiring in the current application before production deployment.
