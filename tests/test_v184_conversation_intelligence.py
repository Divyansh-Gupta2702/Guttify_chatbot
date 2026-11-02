import guttify_agent
from guttify_agent import ConversationManager
from intent_parser import SymptomState


def test_general_capability_question_does_not_start_assessment():
    manager = ConversationManager()
    session = manager._get_session("v184-general")
    result = manager.handle_message("v184-general", "What will you do?")
    assert result["status"] == "ANSWER"
    assert "digestive symptoms" in result["message"]
    assert session.last_question is None
    assert session.symptom_state.primary_symptom is None


def test_explanation_question_keeps_active_question_and_state():
    manager = ConversationManager()
    session = manager._get_session("v184-why")
    session.last_question = "duration"
    session.symptom_state = SymptomState(primary_symptom="acidity")
    result = manager.handle_message("v184-why", "Why?")
    assert result["status"] == "ANSWER"
    assert session.last_question == "duration"
    assert session.symptom_state.duration == "unknown"


def test_safety_warning_followup_explains_without_removing_restriction():
    manager = ConversationManager()
    sid = "v184-safety-why"
    session = manager._get_session(sid)
    manager.handle_message(sid, "I have black tarry stool")
    result = manager.handle_message(sid, "Why?")
    assert result["status"] == "SAFETY_REVIEW"
    assert "doesn't confirm a diagnosis" in result["message"]
    assert result["recommendations"] == []
    assert session.symptom_state.red_flags


def test_vague_digestive_problem_invites_symptom_description():
    manager = ConversationManager()
    result = manager.handle_message("v184-vague", "I have a digestive problem")
    assert result["status"] == "ASK"
    assert "what you're experiencing" in result["message"]
    assert manager._get_session("v184-vague").symptom_state.primary_symptom is None


def test_product_information_aside_preserves_active_assessment():
    manager = ConversationManager()
    sid = "v184-product-aside"
    session = manager._get_session(sid)
    session.last_question = "duration"
    session.symptom_state.primary_symptom = "acidity"
    result = manager.handle_message(sid, "What is Digest Boost?")
    assert result["status"] == "PRODUCT_INFO_FOUND"
    assert session.last_question == "duration"
    assert session.symptom_state.primary_symptom == "acidity"


def test_model_red_flag_labels_cannot_create_safety_state(monkeypatch):
    manager = ConversationManager()
    sid = "v184-unverified-model-flag"
    session = manager._get_session(sid)
    monkeypatch.setattr(manager, "_run_nlu", lambda *_: {
        "intent": "assessment", "symptoms": [], "red_flags": ["vomiting blood"],
        "_question_resolution": {"status": "unresolved", "values": {}},
    })
    result = manager.handle_message(sid, "I have a digestive problem")
    assert result["status"] == "ASK"
    assert session.symptom_state.red_flags == []


def test_structured_multiple_symptoms_are_retained():
    manager = ConversationManager()
    session = manager._get_session("v184-multisymptom")
    manager._apply_nlu_facts(session, {"symptoms": ["gas", "bloating", "constipation"]})
    assert session.symptom_state.primary_symptom == "gas"
    assert session.symptom_state.secondary_symptoms == ["bloating", "constipation"]


def test_natural_multiple_symptoms_survive_full_message_flow():
    manager = ConversationManager()
    sid = "v184-natural-multisymptom"
    manager.handle_message(sid, "I have gas and bloating")
    state = manager._get_session(sid).symptom_state
    assert state.primary_symptom == "bloating"
    assert "gas" in state.secondary_symptoms
    assert state.gas is True
    assert state.bloating is True


def test_plain_language_correction_survives_full_message_flow():
    manager = ConversationManager()
    sid = "v184-natural-correction"
    session = manager._get_session(sid)
    session.symptom_state = SymptomState(
        primary_symptom="constipation", secondary_symptoms=["bloating"],
        constipation_explicit=True, bloating=True,
    )
    manager.handle_message(sid, "Actually, I don't have constipation")
    assert session.symptom_state.constipation_explicit is False
    assert session.symptom_state.primary_symptom == "bloating"
    assert session.symptom_state.secondary_symptoms == []


def test_assessment_can_resume_after_explanation_aside():
    manager = ConversationManager()
    sid = "v184-why-resume"
    session = manager._get_session(sid)
    session.last_question = "duration"
    session.symptom_state.primary_symptom = "acidity"
    manager.handle_message(sid, "Why?")
    manager.handle_message(sid, "3 days")
    assert session.symptom_state.duration == "3 days"
    assert session.last_question != "duration"


def test_symptom_correction_removes_only_corrected_branch():
    manager = ConversationManager()
    session = manager._get_session("v184-correction")
    session.symptom_state = SymptomState(
        primary_symptom="constipation", secondary_symptoms=["bloating"],
        constipation_explicit=True, bloating=True,
    )
    manager._apply_nlu_facts(session, {"constipation": False})
    assert session.symptom_state.constipation_explicit is False
    assert session.symptom_state.primary_symptom == "bloating"
    assert session.symptom_state.secondary_symptoms == []


def test_structured_groq_openai_choice_payload_is_read():
    import json
    from nlu_extractor import _response_payload
    content, finish, refusal, tool_calls = _response_payload({
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"intent": "assessment"})}}]
    })
    import json
    assert json.loads(content) == {"intent": "assessment"}
    assert finish == "stop"
    assert refusal is False
    assert tool_calls is False


def test_groq_structured_parsed_response_is_read():
    from nlu_extractor import _response_payload

    class Response:
        content = ""
        parsed = {"intent": "assessment"}
        response_metadata = {"finish_reason": "stop"}

    assert _response_payload(Response())[0] == '{"intent": "assessment"}'

