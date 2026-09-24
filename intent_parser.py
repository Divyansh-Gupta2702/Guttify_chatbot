"""Structured symptom extraction for GutGPT.

The parser is intentionally deterministic. ConversationManager supplies the
question context, so short answers such as "yes", "no", "5 months", or "23"
are interpreted as answers to the field that was actually asked.
"""
import re
from dataclasses import dataclass, field, asdict

SYMPTOM_SYNONYMS = {
    "constipation": [
        "constipation", "constipated", "can't poop", "cant poop", "can not poop", "cannot poop",
        "not able to poop", "unable to poop", "can't pass stool", "cant pass stool", "can't pass stools",
        "cant pass stools", "can't pass my stool", "cant pass my stool", "can't pass my stools",
        "cant pass my stools", "cannot pass stool", "cannot pass stools", "cannot pass my stool",
        "cannot pass my stools", "unable to pass stool", "unable to pass stools", "unable to pass my stool",
        "unable to pass my stools", "not able to pass stool", "not able to pass stools", "not able to pass my stool",
        "not able to pass my stools", "not passing stool", "not passing stools", "not passing my stool",
        "not passing my stools", "no bowel movement", "hard to poop", "trouble pooping", "difficulty pooping",
        "haven't pooped", "havent pooped", "infrequent bowel movements", "feeling backed up", "backed up",
        "bowel movement problems", "irregular bowel movements", "not going regularly", "not pooping regularly",
    ],
    "hard stools": [
        "hard stool", "hard stools", "hard poop", "dry stool", "dry stools", "lumpy stool", "lumpy stools",
        "pellet-like stools", "pellet stools", "pellets in stool",
    ],
    "bloating": ["bloating", "bloated", "bloat", "stomach becomes bigger", "stomach gets swollen", "stomach got swollen", "gets swollen", "got swollen", "stomach swollen", "swollen stomach", "distended stomach", "stomach distension", "belly bloat", "gas and bloating"],
    "gas": ["gas", "gassy", "excess gas", "too much gas", "flatulence", "trapped wind", "burping a lot", "belching a lot"],
    "acidity": ["acidity", "acid reflux", "reflux", "gerd", "sour taste", "sour burps", "acid coming up", "gastric problem", "gastric issue"],
    "heartburn": ["heartburn", "burning in chest", "burning in my chest", "burning chest", "burning after meals", "burning after food", "burning in throat"],
    "diarrhea": ["diarrhea", "diarrhoea", "loose motion", "loose motions", "loose stool", "loose stools", "watery stool", "watery stools", "runny stool"],
    "stomach pain": ["stomach pain", "abdominal pain", "belly pain", "abdomen pain", "stomach ache", "stomachache", "abdominal ache", "cramps", "cramping"],
    "piles": ["piles", "hemorrhoid", "hemorrhoids", "haemorrhoid", "haemorrhoids"],
    "anal fissures": ["anal fissure", "anal fissures", "fissure", "tear near anus", "cut near anus"],
    "bleeding": ["blood in stool", "blood in my stool", "blood in the stool", "blood while passing stool", "blood after stool", "blood after bowel movement", "blood on toilet paper", "fresh blood", "rectal bleeding", "bleeding from anus", "bleeding while pooping", "blood when i poop", "blood when pooping"],
    "indigestion": ["indigestion", "indigestion after eating", "upset stomach after eating", "dyspepsia", "fullness after eating", "early fullness"],
    "food intolerance": ["food intolerance", "food sensitivity", "intolerance to milk", "intolerance to dairy", "can't tolerate milk", "cannot tolerate milk"],
}

FOOD_TRIGGER_SYNONYMS = {
    "dairy": ["dairy", "milk", "paneer", "cheese", "curd", "yogurt", "yoghurt", "buttermilk", "lassi", "ice cream"],
    "spicy_oily": ["spicy", "oily", "fried", "fatty food", "greasy", "masala", "chilli", "chili", "junk food", "fast food"],
    "wheat_gluten": ["wheat", "gluten", "roti", "bread", "atta", "chapati", "paratha", "maida"],
    "legumes": ["beans", "lentils", "dal", "chickpeas", "rajma", "chana", "kidney beans", "sprouts"],
    "caffeine": ["coffee", "caffeine", "tea", "chai", "energy drink"],
}

NAME_QUESTION_ASPECTS = {
    "ingredients": ["ingredient", "ingredients", "what's in it", "whats in it", "contains", "what does it contain", "made of", "composition"],
    "how_to_use": ["how to use", "how do i use", "dosage", "how much", "how to take", "when to take", "how do i take it", "usage instructions"],
    "warnings": ["warning", "warnings", "side effect", "side effects", "caution", "is it safe", "any risks", "precautions"],
    "price": ["price", "cost", "how much does it cost", "how much is it"],
}

FREQUENCY_PATTERNS = {
    "daily": [r"\bdaily\b", r"every day", r"each day", r"almost every day"],
    "few_times_per_week": [r"few times a week", r"couple times a week", r"2-3 times a week", r"several times a week", r"twice a week"],
    "weekly": [r"once a week", r"weekly", r"every alternate day"],
    "occasional": [r"occasionally", r"sometimes", r"once in a while", r"rarely", r"on and off"],
}


def normalize(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s'/.-]", " ", (text or "").lower())).strip()

_SORTED = sorted(((c, p) for c, ps in SYMPTOM_SYNONYMS.items() for p in ps), key=lambda x: -len(x[1]))
_PATTERNS = [(c, re.compile(r"(?<!\w)" + re.escape(p) + r"(?!\w)")) for c, p in _SORTED]
_FOOD_PATTERNS = {k: [re.compile(r"(?<!\w)" + re.escape(p) + r"(?!\w)") for p in ps] for k, ps in FOOD_TRIGGER_SYNONYMS.items()}

@dataclass
class SymptomState:
    primary_symptom: str = None
    secondary_symptoms: list = field(default_factory=list)
    frequency: str = None
    food_related: bool = None
    food_trigger: str = None
    severity: str = "unknown"
    duration: str = "unknown"
    age: int = None
    bowel_frequency_per_week: float = None
    bowel_frequency_per_day: float = None
    stool_form: int = None
    straining: bool = None
    incomplete_evacuation: bool = None
    abdominal_pain: bool = None
    pain_location: str = None
    pain_related_to_bowel_movement: bool = None
    blood_present: bool = None
    blood_colour: str = None
    blood_location: str = None
    blood_mixed_with_stool: bool = None
    anal_pain: bool = None
    sharp_pain_during_stool: bool = None
    lump_or_prolapse: bool = None
    bloating: bool = None
    diarrhea: bool = None
    mucus: bool = None
    fever: bool = None
    vomiting: bool = None
    abdominal_distension: bool = None
    night_time_symptoms: bool = None
    weight_loss: bool = None
    dehydration: bool = None
    unable_to_pass_stool_and_gas: bool = None
    water_intake: str = None
    fibre_intake: str = None
    medications: str = None
    recent_infection: bool = None
    family_history_gi: bool = None
    red_flags: list = field(default_factory=list)
    asked_fields: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def extract_symptoms(text):
    n = normalize(text)
    found = []
    for canonical, pattern in _PATTERNS:
        if canonical not in found and pattern.search(n):
            found.append(canonical)
    if not found:
        return None, []
    return found[0], found[1:]


def extract_food_trigger(text):
    n = normalize(text)
    for trigger, patterns in _FOOD_PATTERNS.items():
        if any(p.search(n) for p in patterns):
            return trigger
    return None


def extract_food_related(text):
    n = normalize(text)
    if any(x in n for x in ["not related to food", "not related to meals", "not after eating"]):
        return False
    if extract_food_trigger(text):
        return True
    if any(x in n for x in ["after eating", "after meals", "after food", "related to food", "when i eat", "whenever i eat"]):
        return True
    return None


def extract_frequency(text):
    n = normalize(text)
    for k, patterns in FREQUENCY_PATTERNS.items():
        if any(re.search(p, n) for p in patterns):
            return k
    return None


def extract_named_aspect(text):
    n = normalize(text)
    for name, phrases in NAME_QUESTION_ASPECTS.items():
        if any(p in n for p in phrases):
            return name
    return None


def extract_duration(text):
    n = normalize(text)
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(day|days|week|weeks|month|months|year|years)\b", n)
    return m.group(0) if m else None


def extract_age(text):
    n = normalize(text)
    m = re.search(r"\b(?:i am|im|age is|aged)\s*(\d{1,3})\b", n)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"\s*(\d{1,3})\s*(?:years? old)?\s*", n)
    return int(m.group(1)) if m else None


def extract_bowel_frequency(text):
    n = normalize(text)
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:bowel movements?|bowel movement|bm|times?|motions?)\s*(?:per|a|each)\s*week\b", n)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(once|twice|three times|4 times|five times|5 times)\s*(?:a|per)\s*week\b", n)
    if m:
        return {"once": 1.0, "twice": 2.0, "three times": 3.0, "4 times": 4.0, "five times": 5.0, "5 times": 5.0}[m.group(1)]
    m = re.fullmatch(r"\s*(\d+)\s*(?:-|to|or)\s*(\d+)\s*(?:times?)?\s*(?:a|per)?\s*week?\s*", n)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2
    m = re.fullmatch(r"\s*(\d+)\s*times?\s*", n)
    if m:
        return float(m.group(1))
    return None


def extract_bowel_frequency_per_day(text):
    n = normalize(text)
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:loose\s+)?(?:bowel movements?|bm|times?|motions?)\s*(?:per|a|each)\s*day\b", n)
    if m:
        return float(m.group(1))
    m = re.fullmatch(r"\s*(\d+)\s*times?\s*\s*(?:a|per)?\s*day\s*", n)
    if m:
        return float(m.group(1))
    return None


def extract_severity(text):
    n = normalize(text)
    m = re.search(r"\b(?:pain|severity)\s*(?:is|of)?\s*(\d{1,2})\s*(?:/\s*10)?\b", n)
    if m and 0 <= int(m.group(1)) <= 10:
        return m.group(1)
    m = re.search(r"\b(\d{1,2})\s*/\s*10\b", n)
    if m and 0 <= int(m.group(1)) <= 10:
        return m.group(1)
    return None


def extract_lifestyle(text):
    n = normalize(text)
    water = fibre = None
    if any(x in n for x in ["low fibre", "low fiber", "little fibre", "little fiber", "poor fibre", "poor fiber"]):
        fibre = "low"
    elif any(x in n for x in ["high fibre", "high fiber", "good fibre", "good fiber"]):
        fibre = "high"
    elif any(x in n for x in ["average fibre", "average fiber", "normal fibre", "normal fiber"]):
        fibre = "average"
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:litres?|liters?|l)\b", n)
    if m:
        water = m.group(0)
    return water, fibre


def extract_medications(text):
    n = normalize(text)
    if any(x in n for x in ["no medicines", "no medication", "not taking medicines", "not taking medication", "no regular medicines", "no regular medication", "not on medication"]):
        return "none"
    if any(x in n for x in ["taking medicine", "taking medication", "taking medicines", "taking supplements", "regular medication", "regular medicines", "on medication", "on medicines", "i take ", "i'm taking ", "im taking "]):
        return "reported"
    return None


def _phrase_present(n, phrase):
    phrase = normalize(phrase)
    return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", n))


def extract_bool(text, positives, negatives):
    """Phrase-aware boolean parser; negatives win and substring traps are avoided."""
    n = normalize(text)
    for phrase in sorted(negatives, key=len, reverse=True):
        if _phrase_present(n, phrase):
            return False
    for phrase in sorted(positives, key=len, reverse=True):
        if _phrase_present(n, phrase):
            return True
    if n in {"yes", "yeah", "yep", "yup", "sure", "true"}:
        return True
    if n in {"no", "nope", "nah", "none", "false"}:
        return False
    return None


def extract_stool_form(text):
    n = normalize(text)
    m = re.search(r"\b(?:bristol(?:\s+stool)?(?:\s+type|\s+scale)?|stool\s+(?:type|form))\s*([1-7])\b", n)
    if m:
        return int(m.group(1))
    if any(x in n for x in ["hard", "pellet", "lumpy"]):
        return 2
    if any(x in n for x in ["watery", "liquid"]):
        return 7
    if any(x in n for x in ["loose", "mushy"]):
        return 6
    return None


def _merge_value(old, new):
    return new if new is not None else old


def merge_state(previous, text, red_flags=None):
    """Merge volunteered details without replacing the original branch."""
    previous = previous or SymptomState()
    primary, secondary = extract_symptoms(text)
    existing_secondary = list(previous.secondary_symptoms or [])
    for item in secondary + ([primary] if primary else []):
        if item and item != previous.primary_symptom and item not in existing_secondary:
            existing_secondary.append(item)

    n = normalize(text)
    blood_present = previous.blood_present
    if any(x in n for x in ["no blood", "no bleeding", "without blood", "no rectal bleeding"]):
        blood_present = False
    elif any(x in n for x in ["blood in stool", "blood in my stool", "blood in the stool", "blood after stool", "blood on toilet paper", "fresh blood", "rectal bleeding", "bleeding from anus", "blood while passing stool", "blood when pooping", "blood when i poop"]):
        blood_present = True

    updates = previous.to_dict()
    updates.update({
        "primary_symptom": previous.primary_symptom or primary,
        "secondary_symptoms": existing_secondary,
        "frequency": extract_frequency(text) or previous.frequency,
        "food_related": _merge_value(previous.food_related, extract_food_related(text)),
        "food_trigger": extract_food_trigger(text) or previous.food_trigger,
        "severity": extract_severity(text) or previous.severity,
        "duration": extract_duration(text) or previous.duration,
        "age": _merge_value(previous.age, extract_age(text)),
        "bowel_frequency_per_week": _merge_value(previous.bowel_frequency_per_week, extract_bowel_frequency(text)),
        "bowel_frequency_per_day": _merge_value(previous.bowel_frequency_per_day, extract_bowel_frequency_per_day(text)),
        "stool_form": _merge_value(previous.stool_form, extract_stool_form(text)),
        "straining": _merge_value(previous.straining, extract_bool(text, ["strain", "straining", "push hard", "pushing hard"], ["no strain", "without straining"])),
        "incomplete_evacuation": _merge_value(previous.incomplete_evacuation, extract_bool(text, ["incomplete evacuation", "not completely empty", "not fully empty", "still feel like i need to go", "feel incompletely empty"], ["complete evacuation", "completely empty", "fully empty"])),
        "abdominal_pain": _merge_value(previous.abdominal_pain, extract_bool(text, ["abdominal pain", "stomach pain", "belly pain", "stomach ache", "abdominal ache", "cramps", "cramping"], ["no abdominal pain", "no stomach pain", "no cramps", "no pain"])),
        "pain_related_to_bowel_movement": _merge_value(previous.pain_related_to_bowel_movement, extract_bool(text, ["pain improves after stool", "pain improves after bowel movement", "pain relieved after stool", "pain relieved after bowel movement", "pain related to bowel movement", "pain when i need to poop", "pain changes after bowel movement", "pain associated with stool", "better after bowel movement", "worse after bowel movement"], ["pain not related to stool", "not related to bowel movement", "not related to stool"])),
        "blood_present": blood_present,
        "anal_pain": _merge_value(previous.anal_pain, extract_bool(text, ["anal pain", "pain around anus", "pain near anus", "pain during stool", "sharp pain during stool"], ["no anal pain", "no pain"])),
        "sharp_pain_during_stool": _merge_value(previous.sharp_pain_during_stool, extract_bool(text, ["sharp pain during stool", "sharp tearing pain during stool", "sharp pain while passing stool", "cutting pain during stool", "tearing pain during stool", "sharp pain after stool"], ["no sharp pain", "no tearing pain"])),
        "lump_or_prolapse": _merge_value(previous.lump_or_prolapse, extract_bool(text, ["lump near anus", "lump at anus", "lump comes out", "prolapse", "something comes out of anus"], ["no lump", "no prolapse"])),
        "bloating": _merge_value(previous.bloating, extract_bool(text, ["bloating", "bloated", "bloat"], ["no bloating", "not bloated"])),
        "diarrhea": _merge_value(previous.diarrhea, extract_bool(text, ["diarrhea", "diarrhoea", "loose motion", "loose stool", "watery stool"], ["no diarrhea", "no diarrhoea", "no loose motion"])),
        "mucus": _merge_value(previous.mucus, extract_bool(text, ["mucus in stool", "mucus in my stool"], ["no mucus"])),
        "fever": _merge_value(previous.fever, extract_bool(text, ["fever", "high temperature"], ["no fever"])),
        "vomiting": _merge_value(previous.vomiting, extract_bool(text, ["vomiting", "vomit", "throwing up"], ["no vomiting", "not vomiting"])),
        "abdominal_distension": _merge_value(previous.abdominal_distension, extract_bool(text, ["severe abdominal swelling", "severe abdominal distension", "abdomen is very swollen", "severe swelling"], ["no abdominal swelling", "no severe swelling"])),
        "night_time_symptoms": _merge_value(previous.night_time_symptoms, extract_bool(text, ["wakes me at night", "waking at night", "symptoms wake me", "at night while sleeping"], ["not at night", "doesn't wake me", "does not wake me"])),
        "weight_loss": _merge_value(previous.weight_loss, extract_bool(text, ["unexplained weight loss", "losing weight without trying", "weight loss without trying", "weight loss"], ["no weight loss", "not losing weight"])),
        "dehydration": _merge_value(previous.dehydration, extract_bool(text, ["dehydrated", "dehydration", "very thirsty", "dry mouth and not urinating"], ["not dehydrated"])),
        "unable_to_pass_stool_and_gas": _merge_value(previous.unable_to_pass_stool_and_gas, extract_bool(text, ["cannot pass stool or gas", "can't pass stool or gas", "unable to pass stool and gas", "can't pass gas or stool"], ["can pass gas", "can pass stool"])),
        "family_history_gi": _merge_value(previous.family_history_gi, extract_bool(text, ["family history of colon cancer", "family history of colorectal cancer", "family history of ibd", "family history of crohn", "family history of ulcerative colitis", "family history of gi cancer"], ["no family history"])),
        "recent_infection": _merge_value(previous.recent_infection, extract_bool(text, ["recent stomach infection", "recent gut infection", "recent food poisoning", "recent gastroenteritis", "after an infection", "food poisoning"], ["no recent infection"])),
        "water_intake": extract_lifestyle(text)[0] or previous.water_intake,
        "fibre_intake": extract_lifestyle(text)[1] or previous.fibre_intake,
        "medications": extract_medications(text) or previous.medications,
        "blood_colour": previous.blood_colour,
        "blood_location": previous.blood_location,
        "blood_mixed_with_stool": previous.blood_mixed_with_stool,
        "pain_location": previous.pain_location,
        "red_flags": list(dict.fromkeys((previous.red_flags or []) + (red_flags or []))),
        "asked_fields": list(previous.asked_fields or []),
    })

    if any(x in n for x in ["black stool", "black tarry stool", "tarry stool", "black poop"]):
        updates["blood_colour"] = "black"
        updates["blood_present"] = True
    elif any(x in n for x in ["bright red", "fresh blood", "red blood"]):
        updates["blood_colour"] = "bright_red"
        updates["blood_present"] = True
    if any(x in n for x in ["on toilet paper", "on tissue"]):
        updates["blood_location"] = "tissue"
    elif "dripping" in n:
        updates["blood_location"] = "dripping"
    elif "mixed into stool" in n or "mixed with stool" in n:
        updates["blood_location"] = "mixed"
    if "upper abdomen" in n:
        updates["pain_location"] = "upper abdomen"
    elif "lower abdomen" in n:
        updates["pain_location"] = "lower abdomen"
    elif "right side" in n:
        updates["pain_location"] = "right side"
    elif "left side" in n:
        updates["pain_location"] = "left side"
    elif "around the navel" in n or "navel" in n or "belly button" in n:
        updates["pain_location"] = "around navel"
    return SymptomState(**updates)


def validate_llm_extraction(raw):
    if not isinstance(raw, dict):
        return None
    known = set(SYMPTOM_SYNONYMS)
    out = {}
    if raw.get("primary_symptom") in known:
        out["primary_symptom"] = raw["primary_symptom"]
    if isinstance(raw.get("secondary_symptoms"), list):
        out["secondary_symptoms"] = [x for x in raw["secondary_symptoms"] if x in known]
    return out or None
