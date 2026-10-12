
import guttify_agent
import nlu_extractor
from guttify_agent import ConversationManager
from intent_parser import SymptomState
from nlu_extractor import extract_natural_facts
from question_schema import resolve_against_active_question, question_has_answer


def active(question, primary="bloating"):
    cm = ConversationManager()
    sid = "v19-" + question
    session = cm._get_session(sid)
    session.last_question = question
    session.symptom_state.primary_symptom = primary
    return cm, sid, session


def test_bare_yes_is_owned_by_active_boolean_question_only():
    facts = extract_natural_facts("yes", "blood", SymptomState(primary_symptom="piles"))
    assert facts["bleeding"] is True
    assert facts.get("pain") is None
    assert facts.get("constipation") is None
    assert facts.get("diarrhea") is None


def test_bare_no_preserves_unrelated_confirmed_state():
    cm, sid, s = active("blood", "constipation")
    s.symptom_state.bloating = True
    s.symptom_state.constipation_explicit = True
    cm.handle_message(sid, "no")
    assert s.symptom_state.blood_present is False
    assert s.symptom_state.bloating is True
    assert s.symptom_state.constipation_explicit is True


def test_unknown_variants_resolve_and_do_not_repeat():
    for msg in ["I don't know", "dont know", "not sure", "I'm not sure",
                "can't tell", "no idea", "I have no idea", "I'm unsure",
                "I don't remember", "not certain", "maybe", "I can't say"]:
        facts = extract_natural_facts(msg, "stool_form", SymptomState(primary_symptom="bloating"))
        if msg == "maybe":
            assert facts["_answer_status"] == "clarification_needed", msg
            assert facts["_question_resolution"]["status"] == "clarification_needed", msg
        else:
            assert facts["_answer_status"] == "unknown", msg
            assert facts["_question_resolution"]["status"] == "unknown", msg


def test_no_to_optional_stool_type_means_unknown():
    facts = extract_natural_facts("no", "stool_form", SymptomState(primary_symptom="bloating"))
    assert facts["_answer_status"] == "unknown"
    cm, sid, s = active("stool_form")
    cm.handle_message(sid, "no")
    assert s.symptom_state.stool_form == "unknown"
    assert s.last_question != "stool_form"


def test_deterministic_scalar_answers():
    cases = [
        ("43", "age", "age", 43),
        ("I'm 43", "age", "age", 43),
        ("2 days", "duration", "duration", "2 days"),
        ("for 2 weeks", "duration", "duration", "2 weeks"),
        ("hard", "stool_form", "stool_form", 2),
        ("usually hard and lumpy", "stool_form", "stool_form", 2),
        ("dairy", "food_trigger", "food_trigger", "dairy"),
        ("mostly after milk and other dairy products", "food_trigger", "food_trigger", "dairy"),
    ]
    for msg, q, field, expected in cases:
        facts = extract_natural_facts(msg, q, SymptomState(primary_symptom="bloating"))
        assert facts[field] == expected, (msg, facts)


def test_deterministic_answers_do_not_call_llm(monkeypatch):
    calls = []
    monkeypatch.setattr(nlu_extractor, "_llm_extract", lambda *a, **k: calls.append(a) or None)
    for msg, q in [("yes", "blood"), ("no", "blood"), ("43", "age"),
                   ("2 days", "duration"), ("hard", "stool_form"), ("dairy", "food_trigger")]:
        extract_natural_facts(msg, q, SymptomState(primary_symptom="bloating"))
    assert calls == []


def test_natural_sentence_preserves_multiple_facts():
    facts = extract_natural_facts(
        "Yes, I have abdominal pain and it usually gets worse before I pass stool.",
        "pain",
        SymptomState(primary_symptom="bloating"),
    )
    assert facts.get("pain") is True
    assert facts.get("pain_related_to_bowel_movement") is True


def test_long_natural_food_answer_preserves_trigger():
    facts = extract_natural_facts(
        "Yeah, mostly after dairy and I've had this for around two weeks.",
        "food_trigger",
        SymptomState(primary_symptom="bloating"),
    )
    assert facts.get("food_trigger") == "dairy"
    assert facts.get("duration") == "2 weeks"


def test_model_json_parse_failure_falls_back_once(monkeypatch):
    calls = {"n": 0}
    class FakeLLM:
        def invoke(self, prompt):
            calls["n"] += 1
            class R:
                content = "```json\n{this is not valid json}\n```"
            return R()
    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: FakeLLM())
    facts = extract_natural_facts("something completely unusual and difficult to parse", "blood", SymptomState(primary_symptom="bloating"))
    assert calls["n"] == 1
    assert facts["_resolver_source"] == "fallback"


def test_model_content_with_fence_and_preamble_parses():
    class FakeLLM:
        def invoke(self, prompt):
            class R:
                content = 'Here is the JSON:\n```json\n{"intent":"answer_question","bleeding":true,"confidence":0.9}\n```\n'
            return R()
    nlu_extractor._get_llm.cache_clear()
    # Patch cache-backed constructor for this test.
    import pytest
    old = nlu_extractor._get_llm
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: FakeLLM())
    try:
        facts = extract_natural_facts("I have bleeding", "blood", SymptomState(primary_symptom="piles"))
        assert facts["bleeding"] is True
    finally:
        monkeypatch.undo()


def test_repeated_identical_clarification_advances_instead_of_looping():
    cm, sid, s = active("pain_relation", "stomach pain")
    first = cm.handle_message(sid, "not sure which")
    assert first["status"] == "ASK"
    second = cm.handle_message(sid, "not sure which")
    assert s.last_question != "pain_relation"
    assert s.symptom_state.answered_unknown_fields


def test_constipation_bare_no_is_deterministic_negative():
    facts = extract_natural_facts("no", "constipation", SymptomState(primary_symptom="piles"))
    assert facts["_answer_status"] == "answered"
    assert facts["_resolver_source"] == "deterministic"
    assert facts["constipation_explicit"] is False
    assert facts["straining"] is False


def test_constipation_bare_yes_is_deterministic_positive():
    facts = extract_natural_facts("yes", "constipation", SymptomState(primary_symptom="piles"))
    assert facts["_answer_status"] == "answered"
    assert facts["_resolver_source"] == "deterministic"
    assert facts["constipation_explicit"] is True


def test_constipation_maybe_never_mutates_state_or_advances():
    cm, sid, s = active("constipation", "piles")
    s.symptom_state.constipation_explicit = None
    s.symptom_state.straining = None
    result = cm.handle_message(sid, "maybe")
    assert result["status"] == "ASK"
    assert s.last_question == "constipation"
    assert s.symptom_state.constipation_explicit is None
    assert s.symptom_state.straining is None


def test_constipation_unrelated_message_never_mutates_question_facts():
    facts = extract_natural_facts("I was travelling yesterday and watched a movie", "constipation",
                                  SymptomState(primary_symptom="piles"))
    assert facts["_answer_status"] == "unresolved"
    assert facts["_question_resolution"]["values"] == {}
    assert facts.get("constipation") is None
    assert facts.get("straining") is None


def test_unresolved_cannot_become_answered_from_existing_state():
    cm, sid, s = active("constipation", "piles")
    s.symptom_state.constipation_explicit = None
    s.symptom_state.straining = None
    result = cm.handle_message(sid, "something unrelated")
    assert s.last_question == "constipation"
    assert s.symptom_state.constipation_explicit is None
    assert s.symptom_state.straining is None


def test_answered_constipation_advances_to_next_question():
    cm, sid, s = active("constipation", "piles")
    result = cm.handle_message(sid, "no")
    assert s.symptom_state.constipation_explicit is False
    assert s.symptom_state.straining is False
    assert s.last_question != "constipation"


def test_resolution_guard_normalizes_invalid_unresolved_values():
    from question_schema import validate_question_resolution
    result = validate_question_resolution({
        "status": "unresolved",
        "values": {"constipation_explicit": False},
        "confidence": 0.2,
        "source": "fallback",
    })
    assert result["status"] == "unresolved"
    assert result["values"] == {}


def test_natural_straining_does_not_invent_other_constipation_negatives():
    facts = extract_natural_facts(
        "I sometimes strain but otherwise I'm fine",
        "constipation",
        SymptomState(primary_symptom="piles"),
    )
    assert facts.get("straining") is True
    assert facts.get("constipation_explicit") is not False


def test_bowel_frequency_accepts_contextual_short_answers_without_week_suffix():
    cases = [
        ("3 times", 3),
        ("3", 3),
        ("about 3 times", 3),
        ("around 4 bowel movements", 4),
        ("roughly 2", 2),
    ]
    for message, expected in cases:
        facts = extract_natural_facts(message, "bowel_frequency", SymptomState(primary_symptom="constipation"))
        assert facts["bowel_frequency_per_week"] == expected, (message, facts)
        assert facts["_answer_status"] == "answered", (message, facts)
        assert facts["_resolver_source"] == "deterministic", (message, facts)


def test_bowel_frequency_short_answer_does_not_call_llm(monkeypatch):
    calls = []
    monkeypatch.setattr(nlu_extractor, "_llm_extract", lambda *a, **k: calls.append(a) or None)
    facts = extract_natural_facts("3 times", "bowel_frequency", SymptomState(primary_symptom="constipation"))
    assert facts["bowel_frequency_per_week"] == 3
    assert facts["_answer_status"] == "answered"
    assert calls == []
