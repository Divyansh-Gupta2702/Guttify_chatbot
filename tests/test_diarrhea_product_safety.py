import pytest

import recommendation_engine
from clinical_rule_engine import evaluate as evaluate_screening
from guttify_agent import (
    ConversationManager,
    PRODUCT_ELIGIBILITY,
    _approved_names_for_screening,
    _filter_approved_products,
    _with_diarrhea_guidance,
)
from intent_parser import SymptomState, extract_symptoms
import nlu_extractor
from question_schema import resolve_against_active_question
from recommendation_engine import evaluate as evaluate_products
from safety_checker import check_safety, detect_red_flags


@pytest.mark.parametrize("message", [
    "I have diarrhea.",
    "I am having loose motions.",
    "My stools are watery.",
    "I have frequent loose stools.",
    "I have acute diarrhea.",
    "There is a sudden increase in stool frequency.",
    "I have frequent watery bowel movements.",
])
def test_diarrhea_wording_is_recognized(message):
    primary, secondary = extract_symptoms(message)
    assert primary == "diarrhea" or "diarrhea" in secondary


@pytest.mark.parametrize("secondary", ["bloating", "gas", "acidity", "abdominal pain"])
def test_diarrhea_blocks_secondary_symptom_products_before_scoring(secondary, monkeypatch):
    state = SymptomState(
        primary_symptom="bloating",
        secondary_symptoms=[secondary, "diarrhea"],
        bloating=True,
        diarrhea=True,
        diarrhea_explicit=True,
    )
    screening = {
        "pattern": "Functional gas/bloating pattern",
        "likely_condition": "Functional gas/bloating pattern",
        "product_allowed": True,
    }
    allowed = _approved_names_for_screening(screening, state)
    assert allowed == set()

    scored = []
    monkeypatch.setattr(
        recommendation_engine,
        "score_product",
        lambda *args, **kwargs: scored.append(args[0]["product_name"]) or 1000,
    )
    result = evaluate_products(
        state,
        f"diarrhea and {secondary}",
        allowed_names=allowed,
        match_context=screening["pattern"],
    )
    assert result["recommendations"] == []
    assert scored == []


def test_raw_mixed_symptom_query_cannot_bypass_diarrhea_eligibility():
    state = SymptomState(primary_symptom="bloating", bloating=True)
    result = evaluate_products(state, "I have diarrhea and bloating")
    assert result["recommendations"] == []
    assert "does not establish" in result["message"]


@pytest.mark.parametrize("product_name", ["Digest Boost", "Guttify Poopie"])
def test_filter_cannot_reintroduce_products_when_diarrhea_is_unapproved(product_name):
    state = SymptomState(primary_symptom="bloating", diarrhea=True, diarrhea_explicit=True)
    screening = {"pattern": "Functional gas/bloating pattern", "product_allowed": True}
    product = next(p for p in recommendation_engine.products if p["product_name"] == product_name)
    result = {
        "status": "RECOMMENDATION_FOUND",
        "recommendations": [product],
        "message": "",
    }
    filtered = _filter_approved_products(result, screening, state)
    assert filtered["recommendations"] == []
    assert filtered["status"] == "DIAGNOSIS"


@pytest.mark.parametrize("message,expected_flag", [
    ("I have diarrhea and blood in my stool", "blood in stool with diarrhea"),
    ("I have diarrhea and signs of dehydration", "dehydration"),
    ("I have diarrhea and severe abdominal pain", "severe abdominal pain"),
    ("I have diarrhea with a high fever", "high fever"),
    ("I have persistent vomiting and diarrhea", "persistent vomiting"),
    ("I have diarrhea and severe weakness", "severe weakness"),
    ("My diarrhea is persistent or worsening", "persistent/worsening diarrhea"),
    ("My stools are black and tarry", "black/tarry stool"),
])
def test_diarrhea_warning_signs_trigger_medical_review(message, expected_flag):
    flags = detect_red_flags(message)
    safety = check_safety(message)
    assert expected_flag in flags
    assert safety["requires_doctor"] is True
    assert safety["red_flag"] is True
    assert safety["safe_to_recommend"] is False


@pytest.mark.parametrize("message", [
    "I have diarrhea and blood in my stool",
    "I have diarrhea and signs of dehydration",
    "I have diarrhea and severe abdominal pain",
    "My diarrhea is persistent or worsening",
])
def test_warning_signs_interrupt_assessment_before_any_product_recommendation(message):
    result = ConversationManager().handle_message("diarrhea-safety", message)
    assert result["status"] == "SAFETY_REVIEW"
    assert result["recommendations"] == []
    assert result["safety"]["requires_doctor"] is True


def test_diarrhea_first_question_includes_hydration_guidance():
    result = ConversationManager().handle_message("diarrhea-guidance", "I have diarrhea and bloating")
    assert result["status"] == "ASK"
    assert result["recommendations"] == []
    assert "oral rehydration solution (ORS)" in result["message"]
    assert "does not establish any Guttify product as suitable" in result["message"]


def test_diarrhea_guidance_is_added_only_once_per_session():
    manager = ConversationManager()
    session = manager._get_session("diarrhea-guidance-once")
    session.symptom_state.primary_symptom = "diarrhea"

    first = _with_diarrhea_guidance("First question", session.symptom_state, session=session)
    second = _with_diarrhea_guidance("Second question", session.symptom_state, session=session)

    assert "oral rehydration solution (ORS)" in first
    assert "oral rehydration solution (ORS)" not in second
    assert "Second question" in second


@pytest.mark.parametrize("answer,expected", [
    ("5", 5), ("about 4", 4), ("6 stools", 6), ("3 times a day", 3),
    ("once daily", 1), ("twice a day", 2), ("every alternate day", 0.5),
])
def test_daily_frequency_short_answer_resolves_without_llm(answer, expected):
    resolution = resolve_against_active_question("daily_frequency", answer)
    assert resolution["status"] == "answered"
    assert resolution["source"] == "deterministic"
    assert resolution["values"]["bowel_frequency_per_day"] == expected


def test_daily_frequency_short_answer_skips_groq_extraction(monkeypatch):
    monkeypatch.setattr(
        nlu_extractor,
        "_llm_extract",
        lambda *args, **kwargs: pytest.fail("deterministic stool count must not call Groq"),
    )
    facts = nlu_extractor.extract_natural_facts(
        "5", "daily_frequency", SymptomState(primary_symptom="diarrhea"),
    )
    assert facts["_resolver_source"] == "deterministic"
    assert facts["_question_resolution"]["status"] == "answered"
    assert facts["bowel_frequency_per_day"] == 5


@pytest.mark.parametrize("answer", ["yes", "no"])
def test_daily_frequency_non_numeric_yes_no_remains_unresolved(answer):
    resolution = resolve_against_active_question("daily_frequency", answer)
    assert resolution["status"] == "unresolved"
    assert resolution["values"] == {}


@pytest.mark.parametrize("answer", ["sometimes", "occasionally", "rarely"])
def test_qualitative_frequency_requests_a_numeric_estimate_without_llm(answer, monkeypatch):
    monkeypatch.setattr(
        nlu_extractor,
        "_llm_extract",
        lambda *args, **kwargs: pytest.fail("qualitative frequency should use deterministic clarification"),
    )
    resolution = resolve_against_active_question("daily_frequency", answer)
    facts = nlu_extractor.extract_natural_facts(
        answer, "daily_frequency", SymptomState(primary_symptom="diarrhea"),
    )
    assert resolution["status"] == "clarification_needed"
    assert facts["_answer_status"] == "clarification_needed"
    assert facts.get("bowel_frequency_per_day") is None


@pytest.mark.parametrize("pattern", [
    "Functional constipation pattern",
    "Possible medication-associated constipation pattern",
    "IBS-C pattern",
    "Possible hemorrhoid pattern",
    "Possible anal fissure pattern",
    "Reflux/GERD-like symptom pattern",
    "Dyspepsia/indigestion pattern",
    "Functional gas/bloating pattern",
])
def test_non_diarrhea_condition_eligibility_is_preserved(pattern):
    allowed = _approved_names_for_screening({"pattern": pattern})
    assert allowed == PRODUCT_ELIGIBILITY[pattern]


def test_diarrhea_specific_clinical_pattern_has_no_documented_product_eligibility():
    state = SymptomState(primary_symptom="diarrhea", diarrhea=True, diarrhea_explicit=True)
    screening = evaluate_screening(state)
    assert screening["pattern"] == "Diarrhea pattern"
    assert _approved_names_for_screening(screening, state) == set()
