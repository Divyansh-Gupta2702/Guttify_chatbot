import unittest

from guttify_agent import ConversationManager
from intent_parser import SymptomState
from clinical_rule_engine import evaluate as clinical_evaluate
from recommendation_engine import evaluate as product_evaluate, find_named_product


class TestV7ProductCoverage(unittest.TestCase):
    def assert_rec(self, result, expected):
        names = [x["product_name"] for x in result.get("recommendations", [])]
        self.assertIn(expected, names, f"{expected} missing; got {names}, status={result.get('status')}")

    def test_glolux_skin_concern(self):
        r = ConversationManager().handle_message("glolux", "I have dull skin")
        self.assertEqual(r["status"], "RECOMMENDATION_FOUND")
        self.assert_rec(r, "GloLux GlutaGlow Skin Effervescent Tablets")

    def test_vitamin_d_concern(self):
        r = ConversationManager().handle_message("d3", "I have vitamin D deficiency")
        self.assertEqual(r["status"], "RECOMMENDATION_FOUND")
        self.assert_rec(r, "Boost Vitamin D3+")

    def test_vitamin_b12_concern(self):
        r = ConversationManager().handle_message("b12", "I have low energy and brain fog")
        self.assertEqual(r["status"], "RECOMMENDATION_FOUND")
        self.assert_rec(r, "Boost Vitamin B12")

    def test_weight_management_concern(self):
        r = ConversationManager().handle_message("weight", "I want weight management support")
        self.assertEqual(r["status"], "RECOMMENDATION_FOUND")
        self.assert_rec(r, "Apple Active")

    def test_low_fibre_routes_to_poopie(self):
        r = ConversationManager().handle_message("fibre", "I have low fibre intake")
        self.assertEqual(r["status"], "RECOMMENDATION_FOUND")
        self.assert_rec(r, "Guttify Poopie")

    def test_apple_word_is_not_treated_as_product_name(self):
        self.assertIsNone(find_named_product("I ate an apple today"))

    def test_liver_support_concern(self):
        r = ConversationManager().handle_message("liver", "I am looking for liver support")
        self.assertEqual(r["status"], "RECOMMENDATION_FOUND")
        self.assert_rec(r, "Liver Lift")

    def test_fatigue_is_clarified_not_randomly_assigned(self):
        cm = ConversationManager()
        r1 = cm.handle_message("fatigue", "I have fatigue")
        self.assertEqual(r1["status"], "ASK")
        r2 = cm.handle_message("fatigue", "I also have brain fog")
        self.assertEqual(r2["status"], "RECOMMENDATION_FOUND")
        self.assert_rec(r2, "Boost Vitamin B12")

    def test_constipation_maps_to_digest_products(self):
        s = SymptomState(primary_symptom="constipation")
        r = product_evaluate(s, "constipation", allowed_names={"Digest Boost", "Guttify Poopie"})
        self.assertIn(r["status"], ("RECOMMENDATION_FOUND", "AMBIGUOUS"))
        names = {x["product_name"] for x in r["recommendations"]}
        self.assertTrue(names & {"Digest Boost", "Guttify Poopie"})

    def test_hemorrhoid_pattern_maps_to_piles_products(self):
        s = SymptomState(primary_symptom="piles", blood_present=True, blood_colour="bright_red", sharp_pain_during_stool=False, lump_or_prolapse=True)
        screening = clinical_evaluate(s)
        self.assertEqual(screening["pattern"], "Possible hemorrhoid pattern")
        self.assertTrue(screening["product_allowed"])
        r = product_evaluate(s, "piles", allowed_names={"Piles Pure", "Piloease Anal Care Spray"})
        self.assertIn(r["status"], ("RECOMMENDATION_FOUND", "AMBIGUOUS"))
        self.assertTrue({x["product_name"] for x in r["recommendations"]} & {"Piles Pure", "Piloease Anal Care Spray"})

    def test_fissure_pattern_maps_to_piloease(self):
        s = SymptomState(primary_symptom="anal fissures", blood_present=True, blood_colour="bright_red", sharp_pain_during_stool=True)
        screening = clinical_evaluate(s)
        self.assertEqual(screening["pattern"], "Possible anal fissure pattern")
        self.assertTrue(screening["product_allowed"])
        r = product_evaluate(s, "anal fissure", allowed_names={"Piloease Anal Care Spray"})
        self.assertEqual(r["status"], "RECOMMENDATION_FOUND")
        self.assertEqual(r["recommendations"][0]["product_name"], "Piloease Anal Care Spray")

    def test_black_tarry_stool_never_recommends(self):
        s = SymptomState(primary_symptom="constipation", blood_present=True, blood_colour="black")
        screening = clinical_evaluate(s)
        self.assertFalse(screening["product_allowed"])
        self.assertEqual(screening["action"], "urgent_medical_evaluation")


if __name__ == "__main__":
    unittest.main()

class TestV8ClinicalContextBridging(unittest.TestCase):
    def test_blood_plus_sharp_pain_reaches_piloease(self):
        """Regression for the live flow: primary symptom is bleeding, but
        the completed clinical pattern is an anal fissure pattern."""
        cm = ConversationManager()
        sid = "blood-fissure-v8"
        answers = [
            "There is blood in stool", "3 weeks", "50", "Bright red",
            "Tissue", "Sharp pain during bowel movement",
        ]
        result = None
        for answer in answers:
            result = cm.handle_message(sid, answer)
        self.assertEqual(result["status"], "RECOMMENDATION_FOUND")
        self.assertEqual(result["screening"]["pattern"], "Possible anal fissure pattern")
        self.assertIn("Piloease Anal Care Spray", [x["product_name"] for x in result["recommendations"]])

    def test_dyspepsia_pattern_reaches_acid_ease(self):
        s = SymptomState(primary_symptom="indigestion")
        screening = clinical_evaluate(s)
        self.assertEqual(screening["pattern"], "Dyspepsia/indigestion pattern")
        r = product_evaluate(s, "indigestion", allowed_names={"Acid Ease"}, match_context=screening["pattern"])
        self.assertEqual(r["status"], "RECOMMENDATION_FOUND")
        self.assertEqual(r["recommendations"][0]["product_name"], "Acid Ease")

    def test_upper_abdominal_meal_related_dyspepsia_reaches_acid_ease(self):
        s = SymptomState(primary_symptom="stomach pain", food_related=True, pain_location="upper abdomen")
        screening = clinical_evaluate(s)
        self.assertEqual(screening["pattern"], "Upper-abdominal meal-related dyspepsia pattern")
        r = product_evaluate(s, "upper abdominal pain after meals", allowed_names={"Acid Ease"}, match_context=screening["pattern"])
        self.assertEqual(r["status"], "RECOMMENDATION_FOUND")
        self.assertEqual(r["recommendations"][0]["product_name"], "Acid Ease")


class TestV8AllActiveProductEntryPoints(unittest.TestCase):
    def test_all_product_specific_routes_have_a_match(self):
        cases = [
            ("GloLux GlutaGlow Skin Effervescent Tablets", "I have dull skin"),
            ("Boost Vitamin B12", "I have brain fog"),
            ("Boost Vitamin D3+", "I have low immunity"),
            ("Apple Active", "I want weight management support"),
            ("Liver Lift", "I need liver support"),
            ("Guttify Poopie", "I have low fibre intake"),
        ]
        for expected, query in cases:
            with self.subTest(expected=expected):
                result = ConversationManager().handle_message(expected, query)
                self.assertEqual(result["status"], "RECOMMENDATION_FOUND")
                self.assertIn(expected, [x["product_name"] for x in result["recommendations"]])
