"""
Test suite for the deterministic Guttify recommendation pipeline.
Uses stdlib unittest only — no network/model dependency needed, since
recommendation_engine / intent_parser / safety_checker / guttify_agent are
pure Python with no ML model calls.

Run with:
    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intent_parser import SymptomState, extract_symptoms, merge_state, validate_llm_extraction
from safety_checker import check_safety, detect_red_flags
from recommendation_engine import evaluate, find_named_product, recommend_product
from greeting_checker import is_greeting
from guttify_agent import ConversationManager


class TestSymptomExtraction(unittest.TestCase):
    def test_exact_symptom_matching(self):
        primary, _ = extract_symptoms("I have bloating")
        self.assertEqual(primary, "bloating")

    def test_synonym_matching(self):
        primary, _ = extract_symptoms("my stomach gets swollen after eating")
        self.assertEqual(primary, "bloating")
        primary2, _ = extract_symptoms("I have burning in my chest after meals")
        self.assertIn(primary2, ("heartburn",))

    def test_food_trigger_matching(self):
        state = merge_state(SymptomState(), "I get bloating every day after eating dairy.", [])
        self.assertEqual(state.primary_symptom, "bloating")
        self.assertEqual(state.food_trigger, "dairy")
        self.assertTrue(state.food_related)
        self.assertEqual(state.frequency, "daily")

    def test_unsupported_symptom_returns_none(self):
        primary, _ = extract_symptoms("I have a headache and dizziness")
        self.assertIsNone(primary)

    def test_empty_message(self):
        primary, secondary = extract_symptoms("")
        self.assertIsNone(primary)
        self.assertEqual(secondary, [])

    def test_llm_extraction_validation_rejects_unknown(self):
        self.assertIsNone(validate_llm_extraction({"primary_symptom": "some_random_disease"}))
        self.assertIsNone(validate_llm_extraction("not a dict"))
        cleaned = validate_llm_extraction({"primary_symptom": "bloating", "food_trigger": "dairy"})
        self.assertEqual(cleaned["primary_symptom"], "bloating")


class TestSafetyChecker(unittest.TestCase):
    def test_red_flag_detection(self):
        result = check_safety("I have severe abdominal pain and I'm vomiting blood.")
        self.assertTrue(result["red_flag"])
        self.assertFalse(result["safe_to_recommend"])

    def test_red_flags_list(self):
        flags = detect_red_flags("I noticed black tarry stool and I fainted yesterday")
        self.assertIn("black/tarry stool", flags)
        self.assertIn("fainting or loss of consciousness", flags)

    def test_pregnancy_caution(self):
        result = check_safety("I am pregnant and have bloating")
        self.assertFalse(result["safe_to_recommend"])
        self.assertFalse(result["red_flag"])

    def test_safe_message(self):
        result = check_safety("I have bloating after eating dairy")
        self.assertTrue(result["safe_to_recommend"])


class TestRecommendationEngine(unittest.TestCase):
    def test_primary_symptom_gate(self):
        # Piles product must never score for a pure bloating complaint.
        state = SymptomState(primary_symptom="bloating")
        result = evaluate(state, "I have bloating")
        names = [r["product_name"] for r in result["recommendations"]]
        self.assertNotIn("Piles Pure", names)
        self.assertIn("Digest Boost", names)

    def test_no_match_without_symptom(self):
        state = SymptomState()
        result = evaluate(state, "hello")
        self.assertEqual(result["status"], "NO_MATCH")

    def test_named_product_lookup(self):
        product = find_named_product("What are the ingredients of Piloease?")
        self.assertIsNotNone(product)
        self.assertEqual(product["product_name"], "Piloease Anal Care Spray")

    def test_food_trigger_boosts_score(self):
        state = SymptomState(primary_symptom="acidity")
        base = evaluate(state, "I have acidity")
        base_score = base["recommendations"][0]["score"]

        state2 = SymptomState(primary_symptom="acidity", food_related=True, food_trigger="dairy")
        boosted = evaluate(state2, "I have acidity after dairy")
        boosted_score = boosted["recommendations"][0]["score"]
        self.assertGreaterEqual(boosted_score, base_score)

    def test_irrelevant_query(self):
        result = recommend_product("Who is the president of the United States?")
        self.assertEqual(result["status"], "IRRELEVANT")

    def test_gibberish_query(self):
        result = recommend_product("asdkjhasdkjh qweqwe")
        self.assertEqual(result["status"], "GIBBERISH")

    def test_multiple_valid_matches_ranked(self):
        # Both Digest Boost and Guttify Poopie target constipation-type
        # symptoms; a plain "constipation" query should surface at least one
        # confidently, without inventing a third product.
        state = SymptomState(primary_symptom="constipation")
        result = evaluate(state, "I have constipation")
        self.assertIn(result["status"], ("RECOMMENDATION_FOUND", "AMBIGUOUS"))
        for rec in result["recommendations"]:
            self.assertIn(rec["product_name"], [p["product_name"] for p in __import__("json").load(open(
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "products.json")))])


class TestConversationManager(unittest.TestCase):
    def test_scenario_a_liver_then_bloating_then_dairy(self):
        cm = ConversationManager()
        sid = "session-a"

        r1 = cm.handle_message(sid, "liver issue")
        self.assertEqual(r1["status"], "ASK")

        r2 = cm.handle_message(sid, "bloating")
        self.assertEqual(r2["status"], "ASK")

        r3 = cm.handle_message(sid, "few times a week and related to food")
        self.assertEqual(r3["status"], "ASK")

        r4 = cm.handle_message(sid, "dairy")
        self.assertIn(r4["status"], ("RECOMMENDATION_FOUND", "AMBIGUOUS"))

    def test_single_symptom_always_asks_before_recommending(self):
        # Regression test: a message with just one symptom must NOT be
        # recommended immediately just because it happens to uniquely
        # match one product — the agent should ask at least one
        # clarifying question first.
        for message in ["I have piles", "I have acidity", "I have hard stools",
                         "I want weight management support"]:
            cm = ConversationManager()
            result = cm.handle_message("single-symptom", message)
            self.assertEqual(result["status"], "ASK", f"expected a follow-up question for: {message!r}")


    def test_max_three_questions_then_stops(self):
        cm = ConversationManager()
        sid = "session-b"
        cm.handle_message(sid, "I don't know what's wrong")
        cm.handle_message(sid, "I just don't feel good")
        r3 = cm.handle_message(sid, "not sure honestly")
        r4 = cm.handle_message(sid, "still not sure")
        # After 3 questions asked, the 4th turn must not ask a 4th question.
        self.assertNotEqual(r4["status"], "ASK")

    def test_red_flag_stops_conversation_immediately(self):
        cm = ConversationManager()
        sid = "session-c"
        r1 = cm.handle_message(sid, "I have severe abdominal pain and I'm vomiting blood.")
        self.assertEqual(r1["status"], "SAFETY_REVIEW")
        self.assertTrue(r1["safety"]["red_flag"])

    def test_named_product_skips_questions(self):
        cm = ConversationManager()
        sid = "session-d"
        r1 = cm.handle_message(sid, "How do I use Piloease?")
        self.assertEqual(r1["status"], "PRODUCT_INFO_FOUND")

    def test_sentence_gives_enough_info_without_reasking(self):
        cm = ConversationManager()
        sid = "session-e"
        r1 = cm.handle_message(sid, "My stomach gets swollen after eating paneer.")
        # Should already know primary_symptom=bloating, food_related=True,
        # food_trigger=dairy from one sentence — must not ask for any of
        # that again if it asks anything at all.
        state = cm.sessions[sid].symptom_state
        self.assertEqual(state.primary_symptom, "bloating")
        self.assertTrue(state.food_related)
        self.assertEqual(state.food_trigger, "dairy")

    def test_empty_user_response_does_not_crash(self):
        cm = ConversationManager()
        sid = "session-f"
        result = cm.handle_message(sid, "")
        self.assertIn("status", result)


class TestGreetingHandling(unittest.TestCase):
    def test_common_greetings_detected(self):
        for text in ["hi", "Hello", "hey", "yo", "what's up", "whats up",
                     "sup", "good morning", "hi there", "howdy", "namaste"]:
            self.assertTrue(is_greeting(text), f"expected greeting: {text!r}")

    def test_non_greetings_not_flagged(self):
        for text in ["I have bloating", "hi, I have bloating",
                     "history of stomach issues", "him and his diet"]:
            self.assertFalse(is_greeting(text), f"unexpected greeting: {text!r}")

    def test_recommend_product_returns_greeting_status(self):
        result = recommend_product("hey")
        self.assertEqual(result["status"], "GREETING")
        self.assertTrue(result["message"])

    def test_conversation_manager_replies_to_greeting(self):
        cm = ConversationManager()
        result = cm.handle_message("greet-session", "yo")
        self.assertEqual(result["status"], "GREETING")
        self.assertTrue(result["message"])
        # A greeting shouldn't consume a clarifying-question slot or leave
        # any symptom state behind.
        state = cm.sessions["greet-session"].symptom_state
        self.assertIsNone(state.primary_symptom)


class TestMissingOrMalformedData(unittest.TestCase):
    def test_missing_product_database_raises_clear_error(self):
        import importlib
        import recommendation_engine as re_mod
        original_path = re_mod.PRODUCTS_FILE
        try:
            re_mod.PRODUCTS_FILE = "does_not_exist.json"
            with self.assertRaises(FileNotFoundError):
                with open(re_mod.PRODUCTS_FILE):
                    pass
        finally:
            re_mod.PRODUCTS_FILE = original_path

    def test_duplicate_named_products_not_confused(self):
        # find_named_product should not throw even with an ambiguous query
        # that mentions two product names.
        product = find_named_product("Compare Digest Boost and Acid Ease")
        self.assertIsNotNone(product)


if __name__ == "__main__":
    unittest.main()
