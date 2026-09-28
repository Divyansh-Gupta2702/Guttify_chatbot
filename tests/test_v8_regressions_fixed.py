import unittest

from guttify_agent import ConversationManager
from intent_parser import extract_symptoms
from safety_checker import check_safety


class TestV8RegressionFixes(unittest.TestCase):
    def test_contextual_answer_does_not_overwrite_age(self):
        cm = ConversationManager()
        sid = "age-preserved"
        for msg in ["stomach pain", "2 months", "23", "upper abdomen", "5"]:
            cm.handle_message(sid, msg)
        state = cm.sessions[sid].symptom_state
        self.assertEqual(state.age, 23)
        self.assertEqual(state.severity, "5")

    def test_bowel_negation_does_not_create_constipation_or_diarrhea(self):
        self.assertEqual(extract_symptoms("no constipation no diarrhea"), (None, []))
        cm = ConversationManager()
        sid = "bowel-negation"
        for msg in ["stomach pain", "2 months", "23", "upper abdomen", "5", "no constipation no diarrhea", "no vomiting and no fever"]:
            cm.handle_message(sid, msg)
        state = cm.sessions[sid].symptom_state
        self.assertNotIn("constipation", state.secondary_symptoms)
        self.assertFalse(state.diarrhea)

    def test_safety_understands_do_not_have(self):
        for msg in [
            "I do not have vomiting blood",
            "I don't have black stool",
            "I do not have difficulty swallowing",
        ]:
            self.assertFalse(check_safety(msg)["red_flag"])

    def test_bleeding_and_dizziness_is_detected_regardless_of_word_order(self):
        r = check_safety("I have blood in stool and I feel dizzy")
        self.assertTrue(r["red_flag"])
        self.assertIn("fainting/dizziness with bleeding", r["reasons"])

    def test_gas_can_reach_acid_ease(self):
        cm = ConversationManager()
        sid = "gas-route"
        result = None
        for msg in ["gas", "2 weeks", "23", "no constipation", "no food trigger", "no abdominal pain"]:
            result = cm.handle_message(sid, msg)
        self.assertEqual(result["status"], "RECOMMENDATION_FOUND")
        self.assertIn("Acid Ease", [p["product_name"] for p in result["recommendations"]])

    def test_anal_burning_reaches_piloease(self):
        r = ConversationManager().handle_message("anal-burning", "I have anal burning")
        self.assertEqual(r["status"], "RECOMMENDATION_FOUND")
        self.assertIn("Piloease Anal Care Spray", [p["product_name"] for p in r["recommendations"]])

    def test_anal_swelling_reaches_piles_pure(self):
        r = ConversationManager().handle_message("anal-swelling", "I have anal swelling")
        self.assertEqual(r["status"], "RECOMMENDATION_FOUND")
        self.assertIn("Piles Pure", [p["product_name"] for p in r["recommendations"]])

    def test_product_shortcut_cannot_bypass_bleeding_assessment(self):
        r = ConversationManager().handle_message("named-with-symptom", "Can I use Piloease? I have blood in stool")
        self.assertNotEqual(r["status"], "PRODUCT_INFO_FOUND")
        self.assertEqual(r["status"], "ASK")

    def test_product_concern_still_works_after_clarifying_question(self):
        cm = ConversationManager()
        sid = "fatigue-clarify"
        first = cm.handle_message(sid, "I have fatigue")
        self.assertEqual(first["status"], "ASK")
        second = cm.handle_message(sid, "I also have brain fog")
        self.assertEqual(second["status"], "RECOMMENDATION_FOUND")
        self.assertIn("Boost Vitamin B12", [p["product_name"] for p in second["recommendations"]])


    def test_recommendation_does_not_repeat_after_follow_up(self):
        cm = ConversationManager()
        sid = "post-recommendation"
        result = None
        for msg in [
            "I have bright red blood when I poop",
            "2 months",
            "23",
            "on tissue",
            "no sharp pain",
            "yes lump",
        ]:
            result = cm.handle_message(sid, msg)

        self.assertIn(result["status"], ("RECOMMENDATION_FOUND", "AMBIGUOUS"))
        self.assertTrue(cm.sessions[sid].awaiting_close)
        self.assertIsNotNone(cm.sessions[sid].last_product)

        # Naming a product after the recommendation must not restart diagnosis.
        follow_up = cm.handle_message(sid, "Piles Pure")
        self.assertEqual(follow_up["status"], "PRODUCT_INFO_FOUND")
        self.assertEqual(follow_up["recommendations"][0]["product_name"], "Piles Pure")

        # An explicit stop request must close the post-recommendation chat.
        follow_up = cm.handle_message(sid, "please can u stop")
        self.assertEqual(follow_up["status"], "SESSION_ENDED")

    def test_post_recommendation_stop_phrases_close_chat(self):
        from satisfaction_checker import is_satisfied_closing

        for phrase in ["stop", "please stop", "please can u stop", "end chat", "cancel"]:
            self.assertTrue(is_satisfied_closing(phrase))


if __name__ == "__main__":
    unittest.main()
