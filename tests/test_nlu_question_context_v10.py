
import nlu_extractor
from guttify_agent import ConversationManager


def cm_with_active(sid, question, primary="stomach pain"):
    cm = ConversationManager()
    s = cm._get_session(sid)
    s.last_question = question
    s.symptom_state.primary_symptom = primary
    return cm, s


def test_01_severity_and_no_worsening():
    cm, s = cm_with_active("t1", "severity")
    cm.handle_message("t1", "I would rate it 5 and no not getting worse")
    assert s.symptom_state.severity == "5"
    assert s.symptom_state.recent_worsening is False


def test_02_severity_and_worsening():
    cm, s = cm_with_active("t2", "severity")
    cm.handle_message("t2", "around 7, and yes it's getting worse")
    assert s.symptom_state.severity == "7"
    assert s.symptom_state.recent_worsening is True


def test_03_normal_poops():
    cm, s = cm_with_active("t3", "bowel_pattern")
    cm.handle_message("t3", "I am having normal poops")
    assert s.symptom_state.constipation_explicit is False
    assert s.symptom_state.diarrhea is False
    assert s.last_question != "bowel_pattern"


def test_04_normal_no_constipation_diarrhea():
    cm, s = cm_with_active("t4", "bowel_pattern")
    cm.handle_message("t4", "My stools are normal, no constipation or diarrhea")
    assert s.symptom_state.constipation_explicit is False
    assert s.symptom_state.diarrhea is False


def test_05_vomiting_fever_neither():
    cm, s = cm_with_active("t5", "vomiting_fever")
    cm.handle_message("t5", "No, neither")
    assert s.symptom_state.vomiting is False
    assert s.symptom_state.fever is False
    assert s.last_question != "vomiting_fever"


def test_06_vomiting_fever_not_that_i_know():
    cm, s = cm_with_active("t6", "vomiting_fever")
    cm.handle_message("t6", "not that I know of")
    assert s.symptom_state.vomiting is False
    assert s.symptom_state.fever is False


def test_07_fever_no_vomiting():
    cm, s = cm_with_active("t7", "vomiting_fever")
    cm.handle_message("t7", "I've had a fever but no vomiting")
    assert s.symptom_state.vomiting is False
    assert s.symptom_state.fever is True


def test_08_ambiguous_yes_relationship():
    cm, s = cm_with_active("t8", "pain_relation")
    result = cm.handle_message("t8", "yes I think so")
    assert s.last_question == "pain_relation"
    assert s.symptom_state.food_related is None
    assert s.symptom_state.pain_related_to_bowel_movement is None
    assert "meals" in result["message"].lower() or "bowel" in result["message"].lower()


def test_09_upper_stomach_after_eating():
    cm, s = cm_with_active("t9", "pain_location")
    cm.handle_message("t9", "It's mostly in my upper stomach after eating")
    assert s.symptom_state.pain_location == "upper abdomen"
    assert s.symptom_state.food_related is True


def test_10_duration_yesterday_24_hours():
    cm, s = cm_with_active("t10", "duration")
    cm.handle_message("t10", "Since yesterday, maybe around 24 hours")
    assert s.symptom_state.duration in {"1 day", "24 hours"}


def test_11_multiple_facts_one_turn():
    cm = ConversationManager()
    sid = "t11"
    cm.handle_message(
        sid,
        "I've had upper stomach pain for 2 weeks, around 5/10, mostly after meals, "
        "no vomiting, and my bowel movements are normal.",
    )
    state = cm.sessions[sid].symptom_state
    assert state.primary_symptom == "stomach pain"
    assert state.pain_location == "upper abdomen"
    assert state.duration == "2 weeks"
    assert state.severity == "5"
    assert state.food_related is True
    assert state.vomiting is False
    assert state.bowel_pattern if hasattr(state, "bowel_pattern") else True
    assert state.constipation_explicit is False
    assert state.diarrhea is False


def test_required_question_blocks_progress_when_answer_is_ununderstood():
    cm, session = cm_with_active("t12", "vomiting_fever")
    result = cm.handle_message("t12", "what do you mean?")
    assert result["status"] == "ASK"
    assert session.last_question == "vomiting_fever"
    assert not session.diagnosis_complete
    assert not result.get("recommendations")


def test_malformed_groq_json_falls_back_without_erasing_answer(monkeypatch):
    class Response:
        content = "```json\n{ definitely not valid json }\n```"

    class FakeLLM:
        def invoke(self, prompt):
            return Response()

    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: FakeLLM())
    facts = nlu_extractor.extract_natural_facts(
        "I would rate it 5 and no not getting worse",
        "severity",
        type("S", (), {"to_dict": lambda self: {}})(),
    )
    assert facts["severity"] == "5"
    assert facts["recent_worsening"] is False


def test_13_short_pain_relation_choices():
    cm, s = cm_with_active("t13a", "pain_relation")
    cm.handle_message("t13a", "bowel movements")
    assert s.symptom_state.pain_related_to_bowel_movement is True
    assert s.symptom_state.food_related is None
    assert s.last_question != "pain_relation"

    cm, s = cm_with_active("t13b", "pain_relation")
    cm.handle_message("t13b", "meals")
    assert s.symptom_state.food_related is True
    assert s.symptom_state.pain_related_to_bowel_movement is None
    assert s.last_question != "pain_relation"


def test_14_natural_hour_durations():
    cm, s = cm_with_active("t14a", "duration")
    cm.handle_message("t14a", "for like few hours")
    assert s.symptom_state.duration == "3 hours"
    assert s.last_question != "duration"

    cm, s = cm_with_active("t14b", "duration")
    cm.handle_message("t14b", "2-3 hours")
    assert s.symptom_state.duration == "2-3 hours"
    assert s.last_question != "duration"


def test_natural_incomplete_evacuation_affirmatives():
    for answer in ["absolutely", "yes sometimes", "it does"]:
        cm = ConversationManager()
        sid = "nlu-incomplete-" + answer.replace(" ", "-")
        s = cm._get_session(sid)
        s.primary_symptom = "constipation"
        s.last_question = "incomplete_evacuation"
        result = cm.handle_message(sid, answer)
        assert s.symptom_state.incomplete_evacuation is True
        assert result["status"] != "IRRELEVANT"


def test_hard_poop_natural_language_becomes_primary_symptom():
    cm = ConversationManager()
    sid = "nlu-hard-poops"
    result = cm.handle_message(sid, "I am having hard poops")
    state = cm.sessions[sid].symptom_state
    assert state.primary_symptom == "hard stools"
    assert state.stool_form == 2
    assert result["status"] == "ASK"


def test_bloating_pain_natural_relation_variant():
    cm = ConversationManager()
    sid = "nlu-bloating-does-improve"
    s = cm._get_session(sid)
    s.primary_symptom = "bloating"
    s.last_question = "bloating_pain"
    cm.handle_message(sid, "I have bloating and pain, it does improve after a bowel movement")
    assert s.symptom_state.pain_related_to_bowel_movement is True


def test_water_accepts_common_typo_litters():
    cm = ConversationManager()
    sid = "nlu-water-litters"
    s = cm._get_session(sid)
    s.primary_symptom = "constipation"
    s.last_question = "water"
    cm.handle_message(sid, "around 3 litters")
    assert s.symptom_state.water_intake == "3 L"


def test_no_medicines_is_contextually_consumed():
    cm = ConversationManager()
    sid = "nlu-no-meds"
    s = cm._get_session(sid)
    s.primary_symptom = "constipation"
    s.last_question = "medications"
    cm.handle_message(sid, "no medicines")
    assert s.symptom_state.medications == "none"
