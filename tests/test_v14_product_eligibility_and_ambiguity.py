from clinical_rule_engine import evaluate as clinical_evaluate
from intent_parser import SymptomState
from guttify_agent import _approved_names_for_screening
from recommendation_engine import evaluate as product_evaluate


def _product_result(state, query):
    screening = clinical_evaluate(state)
    allowed = _approved_names_for_screening(screening, state)
    return screening, product_evaluate(
        state, query, allowed_names=allowed, match_context=screening.get("pattern")
    )


def test_food_triggered_intolerance_is_diagnosis_only_when_no_matching_product_exists():
    state = SymptomState(primary_symptom="food intolerance", food_trigger="dairy")
    screening, result = _product_result(state, "milk causes digestive symptoms")
    assert screening["pattern"] == "Possible food-triggered intolerance pattern"
    assert screening["product_allowed"] is False
    assert result["recommendations"] == []


def test_unclear_food_triggered_symptoms_are_diagnosis_only():
    state = SymptomState(primary_symptom="food intolerance")
    screening, result = _product_result(state, "some foods upset my stomach")
    assert screening["pattern"] == "Possible food-triggered symptom pattern"
    assert screening["product_allowed"] is False
    assert result["recommendations"] == []


def test_ambiguous_matches_return_all_suitable_products_without_forcing_one():
    state = SymptomState(primary_symptom="bloating")
    state.secondary_symptoms = ["constipation"]
    screening = {
        "pattern": "Constipation-associated bloating pattern",
        "product_allowed": True,
    }
    allowed = _approved_names_for_screening(screening, state)
    result = product_evaluate(
        state,
        "bloating and constipation",
        allowed_names=allowed,
        match_context=screening["pattern"],
    )
    assert result["status"] in {"RECOMMENDATION_FOUND", "AMBIGUOUS"}
    names = [p["product_name"] for p in result["recommendations"]]
    assert set(names) == {"Digest Boost", "Guttify Poopie"}
    assert "intended use" in result["message"].lower()
    assert "choose the product" in result["message"].lower()
