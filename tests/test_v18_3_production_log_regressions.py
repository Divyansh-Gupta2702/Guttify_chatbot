import pytest
import guttify_agent
from guttify_agent import ConversationManager
from intent_parser import SymptomState
from nlu_extractor import extract_natural_facts
from question_schema import question_has_answer


def active(question, primary="bloating"):
    cm = ConversationManager()
    sid = f"v18-3-{question}"
    session = cm._get_session(sid)
    session.last_question = question
    session.symptom_state.primary_symptom = primary
    return cm, sid, session


def test_food_trigger_dairy_resolves_without_llm_needed():
    facts = extract_natural_facts("dairy", "food_trigger", SymptomState(primary_symptom="bloating"))
    assert facts["food_trigger"] == "dairy"
    assert facts["food_related"] is True


def test_food_trigger_dairy_advances():
    cm, sid, session = active("food_trigger")
    cm.handle_message(sid, "dairy")
    assert session.symptom_state.food_trigger == "dairy"
    assert session.symptom_state.food_related is True
    assert session.last_question != "food_trigger"


def test_optional_bristol_question_allows_i_dont_know_without_loop():
    cm, sid, session = active("stool_form", "diarrhea")
    result = cm.handle_message(sid, "I don't know")
    assert session.symptom_state.stool_form == "unknown"
    assert question_has_answer(session.symptom_state, "stool_form") is True
    assert session.last_question != "stool_form"
    assert result["status"] != "ASK" or "Bristol" not in result.get("message", "")


def test_stool_form_numeric_and_consistency_answers_still_work():
    for msg, expected in [("4", 4), ("Bristol type 2", 2), ("hard", 2), ("loose", 6)]:
        cm, sid, session = active("stool_form", "diarrhea")
        cm.handle_message(sid, msg)
        assert session.symptom_state.stool_form == expected
        assert session.last_question != "stool_form"


def test_active_question_does_not_call_llm_twice(monkeypatch):
    calls = []
    original = guttify_agent.extract_natural_facts

    def wrapped(message, last_question, state):
        calls.append((message, last_question))
        return original(message, last_question, state)

    monkeypatch.setattr(guttify_agent, "extract_natural_facts", wrapped)
    cm, sid, session = active("food_trigger")
    cm.handle_message(sid, "dairy")
    assert len(calls) == 1


def test_optional_bristol_question_no_longer_loops_on_unknown_answer():
    cm, sid, session = active("stool_form", "bloating")
    cm.handle_message(sid, "I don't know")
    assert session.last_question != "stool_form"


def test_bowel_pattern_bare_no_is_unresolved():
    from question_schema import resolve_against_active_question
    result = resolve_against_active_question("bowel_pattern", "no")
    assert result["status"] == "unresolved"
    assert result["values"] == {}


def test_bowel_pattern_explicit_denial_of_both_resolves_normal():
    from question_schema import resolve_against_active_question
    for message in (
        "no constipation or diarrhea", "I don't have either", "neither",
        "No, my bowel movements are normal", "no, nothing like that",
        "neither of those", "I have neither constipation nor loose motions",
    ):
        result = resolve_against_active_question("bowel_pattern", message)
        assert result["status"] == "answered", (message, result)
        assert result["values"]["bowel_pattern"] == "normal", (message, result)
        assert result["values"]["constipation_explicit"] is False
        assert result["values"]["diarrhea_explicit"] is False
        assert result["values"]["diarrhea"] is False


def test_neither_is_contextual_not_global():
    from question_schema import resolve_against_active_question
    assert resolve_against_active_question("bowel_pattern", "neither")["status"] == "answered"
    other = resolve_against_active_question("age", "neither")
    assert other["status"] == "unresolved"
    assert other["values"] == {}


def test_bowel_negative_answer_not_overwritten_by_stale_positive_candidate():
    from question_schema import resolve_against_active_question
    from intent_parser import SymptomState
    from nlu_extractor import extract_natural_facts
    state = SymptomState(primary_symptom="bloating", diarrhea=True, diarrhea_explicit=True,
                         constipation_explicit=True, duration="2 weeks", age=34)
    facts = extract_natural_facts("no constipation or diarrhea", "bowel_pattern", state)
    resolution = facts["_question_resolution"]
    assert resolution["status"] == "answered"
    assert resolution["values"]["diarrhea"] is False
    cm, sid, session = active("bowel_pattern")
    session.symptom_state = state
    cm._apply_answer(session, "no constipation or diarrhea", facts)
    assert session.symptom_state.diarrhea is False
    assert session.symptom_state.diarrhea_explicit is False
    assert session.symptom_state.constipation_explicit is False
    assert session.symptom_state.primary_symptom == "bloating"
    assert session.symptom_state.duration == "2 weeks"
    assert session.symptom_state.age == 34


def test_unresolved_bowel_answer_does_not_commit_extracted_normal_default():
    from intent_parser import SymptomState
    from nlu_extractor import extract_natural_facts
    state = SymptomState(primary_symptom="bloating")
    facts = extract_natural_facts("no", "bowel_pattern", state)
    assert facts["_question_resolution"]["status"] == "unresolved"
    cm, sid, session = active("bowel_pattern")
    session.symptom_state = state
    cm._apply_answer(session, "no", facts)
    assert session.symptom_state.constipation_explicit is None
    assert session.symptom_state.diarrhea_explicit is None
    assert session.symptom_state.diarrhea is None


@pytest.mark.parametrize("content", [None, "", "   ", "{ malformed json"])
def test_empty_or_malformed_model_content_returns_safe_fallback(monkeypatch, content):
    import nlu_extractor

    class Response:
        def __init__(self):
            self.content = content

    class FakeLLM:
        def invoke(self, prompt):
            return Response()

    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: FakeLLM())
    result = nlu_extractor._llm_extract(
        "I would rate the pain 5", "severity", __import__("intent_parser").SymptomState(), "answer_question"
    )
    assert result is None


def test_model_missing_expected_fields_is_validated_without_crashing(monkeypatch):
    import json
    import nlu_extractor

    class Response:
        content = json.dumps({"intent": "answer_question"})

    class FakeLLM:
        def invoke(self, prompt):
            return Response()

    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: FakeLLM())
    result = nlu_extractor._llm_extract(
        "I feel some pain", "pain", __import__("intent_parser").SymptomState(), "answer_question"
    )
    assert isinstance(result, dict)
    assert result.get("pain") in (None, False, True)


def test_model_provider_error_returns_safe_fallback(monkeypatch):
    import nlu_extractor

    class FakeLLM:
        def invoke(self, prompt):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: FakeLLM())
    assert nlu_extractor._llm_extract(
        "I would rate the pain 5", "severity", __import__("intent_parser").SymptomState(), "answer_question"
    ) is None
