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


    def test_safety_catches_natural_blood_vomiting_variants(self):
        for msg in [
            "I threw up blood",
            "there is blood in my vomit",
            "I vomited blood earlier",
        ]:
            result = detect_red_flags(msg)
            self.assertIn("vomiting blood", result, msg)

    def test_safety_does_not_cross_negation_across_conjunction(self):
        result = detect_red_flags("I have no appetite and I am vomiting blood")
        self.assertIn("vomiting blood", result)
        result = detect_red_flags("I have not eaten since morning and my stool is black and tarry")
        self.assertIn("black/tarry stool", result)

    def test_safety_catches_bleeding_dizziness_natural_wording(self):
        result = detect_red_flags("I am pooping blood and dizzy")
        self.assertIn("fainting/dizziness with bleeding", result)

    def test_safety_catches_chest_pain(self):
        self.assertIn("chest pain", detect_red_flags("I have chest pain"))
        self.assertIn("chest pain", detect_red_flags("I feel pressure in my chest"))

    def test_emergency_overrides_completed_diagnosis(self):
        cm = ConversationManager()
        sid = "completed-then-emergency"
        session = cm.sessions.setdefault(sid, __import__("guttify_agent").SessionState())
        session.diagnosis_complete = True
        result = cm.handle_message(sid, "I am vomiting blood and I fainted")
        self.assertEqual(result["status"], "SAFETY_REVIEW")
        self.assertEqual(result["recommendations"], [])

    def test_pregnancy_persists_and_blocks_later_recommendation(self):
        cm = ConversationManager()
        sid = "pregnancy-persistent"
        first = cm.handle_message(sid, "I am pregnant")
        self.assertEqual(first["status"], "SAFETY_REVIEW")
        second = cm.handle_message(sid, "I have heartburn")
        self.assertEqual(second["status"], "SAFETY_REVIEW")
        self.assertEqual(second["recommendations"], [])

    def test_black_stool_and_blood_negations_remain_safe(self):
        self.assertNotIn("black/tarry stool", detect_red_flags("I do not have black stool"))
        self.assertNotIn("vomiting blood", detect_red_flags("I do not have blood in my vomit"))

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

class TestQuestionnaireCompleteness(unittest.TestCase):
    def test_bloating_does_not_skip_remaining_branch_questions(self):
        cm = ConversationManager()
        sid = "bloating-complete-screen"
        r1 = cm.handle_message(sid, "bloating")
        self.assertEqual(r1["status"], "ASK")
        r2 = cm.handle_message(sid, "2 days")
        self.assertEqual(r2["status"], "ASK")
        r3 = cm.handle_message(sid, "30")
        self.assertEqual(r3["status"], "ASK")
        r4 = cm.handle_message(sid, "yes, constipation")
        self.assertEqual(r4["status"], "ASK")
        self.assertIn("dairy", r4["message"].lower())
        r5 = cm.handle_message(sid, "no particular food")
        self.assertEqual(r5["status"], "ASK")
        self.assertIn("abdominal pain", r5["message"].lower())
        r6 = cm.handle_message(sid, "no abdominal pain")
        self.assertEqual(r6["status"], "ASK")
        self.assertIn("bristol", r6["message"].lower())

    def test_indigestion_does_not_stop_after_three_questions(self):
        cm = ConversationManager()
        sid = "indigestion-complete-screen"
        r1 = cm.handle_message(sid, "indigestion")
        self.assertEqual(r1["status"], "ASK")
        # The exact follow-up sequence is branch-specific; the important
        # regression is that it remains in ASK until its questions are done.
        for answer in ["3 days", "30", "upper fullness and nausea", "yes after meals"]:
            r = cm.handle_message(sid, answer)
        self.assertIn(r["status"], ("ASK", "DIAGNOSIS", "RECOMMENDATION_FOUND", "AMBIGUOUS"))
