from pathlib import Path
from fastapi.responses import FileResponse

from intent_parser import SymptomState, extract_age
from question_schema import QUESTION_SCHEMA
from symptom_questionnaire import next_question


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


def test_constipation_hard_stools_and_straining_are_independent():
    state = _ready_state("constipation")
    state.bowel_frequency_per_week = 2
    assert next_question(state)[0] == "hard_stools"
    state.hard_stools = True
    assert next_question(state)[0] == "straining"


def test_new_boolean_question_ids_own_one_field_each():
    atomic_ids = {
        "mucus", "fever", "vomiting", "abdominal_distension",
        "night_time_symptoms", "difficulty_swallowing", "persistent_vomiting",
        "vomiting_blood", "recent_worsening", "bloating", "abdominal_pain",
        "pain_bowel_relation", "constipation_symptom", "diarrhea_symptom",
        "sharp_pain_during_stool",
    }
    assert all(len(QUESTION_SCHEMA[item].fields) == 1 for item in atomic_ids)
    assert all(QUESTION_SCHEMA[item].answer_kind == "boolean" for item in atomic_ids)
    assert len(QUESTION_SCHEMA["food_onset_timing"].fields) == 1
    assert len(QUESTION_SCHEMA["food_symptom"].fields) == 1


def test_age_parser_rejects_values_outside_customer_profile_range():
    assert extract_age("I am 34") == 34
    assert extract_age("0") is None
    assert extract_age("121 years old") is None


def test_widget_uses_hosted_chart_with_graceful_embedded_fallback():
    root = Path(__file__).resolve().parents[1]
    widget = (root / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert "${GUTGPT_API_URL}/bristol-stool-chart.png" in widget
    assert 'data-fallback-src="${BRISTOL_STOOL_CHART_DATA_URI}"' in widget
    assert "image.addEventListener(\"error\"" in widget
    assert "data:image/jpeg;base64," in widget


def test_bristol_chart_route_returns_the_repository_png():
    import app

    response = app.bristol_stool_chart()
    assert isinstance(response, FileResponse)
    assert response.media_type == "image/png"
    assert Path(response.path).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
