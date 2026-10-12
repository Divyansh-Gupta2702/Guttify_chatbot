
import pytest

from guttify_agent import ConversationManager
from intent_parser import SymptomState, extract_symptoms
from symptom_questionnaire import next_question


def test_mixed_acidity_bloating_bleeding_prioritizes_bleeding():
    cm = ConversationManager()
    sid = "bleeding-priority-mixed"
    first = cm.handle_message(
        sid,
        "I am feeling acidity as well as bloating and there is blood in my poop",
    )
    session = cm.sessions[sid]
    assert session.symptom_state.blood_present is True
    assert session.symptom_state.primary_symptom == "acidity"
    assert "bloating" in session.symptom_state.secondary_symptoms
    assert "bleeding" in session.symptom_state.secondary_symptoms
    assert first["status"] == "ASK"
    assert session.last_question == "duration"

    cm.handle_message(sid, "1 week")
    result = cm.handle_message(sid, "54")
    assert result["status"] == "ASK"
    assert session.last_question == "blood_colour"
    assert "sour taste" not in result["message"].lower()
    assert "blood" in result["message"].lower()


def test_bleeding_alone_starts_bleeding_assessment():
    cm = ConversationManager()
    sid = "bleeding-alone"
    cm.handle_message(sid, "There is blood in my poop")
    session = cm.sessions[sid]
    cm.handle_message(sid, "1 week")
    result = cm.handle_message(sid, "54")
    assert session.symptom_state.blood_present is True
    assert session.last_question == "blood_colour"
    assert result["status"] == "ASK"


@pytest.mark.parametrize(
    "message",
    [
        "bloody stool",
        "bloody poop",
        "bloody poops",
        "blood in my stool",
        "blood in my poop",
        "poop with blood",
        "stool with blood",
        "blood while pooping",
        "blood when I poop",
        "seeing blood in stool",
    ],
)
def test_bleeding_variants_normalize_to_bleeding(message):
    primary, secondary = extract_symptoms(message)
    assert "bleeding" in ({primary} | set(secondary))


def test_duration_is_reused_in_bleeding_branch():
    state = SymptomState(
        primary_symptom="acidity",
        duration="1 week",
        age=54,
        blood_present=True,
    )
    assert next_question(state)[0] == "blood_colour"


def test_age_is_reused_in_bleeding_branch():
    state = SymptomState(
        primary_symptom="acidity",
        duration="1 week",
        age=54,
        blood_present=True,
    )
    assert next_question(state)[0] == "blood_colour"


def test_answered_blood_colour_is_skipped():
    state = SymptomState(
        primary_symptom="acidity",
        duration="1 week",
        age=54,
        blood_present=True,
        blood_colour="bright_red",
    )
    assert next_question(state)[0] == "blood_location"


def test_no_premature_bleeding_assessment():
    cm = ConversationManager()
    sid = "bleeding-no-premature-assessment"
    cm.handle_message(sid, "I have acidity and blood in my stool")
    cm.handle_message(sid, "1 week")
    result = cm.handle_message(sid, "54")
    assert result["status"] == "ASK"
    assert session_last_question(cm, sid) == "blood_colour"


def session_last_question(cm, sid):
    return cm.sessions[sid].last_question


def test_swallowing_no_is_answered_and_advances():
    cm = ConversationManager()
    sid = "swallowing-no"
    session = cm._get_session(sid)
    session.symptom_state.primary_symptom = "acidity"
    session.last_question = "swallowing"
    result = cm.handle_message(sid, "No")
    assert session.symptom_state.difficulty_swallowing is False
    assert session.symptom_state.persistent_vomiting is False
    assert session.symptom_state.vomiting_blood is False
    assert result["status"] == "ASK"
    assert session.last_question != "swallowing"


def test_timing_at_night_resolves_and_advances():
    cm = ConversationManager()
    sid = "timing-regression"
    session = cm._get_session(sid)
    session.symptom_state.primary_symptom = "acidity"
    session.last_question = "timing"
    result = cm.handle_message(sid, "At night")
    assert session.symptom_state.timing_relation == "at_night"
    assert result["status"] == "ASK"
    assert session.last_question != "timing"


def test_bleeding_safety_priority():
    cm = ConversationManager()
    result = cm.handle_message("bleeding-safety", "I have black tarry stool")
    assert result["status"] == "SAFETY_REVIEW"
    assert result["safety"]["red_flag"] is True


def test_bleeding_branch_logs_priority_and_missing_fields(caplog):
    cm = ConversationManager()
    sid = "bleeding-logging"
    cm.handle_message(sid, "I have acidity and blood in my stool")
    cm.handle_message(sid, "1 week")
    with caplog.at_level("INFO"):
        cm.handle_message(sid, "54")
    joined = "\n".join(caplog.messages)
    assert "[QUESTION][BRANCH]" in joined
    assert "reason=bleeding_priority" in joined
    assert "[QUESTION][BLEEDING]" in joined
    assert "next=blood_colour" in joined


def test_false_is_not_unanswered_for_swallowing():
    state = SymptomState(
        primary_symptom="acidity",
        duration="1 week",
        age=54,
        difficulty_swallowing=False,
        persistent_vomiting=False,
        vomiting_blood=False,
    )
    assert next_question(state)[0] == "reflux"
