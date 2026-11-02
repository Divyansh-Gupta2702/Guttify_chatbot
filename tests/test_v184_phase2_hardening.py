import json

import conversation_intelligence
import llm_provider
import nlu_extractor
import guttify_agent
from guttify_agent import ConversationManager, SessionState
from intent_parser import SymptomState


def test_provider_selection_is_configurable_and_defaults_to_groq(monkeypatch):
    monkeypatch.delenv("GUTGPT_LLM_PROVIDER", raising=False)
    assert llm_provider.selected_provider() == "groq"
    monkeypatch.setenv("GUTGPT_LLM_PROVIDER", "gemini")
    assert llm_provider.selected_provider() == "gemini"


def test_provider_switch_uses_cheaper_gemini_fallback_once(monkeypatch):
    calls = []

    class FakeGemini:
        _gutgpt_provider = "gemini"
        max_output_tokens = 200
        output_mode = "json"
        model_name = "primary"

    class Response:
        content = '{"ok":true}'

    def invoke(client, _prompt, **_kwargs):
        calls.append(client.model_name)
        if len(calls) == 1:
            raise TimeoutError()
        return Response()

    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setattr(llm_provider, "invoke_groq", invoke)
    monkeypatch.setattr(llm_provider, "_GeminiClient", lambda model, tokens, mode: type(
        "Backup", (), {"_gutgpt_provider": "gemini", "model_name": model,
                       "max_output_tokens": tokens, "output_mode": mode}
    )())
    response = llm_provider.invoke_provider(FakeGemini(), "synthetic prompt", reason="test")
    assert response.content == '{"ok":true}'
    assert calls == ["primary", "gemini-3.1-flash-lite"]


def test_only_provider_module_imports_provider_sdk():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for name in ("app.py", "guttify_agent.py", "nlu_extractor.py", "conversation_intelligence.py", "guttify_chatbot.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "from langchain_groq import" not in source
        assert "from google import genai" not in source


def test_structured_red_flag_response_has_validated_provenance():
    manager = ConversationManager()
    result = manager.handle_message("provenance-black-stool", "I have black tarry stool")
    assert result["status"] == "SAFETY_REVIEW"
    assert result["safety"]["reason_code"] == "urgent_red_flag"
    provenance = result["safety"]["flag_provenance"]
    assert provenance
    assert provenance[0]["scope"] == "assessment"
    assert provenance[0]["source"] == "user_text_span"
    assert provenance[0]["evidence"] == "black tarry stool"
    assert provenance[0]["assessment_id"] is None


def test_vague_turn_cannot_create_safety_provenance():
    manager = ConversationManager()
    result = manager.handle_message("provenance-vague", "I have a digestive problem")
    assert result["status"] == "ASK"
    assert manager.sessions["provenance-vague"].safety_flag_provenance == []


def test_customer_safety_restriction_is_stored_as_metadata_without_raw_message(monkeypatch):
    import app

    sid = "persist-pregnancy-restriction"
    customer_id = "customer-restriction-test"
    state = SessionState(pregnancy_lactation_caution=True, pregnancy_lactation_provenance={
        "reason": "pregnancy_lactation_product_restriction", "source": "user_text_span",
        "evidence": "pregnant", "timestamp": "2026-11-02T00:00:00+00:00",
        "scope": "customer", "assessment_id": None,
    })
    monkeypatch.setitem(app.SESSION_CUSTOMER_IDS, sid, customer_id)
    monkeypatch.setitem(app.conversation_manager.sessions, sid, state)
    records = [{"customer_id": customer_id, "name": "Test", "age": 30, "contact": "1234567", "city": "Test City"}]
    monkeypatch.setattr(app, "_read_customer_records", lambda: records)
    monkeypatch.setattr(app, "_write_customer_records", lambda value: None)

    app._persist_customer_safety_restriction(sid, "I am pregnant and having bloating")

    saved = records[0]["customer_safety_restrictions"]["pregnancy_lactation_product_restriction"]
    assert saved["active"] is True
    assert saved["provenance"]["scope"] == "customer"
    assert saved["provenance"]["source"] == "user_text_span"
    assert saved["provenance"]["evidence"] == "pregnant"
    assert "I am pregnant and having bloating" not in json.dumps(saved)


def test_unmapped_symptom_is_preserved_only_when_verbatim_and_not_diagnosed(monkeypatch):
    class Response:
        content = json.dumps({
            "intent": "assessment", "symptoms": [],
            "other_symptoms": ["stomach feels heavy", "nausea after meals"],
        })
        response_metadata = {"finish_reason": "stop"}

    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: object())
    monkeypatch.setattr(nlu_extractor, "invoke_groq", lambda *_a, **_k: Response())
    facts = nlu_extractor._llm_extract(
        "My stomach feels heavy after meals", None, SymptomState(), None,
    )
    assert facts["other_symptoms"] == ["stomach feels heavy"]
    manager = ConversationManager()
    session = manager._get_session("other-symptom-context")
    manager._apply_nlu_facts(session, facts)
    assert session.symptom_state.other_symptoms == ["stomach feels heavy"]
    assert session.symptom_state.primary_symptom is None


def test_conversation_router_feature_flag_uses_safe_deterministic_fallback(monkeypatch):
    monkeypatch.setenv("GUTGPT_CONVERSATION_ROUTER_ENABLED", "false")
    monkeypatch.setattr(guttify_agent, "classify_intent", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("router should be disabled")))
    manager = ConversationManager()
    result = manager.handle_message("router-flag-off", "What causes acidity?")
    assert result["status"] == "ANSWER"
    assert "couldn't prepare a reliable answer" in result["message"]


def test_product_information_path_remains_separate_from_assessment():
    manager = ConversationManager()
    session = manager._get_session("product-still-informational")
    result = manager.handle_message("product-still-informational", "What is Digest Boost?")
    assert result["status"] == "PRODUCT_INFO_FOUND"
    assert session.symptom_state.primary_symptom is None
    assert result.get("screening") is None
    assert result["recommendations"][0]["product_name"] == "Digest Boost"
