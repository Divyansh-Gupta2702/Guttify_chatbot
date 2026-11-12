from pathlib import Path
from fastapi.responses import FileResponse

from intent_parser import SymptomState, extract_age
from question_schema import QUESTION_SCHEMA, question_has_answer, validate_question_resolution
from symptom_questionnaire import next_question
from nlu_extractor import extract_natural_facts
from guttify_agent import ConversationManager


def _ready_state(branch):
    return SymptomState(primary_symptom=branch, duration="2 weeks", age=34)


def test_diarrhea_followups_are_single_questions_and_keep_bristol_marker():
    state = _ready_state("diarrhea")
    assert next_question(state)[0] == "daily_frequency"
    state.bowel_frequency_per_day = 3
    name, question = next_question(state)
    assert name == "stool_form"
    assert "[[BRISTOL_STOOL_CHART]]" in question
    assert "1 to 7" in question


def test_constipation_requests_bristol_type_and_then_straining():
    state = _ready_state("constipation")
    state.bowel_frequency_per_week = 2
    name, question = next_question(state)
    assert name == "stool_form"
    assert "[[BRISTOL_STOOL_CHART]]" in question
    state.stool_form = 2
    assert next_question(state)[0] == "straining"


def test_new_boolean_question_ids_own_one_field_each():
    atomic_ids = {
        "mucus", "fever", "vomiting", "abdominal_distension",
        "night_time_symptoms", "difficulty_swallowing", "persistent_vomiting",
        "vomiting_blood", "bloating_screen", "abdominal_pain_screen",
        "pain_bowel_relation", "constipation_screen", "diarrhea_screen",
        "sharp_pain_during_stool", "straining",
    }
    assert all(len(QUESTION_SCHEMA[item].fields) == 1 for item in atomic_ids)
    assert all(QUESTION_SCHEMA[item].answer_kind == "boolean" for item in atomic_ids)


def test_age_parser_rejects_values_outside_customer_profile_range():
    assert extract_age("I am 34") == 34
    assert extract_age("0") is None
    assert extract_age("121 years old") is None


def test_widget_uses_hosted_chart_with_graceful_text_fallback():
    root = Path(__file__).resolve().parents[1]
    widget = (root / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert "${GUTGPT_API_URL}/assets/bristol-stool-chart.png" in widget
    assert 'fallback.className = "bristol-chart-fallback"' in widget
    assert 'messages.addEventListener("error"' in widget
    assert "The chart image could not be displayed" in widget


def test_bristol_chart_route_returns_the_repository_png():
    import app

    response = app.bristol_stool_chart_asset()
    assert isinstance(response, FileResponse)
    assert response.media_type == "image/png"
    assert Path(response.path).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_short_symptom_labels_answer_upper_symptom_question_without_clarification():
    for answer, expected in (
        ("Bloating", "bloating"), ("gas", "gas"), ("acidity", "acidity"),
        ("constipation", "constipation"), ("diarrhea", "diarrhea"),
        ("indigestion", "indigestion"),
    ):
        result = extract_natural_facts(
            answer, "upper_symptoms", SymptomState(primary_symptom="indigestion"),
        )
        assert result["_answer_status"] == "answered"
        assert result["upper_symptoms"] == expected


def test_severity_adjective_survives_short_upper_symptom_answer():
    result = extract_natural_facts(
        "I have severe bloating", "upper_symptoms",
        SymptomState(primary_symptom="indigestion"),
    )
    assert result["_answer_status"] == "answered"
    assert result["upper_symptoms"] == "bloating"
    assert result["severity"] == "severe"


def test_screenshot_indigestion_bloating_flow_accepts_answer_and_retains_severity():
    manager = ConversationManager()
    session_id = "screenshot-exact-flow"
    manager.handle_message(session_id, "Indigestion")
    # The screenshot is a restored customer session; seed the registered age
    # that the PostgreSQL restore path supplies before the next chat turn.
    manager.sessions[session_id].symptom_state.age = 34
    assert manager.handle_message(session_id, "6 weeks")["status"] == "ASK"
    assert manager.handle_message(session_id, "No")["status"] == "ASK"

    result = manager.handle_message(session_id, "Bloating")
    state = manager.sessions[session_id].symptom_state
    assert result["status"] == "ASK"
    assert "make sure I understood" not in result["message"].lower()
    assert state.upper_symptoms == "bloating"
    assert manager.sessions[session_id].last_question == "food_relation"

    result = manager.handle_message(session_id, "I have severe bloating")
    state = manager.sessions[session_id].symptom_state
    assert state.severity == "severe"
    assert state.bloating is True
    assert "I've noted severe bloating" in result["message"]
    assert "triggered or worsened by meals" in result["message"]


def test_confirmed_bowel_symptom_does_not_prompt_as_if_opposite_were_unrelated():
    constipation = _ready_state("gas")
    constipation.secondary_symptoms = ["constipation"]
    constipation.gas = True
    constipation.bloating = True
    constipation.constipation_explicit = True
    constipation.food_related = False
    constipation.abdominal_pain = False
    assert next_question(constipation)[0] == "bowel_frequency"

    diarrhea = _ready_state("gas")
    diarrhea.secondary_symptoms = ["diarrhea"]
    diarrhea.gas = True
    diarrhea.bloating = True
    diarrhea.diarrhea_explicit = True
    diarrhea.food_related = False
    diarrhea.abdominal_pain = False
    assert next_question(diarrhea)[0] == "daily_frequency"


def test_gas_bloating_branch_asks_bristol_type_after_other_followups():
    state = _ready_state("bloating")
    state.bloating = True
    state.gas = True
    state.constipation_explicit = False
    state.diarrhea_explicit = False
    state.food_related = False
    state.abdominal_pain = False
    assert next_question(state)[0] == "stool_form"


def test_invalid_saved_blood_location_does_not_satisfy_safety_followup():
    state = _ready_state("bleeding")
    state.blood_present = True
    state.blood_colour = "bright_red"
    state.blood_location = "not a recognized choice"
    assert next_question(state)[0] == "blood_location"


def test_null_or_invalid_stool_type_cannot_count_as_answered():
    state = _ready_state("diarrhea")
    assert not question_has_answer(state, "stool_form")
    state.stool_form = "not a Bristol type"
    assert not question_has_answer(state, "stool_form")
    resolution = validate_question_resolution({
        "status": "answered", "values": {"stool_form": None},
    })
    assert resolution["status"] == "unresolved"
    assert resolution["values"] == {}
