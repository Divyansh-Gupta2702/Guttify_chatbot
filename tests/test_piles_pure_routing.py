import pytest

from guttify_agent import ConversationManager


def run(messages):
    cm = ConversationManager()
    result = None
    for i, message in enumerate(messages):
        result = cm.handle_message("piles", message)
    return cm, result


def test_explicit_piles_reaches_piles_pure_without_bleeding():
    cm = ConversationManager()
    sid = "explicit-piles"
    result = cm.handle_message(sid, "I have piles")
    assert result["status"] == "ASK"
    for message in ["2 months", "no weight loss", "23", "no bleeding", "no sharp pain", "no lump", "no hard stools and no straining"]:
        result = cm.handle_message(sid, message)
    assert result["status"] in ("RECOMMENDATION_FOUND", "AMBIGUOUS")
    names = {p["product_name"] for p in result["recommendations"]}
    assert "Piles Pure" in names
    assert cm.sessions[sid].diagnosis_complete
    follow_up = cm.handle_message(sid, "no sharp pain")
    assert follow_up["status"] == "DIAGNOSIS_COMPLETE"


def test_explicit_hemorrhoids_reaches_piles_pure():
    cm = ConversationManager()
    sid = "hemorrhoids"
    result = cm.handle_message(sid, "I have hemorrhoids")
    for message in ["1 month", "no weight loss", "30", "no bleeding", "no sharp pain", "no lump", "no hard stools and no straining"]:
        result = cm.handle_message(sid, message)
    names = {p["product_name"] for p in result["recommendations"]}
    assert "Piles Pure" in names
    assert cm.sessions[sid].diagnosis_complete


def test_piles_with_bright_red_blood_and_lump_reaches_piles_pure():
    cm = ConversationManager()
    sid = "piles-bleeding"
    result = None
    for message in ["I have piles and bright red blood", "2 weeks", "23", "on tissue", "no sharp pain", "yes lump", "no hard stools and no straining"]:
        result = cm.handle_message(sid, message)
    assert result["screening"]["pattern"] == "Possible hemorrhoid pattern"
    names = {p["product_name"] for p in result["recommendations"]}
    assert "Piles Pure" in names


def test_fissure_pattern_still_routes_to_piloease():
    cm = ConversationManager()
    sid = "fissure"
    result = None
    for message in ["I have anal fissure", "2 weeks", "23", "bright red blood", "on tissue", "sharp tearing pain during stool", "no lump", "no hard stools and no straining"]:
        result = cm.handle_message(sid, message)
    assert result["screening"]["pattern"] == "Possible anal fissure pattern"
    names = {p["product_name"] for p in result["recommendations"]}
    assert "Piloease Anal Care Spray" in names


def test_constipation_product_concern_still_routes():
    r = ConversationManager().handle_message("multi-intent", "I have constipation and low fibre intake")
    assert r["status"] == "RECOMMENDATION_FOUND"
    assert "Guttify Poopie" in {p["product_name"] for p in r["recommendations"]}
