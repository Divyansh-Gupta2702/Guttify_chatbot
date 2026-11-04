import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guttify_agent import ConversationManager


def run(messages):
    bot = ConversationManager()
    sid = "test"
    result = None
    for message in messages:
        result = bot.handle_message(sid, message)
    if result and result.get("status") == "SUMMARY_REVIEW":
        result = bot.handle_message(sid, "yes")
    return bot, result


def run_questionnaire(primary, answers):
    """Answer the currently displayed question so tests track the live flow."""
    bot = ConversationManager()
    sid = "flow-" + primary
    result = bot.handle_message(sid, primary)
    fallback = {
        "duration": "3 months", "weight_loss_duration": "no", "age": "34",
        "bowel_frequency": "2 times per week", "daily_frequency": "3",
        "stool_form": "2", "straining": "no", "incomplete_evacuation": "no",
        "bloating_screen": "no", "gas_screen": "no", "constipation_screen": "no",
        "diarrhea_screen": "no", "abdominal_pain_screen": "no", "food_relation": "no",
        "pain_bowel_relation": "no", "blood": "no", "blood_colour": "bright red",
        "blood_location": "on tissue", "anal_discomfort_screen": "no",
        "sharp_pain_during_stool": "no", "lump": "no", "vomiting": "no",
        "fever": "no", "abdominal_distension": "no", "water": "2 litres",
        "fibre": "average", "medications": "no", "reflux": "yes", "timing": "at night",
        "triggers": "no particular foods", "difficulty_swallowing": "no",
        "persistent_vomiting": "no", "vomiting_blood": "no", "food_trigger": "no",
    }
    fallback.update(answers)
    for _ in range(40):
        if result.get("status") != "ASK":
            break
        question = bot.sessions[sid].last_question
        result = bot.handle_message(sid, fallback.get(question, "no"))
    if result.get("status") == "SUMMARY_REVIEW":
        result = bot.handle_message(sid, "yes")
    return bot, result


def test_answer_to_duration_is_not_irrelevant():
    bot = ConversationManager()
    result = bot.handle_message("s", "unable to pass my stools")
    assert result["status"] == "ASK"
    result = bot.handle_message("s", "5 months")
    assert result["status"] == "ASK"
    assert bot.sessions["s"].symptom_state.duration == "5 months"


def test_constipation_full_flow_reaches_assessment_and_product():
    _, result = run_questionnaire("unable to pass my stools", {
        "duration": "5 months", "age": "23", "bowel_frequency": "2 times a week",
        "stool_form": "2", "straining": "yes", "fibre": "low",
    })
    assert result["status"] in ("RECOMMENDATION_FOUND", "AMBIGUOUS")
    assert result["screening"]["pattern"] == "Functional constipation pattern"
    assert {p["product_name"] for p in result["recommendations"]} >= {"Digest Boost", "Guttify Poopie"}


def test_ibs_c_pattern_is_distinguished_from_plain_constipation():
    _, result = run_questionnaire("I am constipated", {
        "duration": "5 months", "age": "23", "bowel_frequency": "2 times a week",
        "stool_form": "2", "straining": "yes", "incomplete_evacuation": "yes",
        "abdominal_pain_screen": "yes", "pain_bowel_relation": "yes",
    })
    assert result["screening"]["pattern"] == "IBS-C pattern"
    assert result["status"] in ("RECOMMENDATION_FOUND", "AMBIGUOUS")
    assert {p["product_name"] for p in result["recommendations"]} >= {"Digest Boost", "Guttify Poopie"}


def test_bright_red_sharp_pain_is_fissure_pattern():
    _, result = run_questionnaire("I have blood in my stool", {
        "duration": "2 months", "age": "23", "anal_discomfort_screen": "yes",
        "sharp_pain_during_stool": "yes",
    })
    assert result["screening"]["pattern"] == "Possible anal fissure pattern"
    assert result["status"] in ("RECOMMENDATION_FOUND", "DIAGNOSIS")


def test_bright_red_painless_lump_is_hemorrhoid_pattern():
    _, result = run_questionnaire("I have bright red blood when I poop", {
        "duration": "2 months", "age": "23", "blood_location": "on tissue",
        "lump": "yes", "straining": "no",
    })
    assert result["screening"]["pattern"] == "Possible hemorrhoid pattern"
    assert result["status"] in ("RECOMMENDATION_FOUND", "AMBIGUOUS")
    assert {p["product_name"] for p in result["recommendations"]} >= {"Piloease Anal Care Spray", "Piles Pure"}


def test_black_stool_is_red_flag():
    _, result = run(["my stool is black and tarry"])
    assert result["status"] == "SAFETY_REVIEW"
    assert result["screening"]["action"] == "urgent_medical_evaluation"


def test_reflux_pattern_can_recommend_acid_ease():
    _, result = run_questionnaire("I have heartburn after meals", {
        "duration": "3 months", "age": "23", "reflux": "yes",
        "timing": "worse lying down at night", "triggers": "no particular foods",
    })
    assert result["screening"]["pattern"] == "Reflux/GERD-like symptom pattern"
    assert result["status"] == "RECOMMENDATION_FOUND"
    assert result["recommendations"][0]["product_name"] == "Acid Ease"


def test_negated_symptoms_do_not_start_wrong_branch():
    from intent_parser import extract_symptoms, extract_food_trigger
    assert extract_symptoms("I don't have constipation, I have bloating")[0] == "bloating"
    assert extract_symptoms("I don't have piles")[0] is None
    assert extract_symptoms("I am not constipated")[0] is None
    assert extract_food_trigger("I don't have bloating after dairy") is None
    assert extract_food_trigger("not triggered by wheat") is None


def test_contrast_after_negation_keeps_positive_symptom():
    from intent_parser import extract_symptoms
    assert extract_symptoms("No constipation but hard stools")[0] == "hard stools"


def test_structured_vomiting_stops_product_recommendation():
    bot = ConversationManager()
    sid = "structured-red-flag"
    for message in [
        "I am constipated", "5 months", "no weight loss", "23", "2 times a week",
        "hard and I strain", "no incomplete", "no abdominal pain",
        "no blood", "no sharp pain", "yes vomiting",
    ]:
        result = bot.handle_message(sid, message)
    assert result["status"] == "SAFETY_REVIEW"
    assert result["recommendations"] == []
