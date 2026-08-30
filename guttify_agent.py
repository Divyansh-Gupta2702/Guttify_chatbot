"""
Guttify Conversation Agent
--------------------------
Owns the multi-turn conversation flow:

    user message
      -> greeting check
      -> gibberish check
      -> intent parsing (structured symptom state)
      -> safety validation (red flags short-circuit everything)
      -> deterministic recommendation engine
      -> at most 3 clarifying questions, never re-asking what's known
      -> final response

The LLM (guttify_chatbot) is used ONLY to phrase the final recommendation
or an unclear-need follow-up in natural language from data this agent has
already decided on — it never chooses the product and never decides which
clarifying question to ask.

Priority for state: current user answer > current conversation > any
previously stored state. This is enforced by `intent_parser.merge_state`,
which only overwrites a field when the new message actually supplies one.
"""
from dataclasses import dataclass, field

from gibberish_checker import is_gibberish, random_gibberish_response
from greeting_checker import is_greeting, random_greeting_response
from intent_parser import SymptomState, extract_named_aspect, merge_state
from recommendation_engine import evaluate, find_named_product, has_domain_overlap, IRRELEVANT_MESSAGE
from safety_checker import check_safety

MAX_QUESTIONS = 3

# Ordered so the flow matches natural triage: what's wrong, how
# often/food-related, then the specific trigger — matching the spec's
# example conversation.
QUESTION_TEMPLATES = [
    (
        "primary_symptom",
        lambda state: state.primary_symptom is None,
        "Got it. What are you experiencing most — bloating, acidity, pain, "
        "constipation, or something else?",
    ),
    (
        "frequency_and_food",
        lambda state: state.primary_symptom is not None and state.food_related is None,
        "How often does it happen, and does it seem related to food?",
    ),
    (
        "food_trigger",
        lambda state: bool(state.food_related) and state.food_trigger is None,
        "Which food seems to trigger it most — dairy, spicy/oily food, "
        "wheat, beans/lentils, or not sure?",
    ),
]


def next_question(state: SymptomState):
    """Return the next clarifying question to ask, or None if there isn't
    one left / everything relevant is already known."""
    for field_name, needs_asking, question_text in QUESTION_TEMPLATES:
        if field_name in (state.asked_fields or []):
            continue
        if needs_asking(state):
            return field_name, question_text
    return None


@dataclass
class SessionState:
    symptom_state: SymptomState = field(default_factory=SymptomState)
    questions_asked: int = 0
    resolved: bool = False  # True once a recommendation/no-match/etc has been delivered


class ConversationManager:
    """Holds per-session structured state across turns."""

    def __init__(self):
        self.sessions: dict[str, SessionState] = {}

    def _get_session(self, session_id: str) -> SessionState:
        return self.sessions.setdefault(session_id, SessionState())

    def reset(self, session_id: str):
        self.sessions[session_id] = SessionState()

    def handle_message(self, session_id: str, user_message: str) -> dict:
        session = self._get_session(session_id)

        if is_greeting(user_message):
            return {"status": "GREETING", "message": random_greeting_response(), "recommendations": []}

        if is_gibberish(user_message):
            return {"status": "GIBBERISH", "message": random_gibberish_response(), "recommendations": []}

        safety_result = check_safety(user_message)
        if not safety_result["safe_to_recommend"]:
            return {
                "status": "SAFETY_REVIEW",
                "message": safety_result["message"],
                "safety": safety_result,
                "recommendations": [],
            }

        # A user naming a specific product (or asking about one aspect of
        # it) bypasses the symptom conversation entirely.
        named_product = find_named_product(user_message)
        if named_product:
            aspect = extract_named_aspect(user_message)
            return {
                "status": "PRODUCT_INFO_FOUND",
                "message": "",
                "product": named_product,
                "aspect": aspect,
                "recommendations": [named_product],
            }

        session.symptom_state = merge_state(session.symptom_state, user_message, [])

        if not session.symptom_state.primary_symptom and not has_domain_overlap(user_message):
            return {"status": "IRRELEVANT", "message": IRRELEVANT_MESSAGE, "recommendations": []}

        # Ask any relevant outstanding question BEFORE finalizing a
        # recommendation — a single unique symptom match is not by itself
        # a reason to skip the conversation. We only skip a question when
        # its underlying field is already known (e.g. the user volunteered
        # food-trigger info up front) or the 3-question budget is spent.
        if session.questions_asked < MAX_QUESTIONS:
            question = next_question(session.symptom_state)
            if question is not None:
                field_name, question_text = question
                session.symptom_state.asked_fields = list(session.symptom_state.asked_fields or []) + [field_name]
                session.questions_asked += 1
                return {
                    "status": "ASK",
                    "message": question_text,
                    "recommendations": [],
                    "safety": safety_result,
                }

        result = evaluate(session.symptom_state, user_message)
        session.resolved = True
        return {**result, "safety": safety_result}
