from intent_parser import SymptomState
from symptom_summary import build_symptom_summary
from clinical_rule_engine import _bowel_patterns, evaluate as evaluate_screening
from guttify_agent import ConversationManager


def test_summary_includes_selected_bristol_type_and_known_symptoms():
    state = SymptomState(
        primary_symptom="constipation",
        secondary_symptoms=["bloating"],
        duration="2 weeks",
        age=32,
        stool_form=2,
        straining=True,
    )
    summary = build_symptom_summary(state)
    assert "Symptoms reported: constipation, bloating" in summary
    assert "Duration: 2 weeks" in summary
    assert "Age: 32" in summary
    assert "Bristol Stool Chart: Type 2" in summary
    assert "Straining to pass stool: Yes" in summary
    assert "not a confirmed medical diagnosis" in summary


def test_summary_does_not_invent_unknown_bristol_type():
    state = SymptomState(primary_symptom="bloating", stool_form="unknown")
    summary = build_symptom_summary(state)
    assert "Bristol Stool Chart: Not sure / not provided" in summary
    assert "Type None" not in summary


def test_bristol_types_support_existing_bowel_pattern_rules_conservatively():
    hard = SymptomState(stool_form=2, straining=True)
    normal = SymptomState(stool_form=4)
    soft = SymptomState(stool_form=5)
    watery = SymptomState(stool_form=7)

    assert _bowel_patterns(hard)[0] is True
    assert _bowel_patterns(normal)[0] is False
    assert _bowel_patterns(soft)[1] is False
    assert _bowel_patterns(watery)[1] is True


def test_bristol_type_is_included_in_deterministic_assessment_evidence():
    manager = ConversationManager()
    state = SymptomState(stool_form=6)
    screening = {"evidence": ["loose stools"]}
    manager._add_bristol_evidence(screening, state)
    assert "Bristol Stool Chart type 6: mushy stool with ragged edges" in screening["evidence"]
    # Calling it twice must not duplicate the evidence line.
    manager._add_bristol_evidence(screening, state)
    assert screening["evidence"].count("Bristol Stool Chart type 6: mushy stool with ragged edges") == 1


def _complete_constipation_session(manager, sid):
    session = manager._get_session(sid)
    state = session.symptom_state
    state.primary_symptom = "constipation"
    state.duration = "2 weeks"
    state.age = 32
    state.bowel_frequency_per_week = 2
    state.stool_form = 2
    state.straining = True
    state.incomplete_evacuation = False
    state.abdominal_pain = False
    state.blood_present = False
    state.weight_loss = False
    state.vomiting = False
    state.fever = False
    state.abdominal_distension = False
    state.medications = "none"
    state.constipation_explicit = True
    state.asked_fields = [
        "duration", "weight_loss", "age", "bowel_frequency", "stool_straining",
        "incomplete_evacuation", "bloating_pain", "pain_relation", "blood",
        "anal_pain", "vomiting_fever_swelling", "water", "fibre", "medications",
        "stool_form", "daily_frequency", "pain", "infection", "blood_mucus",
        "night_weight_fever", "reflux", "timing", "triggers", "swallowing",
    ]
    # This fixture represents a completed questionnaire. Any asked fields not
    # represented in its sample values were explicitly accepted as unknown.
    from question_schema import question_has_answer
    state.answered_unknown_fields = [
        field for field in state.asked_fields if not question_has_answer(state, field)
    ]
    return session


def test_completed_nonurgent_assessment_pauses_for_summary_confirmation():
    manager = ConversationManager()
    sid = "phase1-summary-review"
    session = _complete_constipation_session(manager, sid)

    result = manager.handle_message(sid, "continue")

    assert result["status"] == "SUMMARY_REVIEW"
    assert "Symptoms reported: constipation" in result["message"]
    assert session.awaiting_summary_confirmation is True
    assert session.diagnosis_complete is False


def test_summary_bristol_correction_is_reviewed_before_assessment():
    manager = ConversationManager()
    sid = "phase1-summary-bristol-correction"
    session = _complete_constipation_session(manager, sid)
    first = manager.handle_message(sid, "continue")
    assert first["status"] == "SUMMARY_REVIEW"

    corrected = manager.handle_message(sid, "Bristol type 4")
    assert corrected["status"] == "SUMMARY_REVIEW"
    assert session.symptom_state.stool_form == 4
    assert "Bristol Stool Chart: Type 4" in corrected["message"]
    assert session.diagnosis_complete is False


def test_summary_confirmation_does_not_turn_yes_into_red_flag_facts():
    manager = ConversationManager()
    sid = "phase1-summary-confirm"
    session = _complete_constipation_session(manager, sid)
    assert manager.handle_message(sid, "continue")["status"] == "SUMMARY_REVIEW"

    result = manager.handle_message(sid, "yes")

    assert result["status"] != "SUMMARY_REVIEW"
    assert session.symptom_state.vomiting is False
    assert session.symptom_state.abdominal_distension is False
    assert session.symptom_state.weight_loss is False
    assert session.symptom_state.red_flags == []


def test_summary_no_then_specific_correction_reopens_review():
    manager = ConversationManager()
    sid = "phase1-summary-no-correction"
    session = _complete_constipation_session(manager, sid)
    manager.handle_message(sid, "continue")

    prompt = manager.handle_message(sid, "no")
    assert prompt["status"] == "ASK"
    assert session.summary_correction_mode is True

    corrected = manager.handle_message(sid, "Bristol type 6")
    assert corrected["status"] == "SUMMARY_REVIEW"
    assert session.symptom_state.stool_form == 6
    assert "Bristol Stool Chart: Type 6" in corrected["message"]


def test_bristol_selection_can_change_supporting_pattern_with_other_symptoms():
    # Stool form is supporting evidence: it changes the bowel-pattern assessment
    # only in combination with symptoms such as straining, not as a standalone diagnosis.
    hard_stool_state = SymptomState(primary_symptom="bloating", stool_form=2, straining=True)
    normal_stool_state = SymptomState(primary_symptom="bloating", stool_form=4, straining=True)

    hard_pattern = evaluate_screening(hard_stool_state)
    normal_pattern = evaluate_screening(normal_stool_state)

    assert hard_pattern["pattern"] == "Constipation-associated bloating pattern"
    assert normal_pattern["pattern"] == "Functional gas/bloating pattern"
