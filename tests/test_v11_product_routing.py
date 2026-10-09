from guttify_agent import _approved_names_for_screening
from intent_parser import SymptomState
from clinical_rule_engine import evaluate as clinical_evaluate
from recommendation_engine import evaluate as product_evaluate


def _recommend(state, query="upper abdominal pain after meals"):
    screening = clinical_evaluate(state)
    allowed = _approved_names_for_screening(screening, state)
    return screening, product_evaluate(state, query, allowed_names=allowed, match_context=screening.get("pattern"))


def test_upper_abdominal_meal_related_stomach_pain_defaults_to_digest_boost():
    state = SymptomState(primary_symptom="stomach pain", food_related=True, pain_location="upper abdomen")
    screening, result = _recommend(state)
    assert screening["pattern"] == "Upper-abdominal meal-related dyspepsia pattern"
    assert [p["product_name"] for p in result["recommendations"]] == ["Digest Boost"]


def test_upper_abdominal_meal_related_pain_with_heartburn_routes_to_acid_ease():
    state = SymptomState(primary_symptom="stomach pain", secondary_symptoms=["heartburn"], food_related=True, pain_location="upper abdomen")
    screening, result = _recommend(state)
    assert screening["pattern"] == "Upper-abdominal meal-related dyspepsia pattern"
    assert [p["product_name"] for p in result["recommendations"]] == ["Acid Ease"]


def test_upper_abdominal_meal_related_pain_with_explicit_reflux_routes_to_acid_ease():
    state = SymptomState(primary_symptom="stomach pain", food_related=True, pain_location="upper abdomen", reflux_present=True)
    _, result = _recommend(state)
    assert [p["product_name"] for p in result["recommendations"]] == ["Acid Ease"]
