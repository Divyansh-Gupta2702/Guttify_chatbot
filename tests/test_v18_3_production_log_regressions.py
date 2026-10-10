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
