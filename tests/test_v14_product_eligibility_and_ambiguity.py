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


def test_secondary_constipation_adds_products_to_anorectal_recommendation():
    # A bleeding/fissure assessment may legitimately recommend the topical
    # product, but an explicitly reported constipation/hard-stool cluster must
    # also be evaluated rather than being lost because bleeding is primary.
    state = SymptomState(
        primary_symptom="bleeding",
        secondary_symptoms=["constipation", "hard stools"],
        blood_present=True,
        blood_colour="bright_red",
        sharp_pain_during_stool=True,
        lump_or_prolapse=False,
        constipation_explicit=True,
        stool_form=2,
    )
    screening = clinical_evaluate(state)
    assert screening["pattern"] == "Possible anal fissure pattern"
    allowed = _approved_names_for_screening(screening, state)
    result = product_evaluate(
        state,
        "bright red blood, sharp pain, constipation and hard stools",
        allowed_names=allowed,
        match_context=screening["pattern"],
    )
    names = {p["product_name"] for p in result["recommendations"]}
    assert "Piloease Anal Care Spray" in names
    assert "Guttify Poopie" in names
    assert "Digest Boost" in names


def test_three_symptoms_route_to_all_relevant_product_clusters():
    # More than two symptoms must not collapse into one primary-symptom route.
    state = SymptomState(
        primary_symptom="constipation",
        secondary_symptoms=["hard stools", "acidity"],
        constipation_explicit=True,
        stool_form=2,
    )
    screening = {"pattern": "Functional constipation pattern", "product_allowed": True}
    allowed = _approved_names_for_screening(screening, state)
    result = product_evaluate(
        state,
        "constipation, hard stools and acidity",
        allowed_names=allowed,
        match_context=screening["pattern"],
    )
    names = {p["product_name"] for p in result["recommendations"]}
    assert {"Digest Boost", "Guttify Poopie", "Acid Ease"}.issubset(names)
