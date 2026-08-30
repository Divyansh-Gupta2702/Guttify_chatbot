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
        "bloat", "bloats", "bloating", "bloated", "swollen stomach", "stomach swollen",
        "tummy feels full", "puffed up", "stomach becomes big", "gassy",
        "stomach gets swollen", "feel full and tight", "stomach feels tight",
        "belly bloat", "belly is bloated", "abdominal bloating", "stomach distension",
        "distended stomach", "puffy stomach", "puffy belly", "swollen belly",
        "feeling stuffed", "stomach feels heavy", "heavy stomach", "full and heavy stomach",
        "stomach feels full", "tight stomach", "tummy is swollen", "stomach inflated",
        "feels like a balloon", "bloating after eating", "gas and bloating", "indigestion",
    ],
    "constipation": [
        "constipation", "constipated", "can't poop", "cant poop", "can not poop",
        "not able to poop", "irregular digestion", "backed up",
        "feeling backed up", "not going regularly", "not pooping regularly",
        "trouble pooping", "difficulty pooping", "hard to poop", "unable to poop",
        "not passing stool", "stool is stuck", "poop is stuck", "clogged up",
        "blocked feeling", "bowel movement problems", "infrequent bowel movements",
        "not clearing properly", "not able to pass motion", "motion is not clear",
        "not going to the bathroom", "haven't pooped in days", "havent pooped in days",
        "cant go", "can't go", "no bowel movement",
    ],
    "hard stools": [
        "hard stool", "hard stools", "difficulty passing stool",
        "straining to pass stool", "stool is hard", "stools are hard",
        "dry stool", "dry stools", "hard poop", "poop is hard",
        "lumpy stool", "stools are dry and hard",
    ],
    "irregular bowel movements": [
        "irregular bowel", "irregular bowel movements", "irregular poop",
        "bowel movements are irregular", "unpredictable bowel movements",
        "erratic bowel movements", "irregular bathroom habits", "irregular motions",
    ],
    "acidity": [
        "acidity", "acid reflux", "acid comes up", "sour burps",
        "sour liquid", "sour taste in mouth", "acidic stomach", "stomach acid",
        "too much acid", "acid buildup", "gerd", "reflux", "acid problem",
        "gastric problem", "gastric issue", "gastric trouble", "sour belching",
        "acidic burps", "stomach feels acidic",
    ],
    "heartburn": [
        "heartburn", "burning in chest", "burning in my chest", "burning chest",
        "chest burning", "my chest burning", "burning sensation after meals",
        "burning after meals", "burning after food", "burning throat",
        "burning in throat", "chest pain after eating", "burning feeling in chest",
        "acid coming up my throat", "esophagus burning", "fire in chest",
    ],
    "gas": [
        "gas", "flatulence", "excess gas", "too much gas", "gassy stomach",
        "farting a lot", "trapped wind", "wind problem", "burping a lot",
        "belching a lot", "stomach gas", "gas trouble", "gas issue",
    ],
    "fatigue": [
        "fatigue", "tired", "tiredness", "low energy", "no energy",
        "exhausted", "worn out", "feeling drained", "drained of energy",
        "lethargic", "sleepy all the time", "always tired", "burnt out",
        "zero energy", "feeling weak", "no stamina", "low stamina",
        "constantly fatigued", "feel exhausted all day",
    ],
    "sluggishness": [
        "sluggish", "sluggishness", "feel slow", "low motivation",
        "feeling sluggish", "slow digestion", "feeling lazy", "body feels heavy",
        "everything feels slow", "mentally and physically slow",
    ],
    "liver support": [
        "liver support", "support my liver", "help my liver", "liver detox",
        "detox my liver", "cleanse my liver", "liver cleanse", "liver health",
        "liver function support", "improve liver function", "liver care",
    ],
    "piles": [
        "piles", "hemorrhoid", "hemorrhoids", "haemorrhoid", "haemorrhoids",
        "piles problem", "piles issue", "piles pain", "external piles",
        "internal piles", "pile issue",
    ],
    "pain": ["pain", "hurts", "hurting", "sore", "aching", "painful", "ache"],
    "swelling": ["swelling", "swollen", "puffiness", "inflammation", "inflamed", "swollen area"],
    "bleeding": [
        "bleeding", "blood when i poop", "blood after bowel movement",
        "blood in stool", "blood while pooping", "bleeding from anus",
        "rectal bleeding", "blood while passing stool", "spotting blood",
    ],
    "straining": [
        "straining", "strain to pass stool", "pushing hard to poop",
        "pushing too hard", "straining during bowel movement",
        "hard to pass stool", "have to push a lot",
    ],
    "weight management": [
        "weight management", "lose weight", "weight loss", "manage my weight",
        "want to lose weight", "shed kilos", "shed some kilos", "extra weight",
        "belly fat", "reduce weight", "trying to lose fat", "cut weight",
    ],
    "metabolism support": [
        "metabolism", "slow metabolism", "boost metabolism", "sluggish metabolism",
        "metabolism is slow", "improve my metabolism", "speed up metabolism",
        "metabolic rate is low",
    ],
    "anal fissures": [
        "anal fissure", "fissure", "tear near anus", "cut near anus",
        "fissure pain", "small tear while pooping",
    ],
    "burning sensation": [
        "burning sensation", "burning around anus", "anal burning",
        "burning near anus", "burning down there", "burning feeling in that area",
    ],
    "itching": ["itching", "itchy", "itch", "itchy anus", "itching around anus", "itchy around the anus"],
    "irritation": [
        "irritation", "irritated", "skin irritation near anus",
        "irritated skin", "irritation around anus",
    ],
    "anal discomfort": [
        "anal discomfort", "discomfort around anus", "discomfort in anal area",
        "uncomfortable around anus", "discomfort down there",
    ],
    "dull skin": [
        "dull skin", "skin looks dull", "lackluster skin", "lacklustre skin",
        "skin looks tired", "lifeless skin", "no glow", "skin has lost its glow",
        "skin looks lifeless",
    ],
    "dry skin": ["dry skin", "skin feels dry", "flaky skin", "rough skin", "skin is dry and rough"],
    "uneven skin tone": [
        "uneven skin tone", "patchy skin tone", "skin tone is uneven",
        "dark patches on skin", "blotchy skin", "uneven complexion",
    ],
    "loss of skin elasticity": [
        "loss of skin elasticity", "sagging skin", "skin elasticity",
        "skin is sagging", "loose skin", "skin lost its firmness", "skin feels loose",
    ],
    "brain fog": [
        "brain fog", "foggy head", "can't focus", "cant focus", "poor focus",
        "mind feels foggy", "hard to think clearly", "mentally foggy",
        "head feels cloudy", "can't think straight clearly", "foggy thinking",
    ],
    "poor focus": [
        "poor focus", "trouble concentrating", "difficulty concentrating",
        "can't concentrate", "cant concentrate", "attention issues",
        "distracted easily", "hard to concentrate", "lack of focus",
    ],
    "low immunity": [
        "low immunity", "weak immunity", "catch colds often", "get sick often",
        "fall ill frequently", "immune system is weak", "keep falling sick",
        "frequent colds", "weak immune system",
    ],
    "weak bones": [
        "weak bones", "bone health", "brittle bones", "bones feel weak",
        "joint and bone weakness", "fragile bones",
    ],
    "low mood": [
        "low mood", "feeling low", "mood is low", "feeling down",
        "not in a good mood", "feeling blue", "feeling off lately",
    ],
    "occasional constipation": [
        "occasional constipation", "constipation once in a while",
        "constipated every now and then", "occasionally constipated",
    ],
}

# Longer/more specific synonyms first so e.g. "hard stools" doesn't get
# swallowed by a generic "constipation" match ordering issue.
_SORTED_SYMPTOM_ITEMS = sorted(
    ((canon, phrase) for canon, phrases in SYMPTOM_SYNONYMS.items() for phrase in phrases),
    key=lambda pair: -len(pair[1]),
)

# Word-boundary patterns, precompiled once. Matching on \b...\b instead of
# a raw substring check matters once the synonym lists include short words
# ("gas", "pain", "itch", "tea") — a raw substring match would also fire
# inside unrelated words ("itch" inside "kitchen", "tea" inside "steak").
_SYMPTOM_PATTERNS = [
    (canon, re.compile(r"\b" + re.escape(phrase) + r"\b")) for canon, phrase in _SORTED_SYMPTOM_ITEMS
]

FOOD_TRIGGER_SYNONYMS = {
    "dairy": [
        "dairy", "milk", "paneer", "cheese", "curd", "yogurt", "yoghurt",
        "buttermilk", "lassi", "ice cream", "cream", "milk products",
    ],
    "spicy_oily": [
        "spicy", "oily", "fried", "fatty food", "greasy", "masala",
        "chilli", "chili", "spicy food", "junk food", "street food",
        "fast food", "deep fried", "oily food",
    ],
    "wheat_gluten": [
        "wheat", "gluten", "roti", "bread", "atta", "chapati", "paratha", "maida",
    ],
    "legumes": [
        "beans", "lentils", "dal", "chickpeas", "rajma", "chana",
        "kidney beans", "soybean", "soybeans", "sprouts",
    ],
    "caffeine": ["coffee", "caffeine", "tea", "chai", "cold coffee", "energy drink"],
}
_FOOD_TRIGGER_PATTERNS = {
    trigger: [re.compile(r"\b" + re.escape(phrase) + r"\b") for phrase in phrases]
    for trigger, phrases in FOOD_TRIGGER_SYNONYMS.items()
}

FREQUENCY_PATTERNS = [
    ("daily", [r"\bdaily\b", r"every day", r"each day", r"almost every day", r"all the time"]),
    (
        "few_times_per_week",
        [
            r"few times a week", r"couple times a week", r"2-3 times a week",
            r"several times a week", r"twice a week", r"most days",
        ],
    ),
    ("weekly", [r"once a week", r"weekly", r"every alternate day"]),
    (
        "occasional",
        [
            r"occasionally", r"sometimes", r"once in a while", r"rarely",
            r"on and off", r"now and then", r"every now and then",
        ],
    ),
]

FOOD_RELATED_PATTERNS = [
    r"after eating", r"after meals", r"after food", r"related to food",
    r"food related", r"when i eat", r"post meal", r"post-meal",
    r"right after eating", r"soon after eating", r"whenever i eat",
]

NAME_QUESTION_ASPECTS = {
    "ingredients": [
        "ingredient", "ingredients", "what's in it", "whats in it", "contains",
        "what does it contain", "made of", "composition",
    ],
    "how_to_use": [
        "how to use", "how do i use", "dosage", "how much", "how to take",
        "when to take", "how do i take it", "usage instructions",
    ],
    "warnings": [
        "warning", "warnings", "side effect", "side effects", "caution",
        "is it safe", "any risks", "precautions",
    ],
    "price": ["price", "cost", "how much does it cost", "how much is it"],
}
_NAME_ASPECT_PATTERNS = {
    aspect: [re.compile(r"\b" + re.escape(phrase) + r"\b") for phrase in phrases]
    for aspect, phrases in NAME_QUESTION_ASPECTS.items()
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
    asked_disambiguation: list = field(default_factory=list)  # canonical symptoms already used in a tie-break question

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
    for canonical, pattern in _SYMPTOM_PATTERNS:
        if canonical not in found and pattern.search(norm):
            found.append(canonical)
    if not found:
        return None, []
    return found[0], found[1:]


def extract_food_trigger(text):
    norm = normalize(text)
    for trigger, patterns in _FOOD_TRIGGER_PATTERNS.items():
        if any(p.search(norm) for p in patterns):
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
    for aspect, patterns in _NAME_ASPECT_PATTERNS.items():
        if any(p.search(norm) for p in patterns):
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
        asked_disambiguation=list(previous.asked_disambiguation or []),
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
