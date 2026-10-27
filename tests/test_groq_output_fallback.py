import sys
import types

# The fallback policy itself does not need the provider SDK; stub its import so
# these pure formatting tests can run in minimal CI environments.
if "langchain_groq" not in sys.modules:
    stub = types.ModuleType("langchain_groq")
    stub.ChatGroq = object
    sys.modules["langchain_groq"] = stub

from multilingual import translation_error_message


def build_output_translation_fallback(reply: str, language: str) -> str:
    # Keep this tiny policy aligned with app.py: localized notice plus the exact
    # deterministic rule-engine reply; never fabricate or rewrite clinical text.
    return f"{translation_error_message(language)}\n\n{reply}"


def test_hinglish_fallback_preserves_rule_engine_question():
    english_question = "Where is the blood located?"
    result = build_output_translation_fallback(english_question, "hi-latn")
    assert "dobara try karein" in result
    assert english_question in result


def test_fallback_preserves_urgent_safety_text_exactly():
    safety_text = "Seek urgent medical evaluation now."
    result = build_output_translation_fallback(safety_text, "hi-latn")
    assert safety_text in result


def test_fallback_for_other_supported_language_keeps_source_text():
    english_question = "How long have you had these symptoms?"
    result = build_output_translation_fallback(english_question, "bn")
    assert translation_error_message("bn") in result
    assert english_question in result
