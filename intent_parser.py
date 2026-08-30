"""
Guttify Intent Parser
----------------------
Turns free-text user messages into a small, validated structured record
(`SymptomState`). This is deliberately rule-based and lightweight — no
embedding model, no vector DB — so it stays cheap to run and its output is
always one of a fixed set of known values that the recommendation engine
can trust.

If a local LLM's interpretation is ever plugged in ahead of this, its
output MUST still be validated with `validate_llm_extraction()` before use;
anything that doesn't match the known schema/values is discarded and the
rule-based extraction below is used instead.
"""
import re
from dataclasses import dataclass, field, asdict

# ---------------------------------------------------------------------
# Canonical symptom vocabulary. These strings are the ones that actually
# appear in products.json "symptoms" lists, so a canonical hit here is
# guaranteed to be matchable against real product data.
# ---------------------------------------------------------------------
SYMPTOM_SYNONYMS = {
    "bloating": [
        "bloat", "bloating", "bloated", "swollen stomach", "stomach swollen",
        "tummy feels full", "puffed up", "stomach becomes big", "gassy",
        "stomach gets swollen", "feel full and tight", "stomach feels tight",
    ],
    "constipation": [
        "constipation", "constipated", "can't poop", "cant poop",
        "not able to poop", "irregular digestion", "backed up",
        "feeling backed up", "not going regularly",
    ],
    "hard stools": [
        "hard stool", "hard stools", "difficulty passing stool",
        "straining to pass stool",
    ],
    "irregular bowel movements": [
        "irregular bowel", "irregular bowel movements", "irregular poop",
    ],
    "acidity": [
        "acidity", "acid reflux", "acid comes up", "sour burps",
        "sour liquid", "sour taste in mouth",
    ],
    "heartburn": [
        "heartburn", "burning in chest", "burning in my chest", "burning chest",
        "chest burning", "my chest burning", "burning sensation after meals",
        "burning after meals", "burning after food",
    ],
    "gas": ["gas", "flatulence", "excess gas"],
    "fatigue": [
        "fatigue", "tired", "tiredness", "low energy", "no energy",
        "exhausted", "worn out",
    ],
    "sluggishness": ["sluggish", "sluggishness", "feel slow", "low motivation"],
    "liver support": ["liver support", "support my liver", "help my liver", "liver detox"],
    "piles": [
        "piles", "hemorrhoid", "hemorrhoids", "haemorrhoid", "haemorrhoids",
    ],
    "pain": ["pain", "hurts", "hurting", "sore"],
    "swelling": ["swelling", "swollen"],
    "bleeding": ["bleeding", "blood when i poop", "blood after bowel movement"],
    "straining": ["straining", "strain to pass stool", "pushing hard to poop"],
    "weight management": [
        "weight management", "lose weight", "weight loss", "manage my weight",
    ],
    "metabolism support": ["metabolism", "slow metabolism", "boost metabolism"],
    "anal fissures": ["anal fissure", "fissure"],
    "burning sensation": ["burning sensation", "burning around anus", "anal burning"],
    "itching": ["itching", "itchy", "itch"],
    "irritation": ["irritation", "irritated"],
    "anal discomfort": ["anal discomfort", "discomfort around anus"],
    "dull skin": ["dull skin", "skin looks dull", "lackluster skin"],
    "dry skin": ["dry skin", "skin feels dry"],
    "uneven skin tone": ["uneven skin tone", "patchy skin tone"],
    "loss of skin elasticity": ["loss of skin elasticity", "sagging skin", "skin elasticity"],
    "brain fog": ["brain fog", "foggy head", "can't focus", "cant focus", "poor focus"],
    "poor focus": ["poor focus", "trouble concentrating", "difficulty concentrating"],
    "low immunity": ["low immunity", "weak immunity", "catch colds often"],
    "weak bones": ["weak bones", "bone health", "brittle bones"],
    "low mood": ["low mood", "feeling low", "mood is low"],
    "occasional constipation": ["occasional constipation"],
}

# Longer/more specific synonyms first so e.g. "hard stools" doesn't get
# swallowed by a generic "constipation" match ordering issue.
_SORTED_SYMPTOM_ITEMS = sorted(
    ((canon, phrase) for canon, phrases in SYMPTOM_SYNONYMS.items() for phrase in phrases),
    key=lambda pair: -len(pair[1]),
)

FOOD_TRIGGER_SYNONYMS = {
    "dairy": ["dairy", "milk", "paneer", "cheese", "curd", "yogurt", "yoghurt"],
    "spicy_oily": ["spicy", "oily", "fried", "fatty food", "greasy"],
    "wheat_gluten": ["wheat", "gluten", "roti", "bread"],
    "legumes": ["beans", "lentils", "dal", "chickpeas", "rajma"],
    "caffeine": ["coffee", "caffeine", "tea"],
}

FREQUENCY_PATTERNS = [
    ("daily", [r"\bdaily\b", r"every day", r"each day"]),
    ("few_times_per_week", [r"few times a week", r"couple times a week", r"2-3 times a week", r"several times a week"]),
    ("weekly", [r"once a week", r"weekly"]),
    ("occasional", [r"occasionally", r"sometimes", r"once in a while", r"rarely"]),
]

FOOD_RELATED_PATTERNS = [r"after eating", r"after meals", r"after food", r"related to food", r"food related"]

NAME_QUESTION_ASPECTS = {
    "ingredients": ["ingredient", "ingredients", "what's in it", "whats in it", "contains"],
    "how_to_use": ["how to use", "how do i use", "dosage", "how much"],
    "warnings": ["warning", "warnings", "side effect", "side effects", "caution"],
    "price": ["price", "cost", "how much does it cost"],
}


@dataclass
class SymptomState:
    primary_symptom: str = None
    secondary_symptoms: list = field(default_factory=list)
    frequency: str = None
    food_related: bool = None
    food_trigger: str = None
    severity: str = "unknown"
    duration: str = "unknown"
    red_flags: list = field(default_factory=list)
    asked_fields: list = field(default_factory=list)  # which clarifying Qs we've already asked

    def to_dict(self):
        return asdict(self)

    def has_enough_to_recommend(self):
        return bool(self.primary_symptom) and not self.red_flags


def normalize(text):
    text = re.sub(r"[^a-z0-9\s']", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def extract_symptoms(text):
    """Return (primary_symptom, [secondary_symptoms]) using synonym matching."""
    norm = normalize(text)
    found = []
    for canonical, phrase in _SORTED_SYMPTOM_ITEMS:
        if phrase in norm and canonical not in found:
            found.append(canonical)
    if not found:
        return None, []
    return found[0], found[1:]


def extract_food_trigger(text):
    norm = normalize(text)
    for trigger, phrases in FOOD_TRIGGER_SYNONYMS.items():
        if any(p in norm for p in phrases):
            return trigger
    return None


def extract_food_related(text):
    norm = normalize(text)
    if any(re.search(p, norm) for p in FOOD_RELATED_PATTERNS):
        return True
    if extract_food_trigger(text):
        return True
    return None  # unknown, not necessarily False


def extract_frequency(text):
    norm = normalize(text)
    for canonical, patterns in FREQUENCY_PATTERNS:
        if any(re.search(p, norm) for p in patterns):
            return canonical
    return None


def extract_named_aspect(text):
    """If the user is asking about one specific aspect of a product (rule 14
    in guttify_chatbot's prompt), return which aspect."""
    norm = normalize(text)
    for aspect, phrases in NAME_QUESTION_ASPECTS.items():
        if any(p in norm for p in phrases):
            return aspect
    return None


def merge_state(previous: SymptomState, text: str, red_flags: list) -> SymptomState:
    """
    Merge the latest user message into the running structured state.
    Priority: current user answer > prior conversation state.
    Only overwrite a field when the new message actually supplies a value.
    """
    previous = previous or SymptomState()

    primary, secondary = extract_symptoms(text)
    food_trigger = extract_food_trigger(text)
    food_related = extract_food_related(text)
    frequency = extract_frequency(text)

    new_state = SymptomState(
        primary_symptom=primary or previous.primary_symptom,
        secondary_symptoms=list(dict.fromkeys((previous.secondary_symptoms or []) + secondary)),
        frequency=frequency or previous.frequency,
        food_related=food_related if food_related is not None else previous.food_related,
        food_trigger=food_trigger or previous.food_trigger,
        severity=previous.severity,
        duration=previous.duration,
        red_flags=list(dict.fromkeys((previous.red_flags or []) + (red_flags or []))),
        asked_fields=list(previous.asked_fields or []),
    )
    return new_state


def validate_llm_extraction(raw: dict) -> dict | None:
    """
    Validate a dict that an LLM claims represents extracted symptom data.
    Returns a cleaned dict using only known-good values, or None if the
    payload is unusable (caller should fall back to rule-based extraction).
    """
    if not isinstance(raw, dict):
        return None

    known_symptoms = set(SYMPTOM_SYNONYMS.keys())
    known_triggers = set(FOOD_TRIGGER_SYNONYMS.keys())
    known_frequencies = {f for f, _ in FREQUENCY_PATTERNS}

    cleaned = {}
    symptom = raw.get("primary_symptom")
    if isinstance(symptom, str) and symptom in known_symptoms:
        cleaned["primary_symptom"] = symptom
    else:
        return None  # unusable without at least a valid primary symptom

    secondary = raw.get("secondary_symptoms", [])
    if isinstance(secondary, list):
        cleaned["secondary_symptoms"] = [s for s in secondary if s in known_symptoms]

    trigger = raw.get("food_trigger")
    if isinstance(trigger, str) and trigger in known_triggers:
        cleaned["food_trigger"] = trigger

    freq = raw.get("frequency")
    if isinstance(freq, str) and freq in known_frequencies:
        cleaned["frequency"] = freq

    food_related = raw.get("food_related")
    if isinstance(food_related, bool):
        cleaned["food_related"] = food_related

    return cleaned
