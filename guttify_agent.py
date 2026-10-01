"""GutGPT multi-turn clinical screening conversation manager.

The agent has three strict layers:
1) preserve the user's original symptom branch;
2) interpret every answer against the exact question that was asked;
3) run the deterministic clinical-pattern engine before product matching.

The LLM is never responsible for deciding whether an answer is relevant or
which condition/pattern was selected.
"""
from dataclasses import dataclass, field
import re

from gibberish_checker import is_gibberish, random_gibberish_response
from greeting_checker import is_greeting, random_greeting_response
from satisfaction_checker import is_satisfied_closing, is_gratitude_only, random_closing_response
from intent_parser import (
    SymptomState, merge_state, extract_duration, extract_age,
    extract_bowel_frequency, extract_bowel_frequency_per_day,
    extract_severity, extract_lifestyle, extract_medications,
    extract_bool, extract_stool_form, normalize, extract_symptoms,
)
from symptom_questionnaire import next_question
from clinical_rule_engine import evaluate as evaluate_screening, _duration_days
from safety_checker import check_safety, detect_red_flags, derive_red_flags
from recommendation_engine import evaluate as evaluate_product, find_named_product, has_domain_overlap, IRRELEVANT_MESSAGE, products as ALL_PRODUCTS
from product_concern_router import detect_product_concerns

SESSION_ENDED_MESSAGE = "This conversation has already wrapped up. Please start a new chat if you'd like help with another question."
MAX_QUESTIONS = 15


PRODUCT_ELIGIBILITY = {
    "Functional constipation pattern": {"Digest Boost", "Guttify Poopie"},
    "Possible medication-associated constipation pattern": {"Digest Boost", "Guttify Poopie"},
    "IBS-C pattern": {"Digest Boost", "Guttify Poopie"},
    "Reflux/GERD-like symptom pattern": {"Acid Ease"},
    "Dyspepsia/indigestion pattern": {"Acid Ease"},
    "Upper-abdominal meal-related dyspepsia pattern": {"Acid Ease"},
    "Food-triggered gas/bloating pattern": {"Digest Boost", "Acid Ease", "Guttify Poopie"},
    "Constipation-associated bloating pattern": {"Digest Boost", "Guttify Poopie"},
    "Functional gas/bloating pattern": {"Digest Boost", "Acid Ease", "Guttify Poopie"},
    "Possible hemorrhoid pattern": {"Piles Pure", "Piloease Anal Care Spray"},
    "Possible anal fissure pattern": {"Piloease Anal Care Spray"},
}

# Product-concern branches are not medical diagnoses. They route explicit
# product-relevant concerns to the product database (skin, vitamins, weight
# management, liver support) after the gut-symptom parser has had first pick.
PRODUCT_CONCERN_QUESTIONS = {
}



def _filter_approved_products(result, screening):
    """Keep product matching separate from clinical reasoning and apply a small
    explicit eligibility allow-list so generic products (for example B12) do
    not win simply because their database row contains the word constipation.
    """
    allowed = PRODUCT_ELIGIBILITY.get(screening.get("pattern"), None)
    if allowed is None:
        return result
    if not allowed:
        result["recommendations"] = []
        result["status"] = "DIAGNOSIS"
        return result
    filtered = [p for p in result.get("recommendations", []) if p.get("product_name") in allowed]
    if filtered:
        result["recommendations"] = filtered
        # Do not destroy the recommendation engine's ambiguity decision.
        if result.get("status") != "AMBIGUOUS":
            result["status"] = "RECOMMENDATION_FOUND"
    else:
        result["recommendations"] = []
        result["status"] = "DIAGNOSIS"
    return result


@dataclass
class SessionState:
    symptom_state: SymptomState = field(default_factory=SymptomState)
    questions_asked: int = 0
    last_question: str | None = None
    awaiting_close: bool = False
    ended: bool = False
    # True after a final clinical assessment has already been delivered.
    # Once set, later messages must not restart the questionnaire/diagnosis
    # pipeline in the same session.
    diagnosis_complete: bool = False
    screening: dict | None = None
    product_candidates: list = field(default_factory=list)
    product_concern_question_asked: bool = False
    # Once a recommendation is delivered, follow-up messages must not restart
    # the clinical/product-matching pipeline. Keep the approved product here
    # so short follow-ups can stay in product-conversation mode.
    last_product: dict | None = None


class ConversationManager:
    def __init__(self):
        self.sessions = {}

    def _get_session(self, sid):
        return self.sessions.setdefault(sid, SessionState())

    def reset(self, sid):
        self.sessions[sid] = SessionState()

    @staticmethod
    def _set(data, key, value):
        if value is not None:
            data[key] = value

    def _apply_answer(self, session, text):
        """Parse an answer using the exact question context, then merge any
        additional volunteered details without replacing the primary branch.
        """
        field = session.last_question
        s = session.symptom_state
        n = normalize(text)
        data = s.to_dict()

        if field == "duration":
            self._set(data, "duration", extract_duration(text))

        elif field == "age":
            self._set(data, "age", extract_age(text))

        elif field == "bowel_frequency":
            value = extract_bowel_frequency(text)
            if value is None and normalize(text).replace(".", "", 1).isdigit():
                value = float(normalize(text))
            self._set(data, "bowel_frequency_per_week", value)

        elif field == "daily_frequency":
            self._set(data, "bowel_frequency_per_day", extract_bowel_frequency_per_day(text))

        elif field == "stool_straining":
            self._set(data, "stool_form", extract_stool_form(text))
            v = extract_bool(text, ["strain", "straining", "push hard", "pushing hard"], ["no strain", "without straining"])
            self._set(data, "straining", v)

        elif field == "incomplete_evacuation":
            v = extract_bool(text,
                             ["incomplete evacuation", "not completely empty", "not fully empty", "still feel like i need to go", "feel incompletely empty", "yes", "yeah", "yep"],
                             ["complete evacuation", "completely empty", "fully empty", "no"])
            self._set(data, "incomplete_evacuation", v)

        elif field in ("bloating_pain", "pain"):
            self._set(data, "bloating", extract_bool(text, ["bloating", "bloated", "bloat"], ["no bloating", "not bloated"]))
            self._set(data, "abdominal_pain", extract_bool(text, ["abdominal pain", "stomach pain", "belly pain", "stomach ache", "cramps", "cramping"], ["no abdominal pain", "no stomach pain", "no pain"]))
            self._set(data, "pain_related_to_bowel_movement", extract_bool(text,
                ["pain improves after stool", "pain improves after bowel movement", "pain relieved after stool", "pain relieved after bowel movement", "better after bowel movement", "worse after bowel movement", "related to bowel movement", "changes with bowel movement"],
                ["not related to bowel movement", "not related to stool"]))

        elif field in ("pain_relation", "ibs_pain"):
            self._set(data, "pain_related_to_bowel_movement", extract_bool(text,
                ["improves after bowel movement", "improves after stool", "better after bowel movement", "better after stool", "relieved after bowel movement", "worse after bowel movement", "related to bowel movement", "changes with bowel movement"],
                ["not related to bowel movement", "not related to stool"]))

        elif field == "blood":
            v = extract_bool(text, ["blood", "bleeding", "yes", "yeah", "yep"], ["no blood", "no bleeding", "without blood", "no"])
            self._set(data, "blood_present", v)

        elif field == "blood_colour":
            if any(x in n for x in ["black", "tarry", "dark"]):
                data["blood_colour"] = "black"
            elif any(x in n for x in ["bright red", "fresh red", "fresh blood", "red"]):
                data["blood_colour"] = "bright_red"

        elif field == "blood_location":
            if any(x in n for x in ["tissue", "toilet paper"]): data["blood_location"] = "tissue"
            elif "dripping" in n: data["blood_location"] = "dripping"
            elif "mixed" in n: data["blood_location"] = "mixed"

        elif field == "anal_pain":
            v = extract_bool(text, ["sharp", "tearing", "anal pain", "pain during stool", "yes", "yeah", "yep"], ["no sharp pain", "no tearing pain", "no anal pain", "no pain", "no"])
            self._set(data, "sharp_pain_during_stool", v)
            self._set(data, "anal_pain", v)

        elif field == "lump":
            v = extract_bool(text, ["lump", "prolapse", "comes out", "yes", "yeah", "yep"], ["no lump", "no prolapse", "no"])
            self._set(data, "lump_or_prolapse", v)

        elif field == "weight_loss":
            self._set(data, "weight_loss", extract_bool(text, ["weight loss", "losing weight", "lost weight", "have lost weight", "i lost weight", "yes", "yeah", "yep"], ["no weight loss", "not losing weight", "no"]))

        elif field == "weight_loss_duration":
            # Conditional weight-loss question triggered by duration >= 1 month
            self._set(data, "weight_loss", extract_bool(text, ["weight loss", "losing weight", "lost weight", "have lost weight", "i lost weight", "yes", "yeah", "yep"], ["no weight loss", "not losing weight", "no"]))
            data["weight_loss_duration_asked"] = True

        elif field == "vomiting_fever_swelling":
            self._set(data, "vomiting", extract_bool(text, ["vomiting", "vomit", "throwing up"], ["no vomiting", "not vomiting", "no"]))
            self._set(data, "fever", extract_bool(text, ["fever", "high temperature"], ["no fever", "no"]))
            self._set(data, "abdominal_distension", extract_bool(text, ["severe swelling", "severe abdominal swelling", "severe abdominal distension", "very swollen"], ["no severe swelling", "no swelling", "no"]))

        elif field == "red_flag_check":
            flags = detect_red_flags(text)
            if flags:
                data["red_flags"] = list(dict.fromkeys((s.red_flags or []) + flags))

        elif field == "water":
            water, _ = extract_lifestyle(text)
            if water:
                data["water_intake"] = water
            elif re_fullmatch_number(text):
                data["water_intake"] = normalize(text) + " L"

        elif field == "fibre":
            _, fibre = extract_lifestyle(text)
            if fibre:
                data["fibre_intake"] = fibre
            elif n in {"low", "low fibre", "low fiber"}: data["fibre_intake"] = "low"
            elif n in {"average", "normal", "average fibre", "average fiber"}: data["fibre_intake"] = "average"
            elif n in {"high", "high fibre", "high fiber", "good"}: data["fibre_intake"] = "high"

        elif field in ("medications",):
            self._set(data, "medications", extract_medications(text) or ("none" if n in {"no", "none", "no medicines", "no medication"} else None))

        elif field == "infection":
            self._set(data, "recent_infection", extract_bool(text,
                ["food poisoning", "stomach infection", "gut infection", "gastroenteritis", "after an infection", "yes", "yeah", "yep"],
                ["no recent infection", "no infection", "no"]))

        elif field in ("night_weight_fever",):
            self._set(data, "night_time_symptoms", extract_bool(text, ["wakes me at night", "wake me at night", "at night"], ["not at night", "doesn't wake me", "does not wake me", "no"]))
            self._set(data, "weight_loss", extract_bool(text, ["weight loss", "losing weight"], ["no weight loss", "not losing weight", "no"]))
            self._set(data, "fever", extract_bool(text, ["fever"], ["no fever", "no"]))

        elif field in ("swallowing", "weight_swallow"):
            self._set(data, "difficulty_swallowing", extract_bool(
                text,
                ["difficulty swallowing", "trouble swallowing", "painful swallowing", "yes", "yeah", "yep"],
                ["no difficulty swallowing", "no trouble swallowing", "no painful swallowing", "no"]
            ))
            self._set(data, "persistent_vomiting", extract_bool(
                text,
                ["persistent vomiting", "vomiting repeatedly", "can't stop vomiting", "cant stop vomiting", "yes", "yeah", "yep"],
                ["no vomiting", "not vomiting", "no"]
            ))
            self._set(data, "vomiting_blood", extract_bool(
                text,
                ["vomiting blood", "throwing up blood", "hematemesis"],
                ["no vomiting blood", "not vomiting blood", "no"]
            ))

        elif field in ("reflux", "timing", "triggers", "food_trigger", "food_relation", "trigger"):
            # merge_state captures food triggers and food association.
            pass

        elif field == "stool_form":
            self._set(data, "stool_form", extract_stool_form(text))

        elif field == "severity":
            value = extract_severity(text)
            if value is None and re_fullmatch_number(text):
                try:
                    score = float(normalize(text))
                    if 0 <= score <= 10:
                        value = str(int(score)) if score.is_integer() else str(score)
                except ValueError:
                    pass
            self._set(data, "severity", value)

        elif field == "pain_location":
            if "upper" in n: data["pain_location"] = "upper abdomen"
            elif "lower" in n: data["pain_location"] = "lower abdomen"
            elif "right" in n: data["pain_location"] = "right side"
            elif "left" in n: data["pain_location"] = "left side"
            elif "navel" in n or "belly button" in n: data["pain_location"] = "around navel"

        elif field == "bowel_pattern":
            primary, secondary = extract_symptoms(text)
            symptoms = []
            if primary:
                symptoms.append(primary)
            symptoms.extend(secondary or [])
            for symptom in symptoms:
                if symptom == "constipation":
                    data["secondary_symptoms"] = list(dict.fromkeys((data.get("secondary_symptoms") or []) + ["constipation"]))
                elif symptom == "hard stools":
                    data["stool_form"] = data.get("stool_form") or 1
                    data["secondary_symptoms"] = list(dict.fromkeys((data.get("secondary_symptoms") or []) + ["hard stools"]))
                elif symptom == "diarrhea":
                    data["diarrhea"] = True
                    data["secondary_symptoms"] = list(dict.fromkeys((data.get("secondary_symptoms") or []) + ["diarrhea"]))
            # Explicit negatives should clear any stale positive collected
            # from an earlier answer.
            if re.search(r"\b(?:no|not|never|without|don\'t|dont|doesn\'t|doesnt)\s+(?:have\s+)?(?:constipation|constipated|hard stool|hard stools)\b", n):
                data["secondary_symptoms"] = [x for x in (data.get("secondary_symptoms") or []) if x not in {"constipation", "hard stools"}]
                if data.get("stool_form") in (1, 2):
                    data["stool_form"] = None
            if re.search(r"\b(?:no|not|never|without|don\'t|dont|doesn\'t|doesnt)\s+(?:have\s+)?(?:diarrhea|diarrhoea|loose stool|loose stools|loose motion)\b", n):
                data["diarrhea"] = False
                data["secondary_symptoms"] = [x for x in (data.get("secondary_symptoms") or []) if x != "diarrhea"]

        # Generic merge captures facts the user volunteered in addition to the answer.
        # A bare yes/no is already interpreted against the exact pending question
        # above. Passing it through generic extraction would otherwise make every
        # boolean field True/False (e.g. "Yes" to anal pain becomes vomiting,
        # fever, weight loss, etc.).
        if n in {"yes", "yeah", "yep", "yup", "sure", "true", "no", "nope", "nah", "none", "false"}:
            merged_state = SymptomState(**data)
            merged_data = merged_state.to_dict()
        else:
            merged = merge_state(SymptomState(**data), text, [])
            merged_data = merged.to_dict()
        # Contextual answers always win over generic extraction. This is
        # important for short numeric answers such as "5" to severity: the
        # generic parser must not reinterpret them as an age.
        for key, value in data.items():
            if value is not None:
                merged_data[key] = value
        merged_state = SymptomState(**merged_data)
        merged_state.red_flags = derive_red_flags(merged_state)
        session.symptom_state = merged_state

    def _can_assess(self, session, screening):
        s = session.symptom_state
        if screening.get("action") == "urgent_medical_evaluation":
            return True
        if screening.get("pattern") == "Insufficiently characterized gut symptom pattern":
            return False

        branch = s.primary_symptom
        if s.blood_present:
            if s.blood_colour is None or s.sharp_pain_during_stool is None:
                return False
            if s.blood_colour == "bright_red" and s.sharp_pain_during_stool is False and s.lump_or_prolapse is None:
                return False
            return True

        if branch in ("constipation", "hard stools"):
            # Core constipation assessment: duration, bowel pattern, stool/strain,
            # incomplete evacuation, pain, bleeding, and key warning symptoms.
            required = [
                s.duration != "unknown", s.age is not None,
                s.bowel_frequency_per_week is not None,
                s.stool_form is not None and s.straining is not None,
                s.incomplete_evacuation is not None,
                s.abdominal_pain is not None,
                s.blood_present is not None,
                s.weight_loss is not None,
                s.vomiting is not None and s.fever is not None and s.abdominal_distension is not None,
                s.medications is not None,
            ]
            if not all(required):
                return False
            if s.blood_present:
                if s.blood_colour is None or s.sharp_pain_during_stool is None:
                    return False
                if s.blood_colour == "bright_red" and not s.sharp_pain_during_stool and s.lump_or_prolapse is None:
                    return False
            if s.duration != "unknown" and _duration_days(s.duration) and _duration_days(s.duration) >= 90:
                if s.abdominal_pain is True and s.pain_related_to_bowel_movement is None:
                    return False
            return True

        if branch == "piles":
            # Explicit piles/haemorrhoids can be assessed without forcing the
            # user through a constipation-style questionnaire. If bleeding is
            # present, retain the stricter differentiating questions.
            if s.blood_present:
                if s.blood_colour is None or s.sharp_pain_during_stool is None:
                    return False
                if s.blood_colour == "bright_red" and not s.sharp_pain_during_stool and s.lump_or_prolapse is None:
                    return False
            return s.duration != "unknown" and s.age is not None and s.blood_present is not None

        if branch == "diarrhea":
            return all([
                s.duration != "unknown", s.bowel_frequency_per_day is not None,
                s.abdominal_pain is not None, s.blood_present is not None,
                s.mucus is not None, s.fever is not None, s.weight_loss is not None,
            ])

        if branch in ("acidity", "heartburn"):
            return s.duration != "unknown" and s.weight_loss is not None and s.vomiting is not None

        if branch in ("piles", "anal fissures", "bleeding"):
            if s.blood_colour is None or s.sharp_pain_during_stool is None:
                return False
            if s.blood_colour == "bright_red" and not s.sharp_pain_during_stool and s.lump_or_prolapse is None:
                return False
            return True

        if branch == "stomach pain":
            return s.pain_location is not None and s.severity != "unknown" and s.vomiting is not None and s.fever is not None

        if branch in ("bloating", "gas"):
            return session.questions_asked >= 3 and (s.food_trigger is not None or s.abdominal_pain is not None or s.bowel_frequency_per_week is not None or s.diarrhea is not None)

        if branch in ("acidity", "heartburn"):
            return session.questions_asked >= 3 and s.weight_loss is not None and s.vomiting is not None

        if branch == "indigestion":
            return session.questions_asked >= 3

        if branch == "food intolerance":
            return session.questions_asked >= 3 and s.food_trigger is not None

        return False

    @staticmethod
    def _product_screening(product, matched_phrase):
        return {
            "pattern": f"Product concern: {product['product_name']}",
            "likely_condition": f"Product concern: {matched_phrase}",
            "confidence": "high",
            "evidence": [f"user concern matched: {matched_phrase}"],
            "differentials": [],
            "action": "product_support",
            "product_allowed": True,
            "message": "This concern matches the product information in the Guttify product database.",
        }

    def _product_concern_result(self, session, text):
        matches = detect_product_concerns(text)
        if not matches and session.product_candidates:
            return None
        if matches:
            names = [name for name, _ in matches]
            # If a prior ambiguous concern exists, a new explicit concern
            # narrows it instead of restarting the conversation.
            if session.product_candidates:
                names = [n for n in names if n in session.product_candidates] or names
            unique = list(dict.fromkeys(names))
            session.product_candidates = unique
            if len(unique) == 1:
                product_name = unique[0]
                product = next((p for p in ALL_PRODUCTS if p.get("product_name") == product_name), None)
                if product:
                    matched = next((phrase for name, phrase in matches if name == product_name), product_name)
                    screening = self._product_screening(product, matched)
                    session.screening = screening
                    result = {"status": "RECOMMENDATION_FOUND", "message": "", "recommendations": [product], "product": product, "screening": screening, "safety": {"red_flag": False}}
                    return self._remember_recommendation(session, result)
            key = frozenset(unique)
            question = PRODUCT_CONCERN_QUESTIONS.get(key)
            if question and not session.product_concern_question_asked:
                session.product_concern_question_asked = True
                session.last_question = "product_concern"
                return {"status": "ASK", "message": question, "recommendations": [], "safety": {"red_flag": False}}
        return None

    @staticmethod
    def _clinical_symptom_present(text):
        primary, secondary = extract_symptoms(text)
        symptoms = {x for x in ([primary] if primary else []) + (secondary or [])}
        # Only symptoms that should force clinical/safety assessment block an
        # otherwise legitimate product-concern route. Routine constipation,
        # gas, bloating and diarrhea can coexist with an explicit product
        # concern without preventing that concern from being handled.
        return bool(symptoms & {
            "bleeding", "piles", "anal fissures",
            "stomach pain", "acidity", "heartburn", "indigestion", "vomiting"
        })

    @staticmethod
    def _remember_recommendation(session, result):
        """Record the product already shown so later messages do not rerun diagnosis."""
        recommendations = result.get("recommendations") or []
        if recommendations:
            session.last_product = recommendations[0]
        session.awaiting_close = True
        return result

    def handle_message(self, sid, user_message):
        session = self._get_session(sid)
        if session.ended:
            return {"status": "SESSION_ENDED", "message": SESSION_ENDED_MESSAGE, "recommendations": []}

        # Thank-you messages are acknowledgements, not a reason to lock the
        # conversation. Keep the session usable after "thank you", "thanks",
        # "thx", "appreciate it", etc.
        if is_gratitude_only(user_message):
            return {
                "status": "ACKNOWLEDGEMENT",
                "message": "You're welcome! If you have another question, just ask.",
                "recommendations": [],
            }

        if session.awaiting_close and is_satisfied_closing(user_message):
            session.ended = True
            return {"status": "SESSION_ENDED", "message": random_closing_response(), "recommendations": []}

        if is_greeting(user_message):
            return {"status": "GREETING", "message": random_greeting_response(), "recommendations": []}
        if is_gibberish(user_message):
            return {"status": "GIBBERISH", "message": random_gibberish_response(), "recommendations": []}

        # A final diagnosis is a terminal state for the clinical pipeline.
        # Do not re-run symptom extraction, questionnaire questions, or
        # diagnosis on later messages in the same session. Product-name
        # lookups remain available as non-diagnostic follow-ups.
        if session.diagnosis_complete:
            named_after_diagnosis = find_named_product(user_message)
            if named_after_diagnosis:
                session.last_product = named_after_diagnosis
                return {
                    "status": "PRODUCT_INFO_FOUND",
                    "message": "",
                    "product": named_after_diagnosis,
                    "recommendations": [named_after_diagnosis],
                    # Product follow-ups are informational, not a continuation
                    # of the clinical assessment. Do not pass the old screening
                    # result to the response layer.
                    "screening": None,
                }
            return {
                "status": "DIAGNOSIS_COMPLETE",
                "message": "Your assessment is already complete. I won't start a new diagnosis in this chat. If you want information about a Guttify product or the assessment already given, ask me directly.",
                "recommendations": [],
                "screening": session.screening,
            }

        safety = check_safety(user_message)
        if safety["red_flag"]:
            screening = {
                "pattern": "Red-flag presentation",
                "likely_condition": "Red-flag presentation",
                "confidence": "high",
                "evidence": safety["reasons"],
                "differentials": [],
                "action": "urgent_medical_evaluation",
                "product_allowed": False,
                "message": safety["message"],
            }
            return {"status": "SAFETY_REVIEW", "message": safety["message"], "recommendations": [], "safety": safety, "screening": screening}

        named = find_named_product(user_message)

        # A recommendation has already been delivered. Do not feed subsequent
        # messages back into diagnosis/recommendation matching: doing so can
        # reproduce the same product block for messages such as "Piles Pure",
        # "stop", or a short follow-up. Explicit product names stay in the
        # product-information path; other follow-ups use the last approved
        # product without changing the clinical assessment.
        if session.awaiting_close:
            if named:
                session.last_product = named
                return {
                    "status": "PRODUCT_INFO_FOUND",
                    "message": "",
                    "product": named,
                    "recommendations": [named],
                    # Keep this product-only. The previous clinical assessment
                    # must not be attached to a product-information answer.
                    "screening": None,
                }

            # Once a recommendation has been delivered, this session is
            # finished from the clinical/recommendation pipeline's perspective.
            # Do NOT allow a later symptom (e.g. "constipation") to restart
            # diagnosis. Previously this branch only blocked non-clinical text,
            # so a new symptom could re-enter the questionnaire and set
            # diagnosis_complete=True, after which every later message was
            # incorrectly treated as a completed diagnosis.
            #
            # Product-name lookups above remain available. For ordinary
            # product follow-ups ("what is it for?", "how do I take it?"),
            # keep using the last approved product. Only a new clinical/domain
            # symptom is blocked.
            if not has_domain_overlap(user_message) and session.last_product:
                return {
                    "status": "PRODUCT_INFO_FOUND",
                    "message": "",
                    "product": session.last_product,
                    "recommendations": [session.last_product],
                    "screening": None,
                }

            return {
                "status": "RECOMMENDATION_COMPLETE",
                "message": "That recommendation has already been provided. If you want information about a Guttify product, ask me about the product by name. To discuss a new health concern, please start a new chat.",
                "recommendations": [],
                "screening": None,
            }

        # A named product request is a shortcut only when the user is not
        # also reporting a clinical symptom that needs assessment.
        if named and not session.symptom_state.primary_symptom and not self._clinical_symptom_present(user_message):
            session.awaiting_close = True
            return {"status": "PRODUCT_INFO_FOUND", "message": "", "product": named, "recommendations": [named]}

        # First message establishes the branch. Every later message is treated
        # as an answer to the last question when a question is pending.
        pending_question = session.last_question
        if pending_question:
            self._apply_answer(session, user_message)
            session.last_question = None
        else:
            session.symptom_state = merge_state(session.symptom_state, user_message, [])
            session.symptom_state.red_flags = derive_red_flags(session.symptom_state)

        # Structured questionnaire answers can reveal a warning sign after the
        # raw-message safety check has already run. Never continue to product
        # matching once those facts are present.
        if session.symptom_state.red_flags:
            safety = {
                "safe_to_recommend": False,
                "requires_doctor": True,
                "red_flag": True,
                "reasons": session.symptom_state.red_flags,
                "message": "This needs medical evaluation rather than only self-treatment. I won't recommend a Guttify product for these symptoms.",
            }
            screening = {
                "pattern": "Red-flag presentation",
                "likely_condition": "Red-flag presentation",
                "confidence": "high",
                "evidence": session.symptom_state.red_flags,
                "differentials": [],
                "action": "urgent_medical_evaluation",
                "product_allowed": False,
                "message": safety["message"],
            }
            return {"status": "SAFETY_REVIEW", "message": safety["message"], "recommendations": [], "safety": safety, "screening": screening}

        # Explicit product concerns should not be lost just because the same
        # message also contains a gut symptom (for example, "bloating and dull
        # skin"). Keep this routing small: only the existing product-concern
        # aliases can activate it.
        if pending_question == "product_concern":
            product_result = self._product_concern_result(session, user_message)
            if product_result:
                return product_result
        elif detect_product_concerns(user_message):
            # Product concerns can coexist with low-risk gut symptoms (for
            # example, "bloating and dull skin"), but a clinically relevant
            # symptom must not be bypassed by the product router.
            if not self._clinical_symptom_present(user_message):
                product_result = self._product_concern_result(session, user_message)
                if product_result:
                    return product_result

        if not session.symptom_state.primary_symptom and not has_domain_overlap(user_message) and session.last_question is None:
            return {"status": "IRRELEVANT", "message": IRRELEVANT_MESSAGE, "recommendations": []}

        screening = evaluate_screening(session.symptom_state)
        session.screening = screening

        if self._can_assess(session, screening):
            # Reaching an assessable clinical pattern is the end of the
            # diagnostic pipeline for this session. This MUST be set before
            # product evaluation as well as for diagnosis-only outcomes;
            # otherwise a recommendation response can be followed by another
            # symptom message that re-enters the questionnaire and generates
            # another long diagnosis.
            session.diagnosis_complete = True

            if not screening.get("product_allowed"):
                session.diagnosis_complete = True
                return {"status": "DIAGNOSIS", "message": screening["message"], "recommendations": [], "safety": safety, "screening": screening}

            allowed = PRODUCT_ELIGIBILITY.get(screening.get("pattern"))
            result = evaluate_product(session.symptom_state, user_message, allowed_names=allowed, match_context=screening.get("pattern"))
            result = _filter_approved_products(result, screening)
            result["screening"] = screening
            result["safety"] = safety
            if result.get("status") in ("RECOMMENDATION_FOUND", "AMBIGUOUS"):
                return self._remember_recommendation(session, result)
            # Clinical assessment must never disappear merely because product
            # data is incomplete.
            session.diagnosis_complete = True
            return {"status": "DIAGNOSIS", "message": screening["message"], "recommendations": [], "safety": safety, "screening": screening}

        if session.questions_asked < MAX_QUESTIONS:
            q = next_question(session.symptom_state)
            if q:
                name, question_text = q
                if name not in session.symptom_state.asked_fields:
                    session.symptom_state.asked_fields.append(name)
                session.last_question = name
                session.questions_asked += 1
                return {"status": "ASK", "message": question_text, "recommendations": [], "safety": safety}

        # Hard stop: never loop forever. Produce the best available assessment.
        screening = evaluate_screening(session.symptom_state)
        if screening.get("pattern") == "Insufficiently characterized gut symptom pattern":
            screening = dict(screening)
            screening["pattern"] = "Preliminary gut-symptom assessment"
            screening["likely_condition"] = "Preliminary gut-symptom assessment"
            screening["message"] = "The available answers point to a gut-symptom pattern, but they do not support a more specific preliminary assessment yet."
        if screening.get("product_allowed") and screening.get("pattern") in PRODUCT_ELIGIBILITY:
            allowed = PRODUCT_ELIGIBILITY.get(screening.get("pattern"))
            result = evaluate_product(session.symptom_state, user_message, allowed_names=allowed, match_context=screening.get("pattern"))
            result = _filter_approved_products(result, screening)
            if result.get("status") in ("RECOMMENDATION_FOUND", "AMBIGUOUS"):
                result["screening"] = screening
                result["safety"] = safety
                return self._remember_recommendation(session, result)
        session.diagnosis_complete = True
        return {"status": "DIAGNOSIS", "message": screening["message"], "recommendations": [], "safety": safety, "screening": screening}


def re_fullmatch_number(text):
    return bool(re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", text or ""))
