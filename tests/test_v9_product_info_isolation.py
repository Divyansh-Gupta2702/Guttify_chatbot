import unittest

from guttify_agent import ConversationManager, SessionState
from recommendation_engine import find_named_product


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return type("R", (), {"content": prompt})()


class TestV9ProductInfoIsolation(unittest.TestCase):
    def test_post_diagnosis_product_lookup_drops_old_screening(self):
        cm = ConversationManager()
        sid = "product-after-diagnosis"
        session = cm.sessions.setdefault(sid, SessionState())
        session.diagnosis_complete = True
        session.screening = {
            "pattern": "Possible hemorrhoid pattern",
            "likely_condition": "Possible hemorrhoid pattern",
            "message": "OLD DIAGNOSIS TEXT MUST NOT BE SHOWN",
        }

        result = cm.handle_message(sid, "What are the ingredients of Digest Boost?")

        self.assertEqual(result["status"], "PRODUCT_INFO_FOUND")
        self.assertEqual(result["product"]["product_name"], "Digest Boost")
        self.assertIsNone(result.get("screening"))

    def test_product_info_mode_isolation_is_present_in_response_layer(self):
        source = open("guttify_chatbot.py", encoding="utf-8").read()
        self.assertIn('if mode == "PRODUCT_INFO":', source)
        self.assertIn("Do NOT mention, repeat, summarize, or infer any previous diagnosis", source)
        self.assertIn("PRODUCT_INFO mode deliberately excludes conversation history", source)


if __name__ == "__main__":
    unittest.main()
