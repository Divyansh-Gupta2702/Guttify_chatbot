# GutGPT v18.3 — automatic Hinglish detection patch

## Findings from the supplied project

`app.py` calls `detect_input_language(original_message, req.language)` before the existing conversation engine. The widget always sends `language="en"` intentionally so language is detected per message. The detector did not include several common standalone Hinglish answers (`haan`, `ji`, `bilkul`, `raat ko`, `do din se`) in its marker set or strong-phrase rules. Those messages could therefore be treated as English and passed unchanged to the English-oriented NLU/resolver.

The request path also calls Groq translation for detected Hinglish. If Groq returns 429 or empty content, `app.py` raises HTTP 503 rather than passing an untrustworthy translation into the clinical engine. This patch improves detection but does not bypass that safe failure behavior.

## Changed files

- `multilingual.py`: added common Roman-script Hinglish markers and deterministic patterns for short contextual answers.
- `tests/test_hinglish_auto_detection_patch.py`: added detector regression tests for symptom phrases, short contextual answers, and ordinary English.

## Scope and safety

No changes to diagnosis rules, safety checks, recommendation routing, authentication, session handling, or PostgreSQL persistence. Translation still depends on the configured Groq model for full sentences.

## Verification

- Python compilation: passed for `app.py`, `multilingual.py`, and `language_service.py`.
- Focused detection tests: 3 tests passed in this environment using a stub for the optional `langchain_groq` import; this tests language detection only, not actual Groq translation or end-to-end chat.
- Full regression suite and live Shopify test: not run.
