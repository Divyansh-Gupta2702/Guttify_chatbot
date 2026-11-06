import json
from types import SimpleNamespace

import app as gutgpt_app
import translation_service
from translation_service import TranslationError


def _prepare_session(monkeypatch, session_id):
    gutgpt_app.conversation_manager.reset(session_id)
    gutgpt_app.HISTORY[session_id] = []
    gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.add(session_id)
    monkeypatch.setattr(gutgpt_app, "_persist_assessment_checkpoint", lambda *a, **k: None)
    monkeypatch.setattr(gutgpt_app, "_persist_completed_assessment", lambda *a, **k: None)
    monkeypatch.setattr(gutgpt_app, "_persist_customer_safety_restriction", lambda *a, **k: None)
    monkeypatch.setattr(gutgpt_app, "_persist_customer_profile_age", lambda *a, **k: True)


def _chat(session_id, message, language):
    return gutgpt_app._chat_impl(
        gutgpt_app.ChatRequest(
            session_id=session_id, message=message, language=language, message_id=""
        ),
        request=None,
    )


def test_language_switches_mid_assessment_without_resetting_progress(monkeypatch):
    import nlu_extractor

    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: None)
    _prepare_session(monkeypatch, "hinglish-mid-assessment")
    translated_inputs = []

    def translate_input(text):
        translated_inputs.append(text)
        return {"meri umar 34 hai": "I am 34", "nahi": "no"}.get(text, text)

    monkeypatch.setattr(gutgpt_app, "translate_input_to_english", translate_input)
    monkeypatch.setattr(
        gutgpt_app,
        "translate_chat_output",
        lambda reply, recommendations: ("HINGLISH: " + reply, recommendations),
    )

    first = _chat("hinglish-mid-assessment", "I have heartburn after meals for 2 weeks", "en")
    session = gutgpt_app.conversation_manager.sessions["hinglish-mid-assessment"]
    assert first.status == "ASK"
    assert session.last_question == "age"

    switched = _chat("hinglish-mid-assessment", "meri umar 34 hai", "hinglish")
    assert translated_inputs == ["meri umar 34 hai"]
    assert switched.status == "ASK"
    assert switched.reply.startswith("HINGLISH: ")
    assert session.symptom_state.age == 34
    assert session.last_question == "reflux"

    switched_back = _chat("hinglish-mid-assessment", "no", "en")
    assert switched_back.status == "ASK"
    assert not switched_back.reply.startswith("HINGLISH: ")
    assert session.symptom_state.reflux_present is False


def test_hinglish_input_translation_failure_does_not_advance_assessment(monkeypatch):
    _prepare_session(monkeypatch, "hinglish-translation-failure")

    def unavailable(_text):
        raise TranslationError("provider unavailable")

    monkeypatch.setattr(gutgpt_app, "translate_input_to_english", unavailable)
    result = _chat("hinglish-translation-failure", "pet mein dard hai", "hinglish")

    session = gutgpt_app.conversation_manager.sessions["hinglish-translation-failure"]
    assert result.status == "TRANSLATION_UNAVAILABLE"
    assert "Hinglish" in result.reply
    assert session.symptom_state.primary_symptom is None


def test_english_sentence_in_hinglish_mode_prompts_setting_switch_without_advancing(monkeypatch):
    _prepare_session(monkeypatch, "hinglish-language-mismatch")

    def unexpected_translation(_text):
        raise AssertionError("clear English should be rejected before translation")

    monkeypatch.setattr(gutgpt_app, "translate_input_to_english", unexpected_translation)

    result = _chat(
        "hinglish-language-mismatch",
        "I have stomach pain after eating",
        "hinglish",
    )

    session = gutgpt_app.conversation_manager.sessions["hinglish-language-mismatch"]
    assert result.status == gutgpt_app.LANGUAGE_MISMATCH_STATUS
    assert "switch the language selector to English" in result.reply
    assert session.symptom_state.primary_symptom is None


def test_short_english_answers_and_hinglish_text_are_not_misclassified():
    for message in (
        "yes", "no", "bright red", "upper stomach", "dard after khana",
        "mujhe pain after eating", "haan I have pain after eating",
    ):
        assert gutgpt_app._is_clearly_english_sentence(message) is False, message
    assert gutgpt_app._is_clearly_english_sentence("I have pain after meals") is True
    assert gutgpt_app._is_clearly_english_sentence("I'm bloated") is True


def test_translation_service_preserves_structure_and_catalog_fields(monkeypatch):
    monkeypatch.setattr(translation_service, "_get_llm_cached", lambda *args: object())
    prompts = []

    def fake_invoke(_client, _prompt, *, reason):
        prompts.append(_prompt)
        if reason == "translation_input":
            content = json.dumps({"translation": "I have pain for 2 days"})
        else:
            content = json.dumps({
                "reply": "Brand Product ke liye Aapko pain 2 din se hai? https://example.test/product",
                "recommendations": [{
                    "intended_support": ["Gas aur bloating support"],
                    "how_to_use": "Label ke mutabik lein",
                    "warnings": ["Doctor se salah lein"],
                }],
            })
        return SimpleNamespace(
            content=content,
            response_metadata={"finish_reason": "stop"},
            usage_metadata={},
        )

    monkeypatch.setattr(translation_service, "invoke_provider", fake_invoke)
    assert translation_service.translate_input_to_english("२ din se pain") == "I have pain for 2 days"

    source = [{
        "product_name": "Brand Product",
        "product_url": "https://example.test/product",
        "intended_support": ["Support for gas and bloating"],
        "how_to_use": "Use as labelled",
        "warnings": ["Consult a clinician"],
    }]
    reply, recommendations = translation_service.translate_chat_output(
        "Use Brand Product: https://example.test/product", source
    )
    assert reply == "Brand Product ke liye Aapko pain 2 din se hai? https://example.test/product"
    assert recommendations[0]["product_name"] == "Brand Product"
    assert recommendations[0]["product_url"] == "https://example.test/product"
    assert recommendations[0]["intended_support"] == ["Gas aur bloating support"]
    output_prompt = prompts[-1].lower()
    assert "symptom-summary headings" in output_prompt
    assert "every summary field label and answer" in output_prompt
    assert "diagnosis/screening explanations" in output_prompt
    assert "do not use devanagari or leave whole sentences in english" in output_prompt
