import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guttify_agent import ConversationManager
from symptom_questionnaire import next_question


class TestAllSymptomQuestionnaires(unittest.TestCase):
    ANSWERS = {
        "duration": "2 weeks",
        "age": "30",
        "weight_loss_duration": "no weight loss",
        "weight_loss": "no weight loss",
        "bowel_frequency": "3 times a week",
        "straining": "no",
        "hard_stools": "no",
        "incomplete_evacuation": "no",
        "bloating_screen": "no",
        "abdominal_pain_screen": "no",
        "pain_bowel_relation": "no",
        "blood": "no blood",
        "blood_colour": "bright red",
        "blood_location": "on tissue",
        "anal_discomfort_screen": "no",
        "sharp_pain_during_stool": "no",
        "lump": "no lump",
        "vomiting": "no",
        "fever": "no",
        "abdominal_distension": "no",
        "water": "2 litres",
        "fibre": "average",
        "medications": "no medicines",
        "daily_frequency": "3 loose stools per day",
        "stool_form": "4",
        "infection": "no",
        "mucus": "no",
        "night_time_symptoms": "no",
        "reflux": "no acid coming up",
        "timing": "not worse after meals, lying down, or at night",
        "triggers": "no particular food triggers it",
        "difficulty_swallowing": "no",
        "persistent_vomiting": "no",
        "vomiting_blood": "no",
        "constipation_screen": "no",
        "diarrhea_screen": "no",
        "gas_screen": "no",
        "food_trigger": "no particular food triggers it",
        "severity": "3",
        "pain_location": "upper abdomen",
        "vomiting_fever": "no vomiting and no fever",
        "upper_symptoms": "upper abdominal fullness and nausea",
        "food_relation": "not triggered by meals",
        "weight_loss": "no",
        "trigger": "dairy, repeatedly",
    }

    BRANCHES = [
        ("constipation", "I am constipated"),
        ("diarrhea", "I have diarrhea"),
        ("acidity", "I have heartburn"),
        ("bloating", "I have bloating"),
        ("stomach pain", "I have stomach pain"),
        ("indigestion", "I have indigestion"),
        ("food intolerance", "I think I have a food intolerance"),
        ("piles", "I have piles"),
        ("anal fissures", "I have an anal fissure"),
        ("bleeding", "I have blood in my stool"),
    ]

    def _complete(self, initial):
        cm = ConversationManager()
        sid = initial.replace(" ", "-")
        result = cm.handle_message(sid, initial)
        for _ in range(30):
            session = cm.sessions[sid]
            # The current question is stored separately because asked_fields
            # records a question as soon as it is emitted.
            field = session.last_question
            if field is None:
                if next_question(session.symptom_state) is None:
                    return cm, result
                self.fail(f"{initial}: questionnaire lost its pending question")
            answer = self.ANSWERS[field]
            result = cm.handle_message(sid, answer)
            # The core regression: whenever a branch still has a required
            # question, the API must stay in ASK rather than diagnose early.
            session = cm.sessions[sid]
            remaining = next_question(session.symptom_state)
            if remaining is not None and result.get("status") not in ("SAFETY_REVIEW",):
                self.assertEqual(result.get("status"), "ASK", f"{initial}: skipped {remaining[0]}")
            if session.last_question is None and remaining is None:
                return cm, result
        self.fail(f"{initial}: questionnaire did not converge")

    def test_every_supported_symptom_branch_completes_its_questionnaire(self):
        for branch, initial in self.BRANCHES:
            with self.subTest(branch=branch):
                cm, result = self._complete(initial)
                self.assertNotEqual(result.get("status"), "ASK")
                self.assertIsNotNone(cm.sessions[initial.replace(" ", "-")].symptom_state.primary_symptom)


if __name__ == "__main__":
    unittest.main()
