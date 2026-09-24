"""GutGPT conversation manager: clinical-style assessment first, product second."""
from dataclasses import dataclass, field
from gibberish_checker import is_gibberish, random_gibberish_response
from greeting_checker import is_greeting, random_greeting_response
from satisfaction_checker import is_satisfied_closing, random_closing_response
from intent_parser import SymptomState, merge_state
from symptom_questionnaire import next_question
from clinical_rule_engine import evaluate as evaluate_screening
from safety_checker import check_safety
from recommendation_engine import (
    evaluate as evaluate_product,
    find_named_product,
    has_domain_overlap,
    IRRELEVANT_MESSAGE,
)

SESSION_ENDED_MESSAGE = "This conversation has already wrapped up. Please start a new chat if you'd like help with another question."
MAX_QUESTIONS = 10


@dataclass
class SessionState:
    symptom_state: SymptomState = field(default_factory=SymptomState)
    questions_asked: int = 0
    awaiting_close: bool = False
    ended: bool = False
    screening: dict | None = None


class ConversationManager:
    def __init__(self):
        self.sessions = {}

    def _get_session(self, sid):
        return self.sessions.setdefault(sid, SessionState())

    def reset(self, sid):
        self.sessions[sid] = SessionState()

    def handle_message(self, sid, user_message):
        session = self._get_session(sid)

        if session.ended:
            return {"status": "SESSION_ENDED", "message": SESSION_ENDED_MESSAGE, "recommendations": []}

        if session.awaiting_close and is_satisfied_closing(user_message):
            session.ended = True
            return {"status": "SESSION_ENDED", "message": random_closing_response(), "recommendations": []}

        if is_greeting(user_message):
            return {"status": "GREETING", "message": random_greeting_response(), "recommendations": []}

        if is_gibberish(user_message):
            return {"status": "GIBBERISH", "message": random_gibberish_response(), "recommendations": []}

        safety = check_safety(user_message)
        if safety["red_flag"]:
            return {
                "status": "DIAGNOSIS",
                "message": safety["message"],
                "safety": safety,
                "recommendations": [],
                "screening": {
                    "pattern": "Red-flag presentation",
                    "likely_condition": "Medical evaluation required",
                    "confidence": "high",
                    "evidence": safety["reasons"],
                    "differentials": [],
                    "action": "urgent_medical_evaluation",
                    "product_allowed": False,
                },
            }

        named = find_named_product(user_message)
        if named and not session.symptom_state.primary_symptom:
            session.awaiting_close = True
            return {"status": "PRODUCT_INFO_FOUND", "message": "", "product": named, "recommendations": [named]}

        session.symptom_state = merge_state(session.symptom_state, user_message, [])

        if not session.symptom_state.primary_symptom and not has_domain_overlap(user_message):
            return {"status": "IRRELEVANT", "message": IRRELEVANT_MESSAGE, "recommendations": []}

        # Rectal bleeding gets explicit colour/location/pain clarification before
        # the rule engine is allowed to classify it.
        if session.symptom_state.blood_present:
            if session.symptom_state.blood_colour is None and session.questions_asked < MAX_QUESTIONS:
                q = ("blood_colour", "Is the blood bright/fresh red, or dark/black/tarry?")
                if q[0] not in session.symptom_state.asked_fields:
                    session.symptom_state.asked_fields.append(q[0])
                    session.questions_asked += 1
                    return {"status": "ASK", "message": q[1], "recommendations": [], "safety": safety}
            if session.symptom_state.blood_location is None and session.questions_asked < MAX_QUESTIONS:
                q = ("blood_location", "If it is bright red, is it only on toilet paper/tissue, dripping into the toilet, or mixed into the stool?")
                if q[0] not in session.symptom_state.asked_fields:
                    session.symptom_state.asked_fields.append(q[0])
                    session.questions_asked += 1
                    return {"status": "ASK", "message": q[1], "recommendations": [], "safety": safety}
            if session.symptom_state.sharp_pain_during_stool is None and session.questions_asked < MAX_QUESTIONS:
                q = ("anal_pain", "Is there sharp or tearing pain during or just after passing stool?")
                if q[0] not in session.symptom_state.asked_fields:
                    session.symptom_state.asked_fields.append(q[0])
                    session.questions_asked += 1
                    return {"status": "ASK", "message": q[1], "recommendations": [], "safety": safety}

        # Keep asking targeted questions while useful information remains.
        if session.questions_asked < MAX_QUESTIONS:
            q = next_question(session.symptom_state)
            if q:
                name, text = q
                session.symptom_state.asked_fields.append(name)
                session.questions_asked += 1
                return {"status": "ASK", "message": text, "recommendations": [], "safety": safety}

        screening = evaluate_screening(session.symptom_state)
        session.screening = screening

        if screening["action"] == "clarify_bleeding":
            return {"status": "ASK", "message": screening["message"], "recommendations": [], "safety": safety, "screening": screening}

        # A clinical pattern is now the primary answer. Product logic only runs
        # after the pattern has been established and only if explicitly allowed.
        if not screening["product_allowed"]:
            return {
                "status": "DIAGNOSIS",
                "message": screening["message"],
                "recommendations": [],
                "safety": safety,
                "screening": screening,
            }

        result = evaluate_product(session.symptom_state, user_message)
        result["screening"] = screening
        result["safety"] = safety

        if result["status"] == "RECOMMENDATION_FOUND":
            session.awaiting_close = True
        return result
