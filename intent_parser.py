"""Structured symptom extraction for GutGPT.

The parser is intentionally deterministic. ConversationManager supplies the
question context, so short answers such as "yes", "no", "5 months", or "23"
are interpreted as answers to the field that was actually asked.
"""
import re
from dataclasses import dataclass, field, asdict

SYMPTOM_SYNONYMS = {
    "constipation": [
        "constipation", "constipated",
        "can't poop", "cant poop", "cannot poop", "can not poop",
        "can't poo", "cant poo", "cannot poo", "can not poo",
        "can't pass stool", "cant pass stool", "cannot pass stool", "can not pass stool",
        "can't pass stools", "cant pass stools", "cannot pass stools",
        "can't pass my stool", "cant pass my stool", "cannot pass my stool",
        "can't pass my stools", "cant pass my stools", "cannot pass my stools",
        "unable to poop", "not able to poop", "unable to poo", "not able to poo",
        "unable to pass stool", "unable to pass stools",
        "unable to pass my stool", "unable to pass my stools",
        "not able to pass stool", "not able to pass stools",
        "not able to pass my stool", "not able to pass my stools",
        "not passing stool", "not passing stools",
        "not passing my stool", "not passing my stools",
        "not pooping", "not pooing", "not passing poop", "not passing poo",
        "no bowel movement", "no bowel movements",
        "no bm", "no bowel motion", "no bowel motions",
        "haven't pooped", "havent pooped",
        "haven't pooed", "havent pooed",
        "haven't had a bowel movement", "havent had a bowel movement",
        "not having bowel movements", "not having a bowel movement",
        "infrequent bowel movements", "infrequent bowel movement",
        "infrequent stools", "infrequent stool",
        "hard to poop", "hard to poo",
        "difficulty pooping", "difficulty pooing",
        "difficulty passing stool", "difficulty passing stools",
        "difficulty passing poop", "difficulty passing poo",
        "trouble pooping", "trouble pooing",
        "trouble passing stool", "trouble passing stools",
        "straining to poop", "straining while pooping",
        "straining to pass stool", "straining while passing stool",
        "bowel movement problems", "bowel movement problem",
        "bowel problems", "bowel trouble",
        "irregular bowel movements", "irregular bowel movement",
        "irregular stools", "not going regularly",
        "not pooping regularly", "not passing stool regularly",
        "not going to the toilet regularly",
        "feeling backed up", "feeling blocked", "feeling blocked up",
        "backed up", "bowels backed up", "bowel blockage feeling",
        "blocked bowel", "blocked up",
        "sluggish bowel", "sluggish bowels",
        "slow bowel", "slow bowels",
        "lazy bowel", "lazy bowels",
        "bowels not moving",
        "bowel not moving",
        "stool not coming out",
        "poop won't come out", "poop wont come out",
        "stool won't come out", "stool wont come out",
        "can't empty bowels", "cant empty bowels",
        "unable to empty bowels", "difficulty emptying bowels",
        "incomplete bowel movement",
        "incomplete evacuation",
        "difficulty evacuating",
        "constipation problem", "constipation issues",
        "bowel movement difficulty",
    ],

    "hard stools": [
        "hard stool", "hard stools",
        "hard poop", "hard poo", "hard bowel movement", "hard bowel movements",
        "dry stool", "dry stools", "dry poop", "dry poo",
        "firm stool", "firm stools", "firm poop",
        "hard feces", "hard faeces",
        "lumpy stool", "lumpy stools", "lumpy poop",
        "pellet-like stools", "pellet like stools",
        "pellet stools", "pellet stool",
        "small pellet stools", "small pellets",
        "pellets in stool", "pellets in poop",
        "rabbit pellet stools", "rabbit droppings-like stool",
        "small hard stools", "small hard poop",
        "rock hard stool", "very hard stool",
        "stool is hard", "my stool is hard",
        "poop is hard", "my poop is hard",
        "dry hard stool", "hard dry stool",
    ],

    "bloating": [
        "bloating", "bloated", "bloat",
        "stomach bloat", "stomach bloating",
        "belly bloat", "belly bloating",
        "abdominal bloating", "abdominal distension",
        "stomach becomes bigger", "stomach gets bigger",
        "stomach got bigger", "belly gets bigger",
        "belly becomes bigger",
        "stomach gets swollen", "stomach got swollen",
        "stomach swollen", "swollen stomach",
        "swollen belly", "belly swollen",
        "swelling in stomach", "swelling of stomach",
        "distended stomach", "distended abdomen",
        "stomach distension", "abdominal distension",
        "abdomen feels swollen", "stomach feels swollen",
        "belly feels swollen", "belly feels full",
        "stomach feels full", "full stomach",
        "feeling bloated", "feeling of bloating",
        "bloated stomach", "bloated belly",
        "gas and bloating", "bloating and gas",
        "abdominal fullness", "stomach fullness",
        "tight stomach", "tight belly",
        "stomach feels tight", "belly feels tight",
        "stomach feels inflated", "inflated stomach",
    ],

    "gas": [
        "gas", "gassy", "gas problem", "gas problems",
        "excess gas", "too much gas", "lots of gas", "a lot of gas",
        "excessive gas", "intestinal gas",
        "stomach gas", "belly gas", "abdominal gas",
        "trapped gas", "trapped wind", "wind",
        "gas trapped in stomach", "gas trapped in belly",
        "gas buildup", "gas build up",
        "gas accumulation",
        "flatulence", "passing gas", "passing wind",
        "farting", "fart a lot", "farting a lot",
        "frequent farting", "frequent passing of gas",
        "burping", "burping a lot", "frequent burping",
        "belching", "belching a lot", "frequent belching",
        "stomach discomfort", "gas discomfort",
        "gas pain", "pain from gas", "gastric gas",
    ],

    "acidity": [
        "acidity", "acidic", "acidity problem", "acidity issues",
        "acid reflux", "acid reflux problem", "acid reflux disease",
        "reflux", "reflux problem", "reflux symptoms",
        "gerd", "gord",
        "gastroesophageal reflux", "gastro oesophageal reflux",
        "heartburn", "acid heartburn",
        "sour taste", "sour taste in mouth",
        "sour burps", "sour belching",
        "acid coming up", "acid comes up",
        "acid coming into throat", "acid in throat",
        "acid rising", "acid rising into throat",
        "burning sensation", "burning feeling",
        "burning in stomach", "burning stomach",
        "gastric problem", "gastric issue", "gastric trouble",
        "gastric acidity", "stomach acidity",
        "stomach acid", "excess stomach acid",
        "acid indigestion", "acid dyspepsia",
    ],

    "heartburn": [
        "heartburn",
        "burning in chest", "burning in my chest",
        "burning chest", "chest burning",
        "burning sensation in chest",
        "burning feeling in chest",
        "burning after meals", "burning after food",
        "burning sensation after meals",
        "burning sensation after food",
        "burning after eating",
        "burning feeling after eating",
        "burning in throat", "burning in my throat",
        "throat burning", "burning sensation in throat",
        "chest feels like burning",
        "burning behind breastbone",
        "burning behind the chest",
        "acid burn", "acid burning",
        "acid reflux burning",
    ],

    "diarrhea": [
        "diarrhea", "diarrhoea",
        "loose motion", "loose motions",
        "loose stool", "loose stools",
        "watery stool", "watery stools",
        "watery poop", "watery poo",
        "runny stool", "runny stools",
        "runny poop", "runny poo",
        "frequent loose stools",
        "frequent bowel movements",
        "frequent motions", "frequent loose motions",
        "passing loose stools",
        "passing watery stools",
        "very loose stool", "very loose stools",
        "liquid stool", "liquid stools",
        "liquid poop",
        "soft stool", "soft stools",
        "mushy stool", "mushy stools",
        "explosive diarrhea", "explosive diarrhoea",
        "watery diarrhea", "watery diarrhoea",
        "bowel looseness", "loose bowel",
        "loose bowels",
    ],

    "stomach pain": [
        "stomach pain", "stomach ache", "stomachache",
        "stomach aches", "stomach pains",
        "abdominal pain", "abdomen pain",
        "abdominal ache", "abdominal discomfort",
        "belly pain", "belly ache", "bellyache",
        "pain in stomach", "pain in my stomach",
        "pain in abdomen", "pain in my abdomen",
        "pain in belly", "pain in my belly",
        "stomach cramps", "stomach cramping",
        "abdominal cramps", "abdominal cramping",
        "belly cramps", "belly cramping",
        "cramps", "cramping",
        "tummy pain", "tummy ache",
        "tummy cramps", "tummy cramping",
        "gastric pain",
        "upper abdominal pain", "lower abdominal pain",
        "abdominal soreness", "stomach soreness",
    ],

    "piles": [
        "piles", "pile", "hemorrhoid", "hemorrhoids",
        "haemorrhoid", "haemorrhoids",
        "hemorrhoidal disease", "haemorrhoidal disease",
        "swollen hemorrhoids", "swollen piles",
        "piles problem", "piles symptoms",
        "bleeding piles", "painful piles",
        "internal hemorrhoids", "external hemorrhoids",
        "internal haemorrhoids", "external haemorrhoids",
    ],

    "anal fissures": [
        "anal fissure", "anal fissures",
        "fissure", "fissures",
        "anal tear", "anal tears",
        "tear near anus", "tear around anus",
        "tear in anus", "cut near anus",
        "cut around anus", "cut in anus",
        "small tear in anus",
        "crack near anus", "crack around anus",
        "crack in anus",
        "anal crack", "painful anal tear",
    ],

    "anal burning": [
        "anal burning",
        "burning around anus", "burning near anus",
        "burning sensation around anus",
        "burning sensation near anus",
        "burning in anus", "burning inside anus",
        "burning at anus", "burning around the anus",
        "anus burning", "anal area burning",
        "burning after bowel movement",
        "burning after passing stool",
        "burning after pooping",
        "burning while passing stool",
        "burning while pooping",
        "hot sensation around anus",
        "irritation around anus",
        "anal irritation",
    ],

    "anal swelling": [
        "anal swelling",
        "swelling around anus", "swelling near anus",
        "swelling of anus", "swollen anus",
        "anus is swollen", "anus feels swollen",
        "swollen anal area",
        "swelling around the anal area",
        "lump near anus", "lump around anus",
        "bump near anus", "bump around anus",
        "bulge near anus", "bulge around anus",
        "anal lump", "anal bump",
        "swollen rectum", "rectal swelling",
    ],

    "bleeding": [
        "blood in stool", "blood in my stool", "blood in the stool",
        "blood in poop", "blood in my poop",
        "blood in poo", "blood in my poo",
        "blood while passing stool",
        "blood after stool", "blood after passing stool",
        "blood after bowel movement",
        "blood after pooping", "blood after pooing",
        "blood on toilet paper", "blood while wiping",
        "blood when wiping",
        "fresh blood", "bright red blood",
        "rectal bleeding", "anal bleeding",
        "bleeding from anus", "bleeding from rectum",
        "bleeding while pooping", "bleeding while passing stool",
        "blood when i poop", "blood when pooping",
        "blood when passing stool",
        "blood during bowel movement",
        "blood during defecation",
        "bloody stool", "bloody stools",
        "bloody poop", "bloody poo",
        "red blood in stool", "red blood after stool",
    ],

    "indigestion": [
        "indigestion",
        "indigestion after eating",
        "indigestion after food",
        "upset stomach", "upset stomach after eating",
        "upset stomach after food",
        "dyspepsia",
        "functional dyspepsia",
        "poor digestion", "bad digestion",
        "difficulty digesting food",
        "food not digesting",
        "food is not digesting",
        "feeling too full",
        "fullness after eating",
        "full after eating",
        "feeling full after eating",
        "early fullness", "early satiety",
        "stomach feels heavy",
        "heavy stomach", "heaviness in stomach",
        "stomach discomfort after eating",
        "abdominal discomfort after eating",
        "discomfort after meals",
        "digestive discomfort",
    ],

    "food intolerance": [
        "food intolerance",
        "food intolerances",
        "food sensitivity",
        "food sensitivities",
        "sensitivity to food",
        "sensitive to food",
        "food doesn't suit me",
        "food does not suit me",
        "certain foods don't suit me",
        "certain foods do not suit me",
        "can't tolerate food", "cannot tolerate food",
        "can't digest certain foods",
        "cannot digest certain foods",
        "intolerance to milk",
        "intolerance to dairy",
        "dairy intolerance",
        "milk intolerance",
        "lactose intolerance",
        "lactose sensitive",
        "sensitive to lactose",
        "can't tolerate milk",
        "cannot tolerate milk",
        "milk doesn't suit me",
        "milk does not suit me",
        "dairy doesn't suit me",
        "dairy does not suit me",
        "can't tolerate dairy",
        "cannot tolerate dairy",
        "sensitivity to milk",
        "sensitivity to dairy",
    ],
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


NEGATION_WORD_RE = re.compile(
    r"\b(?:no|not|never|without|don't|dont|doesn't|doesnt|isn't|isnt|aren't|arent)\b"
)


def is_negated(text, phrase):
    """Return True when a symptom/trigger occurrence is locally negated."""
    n = normalize(text)
    phrase_n = normalize(phrase)
    if not phrase_n:
        return False
    match = re.search(r"(?P<prefix>.*?)(?P<phrase>" + re.escape(phrase_n) + r")\b", n)
    if not match:
        return False
    prefix = match.group("prefix")[-100:]
    negations = list(NEGATION_WORD_RE.finditer(prefix))
    if not negations:
        return False
    after = prefix[negations[-1].end():].strip()
    if not after:
        return True
    words = after.split()
    if len(words) > 3:
        return False
    if any(w in {"but", "however", "though", "although", "except"} for w in words):
        return False
    return True


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
    constipation_explicit: bool = None
    diarrhea_explicit: bool = None
    mucus: bool = None
    fever: bool = None
    vomiting: bool = None
    persistent_vomiting: bool = None
    vomiting_blood: bool = None
    difficulty_swallowing: bool = None
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
    # Track if the conditional weight-loss question (triggered by duration >= 1 month) has been asked
    weight_loss_duration_asked: bool = False

    def to_dict(self):
        return asdict(self)


def extract_symptoms(text):
    n = normalize(text)
    found = []
    for canonical, pattern in _PATTERNS:
        if canonical in found:
            continue
        match = pattern.search(n)
        if match:
            phrase = match.group(0)
            if not is_negated(n, phrase):
                found.append(canonical)
    if not found:
        return None, []
    return found[0], found[1:]


def extract_food_trigger(text):
    n = normalize(text)
    for trigger, patterns in _FOOD_PATTERNS.items():
        for p in patterns:
            match = p.search(n)
            if match and not is_negated(n, match.group(0)):
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
    # First try the standard format (e.g., "1 month", "2 weeks", "6 months")
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(day|days|week|weeks|month|months|year|years)\b", n)
    if m:
        return m.group(0)
    
    # Handle natural language expressions
    # "about a month", "around a month", "roughly a month"
    if re.search(r"\b(about|around|roughly)\s+a\s+(month|months)\b", n):
        return "1 month"
    # "more than a month", "over a month", "greater than a month"
    if re.search(r"\b(more than|over|greater than)\s+a\s+(month|months)\b", n):
        return "1 month"
    # "several months", "a few months", "many months"
    if re.search(r"\b(several|a few|many)\s+months?\b", n):
        return "3 months"
    # "about X months", "around X months"
    m = re.search(r"\b(about|around|roughly)\s+(\d+)\s+months?\b", n)
    if m:
        return f"{m.group(2)} months"
    # "since January", "since Feb", etc. - estimate from current date
    m = re.search(r"\bsince\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", n)
    if m:
        month_name = m.group(1).lower()
        month_map = {
            "january": 1, "jan": 1,
            "february": 2, "feb": 2,
            "march": 3, "mar": 3,
            "april": 4, "apr": 4,
            "may": 5,
            "june": 6, "jun": 6,
            "july": 7, "jul": 7,
            "august": 8, "aug": 8,
            "september": 9, "sep": 9,
            "october": 10, "oct": 10,
            "november": 11, "nov": 11,
            "december": 12, "dec": 12,
        }
        target_month = month_map.get(month_name)
        if target_month:
            from datetime import datetime
            now = datetime.now()
            current_month = now.month
            # Calculate months difference
            if target_month <= current_month:
                months_diff = current_month - target_month
            else:
                months_diff = (12 - target_month) + current_month
            # If months_diff is 0, it's less than a month - return a small value
            if months_diff >= 1:
                return f"{months_diff} months"
            else:
                return "2 weeks"  # Same month, treat as less than 1 month
    
    # "for a month", "for months", "for years"
    if re.search(r"\bfor\s+a\s+month\b", n):
        return "1 month"
    if re.search(r"\bfor\s+months?\b", n):
        return "2 months"
    if re.search(r"\bfor\s+years?\b", n):
        return "1 year"
    # "a month ago", "months ago", "years ago"
    if re.search(r"\ba\s+month\s+ago\b", n):
        return "1 month"
    if re.search(r"\bmonths?\s+ago\b", n):
        return "2 months"
    if re.search(r"\byears?\s+ago\b", n):
        return "1 year"
    
    return None


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
        "abdominal_pain": _merge_value(previous.abdominal_pain, extract_bool(text, ["abdominal pain", "stomach pain", "belly pain", "stomach ache", "abdominal ache", "cramps", "cramping"], ["no abdominal pain", "no stomach pain", "no cramps", "no pain", "do not have abdominal pain", "don't have abdominal pain", "dont have abdominal pain", "do not have stomach pain", "don't have stomach pain", "dont have stomach pain", "no pain at all"])),
        "pain_related_to_bowel_movement": _merge_value(previous.pain_related_to_bowel_movement, extract_bool(text, ["pain improves after stool", "pain improves after bowel movement", "pain relieved after stool", "pain relieved after bowel movement", "pain related to bowel movement", "pain when i need to poop", "pain changes after bowel movement", "pain associated with stool", "better after bowel movement", "worse after bowel movement"], ["pain not related to stool", "not related to bowel movement", "not related to stool"])),
        "blood_present": blood_present,
        "anal_pain": _merge_value(previous.anal_pain, extract_bool(text, ["anal pain", "pain around anus", "pain near anus", "pain during stool", "sharp pain during stool"], ["no anal pain", "no pain"])),
        "sharp_pain_during_stool": _merge_value(previous.sharp_pain_during_stool, extract_bool(text, ["sharp pain during stool", "sharp tearing pain during stool", "sharp pain while passing stool", "cutting pain during stool", "tearing pain during stool", "sharp pain after stool"], ["no sharp pain", "no tearing pain"])),
        "lump_or_prolapse": _merge_value(previous.lump_or_prolapse, extract_bool(text, ["lump near anus", "lump at anus", "lump comes out", "prolapse", "something comes out of anus"], ["no lump", "no prolapse"])),
        "bloating": _merge_value(previous.bloating, extract_bool(text, ["bloating", "bloated", "bloat"], ["no bloating", "not bloated"])),
        "diarrhea": _merge_value(previous.diarrhea, extract_bool(text, ["diarrhea", "diarrhoea", "loose motion", "loose stool", "watery stool"], ["no diarrhea", "no diarrhoea", "no loose motion"])),
        "constipation_explicit": _merge_value(previous.constipation_explicit, extract_bool(text, ["constipation", "constipated", "unable to pass stool", "unable to poop", "difficulty passing stool"], ["no constipation", "not constipated", "do not have constipation", "dont have constipation", "don't have constipation"])),
        "diarrhea_explicit": _merge_value(previous.diarrhea_explicit, extract_bool(text, ["diarrhea", "diarrhoea", "loose motion", "loose stool", "watery stool"], ["no diarrhea", "no diarrhoea", "no loose motion"])),
        "mucus": _merge_value(previous.mucus, extract_bool(text, ["mucus in stool", "mucus in my stool"], ["no mucus"])),
        "fever": _merge_value(previous.fever, extract_bool(text, ["fever", "high temperature"], ["no fever", "do not have fever", "don't have fever", "dont have fever", "never had fever", "no temperature"])),
        "vomiting": _merge_value(previous.vomiting, extract_bool(text, ["vomiting", "vomit", "throwing up"], ["no vomiting", "not vomiting", "do not have vomiting", "don't have vomiting", "dont have vomiting", "have not had vomiting", "haven't had vomiting", "haven't been vomiting", "not been vomiting", "never had vomiting", "never vomit", "never vomited"])),
        "abdominal_distension": _merge_value(previous.abdominal_distension, extract_bool(text, ["severe abdominal swelling", "severe abdominal distension", "abdomen is very swollen", "severe swelling"], ["no abdominal swelling", "no severe swelling"])),
        "night_time_symptoms": _merge_value(previous.night_time_symptoms, extract_bool(text, ["wakes me at night", "waking at night", "symptoms wake me", "at night while sleeping"], ["not at night", "doesn't wake me", "does not wake me"])),
        "weight_loss": _merge_value(previous.weight_loss, extract_bool(text, ["unexplained weight loss", "losing weight without trying", "weight loss without trying", "weight loss"], ["no weight loss", "not losing weight", "do not have weight loss", "don't have weight loss", "dont have weight loss", "haven't lost weight", "have not lost weight", "not losing any weight"])),
        "dehydration": _merge_value(previous.dehydration, extract_bool(text, ["dehydrated", "dehydration", "very thirsty", "dry mouth and not urinating"], ["not dehydrated", "do not have dehydration", "don't have dehydration", "dont have dehydration", "not thirsty", "no dehydration"])),
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
