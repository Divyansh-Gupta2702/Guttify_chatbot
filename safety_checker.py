"""Universal red-flag and product-safety gate for GutGPT.

Safety detection intentionally runs on every user turn, including after a
completed assessment. The goal is to catch natural variations rather than
only the exact wording used by the questionnaire.
"""
import re

RED_FLAG_PATTERNS = [
    ("vomiting blood", [
        "vomiting blood", "throwing up blood", "threw up blood", "vomited blood",
        "vomit blood", "blood in my vomit", "blood in vomit", "blood when vomiting",
        "blood while vomiting", "hematemesis",
    ]),
    ("black/tarry stool", [
        "black stool", "black tarry stool", "black and tarry stool", "tarry stool",
        "black poop", "black poo", "black bowel movement", "stool is black",
        "stool is black and tarry", "my stool is black", "my stool is black and tarry",
        "poop is black", "poop is black and tarry", "tarry poop",
    ]),
    ("severe abdominal pain", [
        "severe abdominal pain", "excruciating stomach pain", "unbearable stomach pain",
        "severe stomach pain", "excruciating abdominal pain", "unbearable abdominal pain",
        "worst stomach pain", "worst abdominal pain",
    ]),
    ("persistent vomiting", [
        "persistent vomiting", "vomiting repeatedly", "can't stop vomiting",
        "cant stop vomiting", "cannot stop vomiting", "vomiting continuously",
        "vomiting nonstop", "vomiting non stop", "keep vomiting", "keeps vomiting",
    ]),
    ("severe abdominal distension", [
        "severe abdominal swelling", "severe abdominal distension", "abdomen severely swollen",
        "abdomen is very swollen", "stomach is severely swollen",
    ]),
    ("fainting or loss of consciousness", [
        "fainted", "fainting", "passed out", "pass out", "loss of consciousness",
        "lost consciousness", "blackout", "blacked out",
    ]),
    ("dehydration", [
        "severe dehydration", "dehydrated and unable to keep fluids",
        "not urinating and very thirsty", "unable to keep fluids down and not urinating",
    ]),
    ("unexplained significant weight loss", [
        "unexplained weight loss", "losing weight without trying", "weight loss without trying",
        "significant weight loss", "lost a lot of weight without trying",
    ]),
    ("persistent fever", ["persistent fever", "fever for days", "high fever for days"]),
    ("difficulty swallowing", ["difficulty swallowing", "trouble swallowing", "painful swallowing"]),
    ("unable to pass stool and gas", [
        "cannot pass stool or gas", "can't pass stool or gas", "unable to pass stool and gas",
        "can't pass gas or stool", "cannot pass gas or stool", "unable to pass gas or stool",
    ]),
    ("chest pain", [
        "chest pain", "pain in my chest", "pain in the chest", "pressure in my chest",
        "chest pressure", "tightness in my chest", "chest tightness",
    ]),
]

NEGATION_CUES = {
    "no", "not", "never", "without", "dont", "don't", "doesnt", "doesn't",
    "haven't", "have", "hadn't", "had", "isnt", "isn't", "aren't", "are not",
}
CLAUSE_BREAKS = {"and", "but", "however", "although", "while", "yet"}


def _negative(text, phrase):
    """Return True only when negation clearly applies to this phrase.

    Negation is deliberately local. A generic seven-word window can wrongly
    interpret "no appetite and vomiting blood" as negated vomiting blood.
    """
    n = re.sub(r"\s+", " ", (text or "").lower()).strip()
    phrase = phrase.lower().strip()
    if not n or not phrase:
        return False

    # Direct constructions: "no blood in my stool", "don't have black stool".
    direct_patterns = [
        rf"\b(?:no|not|never|without)\s+(?:any\s+)?{re.escape(phrase)}\b",
        rf"\b(?:do not|dont|don't|does not|doesnt|doesn't)\s+(?:have|has|experience|experiencing|notice|noticing|see|seeing)\s+(?:any\s+)?{re.escape(phrase)}\b",
        rf"\b(?:i am not|im not)\s+(?:having|experiencing)\s+(?:any\s+)?{re.escape(phrase)}\b",
        rf"\b(?:there is no|there's no|there is not|there's not)\s+(?:any\s+)?{re.escape(phrase)}\b",
        rf"\b(?:there are no|there aren't|there are not)\s+(?:any\s+)?{re.escape(phrase)}\b",
    ]
    if any(re.search(pattern, n) for pattern in direct_patterns):
        return True

    words = n.split()
    phrase_words = phrase.split()
    for i in range(len(words) - len(phrase_words) + 1):
        if words[i:i + len(phrase_words)] != phrase_words:
            continue
        before = words[max(0, i - 5):i]
        # Stop at conjunctions so "no appetite and vomiting blood" is not
        # interpreted as "no vomiting blood".
        if any(w in CLAUSE_BREAKS for w in before):
            before = before[before.index(next(w for w in before if w in CLAUSE_BREAKS)) + 1:]
        window = before[-4:]
        joined = " ".join(window)
        if re.search(r"\b(?:no|not|never|without)\b", joined):
            return True
        if re.search(r"\b(?:don't|dont|doesn't|doesnt|haven't|hadn't)\s+(?:have|has|had)?\b", joined):
            return True
    return False


def _concept_present(text, phrases):
    return any(p in text and not _negative(text, p) for p in phrases)


def detect_red_flags(text):
    n = re.sub(r"\s+", " ", (text or "").lower()).strip()
    found = []
    for label, phrases in RED_FLAG_PATTERNS:
        if _concept_present(n, phrases):
            found.append(label)

    bleeding = _concept_present(n, [
        "blood in stool", "blood in my stool", "blood in the stool",
        "blood while passing stool", "blood after stool", "blood after bowel movement",
        "blood on toilet paper", "fresh blood", "rectal bleeding", "bleeding from anus",
        "bleeding while pooping", "bleeding when pooping", "bleeding when i poop",
        "blood when i poop", "blood when pooping", "pooping blood", "pooping with blood",
        "blood in my poop", "blood in poop", "blood in my poo", "blood in poo",
    ])
    dizziness = _concept_present(n, [
        "dizzy", "dizziness", "lightheaded", "light headed", "faint", "fainted",
        "fainting", "passed out", "pass out",
    ])
    if bleeding and dizziness:
        found.append("fainting/dizziness with bleeding")

    return list(dict.fromkeys(found))


def is_pregnancy_or_lactation(text):
    n = (text or "").lower()
    return any(x in n for x in [
        "pregnant", "pregnancy", "breastfeeding", "breast feeding", "lactating", "lactation",
    ])


def derive_red_flags(state):
    """Promote structured questionnaire answers into the same safety gate."""
    flags = list(state.red_flags or [])
    if state.vomiting is True or getattr(state, "persistent_vomiting", False) is True:
        flags.append("persistent vomiting")
    if getattr(state, "vomiting_blood", False) is True:
        flags.append("vomiting blood")
    if getattr(state, "difficulty_swallowing", False) is True:
        flags.append("difficulty swallowing")
    if state.abdominal_distension is True:
        flags.append("severe abdominal distension")
    if state.weight_loss is True:
        flags.append("unexplained significant weight loss")
    if getattr(state, "blood_colour", None) == "black":
        flags.append("black/tarry stool")
    if getattr(state, "blood_present", None) is True and getattr(state, "recent_worsening", None) is True:
        # Worsening bleeding is intentionally surfaced to the safety layer;
        # the existing safety policy decides the final action.
        flags.append("worsening bleeding")
    if state.dehydration is True:
        flags.append("dehydration")
    if state.unable_to_pass_stool_and_gas is True:
        flags.append("unable to pass stool and gas")
    return list(dict.fromkeys(flags))


def check_safety(user_query):
    flags = detect_red_flags(user_query)
    if flags:
        return {
            "safe_to_recommend": False,
            "requires_doctor": True,
            "red_flag": True,
            "reasons": flags,
            "message": "This needs medical evaluation rather than only self-treatment. I won't recommend a Guttify product for these symptoms.",
        }

    if is_pregnancy_or_lactation(user_query):
        return {
            "safe_to_recommend": False,
            "requires_doctor": False,
            "red_flag": False,
            "reasons": ["pregnancy/lactation product caution"],
            "message": "Because pregnancy or breastfeeding was mentioned, I won't recommend a Guttify product without appropriate professional guidance.",
        }

    return {"safe_to_recommend": True, "requires_doctor": False, "red_flag": False, "reasons": [], "message": ""}
