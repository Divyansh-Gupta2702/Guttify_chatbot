"""Central question ownership and resolution policy for GutGPT.

This module is the single source of truth for which state slots an active
question owns and what constitutes a complete answer. It intentionally does
not perform diagnosis or recommendation.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
import re


@dataclass(frozen=True)
class QuestionResolution:
    field: str | None
    answered: bool
    values: dict = field(default_factory=dict)
    confidence: float = 0.0
    clarification_needed: bool = False
    answer_status: str = "unresolved"  # answered | unknown | unresolved
    source: str = "unresolved"         # deterministic | model | fallback | unresolved


@dataclass(frozen=True)
class QuestionSpec:
    fields: frozenset[str]
    answer_kind: str = "free_text"  # boolean, composite_boolean, numeric, choice, free_text
    require_all: bool = True
    allow_bare_no_all: bool = False
    allow_bare_yes_all: bool = False


# Explicit ownership for every questionnaire question id used by the
# questionnaire and legacy branches. New questionnaire prompts use one-field
# IDs; compound legacy IDs remain here for saved-checkpoint compatibility.
QUESTION_SCHEMA = {
    "duration": QuestionSpec(frozenset({"duration"}), "duration"),
    "age": QuestionSpec(frozenset({"age"}), "numeric"),
    "weight_loss": QuestionSpec(frozenset({"weight_loss"}), "boolean"),
    "weight_loss_duration": QuestionSpec(frozenset({"weight_loss"}), "boolean"),
    "bowel_frequency": QuestionSpec(frozenset({"bowel_frequency_per_week"}), "numeric"),
    "daily_frequency": QuestionSpec(frozenset({"bowel_frequency_per_day"}), "numeric"),
    "stool_straining": QuestionSpec(frozenset({"stool_form", "hard_stools", "straining", "constipation_explicit"}), "composite_boolean"),
    "constipation": QuestionSpec(frozenset({"stool_form", "hard_stools", "straining", "constipation_explicit"}), "composite_boolean"),
    "hard_stools": QuestionSpec(frozenset({"hard_stools"}), "boolean"),
    "straining": QuestionSpec(frozenset({"straining"}), "boolean"),
    "incomplete_evacuation": QuestionSpec(frozenset({"incomplete_evacuation"}), "boolean"),
    "abdominal_pain_screen": QuestionSpec(frozenset({"abdominal_pain"}), "boolean"),
    "pain_bowel_relation": QuestionSpec(frozenset({"pain_related_to_bowel_movement"}), "boolean"),
    "anal_discomfort_screen": QuestionSpec(frozenset({"anal_pain"}), "boolean"),
    "sharp_pain_during_stool": QuestionSpec(frozenset({"sharp_pain_during_stool"}), "boolean"),
    "mucus": QuestionSpec(frozenset({"mucus"}), "boolean"),
    "night_time_symptoms": QuestionSpec(frozenset({"night_time_symptoms"}), "boolean"),
    "vomiting": QuestionSpec(frozenset({"vomiting"}), "boolean"),
    "fever": QuestionSpec(frozenset({"fever"}), "boolean"),
    "abdominal_distension": QuestionSpec(frozenset({"abdominal_distension"}), "boolean"),
    "difficulty_swallowing": QuestionSpec(frozenset({"difficulty_swallowing"}), "boolean"),
    "persistent_vomiting": QuestionSpec(frozenset({"persistent_vomiting"}), "boolean"),
    "vomiting_blood": QuestionSpec(frozenset({"vomiting_blood"}), "boolean"),
    # Independent symptom checks reuse the existing canonical state fields.
    "constipation_screen": QuestionSpec(frozenset({"constipation_explicit"}), "boolean"),
    "diarrhea_screen": QuestionSpec(frozenset({"diarrhea_explicit"}), "boolean"),
    "gas_screen": QuestionSpec(frozenset({"gas"}), "boolean"),
    "bloating_screen": QuestionSpec(frozenset({"bloating"}), "boolean"),
    "bloating_pain": QuestionSpec(frozenset({"bloating", "abdominal_pain", "pain_related_to_bowel_movement"}), "composite_boolean"),
    "pain": QuestionSpec(frozenset({"abdominal_pain", "pain_related_to_bowel_movement"}), "conjunctive_boolean", allow_bare_yes_all=True, allow_bare_no_all=True),
    "pain_relation": QuestionSpec(frozenset({"food_related", "pain_related_to_bowel_movement"}), "choice"),
    "blood": QuestionSpec(frozenset({"blood_present"}), "boolean"),
    "bleeding": QuestionSpec(frozenset({"blood_present"}), "boolean"),
    "blood_colour": QuestionSpec(frozenset({"blood_colour"}), "choice"),
    "blood_location": QuestionSpec(frozenset({"blood_location"}), "choice"),
    "blood_mucus": QuestionSpec(frozenset({"blood_present", "mucus"}), "composite_boolean"),
    "anal_pain": QuestionSpec(frozenset({"anal_pain", "sharp_pain_during_stool"}), "boolean"),
    "lump": QuestionSpec(frozenset({"lump_or_prolapse"}), "boolean"),
    "lump_or_prolapse": QuestionSpec(frozenset({"lump_or_prolapse"}), "boolean"),
    "vomiting_fever": QuestionSpec(frozenset({"vomiting", "fever"}), "composite_boolean", allow_bare_no_all=True),
    "vomiting_fever_swelling": QuestionSpec(frozenset({"vomiting", "fever", "abdominal_distension"}), "composite_boolean", allow_bare_no_all=True),
    "night_weight_fever": QuestionSpec(frozenset({"night_time_symptoms", "weight_loss", "fever"}), "composite_boolean", allow_bare_no_all=True),
    "swallowing": QuestionSpec(frozenset({"difficulty_swallowing", "persistent_vomiting", "vomiting_blood"}), "composite_boolean", allow_bare_no_all=True),
    "weight_swallow": QuestionSpec(frozenset({"weight_loss", "difficulty_swallowing", "persistent_vomiting", "vomiting_blood"}), "composite_boolean", allow_bare_no_all=True),
    "upper_symptoms": QuestionSpec(frozenset({"upper_symptoms"}), "free_text"),
    "symptoms": QuestionSpec(frozenset({"abdominal_pain", "bloating", "diarrhea", "constipation_explicit", "gas", "other_symptoms"}), "free_text", require_all=False),
    "stool_form": QuestionSpec(frozenset({"stool_form"}), "numeric"),
    "severity": QuestionSpec(frozenset({"severity"}), "numeric"),
    "pain_location": QuestionSpec(frozenset({"pain_location"}), "choice"),
    "bowel_pattern": QuestionSpec(frozenset({"constipation_explicit", "diarrhea_explicit", "diarrhea"}), "choice"),
    "reflux": QuestionSpec(frozenset({"reflux_present"}), "boolean"),
    "timing": QuestionSpec(frozenset({"meal_timing", "symptom_onset_after_food", "timing_relation"}), "timing"),
    "triggers": QuestionSpec(frozenset({"food_trigger", "food_related"}), "choice"),
    "food_trigger": QuestionSpec(frozenset({"food_trigger", "food_related"}), "choice"),
    "food_relation": QuestionSpec(frozenset({"food_related"}), "boolean"),
    "trigger": QuestionSpec(frozenset({"food_trigger", "food_related"}), "choice"),
    "infection": QuestionSpec(frozenset({"recent_infection"}), "boolean"),
    "water": QuestionSpec(frozenset({"water_intake"}), "numeric"),
    "fibre": QuestionSpec(frozenset({"fibre_intake"}), "choice"),
    "medications": QuestionSpec(frozenset({"medications"}), "free_text"),
    "red_flag_check": QuestionSpec(frozenset({"red_flags"}), "free_text"),
    "product_concern": QuestionSpec(frozenset(), "free_text"),
}



# Complete state-field audit registry. Fields are classified even when they are
# not directly owned by a questionnaire question, so no state slot is silently
# orphaned from the audit.
STATE_FIELD_POLICY = {
    "primary_symptom": "initial_nlu",
    "secondary_symptoms": "initial_nlu",
    "frequency": "legacy_generic",
    "food_related": "question_or_explicit_volunteered",
    "food_trigger": "question_or_explicit_volunteered",
    "reflux_present": "question_owned",
    "meal_timing": "question_owned",
    "symptom_onset_after_food": "question_owned",
    "timing_relation": "question_owned",
    "severity": "question_owned",
    "duration": "question_owned",
    "age": "question_owned",
    "bowel_frequency_per_week": "question_owned",
    "bowel_frequency_per_day": "question_owned",
    "stool_form": "question_owned",
    "hard_stools": "question_owned_or_contextual",
    "straining": "question_owned",
    "incomplete_evacuation": "question_owned",
    "abdominal_pain": "question_owned",
    "upper_symptoms": "question_owned",
    "pain_location": "question_owned",
    "pain_related_to_bowel_movement": "question_owned",
    "blood_present": "question_owned",
    "blood_colour": "question_owned",
    "blood_location": "question_owned",
    "blood_mixed_with_stool": "explicit_or_derived",
    "anal_pain": "question_owned",
    "sharp_pain_during_stool": "question_owned",
    "lump_or_prolapse": "question_owned",
    "bloating": "question_owned_or_contextual",
    "diarrhea": "question_owned_or_contextual",
    "constipation_explicit": "question_owned_or_contextual",
    "diarrhea_explicit": "question_owned_or_contextual",
    "mucus": "question_owned",
    "fever": "question_owned_or_safety",
    "vomiting": "question_owned_or_safety",
    "persistent_vomiting": "question_owned",
    "vomiting_blood": "question_owned",
    "difficulty_swallowing": "question_owned",
    "abdominal_distension": "question_owned_or_safety",
    "night_time_symptoms": "question_owned",
    "weight_loss": "question_owned",
    "dehydration": "safety_or_contextual",
    "unable_to_pass_stool_and_gas": "safety_or_contextual",
    "water_intake": "question_owned",
    "fibre_intake": "question_owned",
    "medications": "question_owned",
    "recent_infection": "question_owned",
    "family_history_gi": "explicit_or_future_question",
    "body_areas": "contextual_nlu",
    "other_symptoms": "verbatim_context_only",
    "pain_character": "contextual_nlu",
    "pain_timing": "contextual_nlu",
    "itching": "contextual_nlu",
    "burning": "contextual_nlu",
    "swelling": "contextual_nlu",
    "gas": "question_owned_or_contextual",
    "recent_worsening": "question_owned_or_contextual",
    "red_flags": "safety_derived",
    "asked_fields": "question_engine",
    "weight_loss_duration_asked": "question_engine",
    "answered_unknown_fields": "question_engine",
    "refused_fields": "question_engine",
}


_UNKNOWN_RE = re.compile(
    r"^(?:(?:well|honestly|i guess|maybe)\s+)?(?:i\s+)?(?:don'?t|do\s+not|dont)\s+(?:really\s+)?know(?:\s+(?:for sure|really|yet))?$|"
    r"^(?:i\s+am|i'?m|im|not|still)\s+(?:not\s+)?(?:sure|certain|positive)(?:\s+(?:about that|yet|really|if|whether).*)?$|"
    r"^(?:unsure|uncertain|not certain|not positive|hard to say)$|"
    r"^(?:i\s+)?can'?t\s+(?:really\s+)?tell$|^no\s+idea$|^i\s+have\s+no\s+idea$|"
    r"^i\s+don'?t\s+remember$|^i\s+can'?t\s+say$|^not that i know(?: of)?$|"
    r"^(?:i\s+)?(?:have\s+)?no clue$|^maybe(?:\s+not)?$|"
    r"^(?:not really sure|i don't think so|i do not think so|i'm not too sure|im not too sure)$",
    re.I,
)
_REFUSAL_RE = re.compile(
    r"^(?:prefer not to say|rather not say|i'?d rather not say|"
    r"i do not want to answer|i don't want to answer|dont want to answer|"
    r"skip|i want to skip|rather not answer)$",
    re.I,
)
_YES_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|correct|that's\s+right|that\s+is\s+right|"
    r"absolutely|sure|definitely|certainly|of\s+course|true|exactly|"
    r"i\s+do|i\s+have|it\s+does|it\s+is|for\s+sure|"
    r"i\s+(?:do|have|am)|i\s+(?:experience|get|notice)\s+(?:it|that|them))$", re.I,
)
_NO_RE = re.compile(
    r"^(?:no|nope|nah|not\s+really|not\s+at\s+all|false|never|"
    r"i\s+don't|i\s+do\s+not|i\s+haven't|i\s+have\s+not|"
    r"it\s+doesn't|it\s+does\s+not|not usually|not often|"
    r"i\s+(?:don't|do not|haven't|have not|never)\s+(?:have|experience|get|notice)\s+(?:it|that|them))$", re.I,
)


_COMPOUND_COMPONENT_PATTERNS = {
    "blood_mucus": {
        "blood_present": r"\b(?:blood|bleeding|bloody)\b",
        "mucus": r"\bmuc(?:us|ous)\b",
    },
    "night_weight_fever": {
        "night_time_symptoms": r"\b(?:wake[s]? me|waking me|symptoms? at night|only at night|at night|during the night)\b",
        "weight_loss": r"\b(?:weight loss|losing weight|lost weight|unintentional weight loss)\b",
        "fever": r"\bfever\b",
    },
    "vomiting_fever": {
        "vomiting": r"\b(?:vomit(?:ing)?|throw(?:ing)? up)\b",
        "fever": r"\bfever\b",
    },
    "vomiting_fever_swelling": {
        "vomiting": r"\b(?:vomit(?:ing)?|throw(?:ing)? up)\b",
        "fever": r"\bfever\b",
        "abdominal_distension": r"\b(?:(?:abdominal|stomach|belly) swelling|distension|distention|swelling|swollen)\b",
    },
    "swallowing": {
        "difficulty_swallowing": r"\b(?:difficulty|trouble|painful|pain) swallowing\b",
        "persistent_vomiting": r"\b(?:persistent|repeated|repeatedly|can't stop|cannot stop) vomit(?:ing)?\b",
        "vomiting_blood": r"\b(?:vomit(?:ing)? blood|throw(?:ing)? up blood|blood in (?:my )?vomit)\b",
    },
    "weight_swallow": {
        "weight_loss": r"\b(?:weight loss|losing weight|lost weight|unintentional weight loss)\b",
        "difficulty_swallowing": r"\b(?:difficulty|trouble|painful|pain) swallowing\b",
        "persistent_vomiting": r"\b(?:persistent|repeated|repeatedly|can't stop|cannot stop) vomit(?:ing)?\b",
        "vomiting_blood": r"\b(?:vomit(?:ing)? blood|throw(?:ing)? up blood|blood in (?:my )?vomit)\b",
    },
}


def _component_boolean(message: str, pattern: str) -> bool | None:
    """Return an explicitly mentioned component value, without inferring absence."""
    negative = re.search(
        r"\b(?:no|not|never|without|don't|dont|do not|doesn't|does not|"
        r"isn't|is not|aren't|are not|haven't|have not|hasn't|has not)\b.{0,45}(?:" + pattern + r")",
        message,
    )
    if negative:
        return False
    if re.search(pattern, message):
        return True
    return None


def _composite_completion(question_id: str, values: dict, state=None) -> bool:
    """Check whether explicit/current values complete this question's required slots."""
    def get(name):
        value = values.get(name)
        return value if value is not None else getattr(state, name, None)

    if question_id == "pain":
        pain = get("abdominal_pain")
        return pain is False or (pain is True and get("pain_related_to_bowel_movement") is not None)
    if question_id == "bloating_pain":
        pain = get("abdominal_pain")
        if pain is True:
            return get("pain_related_to_bowel_movement") is not None
        if get("bloating") is None or pain is None:
            return False
        return pain is False
    if question_id in {"stool_straining", "constipation"}:
        return get("constipation_explicit") is not None or (
            (get("stool_form") is not None or get("hard_stools") is not None)
            and get("straining") is not None
        )
    if question_id in {"pain_relation", "food_relation", "triggers", "food_trigger", "trigger"}:
        if question_id == "pain_relation":
            meal, bowel = get("food_related"), get("pain_related_to_bowel_movement")
            return meal is True or bowel is True or (meal is False and bowel is False)
        return any(get(name) is not None for name in ("food_related", "food_trigger", "pain_related_to_bowel_movement"))
    spec = get_question_spec(question_id)
    return bool(spec) and all(get(name) is not None for name in spec.fields)


_CLARIFICATION_COMPONENTS = {
    "pain": (
        ("abdominal_pain", lambda s: s.abdominal_pain is None, "Do you have recurring abdominal pain or cramps?"),
        ("pain_related_to_bowel_movement", lambda s: s.abdominal_pain is True and s.pain_related_to_bowel_movement is None, "Does the pain improve, worsen, or change after a bowel movement?"),
    ),
    "bloating_pain": (
        ("bloating", lambda s: s.bloating is None, "Do you have bloating?"),
        ("abdominal_pain", lambda s: s.abdominal_pain is None, "Do you have recurring abdominal pain or cramps?"),
        ("pain_related_to_bowel_movement", lambda s: s.abdominal_pain is True and s.pain_related_to_bowel_movement is None, "Does the pain improve, worsen, or change after a bowel movement?"),
    ),
    "blood_mucus": (
        ("blood_present", lambda s: s.blood_present is None, "Have you noticed blood in or around the stool?"),
        ("mucus", lambda s: s.mucus is None, "Have you noticed mucus in the stool?"),
    ),
    "night_weight_fever": (
        ("night_time_symptoms", lambda s: s.night_time_symptoms is None, "Do your symptoms wake you at night or happen only at night?"),
        ("weight_loss", lambda s: s.weight_loss is None, "Have you had unexplained weight loss?"),
        ("fever", lambda s: s.fever is None, "Have you had a fever?"),
    ),
    "vomiting_fever": (
        ("vomiting", lambda s: s.vomiting is None, "Have you had repeated vomiting?"),
        ("fever", lambda s: s.fever is None, "Have you had a fever?"),
    ),
    "vomiting_fever_swelling": (
        ("vomiting", lambda s: s.vomiting is None, "Have you had repeated vomiting?"),
        ("fever", lambda s: s.fever is None, "Have you had a fever?"),
        ("abdominal_distension", lambda s: s.abdominal_distension is None, "Do you have severe abdominal swelling?"),
    ),
    "swallowing": (
        ("difficulty_swallowing", lambda s: s.difficulty_swallowing is None, "Do you have difficulty or pain swallowing?"),
        ("persistent_vomiting", lambda s: s.persistent_vomiting is None, "Have you had persistent or repeated vomiting?"),
        ("vomiting_blood", lambda s: s.vomiting_blood is None, "Have you vomited blood?"),
    ),
    "weight_swallow": (
        ("weight_loss", lambda s: s.weight_loss is None, "Have you had unexplained weight loss?"),
        ("difficulty_swallowing", lambda s: s.difficulty_swallowing is None, "Do you have difficulty or pain swallowing?"),
        ("persistent_vomiting", lambda s: s.persistent_vomiting is None, "Have you had persistent or repeated vomiting?"),
        ("vomiting_blood", lambda s: s.vomiting_blood is None, "Have you vomited blood?"),
    ),
    "stool_straining": (
        ("hard_stools", lambda s: s.hard_stools is None and s.stool_form is None, "Are your stools hard (hard stools) or lumpy?"),
        ("straining", lambda s: s.straining is None, "Do you need to strain to pass stool?"),
    ),
    "constipation": (
        ("hard_stools", lambda s: s.hard_stools is None and s.stool_form is None, "Are your stools hard (hard stools) or lumpy?"),
        ("straining", lambda s: s.straining is None, "Do you need to strain to pass stool?"),
    ),
    "pain_relation": (
        ("food_related", lambda s: s.food_related is None, "Is the pain related to meals or eating?"),
        ("pain_related_to_bowel_movement", lambda s: s.pain_related_to_bowel_movement is None, "Is the pain related to bowel movements?"),
    ),
}


def next_question_component(question_id: str, state) -> tuple[str, str] | None:
    """Return the first explicitly missing sub-question for a compound item."""
    unknown = set(getattr(state, "answered_unknown_fields", []) or [])
    refused = set(getattr(state, "refused_fields", []) or [])
    if question_id in unknown or question_id in refused:
        return None
    for component, missing, prompt in _CLARIFICATION_COMPONENTS.get(question_id, ()):
        if component not in unknown and component not in refused and missing(state):
            return component, prompt
    return None


def question_has_progressed(state: Any, question_id: str | None) -> bool:
    """Question-selection completion, including explicitly unknown components.

    This is only for progression. Clinical completion and safety gates continue
    to use question_has_answer, which requires actual clinical values.
    """
    if question_has_answer(state, question_id):
        return True
    unknown = set(getattr(state, "answered_unknown_fields", []) or [])
    refused = set(getattr(state, "refused_fields", []) or [])
    if question_id in unknown or question_id in refused:
        return True
    return bool(question_id in _CLARIFICATION_COMPONENTS and next_question_component(question_id, state) is None)

# Bare yes/no ownership. Composite questions are deliberately opt-in:
# a bare answer can only fill all slots when the question itself is a
# conjunctive proposition, not merely because the schema owns multiple fields.
_BARE_BOOL = {
    "weight_loss": {"weight_loss"},
    "weight_loss_duration": {"weight_loss"},
    "blood": {"blood_present"},
    "bleeding": {"blood_present"},
    "reflux": {"reflux_present"},
    "hard_stools": {"hard_stools"},
    "straining": {"straining"},
    "incomplete_evacuation": {"incomplete_evacuation"},
    "abdominal_pain_screen": {"abdominal_pain"},
    "pain_bowel_relation": {"pain_related_to_bowel_movement"},
    "anal_discomfort_screen": {"anal_pain"},
    "sharp_pain_during_stool": {"sharp_pain_during_stool"},
    "mucus": {"mucus"},
    "night_time_symptoms": {"night_time_symptoms"},
    "vomiting": {"vomiting"},
    "fever": {"fever"},
    "abdominal_distension": {"abdominal_distension"},
    "difficulty_swallowing": {"difficulty_swallowing"},
    "persistent_vomiting": {"persistent_vomiting"},
    "vomiting_blood": {"vomiting_blood"},
    "constipation_screen": {"constipation_explicit"},
    "diarrhea_screen": {"diarrhea_explicit"},
    "gas_screen": {"gas"},
    "bloating_screen": {"bloating"},
    "lump": {"lump_or_prolapse"},
    "lump_or_prolapse": {"lump_or_prolapse"},
    "infection": {"recent_infection"},
    "food_relation": {"food_related"},
    "anal_pain": {"anal_pain", "sharp_pain_during_stool"},
    "pain": {"abdominal_pain", "pain_related_to_bowel_movement"},
}

# Natural language answers for one-field boolean questions. The active prompt
# supplies the context, so a named positive or negative concept is sufficient
# even when the user doesn't say a bare "yes" or "no".
_SINGLE_BOOLEAN_PATTERNS = {
    "hard_stools": r"\b(?:hard|lumpy|firm)\b|\b(?:stools?|poop|poo)\s+(?:are|is)\s+(?:normal|soft)\b|\b(?:normal|soft)\s+(?:stools?|poop|poo)\b",
    "straining": r"\b(?:strain(?:ing)?|push(?:ing)? hard)\b",
    "incomplete_evacuation": r"\b(?:incomplete evacuation|not completely empty|not fully empty|still feel like i need to go)\b",
    "abdominal_pain_screen": r"\b(?:abdominal pain|stomach pain|belly pain|cramps?|stomach ache)\b",
    "anal_discomfort_screen": r"\b(?:anal\s+)?(?:pain|discomfort|hurt|hurts|soreness|sharp pain|tearing pain)\b",
    "sharp_pain_during_stool": r"\b(?:(?:sharp|tearing|cutting)\s+)+pain\b|\bpain\s+(?:during|after|when passing)\s+(?:a\s+)?(?:stool|poop|bowel movement)\b",
    "bloating_screen": r"\b(?:bloating|bloated|bloat|swollen feeling)\b",
    "gas_screen": r"\b(?:gas|gassy|flatulence|farting|passing gas)\b",
    "constipation_screen": r"\b(?:constipat(?:ion|ed)|hard stools?|unable to pass stool)\b",
    "diarrhea_screen": r"\b(?:diarrh(?:ea|oea)|loose stools?|loose motions?|watery stools?)\b",
    "vomiting": r"\b(?:vomit(?:ing)?|throw(?:ing)? up)\b",
    "fever": r"\bfever\b",
    "abdominal_distension": r"\b(?:abdominal|stomach|belly)?\s*(?:swelling|swollen|distension|distention)\b",
    "difficulty_swallowing": r"\b(?:difficulty|trouble|painful|pain) swallowing\b",
    "persistent_vomiting": r"\b(?:persistent|repeated|repeatedly|can't stop|cannot stop) vomit(?:ing)?\b",
    "vomiting_blood": r"\b(?:vomit(?:ing)? blood|throw(?:ing)? up blood|blood in (?:my )?vomit)\b",
    "mucus": r"\b(?:mucus|mucous)\b",
    "night_time_symptoms": r"\b(?:wake me|waking me|symptoms? at night|only at night|at night|during the night)\b",
    "blood": r"\b(?:blood|bleeding|bloody)\b",
    "lump": r"\b(?:lump|prolapse|protrusion|bulge|bump)\b",
}
# These are explicit multi-question safety checks. Bare "no" means none of
# the listed red-flag concepts; bare "yes" is intentionally unresolved because
# it does not identify which red flag is present.
_BARE_NO_ALL = {
    "vomiting_fever": {"vomiting", "fever"},
    "vomiting_fever_swelling": {"vomiting", "fever", "abdominal_distension"},
    "night_weight_fever": {"night_time_symptoms", "weight_loss", "fever"},
    "swallowing": {"difficulty_swallowing", "persistent_vomiting", "vomiting_blood"},
    "weight_swallow": {"weight_loss", "difficulty_swallowing", "persistent_vomiting", "vomiting_blood"},
}

def normalize_answer_text(value: str) -> str:
    n = (value or "").lower().replace("’", "'")
    n = re.sub(r"\s+", " ", n).strip()
    return n.strip(" \t\r\n.,!?;:")

def classify_answer_status(value: str) -> str:
    n = normalize_answer_text(value)
    if re.fullmatch(r"(?:sometimes|occasionally|rarely|once in a while|every now and then|every so often|from time to time)", n):
        return "sometimes"
    if _UNKNOWN_RE.fullmatch(n):
        return "unknown"
    if _REFUSAL_RE.fullmatch(n):
        return "refused"
    if _YES_RE.fullmatch(n):
        return "yes"
    if _NO_RE.fullmatch(n):
        return "no"
    return "other"

def _mark_unknown(state, question_id):
    unknown = list(getattr(state, "answered_unknown_fields", []) or [])
    if question_id not in unknown:
        unknown.append(question_id)
    state.answered_unknown_fields = unknown

def resolve_against_active_question(
    question_id: str | None,
    message: str,
    extracted: dict | None = None,
    state=None,
    active_component: str | None = None,
) -> dict:
    """Resolve one user turn against the active question.

    Returns a transport-neutral result:
      status: answered | unknown | unresolved
      values: only fields semantically owned by the active question
      confidence: deterministic confidence
      source: deterministic
    """
    spec = get_question_spec(question_id)
    if not question_id or spec is None:
        return {"status": "unresolved", "values": {}, "confidence": 0.0, "source": "unresolved"}

    n = normalize_answer_text(message)
    status = classify_answer_status(n)
    if status == "sometimes":
        # A frequency qualifier confirms a one-field yes/no symptom, but it
        # cannot supply a numeric count or resolve a compound question.
        status = "yes" if spec.answer_kind == "boolean" and len(spec.fields) == 1 else "unknown"

    # A clarification can narrow a compound question to one specific field.
    # In that context a short yes/no belongs to that field alone.
    if active_component in (spec.fields if spec else ()) and status in {"yes", "no"}:
        values = {active_component: status == "yes"}
        if question_id == "pain" and active_component == "abdominal_pain" and status == "no":
            values["pain_related_to_bowel_movement"] = False
        return {
            "status": "answered" if _composite_completion(question_id, values, state) else "partial",
            "values": values,
            "confidence": 0.99,
            "source": "deterministic",
        }
    if active_component in (spec.fields if spec else ()) and status == "unknown":
        return {
            "status": "partial",
            "values": {},
            "unknown_fields": [active_component],
            "confidence": 0.99,
            "source": "deterministic",
        }
    if active_component in (spec.fields if spec else ()) and status == "refused":
        return {
            "status": "partial",
            "values": {},
            "refused_fields": [active_component],
            "confidence": 0.99,
            "source": "deterministic",
        }

    component_patterns = _COMPOUND_COMPONENT_PATTERNS.get(question_id or "", {})
    component_values = {
        field: value
        for field, pattern in component_patterns.items()
        if (value := _component_boolean(n, pattern)) is not None
    }
    if question_id in {"swallowing", "weight_swallow"} and re.search(
        r"\b(?:no|not|never|without|don't|dont|do not)\b.{0,35}\b(?:vomit(?:ing)?|throw(?:ing)? up)\b",
        n,
    ):
        component_values.setdefault("persistent_vomiting", False)
    if question_id == "blood_mucus" and status == "no":
        component_values.update({"blood_present": False, "mucus": False})

    if question_id == "pain_relation":
        meal_negative = bool(re.search(r"\b(?:not|never|no|without|isn't|is not)\b.{0,35}\b(?:meals?|eating|food)\b", n))
        bowel_negative = bool(re.search(r"\b(?:not|never|no|without|isn't|is not)\b.{0,35}\b(?:bowel movements?|stool|poop)\b", n))
        meal_positive = not meal_negative and bool(re.search(r"\b(?:after meals?|after eating|when i eat|triggered by meals?|related to meals?)\b", n))
        bowel_positive = not bowel_negative and bool(re.search(r"\b(?:after (?:a )?(?:bowel movement|stool|poop)|related to (?:bowel movements?|stool)|changes? with (?:bowel movements?|stool))\b", n))
        no_bowel_change = bool(re.search(
            r"\b(?:no change|doesn't change|does not change|remains? the same|stays? the same|nothing changes?)\b",
            n,
        ))
        bowel_change = bool(re.search(
            r"\b(?:changes?|improves?|worsens?|gets? better|gets? worse)\b.{0,35}\b(?:after|with|following)\b.{0,20}\b(?:bowel|stool|poop|motion)",
            n,
        ))
        if no_bowel_change:
            bowel_negative = True
        elif bowel_change:
            bowel_positive = True
        if meal_positive or bowel_positive or meal_negative or bowel_negative:
            if meal_positive:
                component_values["food_related"] = True
            elif meal_negative:
                component_values["food_related"] = False
            if bowel_positive:
                component_values["pain_related_to_bowel_movement"] = True
            elif bowel_negative:
                component_values["pain_related_to_bowel_movement"] = False
            if meal_positive and not bowel_positive:
                component_values["pain_related_to_bowel_movement"] = False
            if bowel_positive and not meal_positive:
                component_values["food_related"] = False

    if question_id == "food_relation":
        meal_negative = bool(re.search(r"\b(?:not|never|no|without|isn't|is not)\b.{0,35}\b(?:triggered|worsened|related|after|by)?\s*(?:by\s+)?(?:meals?|eating|food)\b", n))
        meal_positive = bool(re.search(r"\b(?:triggered|worsened|related to|after)\b.{0,25}\b(?:meals?|eating|food)\b", n))
        if meal_negative or meal_positive:
            component_values["food_related"] = not meal_negative

    if question_id == "bloating_pain":
        bloating = _component_boolean(n, r"\b(?:bloating|bloated|bloat)\b")
        if bloating is not None:
            component_values["bloating"] = bloating

    if question_id in {"pain", "bloating_pain"}:
        pain_pattern = r"\b(?:abdominal pain|stomach pain|belly pain|stomach ache|cramps?|cramping|pain)\b"
        pain = _component_boolean(n, pain_pattern)
        if pain is not None:
            component_values["abdominal_pain"] = pain
            if pain is False:
                component_values["pain_related_to_bowel_movement"] = False
        relation_positive = re.search(
            r"\b(?:related to|changes? with|improves? after|worsens? after|"
            r"better after|worse after|worse before|relieved after)\b.{0,45}\b(?:bowel movements?|stool|poop)\b|"
            r"\b(?:after|when) (?:passing )?(?:a )?(?:bowel movement|stool|poop)\b",
            n,
        )
        relation_negative = re.search(
            r"\b(?:not|never|doesn't|does not|isn't|is not)\b.{0,30}"
            r"\brelated to\s+(?:bowel movements?|stool|poop)\b",
            n,
        )
        meal_link = bool(re.search(r"\b(?:after meals?|after eating|when i eat|triggered by meals?|related to meals?)\b", n))
        if re.search(r"\b(?:no change|doesn't change|does not change|remains? the same|stays? the same|nothing changes?)\b", n):
            relation_negative = True
        elif re.search(r"\b(?:changes?|improves?|worsens?)\b.{0,35}\b(?:after|with|following)\b.{0,20}\b(?:bowel|stool|poop|motion)", n):
            relation_positive = True
        elif meal_link:
            # If pain is explicitly linked to eating and the user says nothing
            # about bowel movements, answer the active bowel relation as no.
            relation_negative = True
        if relation_negative:
            component_values["pain_related_to_bowel_movement"] = False
        elif relation_positive:
            component_values["pain_related_to_bowel_movement"] = True

    if question_id == "pain_bowel_relation":
        if re.search(r"\b(?:no change|doesn't change|does not change|remains? the same|stays? the same|nothing changes?)\b", n):
            return {"status": "answered", "values": {"pain_related_to_bowel_movement": False}, "confidence": 0.99, "source": "deterministic"}
        if re.search(r"\b(?:changes?|improves?|worsens?|gets? better|gets? worse)\b.{0,35}\b(?:after|with|following)\b.{0,20}\b(?:bowel|stool|poop|motion)", n):
            return {"status": "answered", "values": {"pain_related_to_bowel_movement": True}, "confidence": 0.99, "source": "deterministic"}

    if component_values:
        complete = _composite_completion(question_id, component_values, state)
        return {
            "status": "answered" if complete else "partial",
            "values": component_values,
            "confidence": 0.99,
            "source": "deterministic",
        }

    if question_id in _SINGLE_BOOLEAN_PATTERNS:
        field_name = next(iter(spec.fields))
        value = _component_boolean(n, _SINGLE_BOOLEAN_PATTERNS[question_id])
        if value is not None:
            return {
                "status": "answered",
                "values": {field_name: value},
                "confidence": 0.99,
                "source": "deterministic",
            }

    if question_id == "upper_symptoms":
        if re.search(r"\b(?:none|no symptoms|none of those|nothing|not experiencing any)\b", n):
            return {"status": "answered", "values": {"upper_symptoms": "none reported"}, "confidence": 0.99, "source": "deterministic"}
        terms = [term for term, pattern in (
            ("bloating", r"\b(?:bloating|bloated|bloat)\b"),
            ("gas", r"\b(?:gas|gassy|flatulence|farting)\b"),
            ("acidity", r"\b(?:acidity|acidic|acid reflux)\b"),
            ("constipation", r"\b(?:constipation|constipated)\b"),
            ("diarrhea", r"\b(?:diarrhea|diarrhoea)\b"),
            ("indigestion", r"\bindigestion\b"),
            ("nausea", r"\b(?:nausea|nauseous|queasy|sick to my stomach)\b"),
            ("fullness", r"\b(?:fullness|full quickly|early satiety|early fullness)\b"),
            ("burning", r"\b(?:burning|burns)\b"),
            ("belching", r"\b(?:belching|burping|belch|burp)\b"),
            ("upper abdominal discomfort", r"\b(?:upper|epigastric) (?:abdominal )?(?:pain|discomfort|ache)\b"),
        ) if re.search(pattern, n)]
        if terms:
            return {"status": "answered", "values": {"upper_symptoms": ", ".join(terms)}, "confidence": 0.99, "source": "deterministic"}

    if question_id == "symptoms":
        values = {}
        for field_name, pattern in (
            ("bloating", r"\b(?:bloating|bloated|bloat)\b"),
            ("gas", r"\b(?:gas|gassy|flatulence|farting)\b"),
            ("diarrhea", r"\b(?:diarrh(?:ea|oea)|loose stools?|loose motions?)\b"),
            ("constipation_explicit", r"\b(?:constipat(?:ion|ed)|hard stools?)\b"),
            ("abdominal_pain", r"\b(?:pain|cramp(?:s|ing)?|ache)\b"),
        ):
            found = _component_boolean(n, pattern)
            if found is not None:
                values[field_name] = found
        if not values and n:
            values["other_symptoms"] = [n]
        if values:
            return {"status": "answered", "values": values, "confidence": 0.99, "source": "deterministic"}

    # Bowel-pattern is a three-way choice (constipation, diarrhea, or normal),
    # not a yes/no proposition. Resolve only explicit category answers or
    # contextually clear denials of both alternatives. A bare "no" is
    # deliberately ambiguous and must not be promoted to normal.
    if question_id == "bowel_pattern":
        const_neg = bool(re.search(
            r"\b(?:no|not|never|without|don't|dont|do not|neither)\b.{0,45}\b(?:constipat(?:ion|ed)|hard\s+(?:stools?|poop))\b",
            n,
        ))
        diarr_neg = bool(re.search(
            r"\b(?:no|not|never|without|don't|dont|do not|neither)\b.{0,45}\b(?:diarrh(?:ea|oea)|loose\s+(?:stools?|motions?)|watery)\b",
            n,
        ))
        explicit_normal = bool(re.search(
            r"\b(?:normal|fine|regular)\s+(?:poops?|stools?|bowel movements?|bowels?)\b|"
            r"\b(?:my|the)\s+(?:poops?|stools?|bowel movements?|bowels?)\s+(?:are|is)\s+(?:normal|fine|regular)\b|"
            r"\beverything\s+is\s+(?:normal|fine|regular)\b",
            n,
        ))
        neither_phrase = bool(re.search(
            r"\b(?:neither|neither of (?:those|them)|i don't have either|i do not have either|"
            r"no (?:constipation|diarrhea|diarrhoea|loose motions?) or (?:diarrhea|diarrhoea|loose motions?|constipation)|"
            r"nothing like that)\b",
            n,
        ))
        const_pos = bool(re.search(r"\b(?:constipat(?:ion|ed)|hard\s+(?:stools?|poop))\b", n)) and not const_neg
        diarr_pos = bool(re.search(r"\b(?:diarrh(?:ea|oea)|loose\s+(?:stools?|motions?)|watery)\b", n)) and not diarr_neg
        both = bool(re.search(r"\b(?:both|alternat(?:e|ing))\b", n)) and (const_pos or diarr_pos)
        if explicit_normal or (const_neg and diarr_neg) or (neither_phrase and not (const_pos or diarr_pos)):
            return {"status": "answered", "values": {
                "constipation_explicit": False, "diarrhea_explicit": False,
                "diarrhea": False, "bowel_pattern": "normal",
            }, "confidence": 0.99, "source": "deterministic"}
        if both:
            return {"status": "answered", "values": {
                "constipation_explicit": True, "diarrhea_explicit": True,
                "diarrhea": True, "bowel_pattern": "mixed",
            }, "confidence": 0.99, "source": "deterministic"}
        if const_pos and diarr_pos:
            return {"status": "answered", "values": {
                "constipation_explicit": True, "diarrhea_explicit": True,
                "diarrhea": True, "bowel_pattern": "mixed",
            }, "confidence": 0.99, "source": "deterministic"}
        if const_pos:
            return {"status": "answered", "values": {
                "constipation_explicit": True, "diarrhea_explicit": False,
                "diarrhea": False, "bowel_pattern": "constipation",
            }, "confidence": 0.99, "source": "deterministic"}
        if diarr_pos:
            return {"status": "answered", "values": {
                "constipation_explicit": False, "diarrhea_explicit": True,
                "diarrhea": True, "bowel_pattern": "diarrhea",
            }, "confidence": 0.99, "source": "deterministic"}
    if question_id == "vomiting_fever" and re.fullmatch(r"(?:no\s*,?\s*neither|neither|none)", n):
        return {"status": "answered", "values": {"vomiting": False, "fever": False}, "confidence": 0.99, "source": "deterministic"}
    if n == "maybe":
        return {
            "status": "clarification_needed",
            "values": {},
            "confidence": 0.95,
            "source": "deterministic",
        }

    # "Any blood or mucus?" is a yes/no question about the combined
    # presence of either finding. A bare no unambiguously means neither is
    # present, so resolve both fields without sending the answer to the LLM.
    if question_id == "blood_mucus" and status == "no":
        return {
            "status": "answered",
            "values": {"blood_present": False, "mucus": False},
            "confidence": 0.99,
            "source": "deterministic",
        }

    if status == "unknown":
        return {
            "status": "unknown",
            "values": {f: "unknown" for f in spec.fields},
            "confidence": 0.99,
            "source": "deterministic",
        }
    if status == "refused":
        return {
            "status": "refused",
            "values": {},
            "refused_fields": [question_id],
            "confidence": 0.99,
            "source": "deterministic",
        }

    if status in {"yes", "no"}:
        if status == "no" and question_id == "vomiting_fever" and re.search(r"\bneither\b", n):
            return {"status": "answered", "values": {"vomiting": False, "fever": False}, "confidence": 0.99, "source": "deterministic"}
        # Bristol type is optional knowledge: "no" means the user does not
        # know the type, not that stool has a clinical negative value.
        if question_id == "stool_form" and status == "no":
            return {
                "status": "unknown",
                "values": {"stool_form": "unknown"},
                "confidence": 0.99,
                "source": "deterministic",
            }
        if status == "no" and question_id == "medications":
            return {"status": "answered", "values": {"medications": "none"}, "confidence": 0.99, "source": "deterministic"}
        if status == "yes" and question_id == "medications":
            # A bare yes does not identify what medication or supplement is taken.
            return {"status": "unresolved", "values": {}, "confidence": 0.0, "source": "unresolved"}
        if status == "no" and question_id in {"triggers", "food_trigger", "trigger"}:
            return {"status": "answered", "values": {"food_related": False}, "confidence": 0.99, "source": "deterministic"}
        if status == "no" and question_id == "infection":
            return {"status": "answered", "values": {"recent_infection": False}, "confidence": 0.99, "source": "deterministic"}
        # Composite constipation is a special semantic question: a bare
        # yes/no answers the canonical constipation proposition itself. A
        # negative also explicitly establishes the requested supporting
        # negative (no straining); absence must never be synthesized here.
        if question_id in {"constipation", "stool_straining"}:
            if status == "yes":
                return {
                    "status": "answered",
                    "values": {"constipation_explicit": True},
                    "confidence": 0.99,
                    "source": "deterministic",
                }
            return {
                "status": "answered",
                "values": {"constipation_explicit": False, "straining": False},
                "confidence": 0.99,
                "source": "deterministic",
            }

        value = status == "yes"
        if question_id in _BARE_BOOL:
            return {
                "status": "answered",
                "values": (
                    _BARE_BOOL[question_id]
                    if isinstance(_BARE_BOOL[question_id], dict)
                    else {f: value for f in _BARE_BOOL[question_id]}
                ),
                "confidence": 0.99,
                "source": "deterministic",
            }
        if status == "no" and question_id in _BARE_NO_ALL:
            return {
                "status": "answered",
                "values": {f: False for f in _BARE_NO_ALL[question_id]},
                "confidence": 0.99,
                "source": "deterministic",
            }
        # "yes" to an OR/choice/composite question is not enough information.
        return {"status": "unresolved", "values": {}, "confidence": 0.0, "source": "unresolved"}

    # High-confidence scalar answers are deterministic regardless of LLM availability.
    if question_id == "age":
        m = re.fullmatch(r"(?:i\s+am|i'?m|im|aged|age\s+is)?\s*(\d{1,3})(?:\s+years?\s+old)?", n)
        if m:
            v = int(m.group(1))
            if 1 <= v <= 120:
                return {"status": "answered", "values": {"age": v}, "confidence": 0.99, "source": "deterministic"}

    if question_id == "duration":
        if extracted and extracted.get("duration"):
            return {"status": "answered", "values": {"duration": extracted["duration"]}, "confidence": 0.99, "source": "deterministic"}
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(minutes?|mins?|min|hours?|days?|weeks?|months?|years?)\b", n)
        if m:
            unit = "minutes" if m.group(2).startswith("min") else m.group(2)
            return {"status": "answered", "values": {"duration": f"{m.group(1)} {unit}"}, "confidence": 0.99, "source": "deterministic"}

    if question_id == "stool_form":
        stool = None
        m = re.search(r"\b(?:type|form|bristol(?:\s+stool)?(?:\s+type)?)\s*[:#-]?\s*([1-7])\b", n)
        if m:
            stool = int(m.group(1))
        else:
            semantic = {
                1: (r"\b(?:very\s+hard|separate\s+hard\s+pellets?|pellets?)\b",),
                2: (r"\b(?:hard|lumpy)\b",),
                3: (r"\b(?:cracked|sausage)\b",),
                4: (r"\b(?:smooth|formed)\b",),
                5: (r"\b(?:soft\s+blobs?|soft\s+pieces?)\b",),
                6: (r"\b(?:mushy)\b",),
                7: (r"\b(?:watery)\b",),
            }
            for k, pats in semantic.items():
                if any(re.search(p, n) for p in pats):
                    stool = k
                    break
        if stool is not None:
            return {"status": "answered", "values": {"stool_form": stool}, "confidence": 0.99, "source": "deterministic"}

    if question_id in {"triggers", "food_trigger", "trigger"}:
        # The existing extractor owns the canonical trigger vocabulary.
        trigger = (extracted or {}).get("food_trigger")
        if trigger:
            return {"status": "answered", "values": {"food_trigger": trigger, "food_related": True}, "confidence": 0.99, "source": "deterministic"}

    if question_id in {"duration"} and extracted and extracted.get("duration"):
        return {"status": "answered", "values": {"duration": extracted["duration"]}, "confidence": 0.98, "source": "deterministic"}

    # Deterministic contextual patterns for composite natural-language answers.
    if question_id == "bloating_pain":
        bloating = None
        abdominal = None
        if re.search(r"\b(?:no|not|never|without|don't|dont|do not)\b.{0,25}\b(?:bloating|bloated|bloat)\b", n):
            bloating = False
        elif re.search(r"\b(?:bloating|bloated|bloat)\b", n):
            bloating = True
        if re.search(r"\b(?:no|not|never|without|don't|dont|do not)\b.{0,30}\b(?:abdominal pain|stomach pain|belly pain|stomach ache)\b", n):
            abdominal = False
        elif re.search(r"\b(?:abdominal pain|stomach pain|belly pain|stomach ache|cramps?)\b", n):
            abdominal = True
        if bloating is not None or abdominal is not None:
            vals = {}
            if bloating is not None: vals["bloating"] = bloating
            if abdominal is not None: vals["abdominal_pain"] = abdominal
            # No pain makes the relation dimension inapplicable.
            if abdominal is False: vals["pain_related_to_bowel_movement"] = False
            return {"status": "answered" if _composite_completion(question_id, vals, state) else "partial", "values": vals, "confidence": 0.99, "source": "deterministic"}
    if question_id == "pain":
        if re.search(r"\b(?:no|not|never|without|don't|dont|do not)\b.{0,30}\b(?:abdominal pain|stomach pain|belly pain|stomach ache|pain)\b", n):
            return {"status": "answered", "values": {"abdominal_pain": False, "pain_related_to_bowel_movement": False}, "confidence": 0.99, "source": "deterministic"}
    if question_id == "swallowing":
        neg = lambda term: bool(re.search(r"\b(?:no|not|never|without|don't|dont|do not)\b.{0,35}\b" + term + r"\b", n))
        vals = {}
        if neg(r"difficulty\s+swallowing"):
            vals["difficulty_swallowing"] = False
        if neg(r"persistent\s+vomiting"):
            vals["persistent_vomiting"] = False
        if neg(r"vomiting\s+blood"):
            vals["vomiting_blood"] = False
        if vals:
            return {"status": "answered", "values": vals, "confidence": 0.99, "source": "deterministic"}

    # Question-specific aliases bridge the extractor's canonical vocabulary
    # to the schema's state slots. This is still deterministic and contextual;
    # it does not infer missing values.
    if extracted:
        semantic_aliases = {
            "anal_pain": {"anal_pain": "pain", "sharp_pain_during_stool": "pain"},
            "blood": {"blood_present": "bleeding"},
            "bleeding": {"blood_present": "bleeding"},
            "lump": {"lump_or_prolapse": "lump_or_protrusion"},
            "lump_or_prolapse": {"lump_or_prolapse": "lump_or_protrusion"},
            "infection": {"recent_infection": "recent_infection"},
            "triggers": {"food_trigger": "food_trigger", "food_related": "food_related"},
            "food_trigger": {"food_trigger": "food_trigger", "food_related": "food_related"},
            "trigger": {"food_trigger": "food_trigger", "food_related": "food_related"},
            "food_relation": {"food_related": "food_related"},
            "pain_relation": {"pain_related_to_bowel_movement": "pain_related_to_bowel_movement", "food_related": "food_related", "pain_relation": "pain_relation"},
            "medications": {"medications": "medications"},
            "water": {"water_intake": "water_intake"},
            "fibre": {"fibre_intake": "fibre_intake"},
            "severity": {"severity": "severity"},
            "bowel_pattern": {"constipation_explicit": "constipation", "diarrhea_explicit": "loose_stools", "diarrhea": "loose_stools", "bowel_pattern": "bowel_pattern"},
            "constipation": {"constipation_explicit": "constipation", "straining": "straining", "hard_stools": "hard_stools"},
            "stool_straining": {"constipation_explicit": "constipation", "straining": "straining", "hard_stools": "hard_stools"},
        }
        aliased = {}
        for target, source in semantic_aliases.get(question_id, {}).items():
            value = extracted.get(source)
            if value is not None and value != "":
                aliased[target] = value
        if aliased:
            # A canonical boolean/scalar answer is sufficient; only return
            # fields actually present in the extraction.
            return {"status": "answered", "values": aliased, "confidence": 0.98, "source": "deterministic"}

    # Deterministic scalar/choice forms that the generic extractor may leave
    # to legacy handlers are resolved here so the resolver remains the sole
    # owner of question completion.
    if question_id == "blood_colour":
        if re.search(r"\b(?:bright|fresh)(?:\s+red)?\b", n):
            return {"status": "answered", "values": {"blood_colour": "bright_red"}, "confidence": 0.99, "source": "deterministic"}
        if re.search(r"\b(?:black|dark|tarry)\b", n):
            return {"status": "answered", "values": {"blood_colour": "black"}, "confidence": 0.99, "source": "deterministic"}
    if question_id == "timing":
        # This question asks when the symptom occurs, so any clear temporal
        # anchor is a valid answer, even when it is not meal-related. Preserve
        # the user's wording and keep a broad category for downstream rules.
        temporal = re.search(
            r"\b(?:before|after|during|while|when|upon|at|around|every|since)\b.{0,70}"
            r"\b(?:meals?|breakfast|lunch|dinner|food|eating|eat|wake(?:s|n|ning)?(?:\s+up)?|wakeup|"
            r"morning|afternoon|evening|night|bedtime|sleep|bowel movements?|"
            r"stools?|poop|poo|drinking|water|exercise|work|empty stomach)\b|"
            r"\b(?:in the\s+)?(?:morning|afternoon|evening|night|daytime|bedtime|first thing)\b|"
            r"\b\d{1,2}(?::\d{2})?\s?(?:a\.?m\.?|p\.?m\.?)\b|"
            r"\b(?:within\s+)?(?:one|two|three|four|five|six|few|several|\d+(?:\.\d+)?)\s*"
            r"(?:minutes?|mins?|hours?|hrs?)\b",
            n,
        )
        if temporal:
            if re.search(r"\b(?:bowel movements?|stools?|poop|poo)\b", n):
                relation = "after_bowel_movement" if re.search(r"\bafter\b", n) else (
                    "before_bowel_movement" if re.search(r"\bbefore\b", n) else "around_bowel_movement"
                )
            elif re.search(r"\b(?:wake|waking|wakeup|morning|afternoon|evening|night|bedtime|sleep)\b", n):
                if re.search(r"\b(?:wake|waking|wakeup)\b", n):
                    relation = "after_waking" if re.search(r"\bafter\b", n) else (
                        "before_waking" if re.search(r"\bbefore\b", n) else "around_waking"
                    )
                else:
                    relation = "at_night" if re.search(r"\b(?:night|bedtime|sleep)\b", n) else "time_of_day"
            elif re.search(r"\b(?:meal|breakfast|lunch|dinner|food|eating|eat|empty stomach)\b", n):
                relation = "before_meals" if re.search(r"\bbefore\b", n) else (
                    "after_eating" if re.search(r"\bafter\b", n) else "around_meals"
                )
            elif re.search(r"\b\d{1,2}(?::\d{2})?\s?(?:a\.?m\.?|p\.?m\.?)\b", n):
                relation = "at_specific_time"
            else:
                relation = "timing_reported"
            timing_values = {
                "meal_timing": n[:160],
                "timing_relation": relation,
            }
            if relation == "after_eating":
                timing_values["symptom_onset_after_food"] = n[:160]
            return {"status": "answered", "values": timing_values, "confidence": 0.99, "source": "deterministic"}

        # The timing question is context-owned. Short answers such as
        # "10 mins", "soon", and "immediately" are complete answers because
        # the question already establishes that the reference point is eating.
        # They must not fall through to the LLM/fallback path and cause the
        # same question to be repeated.
        immediate = re.fullmatch(
            r"(?:right\s+away|straight\s+away|immediately|instantly|right\s+after|immediate(?:ly)?)",
            n,
        )
        if immediate:
            return {
                "status": "answered",
                "values": {
                    "meal_timing": "immediately_after_eating",
                    "symptom_onset_after_food": "immediately after eating",
                    "timing_relation": "after_eating",
                },
                "confidence": 0.99,
                "source": "deterministic",
            }
        if re.fullmatch(r"(?:very\s+)?soon|shortly", n):
            return {
                "status": "answered",
                "values": {
                    "meal_timing": "soon_after_eating",
                    "symptom_onset_after_food": "soon after eating",
                    "timing_relation": "after_eating",
                },
                "confidence": 0.98,
                "source": "deterministic",
            }
        m = re.fullmatch(
            r"(?:within\s+)?(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)",
            n,
        )
        if m:
            unit = m.group(2)
            value = m.group(1)
            canonical_unit = "minutes" if unit.startswith("min") else "hours"
            onset = f"{value} {canonical_unit} after eating"
            return {
                "status": "answered",
                "values": {
                    "meal_timing": "after_eating",
                    "symptom_onset_after_food": onset,
                    "timing_relation": "after_eating",
                },
                "confidence": 0.99,
                "source": "deterministic",
            }
    if question_id == "bowel_frequency":
        # This question explicitly asks for frequency PER WEEK, so short
        # contextual answers such as "3 times" or "3" are complete answers.
        # Do not send these obvious numeric answers to the LLM/fallback path.
        if re.fullmatch(r"(?:once|one time)\s+(?:daily|a day|per day)", n):
            return {"status": "answered", "values": {"bowel_frequency_per_week": 7}, "confidence": 0.99, "source": "deterministic"}
        if re.fullmatch(r"(?:twice|two times)\s+(?:daily|a day|per day)", n):
            return {"status": "answered", "values": {"bowel_frequency_per_week": 14}, "confidence": 0.99, "source": "deterministic"}
        if re.fullmatch(r"every (?:other|alternate|second) day", n):
            return {"status": "answered", "values": {"bowel_frequency_per_week": 3.5}, "confidence": 0.99, "source": "deterministic"}
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:bowel movements?|times?|motions?)\s*(?:per|a)\s*week\b", n)
        if not m:
            m = re.fullmatch(r"(?:about\s+|around\s+|roughly\s+)?(\d+(?:\.\d+)?)\s*(?:bowel movements?|times?|motions?)", n)
        if not m:
            m = re.fullmatch(r"(?:about\s+|around\s+|roughly\s+)?(\d+(?:\.\d+)?)", n)
        if m:
            value = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
            return {"status": "answered", "values": {"bowel_frequency_per_week": value}, "confidence": 0.99, "source": "deterministic"}
    if question_id == "daily_frequency":
        if re.fullmatch(r"(?:once|one time)\s+(?:daily|a day|per day)", n):
            return {"status": "answered", "values": {"bowel_frequency_per_day": 1}, "confidence": 0.99, "source": "deterministic"}
        if re.fullmatch(r"(?:twice|two times)\s+(?:daily|a day|per day)", n):
            return {"status": "answered", "values": {"bowel_frequency_per_day": 2}, "confidence": 0.99, "source": "deterministic"}
        if re.fullmatch(r"every (?:other|alternate|second) day", n):
            return {"status": "answered", "values": {"bowel_frequency_per_day": 0.5}, "confidence": 0.99, "source": "deterministic"}
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:loose\s+)?(?:bowel movements?|times?|stools?|motions?)\s*(?:per|a)\s*day\b", n)
        if m:
            return {"status": "answered", "values": {"bowel_frequency_per_day": float(m.group(1)) if "." in m.group(1) else int(m.group(1))}, "confidence": 0.99, "source": "deterministic"}
        # The active question already establishes "per day", so accept a
        # concise count such as "5" or "about 5" without an LLM call.
        m = re.fullmatch(
            r"(?:about\s+|around\s+|roughly\s+)?(\d+(?:\.\d+)?)"
            r"(?:\s*(?:loose\s+)?(?:bowel movements?|times?|stools?|motions?))?",
            n,
        )
        if m and 0 <= float(m.group(1)) <= 100:
            value = float(m.group(1))
            return {
                "status": "answered",
                "values": {"bowel_frequency_per_day": int(value) if value.is_integer() else value},
                "confidence": 0.99,
                "source": "deterministic",
            }
        if re.fullmatch(r"(?:sometimes|occasionally|rarely|once in a while)", n):
            return {"status": "unknown", "values": {}, "confidence": 0.99, "source": "deterministic"}
    if question_id == "severity":
        m = re.search(r"\b([1-9]|10)\b", n)
        if m:
            return {"status": "answered", "values": {"severity": m.group(1)}, "confidence": 0.99, "source": "deterministic"}
    if question_id == "fibre":
        m = re.search(r"\b(low|average|normal|high|good)\b(?:\s+(?:fibre|fiber))?", n)
        if m:
            return {"status": "answered", "values": {"fibre_intake": m.group(1)}, "confidence": 0.99, "source": "deterministic"}
    if question_id == "infection" and re.search(r"\b(?:no|not|never|without)\b.{0,25}\b(?:infection|infected|stomach bug|gastro)\b", n):
        return {"status": "answered", "values": {"recent_infection": False}, "confidence": 0.99, "source": "deterministic"}
    if question_id == "medications" and re.fullmatch(r"(?:no|nope|nah|no medicines?|no medication|none)", n):
        return {"status": "answered", "values": {"medications": "none"}, "confidence": 0.99, "source": "deterministic"}
    if question_id == "vomiting_fever" and re.fullmatch(r"(?:neither|none|no neither|no)", n):
        return {"status": "answered", "values": {"vomiting": False, "fever": False}, "confidence": 0.99, "source": "deterministic"}

    # If extraction has exactly one schema-owned, semantically typed value,
    # allow it to resolve the question without an LLM.
    if extracted:
        candidates = {}
        for f in spec.fields:
            v = extracted.get(f)
            if v is not None and v != "":
                candidates[f] = v
        if question_id == "stool_straining":
            candidates = {k: extracted.get(k) for k in ("stool_form", "straining") if extracted.get(k) is not None}
        aliases = {
            "pain": {"abdominal_pain": "pain"},
            "bleeding": {"blood_present": "bleeding"},
            "lump_or_protrusion": {"lump_or_prolapse": "lump_or_protrusion"},
            "swelling": {"abdominal_distension": "swelling"},
        }
        for target, source in aliases.get(question_id, {}).items():
            if target not in candidates and extracted.get(source) is not None:
                candidates[target] = extracted.get(source)
        if candidates:
            complete = _composite_completion(question_id, candidates, state)
            return {"status": "answered" if complete else "partial", "values": candidates, "confidence": 0.98, "source": "deterministic"}

    return {"status": "unresolved", "values": {}, "confidence": 0.0, "source": "unresolved"}

def validate_question_resolution(resolution: dict | None) -> dict:
    """Normalize resolver output at the state-mutation boundary.

    An unresolved/clarification result owns no clinical facts. This prevents
    fallback defaults (especially False) from masquerading as detected
    negatives. An answered result must contain an actual value payload.
    """
    if not isinstance(resolution, dict):
        return {"status": "unresolved", "values": {}, "confidence": 0.0, "source": "unresolved"}

    status = resolution.get("status", "unresolved")
    values = resolution.get("values")
    if not isinstance(values, dict):
        values = {}
    values = {
        key: value for key, value in values.items()
        if value is not None and not (isinstance(value, str) and not value.strip())
    }

    normalized = dict(resolution)
    normalized["status"] = status
    normalized["values"] = values

    if status in {"unresolved", "clarification_needed"}:
        # Invalid resolver payloads are safely normalized rather than allowed
        # to mutate state. The caller logs the discarded keys for observability.
        normalized["values"] = {}
    elif status in {"answered", "partial"}:
        # A partial component can be explicitly unknown/refused without a
        # clinical value. Otherwise an empty answered payload is invalid.
        if not values and not normalized.get("unknown_fields") and not normalized.get("refused_fields"):
            normalized["status"] = "unresolved"
    return normalized


def get_question_spec(question_id: str | None) -> QuestionSpec | None:
    return QUESTION_SCHEMA.get(question_id)


def _has(state: Any, name: str) -> bool:
    value = getattr(state, name, None)
    return value is not None and value != "unknown" and not (isinstance(value, str) and not value.strip())


def _valid_age(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        age = value
    elif isinstance(value, float) and value.is_integer():
        age = int(value)
    elif isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        age = int(value.strip())
    else:
        return None
    return age if 1 <= age <= 120 else None


def question_has_answer(state: Any, question_id: str | None) -> bool:
    """Semantic completion, never based on unrelated populated state."""
    if not question_id:
        return True
    if question_id in set(getattr(state, "answered_unknown_fields", []) or []):
        # Unknown cannot satisfy safety-critical bleeding discriminators. The
        # engine must keep asking/clarifying rather than treating absence of
        # information as a negative clinical finding.
        if question_id in {"blood", "bleeding", "blood_colour", "blood_location", "blood_mucus", "mucus", "anal_pain", "anal_discomfort_screen", "sharp_pain_during_stool", "lump", "night_time_symptoms", "weight_loss", "vomiting", "fever", "persistent_vomiting", "vomiting_blood", "difficulty_swallowing", "abdominal_distension"}:
            return False
        return True
    if question_id in set(getattr(state, "refused_fields", []) or []):
        if question_id in {"blood", "bleeding", "blood_colour", "blood_location", "blood_mucus", "mucus", "anal_pain", "anal_discomfort_screen", "sharp_pain_during_stool", "lump", "night_weight_fever", "night_time_symptoms", "weight_loss", "vomiting_fever", "vomiting_fever_swelling", "vomiting", "fever", "persistent_vomiting", "vomiting_blood", "difficulty_swallowing", "abdominal_distension", "swallowing", "weight_swallow"}:
            return False
        return True
    # Compatibility: unknown legacy IDs remain governed by their explicit
    # questionnaire condition rather than being treated as answered.
    spec = get_question_spec(question_id)
    if spec is None:
        return False

    if question_id in {"duration"}:
        return _has(state, "duration")
    if question_id in {"age"}:
        return _valid_age(getattr(state, "age", None)) is not None
    if question_id in {"weight_loss", "weight_loss_duration"}:
        return _has(state, "weight_loss")
    if question_id == "bowel_frequency":
        return _has(state, "bowel_frequency_per_week")
    if question_id == "daily_frequency":
        return _has(state, "bowel_frequency_per_day")
    if question_id in {"stool_straining", "constipation"}:
        # A positive answer may identify only one component; the combined
        # question is complete only when both requested supporting dimensions
        # are known, unless the user explicitly supplied a canonical
        # constipation yes/no answer.
        return _has(state, "constipation_explicit") or (
            (_has(state, "stool_form") or _has(state, "hard_stools")) and _has(state, "straining")
        )
    if question_id == "hard_stools":
        return _has(state, "hard_stools")
    if question_id == "straining":
        return _has(state, "straining")
    if question_id == "incomplete_evacuation":
        return _has(state, "incomplete_evacuation")
    if question_id in {
        "abdominal_pain_screen", "pain_bowel_relation", "anal_discomfort_screen",
        "sharp_pain_during_stool", "mucus", "night_time_symptoms", "vomiting",
        "fever", "abdominal_distension", "difficulty_swallowing",
        "persistent_vomiting", "vomiting_blood",
    }:
        return _has(state, next(iter(get_question_spec(question_id).fields)))
    if question_id == "constipation_screen":
        return _has(state, "constipation_explicit")
    if question_id == "diarrhea_screen":
        return _has(state, "diarrhea_explicit")
    if question_id == "gas_screen":
        return _has(state, "gas")
    if question_id == "bloating_screen":
        return _has(state, "bloating")
    if question_id == "bloating_pain":
        if state.abdominal_pain is True:
            return _has(state, "pain_related_to_bowel_movement")
        if state.bloating is None or state.abdominal_pain is None:
            return False
        return state.abdominal_pain is False
    if question_id == "pain":
        return _has(state, "abdominal_pain") and (
            state.abdominal_pain is False or _has(state, "pain_related_to_bowel_movement")
        )
    if question_id == "pain_relation":
        return (
            state.food_related is True
            or state.pain_related_to_bowel_movement is True
            or (state.food_related is False and state.pain_related_to_bowel_movement is False)
        )
    if question_id in {"blood", "bleeding"}:
        return _has(state, "blood_present")
    if question_id == "blood_colour":
        return getattr(state, "blood_colour", None) in {"bright_red", "black"}
    if question_id == "blood_location":
        return getattr(state, "blood_location", None) in {"tissue", "dripping", "mixed"}
    if question_id == "blood_mucus":
        return _has(state, "blood_present") and _has(state, "mucus")
    if question_id == "anal_pain":
        return _has(state, "sharp_pain_during_stool") and _has(state, "anal_pain")
    if question_id in {"lump", "lump_or_prolapse"}:
        return _has(state, "lump_or_prolapse")
    if question_id == "vomiting_fever":
        return _has(state, "vomiting") and _has(state, "fever")
    if question_id == "vomiting_fever_swelling":
        return _has(state, "vomiting") and _has(state, "fever") and _has(state, "abdominal_distension")
    if question_id == "night_weight_fever":
        return _has(state, "night_time_symptoms") and _has(state, "weight_loss") and _has(state, "fever")
    if question_id in {"swallowing"}:
        return _has(state, "difficulty_swallowing") and _has(state, "persistent_vomiting") and _has(state, "vomiting_blood")
    if question_id == "weight_swallow":
        return _has(state, "weight_loss") and _has(state, "difficulty_swallowing") and _has(state, "persistent_vomiting") and _has(state, "vomiting_blood")
    if question_id == "upper_symptoms":
        return _has(state, "upper_symptoms")
    if question_id == "symptoms":
        # The food-intolerance question asks what symptoms occur; a category
        # answer, not pre-existing pain/frequency, is required.
        return any(_has(state, f) for f in ("bloating", "diarrhea", "abdominal_pain", "constipation_explicit", "gas")) or bool(getattr(state, "other_symptoms", []))
    if question_id == "stool_form":
        # "I don't know" is a valid answer to the optional
        # "if you know it" Bristol-type question. The sentinel prevents the
        # questionnaire from looping while remaining clinically non-numeric.
        value = getattr(state, "stool_form", None)
        return value == "unknown" or (
            isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 7
        )
    if question_id == "severity":
        return _has(state, "severity")
    if question_id == "pain_location":
        return _has(state, "pain_location")
    if question_id == "bowel_pattern":
        # This is a categorical question. Frequency alone is not an answer.
        return _has(state, "constipation_explicit") or _has(state, "diarrhea_explicit")
    if question_id == "reflux":
        return _has(state, "reflux_present")
    if question_id == "timing":
        return _has(state, "timing_relation")
    if question_id in {"triggers", "food_trigger", "trigger"}:
        return _has(state, "food_trigger") or state.food_related is False
    if question_id == "food_relation":
        return _has(state, "food_related")
    if question_id == "infection":
        return _has(state, "recent_infection")
    if question_id == "water":
        return _has(state, "water_intake")
    if question_id == "fibre":
        return _has(state, "fibre_intake")
    if question_id == "medications":
        return _has(state, "medications")
    if question_id == "red_flag_check":
        return bool(state.red_flags) or _has(state, "red_flags_answered")
    return True
