"""Regression tests for issues reproduced in the read-only GutGPT audit."""
from safety_checker import detect_red_flags, is_pregnancy_or_lactation
from guttify_agent import ConversationManager
from question_schema import question_has_answer
from intent_parser import SymptomState


def test_punctuation_does_not_hide_separate_red_flags():
    assert "chest pain" in detect_red_flags("no fever, chest pain")
    assert "severe abdominal pain" in detect_red_flags("no pain, severe stomach pain")
    assert "fainting or loss of consciousness" in detect_red_flags("no energy, fainted yesterday")
    assert "vomiting blood" in detect_red_flags("no fever, vomiting blood")
    assert "black/tarry stool" in detect_red_flags("No, I have black stool")


def test_negated_fainting_is_not_a_red_flag():
    assert "fainting or loss of consciousness" not in detect_red_flags("I haven't fainted")


def test_bleeding_with_lightheadedness_is_detected():
    flags = detect_red_flags("Bloody stool and feeling lightheaded")
    assert "fainting/dizziness with bleeding" in flags


def test_pregnancy_detector_respects_negation_and_third_party():
    assert not is_pregnancy_or_lactation("I am not pregnant")
    assert not is_pregnancy_or_lactation("my wife is pregnant")
    assert not is_pregnancy_or_lactation("stopped breastfeeding")
    assert is_pregnancy_or_lactation("I am pregnant")
    assert is_pregnancy_or_lactation("I am breastfeeding")


def test_red_flag_remains_active_after_follow_up():
    manager = ConversationManager()
    first = manager.handle_message("sticky-red-flag", "My stool is black and tarry")
    second = manager.handle_message("sticky-red-flag", "Sorry, it is just piles for two weeks")
    assert first["status"] == "SAFETY_REVIEW"
    assert second["status"] == "SAFETY_REVIEW"
    assert second["screening"]["action"] == "urgent_medical_evaluation"
    assert manager.sessions["sticky-red-flag"].symptom_state.red_flags


def test_blood_positive_evidence_is_not_overwritten_by_no_pain():
    manager = ConversationManager()
    session = manager._get_session("blood-state")
    session.last_question = "anal_pain"
    session.symptom_state.primary_symptom = "piles"
    session.symptom_state.blood_present = True
    session.symptom_state.blood_colour = "bright_red"
    manager.handle_message("blood-state", "No pain. Blood is bright red on the paper")
    state = manager.sessions["blood-state"].symptom_state
    assert state.blood_present is True
    assert state.blood_colour == "bright_red"


def test_unknown_does_not_satisfy_bleeding_safety_discriminators():
    state = SymptomState()
    state.answered_unknown_fields = ["blood_colour", "anal_pain"]
    assert not question_has_answer(state, "blood_colour")
    assert not question_has_answer(state, "anal_pain")


def test_product_concern_recommendation_does_not_mark_clinical_diagnosis_complete():
    manager = ConversationManager()
    result = manager.handle_message("product-complete", "I have dull skin")
    assert result["status"] == "RECOMMENDATION_FOUND"
    assert manager.sessions["product-complete"].awaiting_close is True
    assert manager.sessions["product-complete"].diagnosis_complete is False
