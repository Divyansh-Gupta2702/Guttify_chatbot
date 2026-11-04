"""Regression contracts for one-field questions and multi-symptom sequencing."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from intent_parser import SymptomState
from question_schema import QUESTION_SCHEMA, resolve_against_active_question
from symptom_questionnaire import next_question


INDEPENDENT_QUESTION_IDS = {
    "hard_stools", "straining", "incomplete_evacuation",
    "abdominal_pain_screen", "pain_bowel_relation",
    "anal_discomfort_screen", "sharp_pain_during_stool",
    "mucus", "night_time_symptoms", "vomiting", "fever",
    "abdominal_distension", "difficulty_swallowing",
    "persistent_vomiting", "vomiting_blood", "constipation_screen",
    "diarrhea_screen", "gas_screen", "bloating_screen",
}


def _base_state(**kwargs):
    values = {"duration": "2 days", "age": 30}
    values.update(kwargs)
    return SymptomState(**values)


def test_each_new_symptom_question_owns_exactly_one_state_field():
    for question_id in INDEPENDENT_QUESTION_IDS:
        assert question_id in QUESTION_SCHEMA
        assert len(QUESTION_SCHEMA[question_id].fields) == 1, question_id


def test_gas_branch_asks_bloating_as_a_separate_question():
    state = _base_state(primary_symptom="gas", gas=True)
    question = next_question(state)
    assert question is not None
    assert question[0] == "bloating_screen"
    assert "bloating" in question[1].lower()
    assert "gas" not in question[1].lower()


def test_bloating_branch_asks_gas_as_a_separate_question():
    state = _base_state(primary_symptom="bloating", bloating=True)
    question = next_question(state)
    assert question is not None
    assert question[0] == "gas_screen"
    assert "gas" in question[1].lower()
    assert "bloating" not in question[1].lower()


def test_compound_symptoms_use_independent_question_ids():
    state = _base_state(primary_symptom="constipation")
    question = next_question(state)
    assert question is not None
    assert question[0] == "bowel_frequency"
    state.bowel_frequency_per_week = 3
    state.asked_fields.append("bowel_frequency")
    question = next_question(state)
    assert question is not None
    assert question[0] == "stool_form"
    assert "[[BRISTOL_STOOL_CHART]]" in question[1]


def test_secondary_symptom_branch_is_not_lost_after_primary_branch():
    state = _base_state(
        primary_symptom="constipation",
        secondary_symptoms=["diarrhea"],
        bowel_frequency_per_week=3,
        stool_form=4,
        hard_stools=False,
        straining=False,
        incomplete_evacuation=False,
        bloating=False,
        abdominal_pain=False,
        blood_present=False,
        anal_pain=False,
        sharp_pain_during_stool=False,
        vomiting=False,
        fever=False,
        abdominal_distension=False,
        water_intake="2 litres",
        fibre_intake="average",
        medications="none",
    )
    state.asked_fields.extend([
        "bowel_frequency", "stool_form", "straining", "incomplete_evacuation",
        "bloating_screen", "abdominal_pain_screen", "blood",
        "anal_discomfort_screen", "sharp_pain_during_stool", "vomiting",
        "fever", "abdominal_distension", "water", "fibre", "medications",
    ])
    question = next_question(state)
    assert question is not None
    assert question[0] == "daily_frequency"


def test_independent_boolean_questions_resolve_bare_yes_and_no():
    yes = resolve_against_active_question("gas_screen", "yes")
    no = resolve_against_active_question("bloating_screen", "no")
    assert yes["status"] == "answered"
    assert yes["values"] == {"gas": True}
    assert no["status"] == "answered"
    assert no["values"] == {"bloating": False}


def test_legacy_composite_question_ids_remain_for_saved_checkpoints():
    for question_id in (
        "stool_straining", "constipation", "bloating_pain", "pain",
        "blood_mucus", "night_weight_fever", "vomiting_fever",
        "vomiting_fever_swelling", "swallowing", "weight_swallow",
    ):
        assert question_id in QUESTION_SCHEMA


def test_valid_customer_age_skips_age_question():
    state = _base_state(primary_symptom="constipation", age=28)
    question = next_question(state)
    assert question is not None
    assert question[0] != "age"


def test_missing_customer_age_is_requested_when_required():
    state = _base_state(primary_symptom="constipation", age=None)
    question = next_question(state)
    assert question is not None
    assert question[0] == "age"
