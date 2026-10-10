"""GutGPT multi-turn clinical screening conversation manager.

The agent has three strict layers:
1) preserve the user's original symptom branch;
2) interpret every answer against the exact question that was asked;
3) run the deterministic clinical-pattern engine before product matching.

The LLM is never responsible for deciding whether an answer is relevant or
which condition/pattern was selected.
"""
from dataclasses import dataclass, field
from threading import RLock
import re
import time
import logging

from gibberish_checker import is_gibberish, random_gibberish_response
from greeting_checker import is_greeting, random_greeting_response
from satisfaction_checker import is_satisfied_closing, is_gratitude_only, random_closing_response
from intent_parser import (
    SymptomState, merge_state, extract_duration, extract_age,
    extract_bowel_frequency, extract_bowel_frequency_per_day,
    extract_severity, extract_lifestyle, extract_medications, extract_food_trigger, extract_food_related,
    extract_bool, extract_stool_form, normalize, extract_symptoms,
)
from symptom_questionnaire import next_question
from clinical_rule_engine import evaluate as evaluate_screening, _duration_days
from safety_checker import check_safety, detect_red_flags, derive_red_flags, is_pregnancy_or_lactation
from recommendation_engine import evaluate as evaluate_product, find_named_product, has_domain_overlap, IRRELEVANT_MESSAGE, products as ALL_PRODUCTS
from nlu_extractor import extract_natural_facts
from product_concern_router import detect_product_concerns

SESSION_ENDED_MESSAGE = "This conversation has already wrapped up. Please start a new chat if you'd like help with another question."
logger = logging.getLogger("gutgpt.nlu")
MAX_QUESTIONS = 15


PRODUCT_ELIGIBILITY = {
    "Functional constipation pattern": {"Digest Boost", "Guttify Poopie"},
    "Possible medication-associated constipation pattern": {"Digest Boost", "Guttify Poopie"},
    "IBS-C pattern": {"Digest Boost", "Guttify Poopie"},
    # Bowel-related abdominal pain with a documented bowel-habit change can
    # still route to Digest Boost when no safety/red-flag rule has blocked
    # product recommendations.
    "Bowel-related abdominal pain pattern": {"Digest Boost"},
    "Reflux/GERD-like symptom pattern": {"Acid Ease"},
    "Dyspepsia/indigestion pattern": {"Acid Ease"},
    # Upper-abdominal meal-related pain is not automatically an acidity case.
    # _filter_approved_products() narrows this dynamically: Digest Boost is the
    # default for stomach-pain/dyspepsia without clear acid features, while
    # Acid Ease is retained when heartburn/acidity/reflux is explicitly present.
    "Upper-abdominal meal-related dyspepsia pattern": {"Digest Boost", "Acid Ease"},
    "Food-triggered gas/bloating pattern": {"Digest Boost", "Acid Ease", "Guttify Poopie"},
    "Constipation-associated bloating pattern": {"Digest Boost", "Guttify Poopie"},
    "Functional gas/bloating pattern": {"Digest Boost", "Acid Ease", "Guttify Poopie"},
    "Possible hemorrhoid pattern": {"Piles Pure", "Piloease Anal Care Spray"},
    "Possible anal fissure pattern": {"Piloease Anal Care Spray"},
}

# Additional symptom-cluster routing. These are deliberately explicit rather
# than inferred from every product.json symptom field, so a broad database
# match can never silently turn into a recommendation. The completed clinical
# pattern remains the safety gate; these routes only add products for other
# symptoms that the user explicitly reported in the same assessment.
ADDITIONAL_SYMPTOM_PRODUCT_ELIGIBILITY = {
    "constipation": {"Digest Boost", "Guttify Poopie"},
    "hard stools": {"Digest Boost", "Guttify Poopie"},
    "acidity": {"Acid Ease"},
    "heartburn": {"Acid Ease"},
    "acid reflux": {"Acid Ease"},
    "indigestion": {"Acid Ease"},
    "bloating": {"Digest Boost", "Acid Ease", "Guttify Poopie"},
    "gas": {"Digest Boost", "Acid Ease", "Guttify Poopie"},
    "piles": {"Piles Pure", "Piloease Anal Care Spray"},
    "haemorrhoids": {"Piles Pure", "Piloease Anal Care Spray"},
    "hemorrhoids": {"Piles Pure", "Piloease Anal Care Spray"},
    "anal fissures": {"Piloease Anal Care Spray"},
}

# Product-concern branches are not medical diagnoses. They route explicit
# product-relevant concerns to the product database (skin, vitamins, weight
# management, liver support) after the gut-symptom parser has had first pick.
PRODUCT_CONCERN_QUESTIONS = {
    frozenset({"Piles Pure", "Piloease Anal Care Spray"}): (
        "Are you mainly looking for support with swelling/lumps and piles discomfort, "
        "or with burning, itching, or irritation around the anal area?"
    ),
}



def _approved_names_for_screening(screening, state=None):
    """Return the product allow-list for a completed clinical pattern.

    Upper-abdominal meal-related stomach pain is routed by the actual acid
    evidence: Digest Boost is the default; Acid Ease is used when clear
    heartburn/acidity/reflux is explicitly present.
    """
    pattern = screening.get("pattern") if isinstance(screening, dict) else None
    allowed = set(PRODUCT_ELIGIBILITY.get(pattern) or set())

    if pattern == "Upper-abdominal meal-related dyspepsia pattern" and state is not None:
        secondary = {str(x).strip().lower() for x in (state.secondary_symptoms or [])}
        clear_acid = bool(
            getattr(state, "reflux_present", None) is True
            or secondary.intersection({"acidity", "heartburn", "acid reflux"})
        )
        allowed = {"Acid Ease"} if clear_acid else {"Digest Boost"}

    # Add independently eligible products for other symptoms explicitly
    # present in this same assessment. Primary-pattern safety remains intact;
    # this only broadens the product allow-list for already reported symptom
    # clusters.
    if state is not None and allowed:
        reported = set()
        if state.primary_symptom:
            reported.add(str(state.primary_symptom).strip().lower())
        reported.update(str(x).strip().lower() for x in (state.secondary_symptoms or []))
        for symptom in reported:
            allowed.update(ADDITIONAL_SYMPTOM_PRODUCT_ELIGIBILITY.get(symptom, set()))

    return allowed or None


def _filter_approved_products(result, screening, state=None):
    """Keep product matching separate from clinical reasoning and apply a small
    explicit eligibility allow-list so generic products (for example B12) do
    not win simply because their database row contains the word constipation.
    """
    allowed = _approved_names_for_screening(screening, state)
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
    # Product recommendations remain blocked for the rest of this session
    # after pregnancy/lactation is disclosed.
    pregnancy_lactation_caution: bool = False


class ConversationManager:
    def __init__(self):
        self.sessions = {}
        self.last_access = {}
        self._lock = RLock()

    def _get_session(self, sid):
        self.last_access[sid] = time.monotonic()
        return self.sessions.setdefault(sid, SessionState())

    def reset(self, sid):
        self.sessions[sid] = SessionState()
        self.last_access[sid] = time.monotonic()

    def remove(self, sid):
        self.sessions.pop(sid, None)
        self.last_access.pop(sid, None)

    @staticmethod
    def _set(data, key, value):
        if value is not None:
            data[key] = value

    def _apply_nlu_facts(self, session, facts):
        """Merge validated NLU facts; never diagnose or select products."""
        if not isinstance(facts, dict):
            return
        s = session.symptom_state
        data = s.to_dict()
        symptoms = [x for x in (facts.get("symptoms") or []) if isinstance(x, str)]

        primary = data.get("primary_symptom")
        if not primary and symptoms:
            data["primary_symptom"] = symptoms[0]
            primary = symptoms[0]

        secondary = list(data.get("secondary_symptoms") or [])
        for symptom in symptoms:
            if symptom != primary and symptom not in secondary:
                secondary.append(symptom)
        data["secondary_symptoms"] = secondary

        def set_if(value, key):
            if value is not None:
                data[key] = value

        set_if(facts.get("duration"), "duration")
        set_if(facts.get("age"), "age")
        if facts.get("severity") in {"mild", "moderate", "severe"} or (
            isinstance(facts.get("severity"), str) and re.fullmatch(r"(?:10|[0-9])(?:\.\d+)?", facts["severity"].strip())
        ):
            data["severity"] = facts["severity"]

        for src, dst in {
            "straining": "straining",
            "weight_loss": "weight_loss",
            "lump_or_protrusion": "lump_or_prolapse",
            "itching": "itching",
            "burning": "burning",
            "swelling": "swelling",
            "gas": "gas",
            "recent_worsening": "recent_worsening",
            "vomiting": "vomiting",
            "fever": "fever",
        }.items():
            if isinstance(facts.get(src), bool):
                data[dst] = facts[src]

        if isinstance(facts.get("meal_relation"), bool):
            data["food_related"] = facts["meal_relation"]
        if facts.get("pain_relation") == "bowel_movements":
            data["pain_related_to_bowel_movement"] = True
        elif facts.get("pain_relation") == "none":
            data["pain_related_to_bowel_movement"] = False
        if isinstance(facts.get("bowel_pattern"), str):
            bp = facts["bowel_pattern"]
            if bp == "normal":
                data["constipation_explicit"] = False
                data["diarrhea"] = False
                data["diarrhea_explicit"] = False
                data["stool_form"] = None
                data["secondary_symptoms"] = [
                    x for x in (data.get("secondary_symptoms") or [])
                    if x not in {"constipation", "hard stools", "diarrhea"}
                ]
            elif bp == "constipation":
                data["constipation_explicit"] = True
            elif bp == "diarrhea":
                data["diarrhea"] = True
                data["diarrhea_explicit"] = True
            elif bp == "mixed":
                data["constipation_explicit"] = True
                data["diarrhea"] = True
                data["diarrhea_explicit"] = True

        set_if(facts.get("pain_location"), "pain_location")

        if isinstance(facts.get("swelling"), bool) and session.last_question == "vomiting_fever_swelling":
            data["abdominal_distension"] = facts["swelling"]

        if isinstance(facts.get("hard_stools"), bool):
            data["hard_stools"] = facts["hard_stools"]
            data["stool_form"] = 2 if facts["hard_stools"] else (
                None if data.get("stool_form") in (1, 2) else data.get("stool_form")
            )
            if facts["hard_stools"] and "hard stools" not in data["secondary_symptoms"]:
                data["secondary_symptoms"].append("hard stools")

        if isinstance(facts.get("constipation"), bool):
            data["constipation_explicit"] = facts["constipation"]
            if facts["constipation"] and "constipation" not in data["secondary_symptoms"]:
                data["secondary_symptoms"].append("constipation")

        if isinstance(facts.get("loose_stools"), bool):
            data["diarrhea"] = facts["loose_stools"]
            data["diarrhea_explicit"] = facts["loose_stools"]

        if isinstance(facts.get("pain"), bool):
            body_areas = {str(x).lower() for x in (facts.get("body_areas") or [])}
            question_context = session.last_question
            anal_context = (
                question_context == "anal_pain"
                or "anal" in body_areas
                or primary in {"piles", "anal fissures", "anal burning", "anal swelling"}
            )
            abdominal_context = question_context in {"bloating_pain", "pain", "ibs_pain", "pain_relation"}
            if anal_context:
                data["anal_pain"] = facts["pain"]
            elif abdominal_context:
                data["abdominal_pain"] = facts["pain"]

        body_areas = list(data.get("body_areas") or [])
        for area in facts.get("body_areas") or []:
            if area not in body_areas:
                body_areas.append(area)
        data["body_areas"] = body_areas
        set_if(facts.get("pain_character"), "pain_character")
        set_if(facts.get("pain_timing"), "pain_timing")

        if facts.get("pain_character") in {"sharp", "sharp/tearing", "tearing", "cutting"}:
            data["sharp_pain_during_stool"] = True

        if facts.get("bleeding") is True:
            data["blood_present"] = True
            if "bleeding" not in data["secondary_symptoms"] and primary != "bleeding":
                data["secondary_symptoms"].append("bleeding")
        elif facts.get("bleeding") is False:
            data["blood_present"] = False

        if facts.get("blood_type") == "bright_red":
            data["blood_colour"] = "bright_red"
            data["blood_present"] = True
        elif facts.get("blood_type") in {"black", "dark"}:
            data["blood_colour"] = "black"
            data["blood_present"] = True

        if facts.get("blood_location") in {"tissue", "dripping", "mixed"}:
            data["blood_location"] = facts["blood_location"]

        if facts.get("red_flags"):
            data["red_flags"] = list(dict.fromkeys(
                (data.get("red_flags") or []) + [str(x) for x in facts["red_flags"]]
            ))

        # Explicit contextual negatives can correct stale generic positives.
        if facts.get("weight_loss") is False:
            data["weight_loss"] = False
        if facts.get("hard_stools") is False and data.get("stool_form") in (1, 2):
            data["stool_form"] = None
        if facts.get("straining") is False:
            data["straining"] = False

        session.symptom_state = SymptomState(**data)

    @staticmethod
    def _question_has_answer(session, field):
        """Return True only when the pending question has actually been answered.

        `asked_fields` records that a question was shown; it must NOT be treated
        as proof that the user answered it. This prevents a mismatched reply
        such as "no lump" from causing the missing stool/strain question to be
        skipped and the assessment to terminate prematurely.
        """
        s = session.symptom_state
        # Only enforce answer-consumption for question fields whose parser has
        # an exact contextual handler. Other multi-part questions intentionally
        # retain the existing questionnaire behavior.
        checks = {
            "duration": lambda: s.duration not in (None, "unknown"),
            "age": lambda: s.age is not None,
            "weight_loss": lambda: s.weight_loss is not None,
            "weight_loss_duration": lambda: s.weight_loss is not None,
            "bowel_frequency": lambda: s.bowel_frequency_per_week is not None,
            "daily_frequency": lambda: s.bowel_frequency_per_day is not None,
            # These are intentionally OR-based: the user may explicitly deny
            # constipation, explicitly confirm it, or describe only one of the
            # two supporting features (hard stools / straining).
            "stool_straining": lambda: s.stool_form is not None or s.straining is not None or s.constipation_explicit is not None,
            "constipation": lambda: s.stool_form is not None or s.straining is not None or s.constipation_explicit is not None,
            "incomplete_evacuation": lambda: s.incomplete_evacuation is not None,
            "bloating_pain": lambda: s.bloating is not None or s.abdominal_pain is not None,
            "pain": lambda: s.abdominal_pain is not None or s.pain_related_to_bowel_movement is not None,
            # The question explicitly asks for the relationship; either a meal
            # relationship or a bowel-movement relationship is sufficient, but
            # a bare "yes" is not.
            "pain_relation": lambda: s.food_related is not None or s.pain_related_to_bowel_movement is not None,
            "blood": lambda: s.blood_present is not None,
            "bleeding": lambda: s.blood_present is not None,
            "blood_colour": lambda: s.blood_colour is not None,
            "blood_location": lambda: s.blood_location is not None,
            "blood_mucus": lambda: s.blood_present is not None or s.mucus is not None,
            "anal_pain": lambda: s.sharp_pain_during_stool is not None or s.anal_pain is not None,
            "lump": lambda: s.lump_or_prolapse is not None,
            "lump_or_prolapse": lambda: s.lump_or_prolapse is not None,
            "hard_stools": lambda: s.hard_stools is not None,
            "straining": lambda: s.straining is not None,
            "vomiting_fever_swelling": lambda: (
                s.vomiting is not None and s.fever is not None and s.abdominal_distension is not None
            ),
            "vomiting_fever": lambda: s.vomiting is not None and s.fever is not None,
            "water": lambda: s.water_intake is not None,
            "fibre": lambda: s.fibre_intake is not None,
            "medications": lambda: s.medications is not None,
            "infection": lambda: s.recent_infection is not None,
            "night_weight_fever": lambda: s.night_time_symptoms is not None or s.weight_loss is not None or s.fever is not None,
            "swallowing": lambda: s.difficulty_swallowing is not None or s.persistent_vomiting is not None or s.vomiting_blood is not None,
            "weight_swallow": lambda: s.weight_loss is not None or s.difficulty_swallowing is not None or s.persistent_vomiting is not None or s.vomiting_blood is not None,
            "upper_symptoms": lambda: s.abdominal_pain is not None,
            "symptoms": lambda: s.abdominal_pain is not None or s.bloating is not None or s.diarrhea is not None or "constipation" in (s.secondary_symptoms or []),
            "stool_form": lambda: s.stool_form is not None,
            "severity": lambda: s.severity not in (None, "unknown"),
            "pain_location": lambda: s.pain_location is not None,
            "bowel_pattern": lambda: (
                s.diarrhea is not None
                or s.constipation_explicit is not None
                or s.bowel_frequency_per_week is not None
                or (s.stool_form is None and s.primary_symptom is not None and getattr(s, "diarrhea_explicit", None) is False and s.constipation_explicit is False)
            ),
            "reflux": lambda: getattr(s, "reflux_present", None) is not None,
            # For trigger questions, food_related=False is a valid explicit
            # answer meaning that no repeatable food/meal trigger was reported.
            "timing": lambda: s.night_time_symptoms is not None,
            "triggers": lambda: s.food_trigger is not None or s.food_related is False,
            "food_trigger": lambda: s.food_trigger is not None or s.food_related is False,
            "food_relation": lambda: s.food_related is not None,
            "trigger": lambda: s.food_trigger is not None or s.food_related is False,
        }
        check = checks.get(field)
        if check is None:
            return True
        return bool(check())

    def _run_nlu(self, session, text):
        before = session.symptom_state.to_dict()
        current_question = session.last_question
        facts = extract_natural_facts(text, current_question, session.symptom_state)
        self._apply_nlu_facts(session, facts)
        after = session.symptom_state.to_dict()

        changed = {}
        for key, value in after.items():
            if before.get(key) != value and value not in (None, [], "unknown"):
                changed[key] = value

        logger.info("[NLU][QUESTION_CONTEXT] last_question=%s", current_question)
        logger.info("[NLU][RAW] %r", text)
        logger.info(
            "[NLU] message_length=%d assessment_active=%s last_question=%s intent=%s confidence=%.2f",
            len(text), bool(session.symptom_state.primary_symptom or current_question),
            current_question, facts.get("intent"), facts.get("confidence", 0.0),
        )
        logger.info(
            "[NLU][EXTRACTED] facts=%s normalized_symptoms=%s",
            {k: v for k, v in facts.items() if v not in (None, [], "", False)},
            list(dict.fromkeys((facts.get("symptoms") or []) +
                               [session.symptom_state.primary_symptom] +
                               (session.symptom_state.secondary_symptoms or []))),
        )
        logger.info("[NLU][QUESTION_RESOLUTION] field=%s answered=%s", current_question, self._question_has_answer(session, current_question) if current_question else True)
        logger.info("[NLU][STATE_UPDATE] newly_added=%s", changed)
        return facts

    def _apply_answer(self, session, text):
        """Parse an answer using the exact question context, then merge any
        additional volunteered details without replacing the primary branch.
        """
        field = session.last_question
        s = session.symptom_state
        n = normalize(text)
        data = s.to_dict()

        # Deterministic contextual extractor is the first authority for the
        # active question. It may resolve multiple slots in one message.
        contextual = extract_natural_facts(text, field, s)

        # The contextual NLU is authoritative for the active question. The
        # legacy field-specific parsers below remain as compatibility fallbacks,
        # but they must not overwrite a correctly understood natural-language
        # answer with None. This closes gaps such as "absolutely", "yes
        # sometimes", "it does", and long-form numeric/lifestyle answers.
        contextual_to_state = {
            "incomplete_evacuation": "incomplete_evacuation",
            "blood": "bleeding",
            "anal_pain": "pain",
            "lump": "lump_or_prolapse",
            "weight_loss": "weight_loss",
            "weight_loss_duration": "weight_loss",
            "infection": "recent_infection",
            "timing": "night_time_symptoms",
        }
        key = contextual_to_state.get(field)
        if key and isinstance(contextual.get(key), bool):
            if key == "bleeding":
                data["blood_present"] = contextual[key]
            elif key == "pain":
                if field == "anal_pain":
                    data["anal_pain"] = contextual[key]
                    data["sharp_pain_during_stool"] = contextual[key]
                elif field in {"bloating_pain", "pain", "pain_relation"}:
                    data["abdominal_pain"] = contextual[key]
            elif key == "lump_or_prolapse":
                data["lump_or_prolapse"] = contextual[key]
            else:
                data[key] = contextual[key]

        if isinstance(contextual.get("incomplete_evacuation"), bool):
            data["incomplete_evacuation"] = contextual["incomplete_evacuation"]
        if isinstance(contextual.get("pain_related_to_bowel_movement"), bool):
            data["pain_related_to_bowel_movement"] = contextual["pain_related_to_bowel_movement"]
        if isinstance(contextual.get("water_intake"), str):
            data["water_intake"] = contextual["water_intake"]
        if isinstance(contextual.get("fibre_intake"), str):
            data["fibre_intake"] = contextual["fibre_intake"]
        if isinstance(contextual.get("medications"), str):
            data["medications"] = contextual["medications"]

        if field == "severity" and contextual.get("severity") is not None:
            data["severity"] = contextual["severity"]
            if isinstance(contextual.get("recent_worsening"), bool):
                data["recent_worsening"] = contextual["recent_worsening"]
        if field == "bowel_pattern" and contextual.get("bowel_pattern"):
            bp = contextual["bowel_pattern"]
            if bp == "normal":
                data["constipation_explicit"] = False
                data["diarrhea"] = False
                data["diarrhea_explicit"] = False
                data["stool_form"] = None
                data["secondary_symptoms"] = [
                    x for x in (data.get("secondary_symptoms") or [])
                    if x not in {"constipation", "hard stools", "diarrhea"}
                ]
            elif bp == "constipation":
                data["constipation_explicit"] = True
            elif bp == "diarrhea":
                data["diarrhea"] = True
                data["diarrhea_explicit"] = True
            elif bp == "mixed":
                data["constipation_explicit"] = True
                data["diarrhea"] = True
                data["diarrhea_explicit"] = True
        if field == "pain_location" and contextual.get("pain_location"):
            data["pain_location"] = contextual["pain_location"]
        if field in {"pain_relation", "food_relation"}:
            if contextual.get("meal_relation") is True:
                data["food_related"] = True
            if contextual.get("pain_relation") == "bowel_movements":
                data["pain_related_to_bowel_movement"] = True
            elif contextual.get("pain_relation") == "none":
                data["food_related"] = False
                data["pain_related_to_bowel_movement"] = False

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

        elif field in ("stool_straining", "constipation"):
            # Both question IDs exist in older questionnaire branches. Treat
            # them as the same semantic slot so a branch cannot ask the same
            # stool/strain question forever.
            stool_form = extract_stool_form(text)
            self._set(data, "stool_form", stool_form)
            # A bare yes/no answers the combined constipation question as a
            # whole; it must not be reused as a yes/no answer for one arbitrary
            # sub-feature such as straining.
            if n in {"yes", "yeah", "yep", "yup", "sure", "true"}:
                v = None
            elif n in {"no", "nope", "nah", "none", "false"}:
                v = False
            else:
                v = extract_bool(text, ["strain", "straining", "push hard", "pushing hard"], ["no strain", "without straining"])
            self._set(data, "straining", v)

            # Explicit constipation answers are useful even when the user does
            # not specify which supporting feature they mean.
            if n in {"no", "nope", "nah", "none", "false"} or re.search(r"\b(?:no|not|never|without|dont|don't|do not)\s+(?:have\s+)?(?:constipation|constipated)\b", n):
                data["constipation_explicit"] = False
                if stool_form is None:
                    data["stool_form"] = None
                data["straining"] = False if v is None else v
            elif n in {"yes", "yeah", "yep", "yup", "sure", "true"} or re.search(r"\b(?:constipation|constipated)\b", n):
                data["constipation_explicit"] = True

        elif field == "incomplete_evacuation":
            v = extract_bool(text,
                             ["incomplete evacuation", "not completely empty", "not fully empty", "still feel like i need to go", "feel incompletely empty", "yes", "yeah", "yep"],
                             ["complete evacuation", "completely empty", "fully empty", "no"])
            self._set(data, "incomplete_evacuation", v)

        elif field in ("bloating_pain", "pain"):
            if n not in {"yes", "yeah", "yep", "yup", "sure", "true"}:
                self._set(data, "bloating", extract_bool(text, ["bloating", "bloated", "bloat"], ["no bloating", "not bloated"]))
                self._set(data, "abdominal_pain", extract_bool(text, ["abdominal pain", "stomach pain", "belly pain", "stomach ache", "cramps", "cramping"], ["no abdominal pain", "no stomach pain", "no pain", "no"]))
                self._set(data, "pain_related_to_bowel_movement", extract_bool(text,
                    ["pain improves after stool", "pain improves after bowel movement", "pain relieved after stool", "pain relieved after bowel movement", "better after bowel movement", "worse after bowel movement", "related to bowel movement", "changes with bowel movement"],
                    ["not related to bowel movement", "not related to stool", "no pain"]))

        elif field in ("pain_relation", "ibs_pain"):
            self._set(data, "pain_related_to_bowel_movement", extract_bool(text,
                ["improves after bowel movement", "improves after stool", "better after bowel movement", "better after stool", "relieved after bowel movement", "worse after bowel movement", "related to bowel movement", "changes with bowel movement"],
                ["not related to bowel movement", "not related to bowel movements", "not related to stool", "no bowel relation"]))
            # The stomach-pain question asks about meals OR bowel movements.
            # Capture an explicit meal answer as a valid part of that slot.
            meal_relation = extract_bool(
                text,
                ["after meals", "after meal", "after eating", "after food", "when i eat", "whenever i eat", "related to meals", "triggered by meals"],
                ["not after meals", "not after meal", "not after eating", "not related to meals", "not triggered by meals", "not related to food"]
            )
            self._set(data, "food_related", meal_relation)

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
            if n in {"yes", "yeah", "yep", "yup", "sure", "true"}:
                # A bare yes is ambiguous for a 3-part question; leave the
                # fields unset so the caller asks a targeted clarification.
                pass
            else:
                self._set(data, "vomiting", extract_bool(text, ["vomiting", "vomit", "throwing up"], ["no vomiting", "not vomiting", "no"]))
                self._set(data, "fever", extract_bool(text, ["fever", "high temperature"], ["no fever", "no"]))
                self._set(data, "abdominal_distension", extract_bool(text, ["severe swelling", "severe abdominal swelling", "severe abdominal distension", "very swollen"], ["no severe swelling", "no swelling", "no"]))

        elif field == "vomiting_fever":
            if n in {"yes", "yeah", "yep", "yup", "sure", "true"}:
                pass
            else:
                self._set(data, "vomiting", extract_bool(text, ["vomiting", "vomit", "throwing up"], ["no vomiting", "not vomiting", "no"]))
                self._set(data, "fever", extract_bool(text, ["fever", "high temperature"], ["no fever", "no"]))

        elif field == "blood_mucus":
            if n in {"yes", "yeah", "yep", "yup", "sure", "true"}:
                pass
            else:
                self._set(data, "blood_present", extract_bool(text, ["blood", "bleeding"], ["no blood", "no bleeding", "no"]))
                self._set(data, "mucus", extract_bool(text, ["mucus"], ["no mucus", "no"]))

        elif field == "red_flag_check":
            flags = detect_red_flags(text)
            if flags:
                data["red_flags"] = list(dict.fromkeys((s.red_flags or []) + flags))

        elif field == "water":
            water, _ = extract_lifestyle(text)
            if water:
                data["water_intake"] = water
            else:
                m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:litres?|liters?|litters?|l)\b", n)
                if m:
                    data["water_intake"] = m.group(1) + " L"
                elif re.fullmatch(r"(?:one|two|three|four|five|six)\s*(?:litres?|liters?|litters?|l)?", n):
                    words = {"one":"1", "two":"2", "three":"3", "four":"4", "five":"5", "six":"6"}
                    data["water_intake"] = words[n.split()[0]] + " L"
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
            self._set(data, "medications", extract_medications(text) or ("none" if n in {"no", "none", "no medicines", "no medication", "no medications", "no supplements", "not taking anything"} else None))

        elif field == "infection":
            self._set(data, "recent_infection", extract_bool(text,
                ["food poisoning", "stomach infection", "gut infection", "gastroenteritis", "after an infection", "yes", "yeah", "yep"],
                ["no recent infection", "no infection", "no"]))

        elif field in ("night_weight_fever",):
            if n not in {"yes", "yeah", "yep", "yup", "sure", "true"}:
                self._set(data, "night_time_symptoms", extract_bool(text, ["wakes me at night", "wake me at night", "at night"], ["not at night", "doesn't wake me", "does not wake me", "no"]))
                self._set(data, "weight_loss", extract_bool(text, ["weight loss", "losing weight"], ["no weight loss", "not losing weight", "no"]))
                self._set(data, "fever", extract_bool(text, ["fever"], ["no fever", "no"]))

        elif field in ("swallowing", "weight_swallow"):
            if n not in {"yes", "yeah", "yep", "yup", "sure", "true"}:
                self._set(data, "difficulty_swallowing", extract_bool(
                    text,
                    ["difficulty swallowing", "trouble swallowing", "painful swallowing"],
                    ["no difficulty swallowing", "no trouble swallowing", "no painful swallowing", "no"]
                ))
                self._set(data, "persistent_vomiting", extract_bool(
                    text,
                    ["persistent vomiting", "vomiting repeatedly", "can't stop vomiting", "cant stop vomiting"],
                    ["no vomiting", "not vomiting", "no"]
                ))
                self._set(data, "vomiting_blood", extract_bool(
                    text,
                    ["vomiting blood", "throwing up blood", "hematemesis"],
                    ["no vomiting blood", "not vomiting blood", "no"]
                ))

        elif field == "upper_symptoms":
            # The indigestion questionnaire asks about upper-GI discomfort in
            # several natural forms (fullness, early satiety, burning, nausea,
            # belching). Store the presence of upper abdominal discomfort so
            # the questionnaire can advance without inventing a new clinical
            # state field. Meal association is collected separately.
            v = extract_bool(
                text,
                [
                    "upper abdominal fullness", "upper fullness", "fullness",
                    "early fullness", "early satiety", "burning", "nausea",
                    "nauseous", "belching", "burping", "upper abdominal discomfort",
                ],
                ["none", "no symptoms"]
            )
            self._set(data, "abdominal_pain", v)

        elif field == "symptoms":
            # Capture the main symptom categories named in the food-intolerance
            # question so its branch-specific screening can actually advance.
            n2 = normalize(text)
            if any(term in n2 for term in ("diarrhea", "diarrhoea", "loose stool", "loose stools", "loose motion")):
                data["diarrhea"] = True
            if any(term in n2 for term in ("constipation", "constipated", "hard stool", "hard stools")):
                data["secondary_symptoms"] = list(dict.fromkeys((data.get("secondary_symptoms") or []) + ["constipation"]))
            if any(term in n2 for term in ("abdominal pain", "stomach pain", "belly pain", "cramps", "cramping")):
                data["abdominal_pain"] = True
            if any(term in n2 for term in ("bloating", "bloated", "gas")):
                data["bloating"] = True

        elif field == "reflux":
            # `reflux_present` is a questionnaire slot only; it is deliberately
            # separate from `food_related`, which means meal association.
            data["reflux_present"] = extract_bool(
                text,
                ["acid coming back up", "acid reflux", "sour taste", "food coming back up", "regurgitation", "yes"],
                ["no acid coming up", "no reflux", "no sour taste", "no food coming back up", "no"]
            )

        elif field == "timing":
            # This is a timing/choice question, not a boolean presence question.
            # A bare "no" does not answer "How soon after eating does it start?"
            # and must therefore keep the question active. Only explicit timing
            # language can resolve this field.
            if re.search(r"\b(at night|during the night|when lying down|while lying down|when i lie down)\b", n):
                data["night_time_symptoms"] = True
            elif re.search(r"\b(not at night|does not happen at night|doesn't happen at night|not when lying down|not lying down|not after eating|not after meals|not related to meals)\b", n):
                data["night_time_symptoms"] = False

        elif field == "food_relation":
            data["food_related"] = extract_bool(
                text,
                ["after meals", "after meal", "after eating", "after food", "when i eat", "whenever i eat", "related to meals", "triggered by meals"],
                ["not after meals", "not after meal", "not after eating", "not related to meals", "not triggered by meals", "not related to food", "no"]
            )
            if data.get("food_related") is None:
                self._set(data, "food_related", extract_food_related(text))

        elif field in ("triggers", "food_trigger", "trigger"):
            trigger = extract_food_trigger(text)
            if trigger:
                data["food_trigger"] = trigger
                data["food_related"] = True
            elif re.search(r"\b(no|none|not|never|no particular|nothing)\b", n):
                # Explicitly answered: no repeatable food trigger. Keep the
                # canonical trigger field empty and record the negative in the
                # meal-association slot so the questionnaire can advance.
                data["food_related"] = False

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

        # A contextual numeric/lifestyle answer must not be reinterpreted by
        # the generic parser as an unrelated clinical score. For example,
        # "3 litters" is water intake, not pain severity 3. Preserve the
        # pre-merge severity unless the same message explicitly contains a
        # severity expression.
        if field == "water" and contextual.get("water_intake"):
            if not re.search(r"\b(?:pain|severity)\s*(?:is|of|around|about)?\s*\d|\b\d+\s*/\s*10\b", n):
                merged_data["severity"] = data.get("severity")

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
            # Do not end the assessment merely because three questions have
            # been asked. Bloating needs its branch-specific differentiators
            # (bowel pattern, food trigger, abdominal-pain relation, and stool
            # form) before a clinical pattern is finalized.
            return next_question(s) is None

        if branch == "indigestion":
            # Complete the upper-GI screening questions before diagnosis.
            return next_question(s) is None

        if branch == "food intolerance":
            # This branch has three dedicated questions; assess only after
            # those questions are answered or already known from the user's
            # messages.
            return next_question(s) is None

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

        # Resolve an answer to an earlier ambiguous product-concern question.
        if session.product_candidates and set(session.product_candidates) == {"Piles Pure", "Piloease Anal Care Spray"}:
            n = normalize(text)
            if set(session.product_candidates) == {"Piles Pure", "Piloease Anal Care Spray"}:
                if any(term in n for term in ("swelling", "swollen", "lump", "piles discomfort")):
                    matches = [("Piles Pure", "swelling")]
                elif any(term in n for term in ("burning", "itching", "itch", "irritation")):
                    matches = [("Piloease Anal Care Spray", "burning/itching/irritation")]

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
                    session.last_question = None
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
        # Serialize session mutation so concurrent requests cannot interleave
        # questionnaire updates for the same in-memory manager.
        with self._lock:
            return self._handle_message(sid, user_message)

    def _handle_message(self, sid, user_message):
        session = self._get_session(sid)

        # SAFETY MUST ALWAYS RUN FIRST. A user can disclose an emergency after
        # diagnosis, after a product recommendation, or after saying thanks.
        safety = check_safety(user_message)
        if is_pregnancy_or_lactation(user_message):
            session.pregnancy_lactation_caution = True

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
            session.screening = screening
            return {"status": "SAFETY_REVIEW", "message": safety["message"], "recommendations": [], "safety": safety, "screening": screening}

        if session.pregnancy_lactation_caution:
            caution = {
                "safe_to_recommend": False,
                "requires_doctor": False,
                "red_flag": False,
                "reasons": ["pregnancy/lactation product caution"],
                "message": "Because pregnancy or breastfeeding was mentioned, I won't recommend a Guttify product without appropriate professional guidance.",
            }
            return {"status": "SAFETY_REVIEW", "message": caution["message"], "recommendations": [], "safety": caution, "screening": session.screening}

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

        # Contextual NLU runs before relevance routing. An active question has
        # priority over generic domain/product classification.
        pending_question = session.last_question
        nlu_facts = self._run_nlu(session, user_message)

        # Keep the existing deterministic parser as a second layer.
        if pending_question:
            self._apply_answer(session, user_message)
            self._apply_nlu_facts(session, nlu_facts)
            session.symptom_state.red_flags = derive_red_flags(session.symptom_state)

            # Safety overrides question completeness: a newly extracted red
            # flag must stop the assessment even when a multi-part question
            # still has unanswered subfields.
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
                return {"status": "SAFETY_REVIEW", "message": safety["message"],
                        "recommendations": [], "safety": safety, "screening": screening}

            # Do not consume a question merely because it was displayed. If
            # the response did not answer that question, keep the context
            # active and ask for clarification instead of skipping a required
            # clinical field or declaring a diagnosis prematurely.
            if not self._question_has_answer(session, pending_question):
                session.last_question = pending_question
                # Use the exact question text associated with the pending field.
                question_texts = {
                    "duration": "How long has this been happening?",
                    "age": "What is your age?",
                    "weight_loss": "Have you lost any significant weight?",
                    "weight_loss_duration": "Have you lost any significant weight?",
                    "blood": "Have you noticed any bleeding or blood around/after a bowel movement?",
                    "blood_colour": "Is the blood bright/fresh red, or dark/black/tarry?",
                    "blood_location": "If it is bright red, is it on tissue, dripping into the toilet, or mixed into the stool?",
                    "anal_pain": "Is there sharp or tearing pain during or just after a bowel movement?",
                    "lump": "Is there a lump or something protruding from the anus?",
                    "stool_straining": "Are your stools hard or lumpy, and do you need to strain to pass them?",
                    "constipation": "Do you have hard stools or strain when passing stool?",
                    "blood_mucus": "Do you have blood or mucus in the stool?",
                    "vomiting_fever": "Any vomiting or fever?",
                    "vomiting_fever_swelling": "Any repeated vomiting, fever, or severe abdominal swelling?",
                    "reflux": "Do you get a sour taste or acid/food coming back up?",
                    "timing": "How soon after eating does it start?",
                    "triggers": "Do tea/coffee, spicy, oily, or particular foods trigger it?",
                    "food_trigger": "Is it repeatedly linked to dairy, wheat, beans/lentils, or another particular food?",
                    "food_relation": "Is it triggered or worsened by meals?",
                    "trigger": "Which food triggers it, and does it happen repeatedly after the same food?",
                    "pain_relation": "Is the pain more related to meals or to bowel movements?",
                    "bowel_pattern": "Do you mainly have constipation, diarrhea, or both at different times?",
                    "symptoms": "What happens after the food: bloating, gas, diarrhea, cramps, constipation, or something else?",
                }
                question_text = question_texts.get(pending_question, "Could you answer the question above in a little more detail?")
                logger.info("[QUESTION][BLOCK] field=%s reason=answer_not_understood action=ASK_CLARIFICATION", pending_question)
                logger.info("[NLU] unanswered_question field=%s; preserving context", pending_question)
                return {
                    "status": "ASK",
                    "message": f"I want to make sure I understood that. {question_text}",
                    "recommendations": [],
                    "safety": safety,
                }
            session.last_question = None
        else:
            session.symptom_state = merge_state(session.symptom_state, user_message, [])
            self._apply_nlu_facts(session, nlu_facts)

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

        # Never use product/domain keyword overlap to judge an answer while an
        # assessment is active. "2 days" is a valid answer to a duration
        # question even though it contains no symptom/product keyword.
        nlu_intent = nlu_facts.get("intent") if isinstance(nlu_facts, dict) else None
        if (
            not session.symptom_state.primary_symptom
            and not has_domain_overlap(user_message)
            and nlu_intent not in {"assessment", "answer_question", "new_symptom"}
            and not session.last_question
        ):
            return {"status": "IRRELEVANT", "message": IRRELEVANT_MESSAGE, "recommendations": []}

        if (
            not session.symptom_state.primary_symptom
            and nlu_intent in {"assessment", "answer_question", "new_symptom"}
            and not has_domain_overlap(user_message)
        ):
            return {
                "status": "ASK",
                "message": "I'm not completely sure I understood the main symptom. Could you tell me whether you're mainly experiencing pain, bleeding, itching, constipation, loose stools, bloating, acidity, or another digestive symptom?",
                "recommendations": [],
            }

        screening = evaluate_screening(session.symptom_state)
        session.screening = screening

        # Questionnaire completeness is the final gate before a normal
        # clinical assessment. Every branch must finish its own required
        # screening questions; do not let a branch-specific _can_assess()
        # shortcut diagnose early. Safety/urgent cases are handled above and
        # are deliberately allowed through immediately.
        if screening.get("action") != "urgent_medical_evaluation" and session.symptom_state.primary_symptom:
            pending = next_question(session.symptom_state)
            if pending:
                name, question_text = pending
                if name not in session.symptom_state.asked_fields:
                    session.symptom_state.asked_fields.append(name)
                session.last_question = name
                session.questions_asked += 1
                logger.info("[QUESTION] next=%s safety_flags=%s", name, session.symptom_state.red_flags)
                return {"status": "ASK", "message": question_text, "recommendations": [], "safety": safety}

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

            allowed = _approved_names_for_screening(screening, session.symptom_state)
            result = evaluate_product(session.symptom_state, user_message, allowed_names=allowed, match_context=screening.get("pattern"))
            result = _filter_approved_products(result, screening, session.symptom_state)
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
                logger.info("[QUESTION] next=%s safety_flags=%s", name, session.symptom_state.red_flags)
                return {"status": "ASK", "message": question_text, "recommendations": [], "safety": safety}

        # A required question is never bypassed by the max-question fallback.
        # If we still have active question context, keep the assessment blocked.
        if session.last_question:
            logger.warning(
                "[SAFETY][BLOCK] reason=required_question_unanswered field=%s",
                session.last_question,
            )
            return {
                "status": "ASK",
                "message": "I still need an answer to the question above before I can complete the assessment.",
                "recommendations": [],
                "safety": safety,
            }

        # Hard stop: never loop forever. Produce the best available assessment.
        screening = evaluate_screening(session.symptom_state)
        if screening.get("pattern") == "Insufficiently characterized gut symptom pattern":
            screening = dict(screening)
            screening["pattern"] = "Preliminary gut-symptom assessment"
            screening["likely_condition"] = "Preliminary gut-symptom assessment"
            screening["message"] = "The available answers point to a gut-symptom pattern, but they do not support a more specific preliminary assessment yet."
        if screening.get("product_allowed") and screening.get("pattern") in PRODUCT_ELIGIBILITY:
            allowed = _approved_names_for_screening(screening, session.symptom_state)
            result = evaluate_product(session.symptom_state, user_message, allowed_names=allowed, match_context=screening.get("pattern"))
            result = _filter_approved_products(result, screening, session.symptom_state)
            if result.get("status") in ("RECOMMENDATION_FOUND", "AMBIGUOUS"):
                result["screening"] = screening
                result["safety"] = safety
                return self._remember_recommendation(session, result)
        session.diagnosis_complete = True
        return {"status": "DIAGNOSIS", "message": screening["message"], "recommendations": [], "safety": safety, "screening": screening}


def re_fullmatch_number(text):
    return bool(re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", text or ""))
