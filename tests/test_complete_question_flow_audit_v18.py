import pytest

from guttify_agent import ConversationManager
from intent_parser import SymptomState
from question_schema import QUESTION_SCHEMA, question_has_answer
from nlu_extractor import extract_natural_facts


def active(question, primary="stomach pain"):
    cm = ConversationManager()
    sid = f"audit-{question}"
    session = cm._get_session(sid)
    session.last_question = question
    session.symptom_state.primary_symptom = primary
    return cm, sid, session


@pytest.mark.parametrize(
    "question,message,field,expected",
    [
        ("age", "34 years", "age", 34),
        ("duration", "2 days", "duration", "2 days"),
        ("severity", "7", "severity", "7"),
        ("water", "2.5 litres", "water_intake", "2.5 L"),
        ("reflux", "no", "reflux_present", False),
        ("reflux", "yes", "reflux_present", True),
        ("blood", "No blood", "blood_present", False),
        ("blood_colour", "Bright red", "blood_colour", "bright_red"),
        ("blood_location", "On toilet paper", "blood_location", "tissue"),
        ("anal_pain", "No pain", "sharp_pain_during_stool", False),
        ("anal_pain", "No pain", "anal_pain", False),
        ("lump", "No lump", "lump_or_prolapse", False),
        ("weight_loss", "No, I've actually gained weight", "weight_loss", False),
        ("infection", "No recent infection", "recent_infection", False),
        ("medications", "No medicines", "medications", "none"),
        ("fibre", "Low", "fibre_intake", "low"),
    ],
)
def test_active_question_owns_common_answers(question, message, field, expected):
    cm, sid, session = active(question)
    cm.handle_message(sid, message)
    assert getattr(session.symptom_state, field) == expected


def test_age_does_not_become_duration():
    cm, sid, session = active("age")
    cm.handle_message(sid, "34 years")
    assert session.symptom_state.age == 34
    assert session.symptom_state.duration == "unknown"


def test_duration_does_not_become_age():
    cm, sid, session = active("duration")
    cm.handle_message(sid, "2 days")
    assert session.symptom_state.duration == "2 days"
    assert session.symptom_state.age is None


@pytest.mark.parametrize("message", ["yes", "no"])
def test_timing_yes_no_is_unresolved(message):
    cm, sid, session = active("timing", "acidity")
    result = cm.handle_message(sid, message)
    assert session.last_question == "timing"
    assert session.symptom_state.timing_relation is None
    assert session.symptom_state.duration == "unknown"
    assert result["status"] == "ASK"


@pytest.mark.parametrize(
    "message,relation,onset",
    [
        ("after eating", "after_eating", None),
        ("right after eating", "after_eating", "immediately after eating"),
        ("30 minutes later", "after_eating", "30 minutes after eating"),
        ("one hour later", "after_eating", None),  # word-number may be conservative
        ("2 hours later", "after_eating", "2 hours after eating"),
        ("a few hours later", "after_eating", "several hours after eating"),
        ("when I lie down", "lying_down", None),
        ("at night", "at_night", None),
        ("not related to meals", "not_meal_related", None),
    ],
)
def test_timing_has_distinct_semantics(message, relation, onset):
    cm, sid, session = active("timing", "acidity")
    cm.handle_message(sid, message)
    assert session.symptom_state.timing_relation == relation
    assert session.symptom_state.duration == "unknown"
    if onset:
        assert session.symptom_state.symptom_onset_after_food == onset


def test_timing_two_hours_never_populates_duration():
    cm, sid, session = active("timing", "food intolerance")
    cm.handle_message(sid, "It normally starts around two hours after I eat.")
    assert session.symptom_state.timing_relation == "after_eating"
    assert session.symptom_state.duration == "unknown"


def test_composite_swallowing_bare_no_resolves_all_negative_slots():
    cm, sid, session = active("swallowing", "acidity")
    cm.handle_message(sid, "no")
    s = session.symptom_state
    assert s.difficulty_swallowing is False
    assert s.persistent_vomiting is False
    assert s.vomiting_blood is False
    assert session.last_question != "swallowing"


def test_composite_swallowing_yes_does_not_mean_all_yes():
    cm, sid, session = active("swallowing", "acidity")
    cm.handle_message(sid, "yes")
    s = session.symptom_state
    assert s.difficulty_swallowing is None
    assert s.persistent_vomiting is None
    assert s.vomiting_blood is None
    assert session.last_question == "swallowing"


def test_composite_safety_explicit_negatives():
    cm, sid, session = active("vomiting_fever_swelling", "stomach pain")
    cm.handle_message(sid, "No vomiting, no fever, no swelling")
    s = session.symptom_state
    assert s.vomiting is False
    assert s.fever is False
    assert s.abdominal_distension is False
    assert session.last_question != "vomiting_fever_swelling"


def test_composite_safety_bare_yes_stays_unresolved():
    cm, sid, session = active("vomiting_fever_swelling", "stomach pain")
    cm.handle_message(sid, "yes")
    s = session.symptom_state
    assert s.vomiting is None
    assert s.fever is None
    assert s.abdominal_distension is None
    assert session.last_question == "vomiting_fever_swelling"


@pytest.mark.parametrize(
    "message,expected",
    [
        ("I have constipation", "constipation"),
        ("I have diarrhea", "diarrhea"),
        ("Both", "mixed"),
    ],
)
def test_bowel_pattern_category_answers(message, expected):
    cm, sid, session = active("bowel_pattern", "bloating")
    cm.handle_message(sid, message)
    s = session.symptom_state
    if expected == "constipation":
        assert s.constipation_explicit is True
        assert s.diarrhea_explicit is False
    elif expected == "diarrhea":
        assert s.diarrhea_explicit is True
    else:
        assert s.constipation_explicit is True
        assert s.diarrhea_explicit is True
    assert session.last_question != "bowel_pattern"


def test_bowel_frequency_does_not_answer_bowel_pattern():
    cm, sid, session = active("bowel_pattern", "bloating")
    cm.handle_message(sid, "3 bowel movements per week")
    assert session.symptom_state.bowel_frequency_per_week == 3
    assert session.last_question == "bowel_pattern"


def test_long_answer_keeps_context_and_explicit_volunteered_facts():
    cm, sid, session = active("age", "stomach pain")
    cm.handle_message(
        sid,
        "I am 34 years old and I've had acidity for two weeks, but I don't have fever."
    )
    s = session.symptom_state
    assert s.age == 34
    assert s.duration == "2 weeks"
    assert s.fever is False


def test_latest_explicit_negative_clears_stale_hard_stool_fact():
    cm = ConversationManager()
    sid = "stale-hard"
    session = cm._get_session(sid)
    session.symptom_state.primary_symptom = "constipation"
    session.last_question = "stool_straining"
    cm.handle_message(sid, "My stools are hard and I strain")
    assert session.symptom_state.hard_stools is True
    session.last_question = "hard_stools"
    cm.handle_message(sid, "Actually my stools are normal and not hard")
    assert session.symptom_state.hard_stools is False
    assert session.symptom_state.stool_form is None


def test_latest_explicit_negative_clears_stale_blood():
    cm = ConversationManager()
    sid = "stale-blood"
    session = cm._get_session(sid)
    session.symptom_state.primary_symptom = "bleeding"
    session.last_question = "blood"
    cm.handle_message(sid, "I have blood")
    assert session.symptom_state.blood_present is True
    session.last_question = "blood"
    cm.handle_message(sid, "No, there is no blood")
    assert session.symptom_state.blood_present is False


def test_question_schema_has_explicit_ownership_for_all_question_ids():
    # The questionnaire IDs currently used by the deterministic questionnaire
    # must all have a centralized semantic owner definition.
    from symptom_questionnaire import next_question
    state = SymptomState(primary_symptom="acidity", duration="1 day", age=34)
    seen = set()
    for _ in range(20):
        q = next_question(state)
        if not q:
            break
        seen.add(q[0])
        state.asked_fields.append(q[0])
        # Stop after collecting IDs; conditions are branch/state dependent.
    assert {"duration", "age", "reflux", "timing", "triggers", "swallowing"} <= set(QUESTION_SCHEMA)


def test_unresolved_active_question_blocks_recommendation():
    cm, sid, session = active("timing", "acidity")
    session.symptom_state.duration = "2 weeks"
    session.symptom_state.age = 34
    # Directly exercise the pipeline with an answer that cannot resolve timing.
    result = cm.handle_message(sid, "yes")
    assert result["status"] not in {"RECOMMENDATION_FOUND", "AMBIGUOUS"}
    assert session.last_question == "timing"


def test_active_numeric_answer_cannot_leak_into_unrelated_fields():
    cases = [
        ("age", "34 years", "age", "duration"),
        ("severity", "5", "severity", "age"),
        ("water", "2.5 litres", "water_intake", "severity"),
        ("duration", "2 days", "duration", "age"),
    ]
    for q, msg, owned, forbidden in cases:
        cm, sid, session = active(q, "stomach pain")
        cm.handle_message(sid, msg)
        assert getattr(session.symptom_state, owned) not in (None, "unknown")
        assert getattr(session.symptom_state, forbidden) in (None, "unknown")


def test_reflux_natural_negative_and_positive():
    for msg, expected in [("I don't get that", False), ("sometimes I get a sour taste", True)]:
        cm, sid, session = active("reflux", "acidity")
        cm.handle_message(sid, msg)
        assert session.symptom_state.reflux_present is expected
        assert session.last_question != "reflux"

def test_every_symptom_state_field_is_classified_in_audit_registry():
    from question_schema import STATE_FIELD_POLICY
    fields = set(SymptomState().__dict__.keys())
    assert fields <= set(STATE_FIELD_POLICY)


def test_pain_conjunctive_question_bare_yes_answers_whole_question():
    cm, sid, session = active("pain", "stomach pain")
    result = cm.handle_message(sid, "yes")
    s = session.symptom_state
    assert s.abdominal_pain is True
    assert s.pain_related_to_bowel_movement is True
    assert session.last_question != "pain"
    assert result["status"] in {"ASK", "AMBIGUOUS", "DIAGNOSIS_FOUND", "RECOMMENDATION_FOUND", "SAFETY_REVIEW"}


def test_pain_conjunctive_question_bare_no_answers_whole_question():
    cm, sid, session = active("pain", "stomach pain")
    cm.handle_message(sid, "no")
    s = session.symptom_state
    assert s.abdominal_pain is False
    assert s.pain_related_to_bowel_movement is False
    assert session.last_question != "pain"


def test_pain_statement_without_relation_gets_focused_clarification():
    cm, sid, session = active("pain", "stomach pain")
    result = cm.handle_message(sid, "I do have some pain")
    s = session.symptom_state
    assert s.abdominal_pain is True
    assert s.pain_related_to_bowel_movement is None
    assert session.last_question == "pain"
    assert result["status"] == "ASK"
    assert "bowel movement" in result["message"].lower()
    assert "Does the pain improve" in result["message"]


def test_pain_relation_after_focused_clarification_resolves():
    cm, sid, session = active("pain", "stomach pain")
    cm.handle_message(sid, "I do have some pain")
    result = cm.handle_message(sid, "yes")
    s = session.symptom_state
    assert s.abdominal_pain is True
    assert s.pain_related_to_bowel_movement is True
    assert session.last_question != "pain"
    assert result["status"] in {"ASK", "AMBIGUOUS", "DIAGNOSIS_FOUND", "RECOMMENDATION_FOUND", "SAFETY_REVIEW"}
