import unittest

from clinical_rule_engine import _duration_days
from guttify_agent import ConversationManager
from safety_checker import detect_red_flags


class TestFinalProductionHardening(unittest.TestCase):
    def test_common_negations_do_not_trigger_red_flags(self):
        self.assertEqual(detect_red_flags("I haven't had any black stool"), [])
        self.assertEqual(detect_red_flags("there is no blood in my stool"), [])
        self.assertEqual(detect_red_flags("I don't have black stool"), [])
        self.assertEqual(detect_red_flags("I have black stool"), ["black/tarry stool"])

    def test_duration_engine_accepts_common_natural_language(self):
        self.assertEqual(_duration_days("about a month"), 30)
        self.assertEqual(_duration_days("over a month"), 30)
        self.assertEqual(_duration_days("several months"), 90)

    def test_ambiguous_anal_concern_is_clarified_and_resolved(self):
        cm = ConversationManager()
        sid = "final-product-concern"
        first = cm.handle_message(sid, "I have anal discomfort")
        self.assertEqual(first["status"], "ASK")
        self.assertIn("swelling/lumps", first["message"])
        second = cm.handle_message(sid, "mainly burning and itching")
        self.assertEqual(second["status"], "RECOMMENDATION_FOUND")
        self.assertEqual(second["recommendations"][0]["product_name"], "Piloease Anal Care Spray")


if __name__ == "__main__":
    unittest.main()
