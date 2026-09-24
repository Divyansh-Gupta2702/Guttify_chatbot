"""Structured symptom extraction for GutGPT.

Important design rule: the first user symptom remains the primary branch.
Later answers such as "yes, I also have abdominal pain" become secondary
features instead of accidentally replacing the branch with a new symptom.
"""
import re
from dataclasses import dataclass, field, asdict

SYMPTOM_SYNONYMS = {
    "constipation": ["constipation", "constipated", "can't poop", "cant poop", "not passing stool", "no bowel movement", "hard to poop", "trouble pooping", "difficulty pooping", "haven't pooped", "havent pooped", "infrequent bowel movements", "feeling backed up"],
    "hard stools": ["hard stool", "hard stools", "hard poop", "dry stool", "dry stools", "lumpy stool", "lumpy stools", "pellet-like stools", "pellet stools"],
    "bloating": ["bloating", "bloated", "bloat", "stomach becomes bigger", "stomach swollen", "swollen stomach", "distended stomach", "stomach distension", "belly bloat", "gas and bloating"],
    "gas": ["gas", "gassy", "excess gas", "too much gas", "flatulence", "trapped wind", "burping a lot", "belching a lot"],
    "acidity": ["acidity", "acid reflux", "reflux", "gerd", "sour taste", "sour burps", "acid coming up", "gastric problem", "gastric issue"],
    "heartburn": ["heartburn", "burning in chest", "burning chest", "burning after meals", "burning after food", "burning in throat"],
    "diarrhea": ["diarrhea", "diarrhoea", "loose motion", "loose motions", "loose stool", "loose stools", "watery stool", "watery stools", "runny stool"],
    "stomach pain": ["stomach pain", "abdominal pain", "belly pain", "abdomen pain", "stomach ache", "stomachache", "abdominal ache", "cramps", "cramping"],
    "piles": ["piles", "hemorrhoid", "hemorrhoids", "haemorrhoid", "haemorrhoids"],
    "anal fissures": ["anal fissure", "anal fissures", "fissure", "tear near anus", "cut near anus"],
    "bleeding": ["blood in stool", "blood while passing stool", "blood after stool", "blood after bowel movement", "blood on toilet paper", "fresh blood", "rectal bleeding", "bleeding from anus", "bleeding while pooping", "blood when i poop", "blood when pooping"],
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
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s'/.-]", " ", text.lower())).strip()

_SORTED = sorted(((c, p) for c, ps in SYMPTOM_SYNONYMS.items() for p in ps), key=lambda x: -len(x[1]))
_PATTERNS = [(c, re.compile(r"\b" + re.escape(p) + r"\b")) for c, p in _SORTED]
_FOOD_PATTERNS = {k: [re.compile(r"\b" + re.escape(p) + r"\b") for p in ps] for k, ps in FOOD_TRIGGER_SYNONYMS.items()}
_ASPECT_PATTERNS = {k: [re.compile(r"\b" + re.escape(p) + r"\b") for p in ps] for k, ps in NAME_QUESTION_ASPECTS.items()}

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

    def to_dict(self): return asdict(self)


def extract_symptoms(text):
    n = normalize(text); found=[]
    for c,p in _PATTERNS:
        if c not in found and p.search(n): found.append(c)
    return (found[0], found[1:]) if found else (None, [])


def extract_food_trigger(text):
    n=normalize(text)
    for trigger, pats in _FOOD_PATTERNS.items():
        if any(p.search(n) for p in pats): return trigger
    return None


def extract_food_related(text):
    n=normalize(text)
    if extract_food_trigger(text): return True
    if any(x in n for x in ["after eating", "after meals", "after food", "related to food", "when i eat", "whenever i eat"]): return True
    if any(x in n for x in ["not related to food", "not related to meals"]): return False
    return None


def extract_frequency(text):
    n=normalize(text)
    for k,ps in FREQUENCY_PATTERNS.items():
        if any(re.search(p,n) for p in ps): return k
    return None


def extract_named_aspect(text):
    n=normalize(text)
    aspects={
        "ingredients":["ingredient","ingredients","what is in it","what does it contain"],
        "how_to_use":["how to use","dosage","how to take","when to take"],
        "warnings":["warning","warnings","side effect","side effects","is it safe","precautions"],
        "price":["price","cost","how much does it cost"],
    }
    for name, phrases in aspects.items():
        if any(p in n for p in phrases): return name
    return None


def extract_duration(text):
    n=normalize(text)
    m=re.search(r"\b(\d+(?:\.\d+)?)\s*(day|days|week|weeks|month|months|year|years)\b", n)
    return m.group(0) if m else None


def extract_age(text):
    n=normalize(text)
    m=re.search(r"\b(?:i am|im|age is|aged)\s*(\d{1,3})\b", n)
    if m: return int(m.group(1))
    m=re.fullmatch(r"\s*(\d{1,3})\s*(?:years? old)?\s*", n)
    return int(m.group(1)) if m else None


def extract_bowel_frequency(text):
    n=normalize(text)
    m=re.search(r"\b(\d+(?:\.\d+)?)\s*(?:bowel movements?|bm|times?)\s*(?:per|a|each)\s*week\b", n)
    if m: return float(m.group(1))
    m=re.search(r"\b(once|twice|three times|4 times|five times|5 times)\s*(?:a|per)\s*week\b", n)
    if m: return {"once":1.0,"twice":2.0,"three times":3.0,"4 times":4.0,"five times":5.0,"5 times":5.0}[m.group(1)]
    return None


def extract_bowel_frequency_per_day(text):
    n=normalize(text)
    m=re.search(r"\b(\d+(?:\.\d+)?)\s*(?:loose\s+)?(?:bowel movements?|bm|times?)\s*(?:per|a|each)\s*day\b", n)
    return float(m.group(1)) if m else None


def extract_severity(text):
    n=normalize(text)
    m=re.search(r"\b(?:pain|severity)\s*(?:is|of)?\s*(\d{1,2})\s*(?:/\s*10)?\b", n)
    if m and 0 <= int(m.group(1)) <= 10: return m.group(1)
    return None


def extract_lifestyle(text):
    n=normalize(text); water=fibre=None
    if any(x in n for x in ["low fibre", "low fiber", "little fibre", "little fiber", "poor fibre", "poor fiber"]): fibre="low"
    elif any(x in n for x in ["high fibre", "high fiber", "good fibre", "good fiber"]): fibre="high"
    elif any(x in n for x in ["average fibre", "average fiber", "normal fibre", "normal fiber"]): fibre="average"
    m=re.search(r"\b(\d+(?:\.\d+)?)\s*(?:litres?|liters?|l)\b", n)
    if m: water=m.group(0)
    return water,fibre


def extract_medications(text):
    n=normalize(text)
    if any(x in n for x in ["no medicines","no medication","not taking medicines","not taking medication","no regular medicines","no regular medication"]): return "none"
    if any(x in n for x in ["taking medicine","taking medication","taking medicines","taking supplements","regular medication","regular medicines","on medication","on medicines"]): return "reported"
    return None


def extract_bool(text, positives, negatives):
    n=normalize(text)
    if any(x in n for x in negatives): return False
    if any(x in n for x in positives): return True
    return None


def _stool_form(text):
    n=normalize(text)
    if "bristol" in n:
        m=re.search(r"bristol(?:\s+stool)?(?:\s+type|\s+scale)?\s*([1-7])\b", n)
        if m: return int(m.group(1))
    m=re.search(r"\bstool\s+(?:type|form)\s*([1-7])\b", n)
    if m: return int(m.group(1))
    if any(x in n for x in ["hard", "pellet", "lumpy"]): return 2
    if any(x in n for x in ["watery", "liquid"]): return 7
    if any(x in n for x in ["loose", "mushy"]): return 6
    return None


def merge_state(previous, text, red_flags=None):
    """Merge a user message without changing the original symptom branch."""
    primary, secondary = extract_symptoms(text)
    existing_secondary=list(previous.secondary_symptoms or [])
    for s in secondary + ([primary] if primary else []):
        if s and s != previous.primary_symptom and s not in existing_secondary: existing_secondary.append(s)
    inferred_blood = previous.blood_present
    n_text = normalize(text)
    if (primary == "bleeding" or "bleeding" in secondary or "blood" in n_text) and not any(x in n_text for x in ["no blood","no bleeding","without blood"]):
        inferred_blood = True
    updates = {
        "primary_symptom": previous.primary_symptom or primary,
        "secondary_symptoms": existing_secondary,
        "frequency": extract_frequency(text) or previous.frequency,
        "food_related": extract_food_related(text) if extract_food_related(text) is not None else previous.food_related,
        "food_trigger": extract_food_trigger(text) or previous.food_trigger,
        "severity": extract_severity(text) or previous.severity,
        "duration": extract_duration(text) or previous.duration,
        "age": extract_age(text) if extract_age(text) is not None else previous.age,
        "bowel_frequency_per_week": extract_bowel_frequency(text) if extract_bowel_frequency(text) is not None else previous.bowel_frequency_per_week,
        "bowel_frequency_per_day": extract_bowel_frequency_per_day(text) if extract_bowel_frequency_per_day(text) is not None else previous.bowel_frequency_per_day,
        "stool_form": _stool_form(text) or previous.stool_form,
        "straining": extract_bool(text,["strain","straining","push hard","pushing hard"],["no strain","without straining"]) if extract_bool(text,["strain","straining","push hard","pushing hard"],["no strain","without straining"]) is not None else previous.straining,
        "incomplete_evacuation": extract_bool(text,["incomplete evacuation","not completely empty","not fully empty","still feel like i need to go"],["complete evacuation","completely empty"]) if extract_bool(text,["incomplete evacuation","not completely empty","not fully empty","still feel like i need to go"],["complete evacuation","completely empty"]) is not None else previous.incomplete_evacuation,
        "abdominal_pain": extract_bool(text,["abdominal pain","stomach pain","belly pain","stomach ache","abdominal ache","cramps","cramping"],["no abdominal pain","no stomach pain","no cramps"]) if extract_bool(text,["abdominal pain","stomach pain","belly pain","stomach ache","abdominal ache","cramps","cramping"],["no abdominal pain","no stomach pain","no cramps"]) is not None else previous.abdominal_pain,
        "pain_related_to_bowel_movement": extract_bool(text,["pain improves after stool","pain improves after bowel movement","pain relieved after stool","pain relieved after bowel movement","pain related to bowel movement","pain when i need to poop","pain changes after bowel movement","pain associated with stool","better after bowel movement","worse after bowel movement"],["pain not related to stool","not related to bowel movement"]) if extract_bool(text,["pain improves after stool","pain improves after bowel movement","pain relieved after stool","pain relieved after bowel movement","pain related to bowel movement","pain when i need to poop","pain changes after bowel movement","pain associated with stool","better after bowel movement","worse after bowel movement"],["pain not related to stool","not related to bowel movement"]) is not None else previous.pain_related_to_bowel_movement,
        "blood_present": inferred_blood if inferred_blood is not None else extract_bool(text,["blood in stool","blood after stool","blood on toilet paper","fresh blood","rectal bleeding","bleeding from anus","blood while passing stool"],["no blood","no bleeding","without blood"]) if extract_bool(text,["blood in stool","blood after stool","blood on toilet paper","fresh blood","rectal bleeding","bleeding from anus","blood while passing stool"],["no blood","no bleeding","without blood"]) is not None else previous.blood_present,
        "anal_pain": extract_bool(text,["anal pain","pain around anus","pain near anus","pain during stool","sharp pain during stool"],["no anal pain"]) if extract_bool(text,["anal pain","pain around anus","pain near anus","pain during stool","sharp pain during stool"],["no anal pain"]) is not None else previous.anal_pain,
        "sharp_pain_during_stool": extract_bool(text,["sharp pain during stool","sharp tearing pain during stool","sharp pain while passing stool","cutting pain during stool","tearing pain during stool"],["no sharp pain"]) if extract_bool(text,["sharp pain during stool","sharp tearing pain during stool","sharp pain while passing stool","cutting pain during stool","tearing pain during stool"],["no sharp pain"]) is not None else previous.sharp_pain_during_stool,
        "lump_or_prolapse": extract_bool(text,["lump near anus","lump at anus","lump comes out","prolapse","something comes out of anus"],["no lump","no prolapse"]) if extract_bool(text,["lump near anus","lump at anus","lump comes out","prolapse","something comes out of anus"],["no lump","no prolapse"]) is not None else previous.lump_or_prolapse,
        "bloating": extract_bool(text,["bloating","bloated","bloat"],["no bloating","not bloated"]) if extract_bool(text,["bloating","bloated","bloat"],["no bloating","not bloated"]) is not None else previous.bloating,
        "diarrhea": extract_bool(text,["diarrhea","diarrhoea","loose motion","loose stool","watery stool"],["no diarrhea","no diarrhoea","no loose motion"]) if extract_bool(text,["diarrhea","diarrhoea","loose motion","loose stool","watery stool"],["no diarrhea","no diarrhoea","no loose motion"]) is not None else previous.diarrhea,
        "mucus": extract_bool(text,["mucus in stool","mucus in my stool"],["no mucus"]) if extract_bool(text,["mucus in stool","mucus in my stool"],["no mucus"]) is not None else previous.mucus,
        "fever": extract_bool(text,["fever","high temperature"],["no fever"]) if extract_bool(text,["fever","high temperature"],["no fever"]) is not None else previous.fever,
        "vomiting": extract_bool(text,["vomiting","vomit","throwing up"],["no vomiting","not vomiting"]) if extract_bool(text,["vomiting","vomit","throwing up"],["no vomiting","not vomiting"]) is not None else previous.vomiting,
        "abdominal_distension": extract_bool(text,["severe abdominal swelling","severe abdominal distension","abdomen is very swollen"],["no abdominal swelling"]) if extract_bool(text,["severe abdominal swelling","severe abdominal distension","abdomen is very swollen"],["no abdominal swelling"]) is not None else previous.abdominal_distension,
        "night_time_symptoms": extract_bool(text,["wakes me at night","waking at night","symptoms wake me","at night while sleeping"],["not at night"]) if extract_bool(text,["wakes me at night","waking at night","symptoms wake me","at night while sleeping"],["not at night"]) is not None else previous.night_time_symptoms,
        "weight_loss": extract_bool(text,["unexplained weight loss","losing weight without trying","weight loss without trying"],["no weight loss","not losing weight"]) if extract_bool(text,["unexplained weight loss","losing weight without trying","weight loss without trying"],["no weight loss","not losing weight"]) is not None else previous.weight_loss,
        "dehydration": extract_bool(text,["dehydrated","dehydration","very thirsty","dry mouth and not urinating"],["not dehydrated"]) if extract_bool(text,["dehydrated","dehydration","very thirsty","dry mouth and not urinating"],["not dehydrated"]) is not None else previous.dehydration,
        "unable_to_pass_stool_and_gas": extract_bool(text,["cannot pass stool or gas","can't pass stool or gas","unable to pass stool and gas","can't pass gas or stool"],["can pass gas","can pass stool"]) if extract_bool(text,["cannot pass stool or gas","can't pass stool or gas","unable to pass stool and gas","can't pass gas or stool"],["can pass gas","can pass stool"]) is not None else previous.unable_to_pass_stool_and_gas,
        "family_history_gi": extract_bool(text,["family history of colon cancer","family history of colorectal cancer","family history of ibd","family history of crohn","family history of ulcerative colitis","family history of gi cancer"],["no family history"]) if extract_bool(text,["family history of colon cancer","family history of colorectal cancer","family history of ibd","family history of crohn","family history of ulcerative colitis","family history of gi cancer"],["no family history"]) is not None else previous.family_history_gi,
        "recent_infection": extract_bool(text,["recent stomach infection","recent gut infection","recent food poisoning","recent gastroenteritis","after an infection","food poisoning"],["no recent infection"]) if extract_bool(text,["recent stomach infection","recent gut infection","recent food poisoning","recent gastroenteritis","after an infection","food poisoning"],["no recent infection"]) is not None else previous.recent_infection,
        "water_intake": (extract_lifestyle(text)[0] or previous.water_intake),
        "fibre_intake": (extract_lifestyle(text)[1] or previous.fibre_intake),
        "medications": extract_medications(text) or previous.medications,
        "blood_colour": previous.blood_colour,
        "blood_location": previous.blood_location,
        "blood_mixed_with_stool": previous.blood_mixed_with_stool,
        "pain_location": previous.pain_location,
        "red_flags": list(dict.fromkeys((previous.red_flags or []) + (red_flags or []))),
        "asked_fields": list(previous.asked_fields or []),
    }
    n=normalize(text)
    if any(x in n for x in ["black stool","black tarry stool","tarry stool"]): updates["blood_colour"]="black"
    elif any(x in n for x in ["bright red","fresh blood","red blood"]): updates["blood_colour"]="bright_red"
    if any(x in n for x in ["on toilet paper","on tissue"]): updates["blood_location"]="tissue"
    elif "dripping" in n: updates["blood_location"]="dripping"
    elif "mixed into stool" in n or "mixed with stool" in n: updates["blood_location"]="mixed"
    if "upper abdomen" in n: updates["pain_location"]="upper abdomen"
    elif "lower abdomen" in n: updates["pain_location"]="lower abdomen"
    elif "right side" in n: updates["pain_location"]="right side"
    elif "left side" in n: updates["pain_location"]="left side"
    elif "around the navel" in n or "navel" in n: updates["pain_location"]="around navel"
    return SymptomState(**updates)
