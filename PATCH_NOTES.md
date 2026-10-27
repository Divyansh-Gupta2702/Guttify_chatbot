# GutGPT v18.3 patch — registration unlock + automatic English/Hinglish detection

## What changed

### `gutgpt-widget.js`
- Preserves the targeted registration-to-chat unlock fix: after successful registration the composer is enabled, the status is cleared, and the first greeting appears without a page refresh.
- Removes the language selector, including the Hindi (Devanagari) option. The widget now accepts typed English or Roman-script Hinglish without requiring the customer to switch a setting.
- The widget continues sending the existing `language` field as English-compatible default; the backend detects the language per message. This avoids changing the existing API request shape.

### `multilingual.py`
- Adds a conservative `detect_input_language()` helper for common Roman-script Hindi/Hinglish words and symptom phrases.
- Removes Hindi (`hi`) from selectable/supported translation output. Hinglish (`hi-latn`) remains supported.
- Hinglish input is translated to English before entering the existing deterministic NLU/contextual resolver/rule engine; the generated existing response is translated back to Hinglish. English messages stay in English.
- Detection is per message, so the customer can alternate between English and Hinglish during the same assessment without changing settings.

### `app.py`
- Uses the detector on each incoming `/api/chat` message before translation and before the existing conversation engine. Diagnosis, safety, and recommendation decisions are not replaced or rewritten by this patch.

## Validation performed for this patch
- `node --check gutgpt-widget.js`: PASS
- `python -m py_compile app.py multilingual.py`: PASS
- Detector smoke tests: PASS for seven English/Hinglish examples, including `mujhe pet me gas hai`, `kal se loose motions hain`, and English-only symptom text.
- Import-level smoke test used a stub for `langchain_groq` because the dependency is not installed in this environment; this validates the pure detection helper but does not validate live translation calls.
- Full pytest regression suite: NOT VERIFIED in this environment; previous attempt was blocked during collection by missing `langchain_core`.
- Live Shopify / production tests: NOT performed.

## Deployment precautions
1. Back up the current working widget and backend files.
2. Apply these files to the matching GutGPT v18.3 codebase; do not reset, delete, or overwrite PostgreSQL data.
3. Ensure the existing `GROQ_API_KEY` and translation dependencies are available for Hinglish conversations.
4. Run the project's full regression suite in the normal deployment environment.
5. Verify on the actual Shopify embed: send English, then Hinglish, then English again in the same assessment; confirm responses follow the input language and progress remains intact.

## Limitations
- Language detection uses a conservative list of common Roman-script Hinglish markers. Unusual spellings, very short messages, or messages containing only shared English/Hindi words may be classified as English.
- Devanagari Hindi is no longer a selectable/output language and is not a guaranteed input mode.
- No live Shopify, production authentication, PostgreSQL recovery, or full regression pass is claimed.
