"""Conversation-level guards against questionnaire cycles and re-asking."""
import json

from guttify_agent import ConversationManager
from question_schema import question_has_answer
from symptom_questionnaire import next_question
from test_all_symptom_questionnaire_completeness import TestAllSymptomQuestionnaires
from clinical_rule_engine import evaluate
from intent_parser import SymptomState


def _clinical_signature(state):
    values = state.to_dict()
    # Question history is intentionally excluded: a repeated clinical state
    # with the same pending field/component is a genuine stalled transition.
    values.pop("asked_fields", None)
    return json.dumps(values, sort_keys=True, default=str)


def test_scripted_questionnaire_conversations_terminate_without_stalled_states():
    scripts = TestAllSymptomQuestionnaires()
    for _, initial in scripts.BRANCHES:
        manager = ConversationManager()
        session_id = "loop-audit-" + initial.replace(" ", "-")
        result = manager.handle_message(session_id, initial)
        visited_pending_states = set()
        while True:
            session = manager.sessions[session_id]
            question_id = session.last_question
            if question_id is None:
                assert next_question(session.symptom_state) is None
                assert result["status"] != "ASK"
                break

            signature = (
                question_id,
                session.active_question_component,
                _clinical_signature(session.symptom_state),
            )
            assert signature not in visited_pending_states, (
                f"Stalled assessment for {initial}; question={question_id}; "
                f"component={session.active_question_component}"
            )
            visited_pending_states.add(signature)

            was_answered = question_has_answer(session.symptom_state, question_id)
            response = scripts.ANSWERS[question_id]
            result = manager.handle_message(session_id, response)
            if was_answered:
                assert manager.sessions[session_id].last_question != question_id, (
                    f"Resolved question {question_id} was selected again for {initial}"
                )


def test_frequency_answer_advances_and_preserves_count_without_groq(monkeypatch):
    import nlu_extractor

    monkeypatch.setattr(nlu_extractor, "_llm_extract", lambda *args, **kwargs: None)
    manager = ConversationManager()
    session_id = "loop-audit-daily-count"
    session = manager._get_session(session_id)
    session.symptom_state.primary_symptom = "diarrhea"
    session.last_question = "daily_frequency"

    result = manager.handle_message(session_id, "3 loose stools per day")

    assert session.symptom_state.bowel_frequency_per_day == 3
    assert session.last_question != "daily_frequency"
    assert result["status"] != "ASK" or "loose or watery stools" not in result["message"]


def test_explicit_blood_correction_updates_state_and_activates_bleeding_followups():
    manager = ConversationManager()
    session_id = "loop-audit-corrected-bleeding"
    for response in (
        "I am constipated", "2 weeks", "30", "2 times a week",
        "4", "no", "no", "no", "no blood", "no anal discomfort",
    ):
        manager.handle_message(session_id, response)

    session = manager.sessions[session_id]
    assert session.symptom_state.blood_present is False
    assert session.last_question == "abdominal_pain_screen"

    manager.handle_message(session_id, "Actually, I noticed blood")
    assert session.symptom_state.blood_present is True
    # Bleeding retains priority once explicitly corrected.
    manager.handle_message(session_id, "no abdominal pain")
    assert manager.sessions[session_id].last_question == "blood_colour"


def test_every_rule_engine_outcome_pattern_remains_reachable():
    cases = [
        ("Anal irritation/burning symptom pattern", {"primary_symptom": "anal burning", "blood_present": False}),
        ("Anal swelling/lump symptom pattern", {"primary_symptom": "anal swelling", "blood_present": False, "lump_or_prolapse": True}),
        ("Bowel-related abdominal pain pattern", {"primary_symptom": "stomach pain", "abdominal_pain": True, "pain_related_to_bowel_movement": True, "constipation_explicit": True, "bowel_frequency_per_week": 2, "stool_form": 2}),
        ("Constipation-associated bloating pattern", {"primary_symptom": "bloating", "constipation_explicit": True, "bowel_frequency_per_week": 2, "stool_form": 2, "straining": True}),
        ("Diarrhea pattern", {"primary_symptom": "diarrhea", "diarrhea_explicit": True, "bowel_frequency_per_day": 4, "stool_form": 6}),
        ("Dyspepsia/indigestion pattern", {"primary_symptom": "indigestion"}),
        ("Food-triggered gas/bloating pattern", {"primary_symptom": "bloating", "food_trigger": "dairy"}),
        ("Functional constipation pattern", {"primary_symptom": "constipation", "constipation_explicit": True, "bowel_frequency_per_week": 2, "stool_form": 2, "straining": True}),
        ("Functional gas/bloating pattern", {"primary_symptom": "bloating"}),
        ("IBS-C pattern", {"primary_symptom": "constipation", "constipation_explicit": True, "abdominal_pain": True, "pain_related_to_bowel_movement": True, "duration": "6 months", "bowel_frequency_per_week": 2, "stool_form": 2, "straining": True}),
        ("IBS-D pattern", {"primary_symptom": "diarrhea", "diarrhea_explicit": True, "constipation_explicit": False, "abdominal_pain": True, "pain_related_to_bowel_movement": True, "duration": "6 months", "bowel_frequency_per_day": 5, "stool_form": 6}),
        ("IBS-M (mixed) pattern", {"primary_symptom": "stomach pain", "constipation_explicit": True, "diarrhea_explicit": True, "abdominal_pain": True, "pain_related_to_bowel_movement": True, "duration": "6 months", "bowel_frequency_per_week": 2, "bowel_frequency_per_day": 4, "stool_form": 6}),
        ("Insufficiently characterized anal-symptom pattern", {"primary_symptom": "anal fissures", "blood_present": False, "sharp_pain_during_stool": False}),
        ("Insufficiently characterized gut symptom pattern", {}),
        ("Nonspecific abdominal pain pattern", {"primary_symptom": "stomach pain", "abdominal_pain": True, "pain_location": "lower abdomen", "severity": "4"}),
        ("Possible anal fissure pattern", {"primary_symptom": "anal fissures", "blood_present": False, "sharp_pain_during_stool": True}),
        ("Possible food-triggered intolerance pattern", {"primary_symptom": "food intolerance", "food_trigger": "dairy"}),
        ("Possible food-triggered symptom pattern", {"primary_symptom": "food intolerance"}),
        ("Possible gastrointestinal bleeding", {"primary_symptom": "diarrhea", "blood_present": True, "blood_colour": "black"}),
        ("Possible hemorrhoid pattern", {"primary_symptom": "piles", "blood_present": True, "blood_colour": "bright_red", "sharp_pain_during_stool": False, "lump_or_prolapse": True}),
        ("Possible medication-associated constipation pattern", {"primary_symptom": "constipation", "constipation_explicit": True, "bowel_frequency_per_week": 2, "stool_form": 2, "straining": True, "medications": "reported"}),
        ("Recent-infection or food-related diarrhea pattern", {"primary_symptom": "diarrhea", "diarrhea_explicit": True, "bowel_frequency_per_day": 4, "stool_form": 6, "recent_infection": True}),
        ("Rectal bleeding of unclear cause", {"primary_symptom": "piles", "blood_present": True, "blood_colour": "bright_red", "sharp_pain_during_stool": False, "lump_or_prolapse": False}),
        ("Rectal bleeding — pattern not yet distinguishable", {"primary_symptom": "piles", "blood_present": True}),
        ("Red-flag presentation", {"primary_symptom": "bloating", "red_flags": ["severe abdominal pain"]}),
        ("Reflux/GERD-like symptom pattern", {"primary_symptom": "acidity"}),
        ("Upper-abdominal meal-related dyspepsia pattern", {"primary_symptom": "stomach pain", "food_related": True, "pain_location": "upper abdomen"}),
    ]
    for expected, updates in cases:
        state = SymptomState(
            duration="2 months", age=25, weight_loss=False, fever=False,
            family_history_gi=False, night_time_symptoms=False, red_flags=[],
        )
        for field, value in updates.items():
            setattr(state, field, value)
        result = evaluate(state)
        assert result["pattern"] == expected, (expected, result["pattern"])
