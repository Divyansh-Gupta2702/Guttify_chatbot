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
    return bot, result


def test_answer_to_duration_is_not_irrelevant():
    bot = ConversationManager()
    result = bot.handle_message("s", "unable to pass my stools")
    assert result["status"] == "ASK"
    result = bot.handle_message("s", "5 months")
    assert result["status"] == "ASK"
    assert bot.sessions["s"].symptom_state.duration == "5 months"


def test_constipation_full_flow_reaches_assessment_and_product():
    _, result = run([
        "unable to pass my stools", "5 months", "no weight loss", "23", "2 times a week",
        "hard and strain", "no incomplete", "bloating but no abdominal pain",
        "no blood", "no sharp pain",
        "no vomiting no fever no swelling", "2 litres", "low", "no medicines",
    ])
    assert result["status"] in ("RECOMMENDATION_FOUND", "AMBIGUOUS")
    assert result["screening"]["pattern"] == "Functional constipation pattern"
    assert {p["product_name"] for p in result["recommendations"]} >= {"Digest Boost", "Guttify Poopie"}


def test_ibs_c_pattern_is_distinguished_from_plain_constipation():
    _, result = run([
        "I am constipated", "5 months", "no weight loss", "23", "2 times a week",
        "hard and I strain", "yes incomplete",
        "yes abdominal pain, it gets better after bowel movement",
        "no blood", "no sharp pain",
        "no vomiting, no fever, no severe swelling", "2 litres", "average", "no medicines",
    ])
    assert result["screening"]["pattern"] == "IBS-C pattern"
    assert result["status"] in ("RECOMMENDATION_FOUND", "AMBIGUOUS")
    assert {p["product_name"] for p in result["recommendations"]} >= {"Digest Boost", "Guttify Poopie"}


def test_bright_red_sharp_pain_is_fissure_pattern():
    _, result = run([
        "I have blood in my stool", "2 months", "23", "bright red",
        "on tissue", "sharp tearing pain during stool", "no lump", "no hard stools and no straining",
    ])
    assert result["screening"]["pattern"] == "Possible anal fissure pattern"
    assert result["status"] in ("RECOMMENDATION_FOUND", "DIAGNOSIS")


def test_bright_red_painless_lump_is_hemorrhoid_pattern():
    _, result = run([
        "I have bright red blood when I poop", "2 months", "23",
        "on tissue", "no sharp pain", "yes lump", "no hard stools and no straining",
    ])
    assert result["screening"]["pattern"] == "Possible hemorrhoid pattern"
    assert result["status"] in ("RECOMMENDATION_FOUND", "AMBIGUOUS")
    assert {p["product_name"] for p in result["recommendations"]} >= {"Piloease Anal Care Spray", "Piles Pure"}


def test_black_stool_is_red_flag():
    _, result = run(["my stool is black and tarry"])
    assert result["status"] == "SAFETY_REVIEW"
    assert result["screening"]["action"] == "urgent_medical_evaluation"


def test_reflux_pattern_can_recommend_acid_ease():
    _, result = run([
        "I have heartburn after meals", "3 months", "no weight loss", "23",
        "yes acid comes up", "worse lying down at night",
        "no particular food triggers it",
        "no difficulty swallowing, no persistent vomiting, no vomiting blood",
    ])
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
