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
        "unable to pass my stools", "5 months", "23", "2 times a week",
        "hard and strain", "no incomplete", "bloating but no abdominal pain",
        "no blood", "no sharp pain", "no weight loss",
        "no vomiting no fever no swelling", "2 litres", "low", "no medicines",
    ])
    assert result["status"] == "RECOMMENDATION_FOUND"
    assert result["screening"]["pattern"] == "Functional constipation pattern"
    assert result["recommendations"][0]["product_name"] == "Digest Boost"


def test_ibs_c_pattern_is_distinguished_from_plain_constipation():
    _, result = run([
        "I am constipated", "5 months", "23", "2 times a week",
        "hard and I strain", "yes incomplete",
        "yes abdominal pain, it gets better after bowel movement",
        "no blood", "no sharp pain", "no weight loss",
        "no vomiting, no fever, no severe swelling", "2 litres", "average", "no medicines",
    ])
    assert result["screening"]["pattern"] == "IBS-C pattern"
    assert result["status"] == "RECOMMENDATION_FOUND"


def test_bright_red_sharp_pain_is_fissure_pattern():
    _, result = run([
        "I have blood in my stool", "2 months", "23", "bright red",
        "on tissue", "sharp tearing pain during stool",
    ])
    assert result["screening"]["pattern"] == "Possible anal fissure pattern"
    assert result["status"] in ("RECOMMENDATION_FOUND", "DIAGNOSIS")


def test_bright_red_painless_lump_is_hemorrhoid_pattern():
    _, result = run([
        "I have bright red blood when I poop", "2 months", "23",
        "on tissue", "no sharp pain", "yes lump",
    ])
    assert result["screening"]["pattern"] == "Possible hemorrhoid pattern"
    assert result["status"] == "RECOMMENDATION_FOUND"
    assert any(p["product_name"] in {"Piloease Anal Care Spray", "Piles Pure"} for p in result["recommendations"])


def test_black_stool_is_red_flag():
    _, result = run(["my stool is black and tarry"])
    assert result["status"] == "SAFETY_REVIEW"
    assert result["screening"]["action"] == "urgent_medical_evaluation"


def test_reflux_pattern_can_recommend_acid_ease():
    _, result = run([
        "I have heartburn after meals", "3 months", "23",
        "yes acid comes up", "worse lying down at night",
        "no vomiting", "no weight loss",
    ])
    assert result["screening"]["pattern"] == "Reflux/GERD-like symptom pattern"
    assert result["status"] == "RECOMMENDATION_FOUND"
    assert result["recommendations"][0]["product_name"] == "Acid Ease"
