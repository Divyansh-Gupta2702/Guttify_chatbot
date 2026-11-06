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
        "black poop", "black poo", "black bowel movement", "stool is black", "stools are black",
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
        "signs of dehydration", "symptoms of dehydration", "very little urine",
        "not urinating", "unable to urinate", "dry mouth and dizziness",
    ]),
    ("high fever", [
        "high fever", "very high fever", "fever above 102", "fever over 102",
        "fever of 102", "fever above 39", "fever over 39", "fever of 39",
    ]),
    ("severe weakness", [
        "severe weakness", "extreme weakness", "too weak to stand",
        "so weak i can't stand", "so weak i cannot stand",
    ]),
    ("persistent/worsening diarrhea", [
        "persistent diarrhea", "persistent diarrhoea", "chronic diarrhea",
        "chronic diarrhoea", "worsening diarrhea", "worsening diarrhoea",
        "persistent or worsening diarrhea", "persistent or worsening diarrhoea",
        "diarrhea is persistent or worsening", "diarrhoea is persistent or worsening",
        "diarrhea getting worse", "diarrhoea getting worse",
        "diarrhea is getting worse", "diarrhoea is getting worse",
        "diarrhea that is getting worse", "diarrhoea that is getting worse",
        "diarrhea for more than 2 days", "diarrhoea for more than 2 days",
        "diarrhea for over 2 days", "diarrhoea for over 2 days",
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
    ("significant rectal bleeding", [
        "heavy rectal bleeding", "significant rectal bleeding", "large amount of blood in stool",
        "large amount of blood in my stool", "a lot of blood in stool", "a lot of blood in my stool",
        "blood pouring out when passing stool", "blood pouring out when i poop",
    ]),
]

NEGATION_CUES = {
    "no", "not", "never", "without", "dont", "don't", "doesnt", "doesn't",
    "haven't", "have", "hadn't", "had", "isnt", "isn't", "aren't", "are not",
}
CLAUSE_BREAKS = {"and", "but", "however", "although", "while", "yet"}


def _negative(text, phrase):
    """Return True only when negation applies within the same clause.

    Punctuation and contrast/conjunction boundaries prevent a preceding
    negative from suppressing a separate symptom ("no fever, chest pain").
    """
    n = re.sub(r"\s+", " ", (text or "").lower()).strip()
    phrase = phrase.lower().strip()
    if not n or not phrase:
        return False

    direct_patterns = [
        rf"\b(?:no|not|never|without)\s+(?:any\s+)?{re.escape(phrase)}\b",
        rf"\b(?:do not|dont|don't|does not|doesnt|doesn't)\s+(?:have|has|experience|experiencing|notice|noticing|see|seeing)\s+(?:any\s+)?{re.escape(phrase)}\b",
        rf"\b(?:i am not|im not)\s+(?:having|experiencing)\s+(?:any\s+)?{re.escape(phrase)}\b",
        rf"\b(?:there is no|there's no|there is not|there's not)\s+(?:any\s+)?{re.escape(phrase)}\b",
        rf"\b(?:there are no|there aren't|there are not)\s+(?:any\s+)?{re.escape(phrase)}\b",
    ]
    if any(re.search(pattern, n) for pattern in direct_patterns):
        return True

    # Split at punctuation and clause-level conjunctions before applying the
    # local negation window. A comma or full stop is a hard boundary.
    clauses = re.split(r"[,.!?;:]+|\b(?:and|but|however|although|while|yet)\b", n)
    phrase_words = phrase.split()
    for clause in clauses:
        words = clause.split()
        for i in range(len(words) - len(phrase_words) + 1):
            if words[i:i + len(phrase_words)] != phrase_words:
                continue
            before = words[max(0, i - 5):i]
            joined = " ".join(before[-4:])
            if re.search(r"\b(?:no|not|never|without)\b", joined):
                return True
            if re.search(r"\b(?:don't|dont|doesn't|doesnt|haven't|havent|hadn't|hadnt)(?:\s+(?:have|has|had))?\b", joined):
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
        "bloody stool", "bloody stools", "blood in stool", "blood in my stool", "blood in the stool",
        "blood while passing stool", "blood after stool", "blood after bowel movement",
        "blood on toilet paper", "fresh blood", "rectal bleeding", "bleeding from anus",
        "bleeding while pooping", "bleeding when pooping", "bleeding when i poop",
        "blood when i poop", "blood when pooping", "pooping blood", "pooping with blood",
        "blood in my poop", "blood in poop", "blood in my poo", "blood in poo",
    ])
    diarrhea = _concept_present(n, [
        "diarrhea", "diarrhoea", "loose stool", "loose stools", "loose motion",
        "loose motions", "watery stool", "watery stools", "watery bowel movements",
    ])
    if bleeding and diarrhea:
        found.append("blood in stool with diarrhea")
    dizziness = _concept_present(n, [
        "dizzy", "dizziness", "lightheaded", "light headed", "faint", "fainted",
        "fainting", "passed out", "pass out",
    ])
    if bleeding and dizziness:
        found.append("fainting/dizziness with bleeding")

    return list(dict.fromkeys(found))


def is_pregnancy_or_lactation(text):
    """Detect an affirmative self-disclosure, not negations or third parties."""
    n = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not n:
        return False
    status = re.compile(r"\b(?:pregnant|pregnancy|breastfeeding|breast\s+feeding|lactating|lactation)\b", re.I)
    # Evaluate each mention in its own clause. A negative pregnancy correction
    # or a relative's status must not mask the user's separate disclosure.
    clauses = re.split(
        r"[,;.!?]+|\b(?:but|however|although|while|yet)\b|"
        r"\band\s+(?=(?:i|i'm|im|we|pregnant|pregnancy|breastfeeding|breast\s+feeding|lactating|lactation)\b)",
        n,
    )
    negative_before = re.compile(
        r"\b(?:not|isn't|isnt|aren't|arent|never|no longer|stopped|quit|finished|"
        r"don't|dont|doesn't|doesnt|haven't|havent|hasn't|hasnt|hadn't|hadnt)\b"
        r"(?:\s+\w+){0,4}\s*$", re.I
    )
    third_party_before = re.compile(
        r"\b(?:my\s+(?:wife|partner|girlfriend|sister|mother|friend)|she|her)"
        r"(?:\s+\w+){0,5}\s*$", re.I
    )
    for clause in clauses:
        for match in status.finditer(clause):
            preceding = clause[:match.start()]
            if negative_before.search(preceding) or third_party_before.search(preceding):
                continue
            return True
    return False


def pregnancy_lactation_evidence(text):
    """Return only the validated disclosure term, never the full user turn."""
    if not is_pregnancy_or_lactation(text):
        return None
    match = re.search(r"\b(?:pregnant|pregnancy|breastfeeding|breast\s+feeding|lactating|lactation)\b", text or "", re.I)
    return match.group(0) if match else None


def red_flag_evidence(text, reason):
    """Return a short matched phrase that deterministically supports a flag."""
    n = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if reason == "fainting/dizziness with bleeding":
        parts = []
        for phrase in ("dizziness", "dizzy", "lightheaded", "fainting", "fainted", "passed out", "blood in stool", "rectal bleeding"):
            if phrase in n and not _negative(n, phrase):
                parts.append(phrase)
        return parts or None
    for label, phrases in RED_FLAG_PATTERNS:
        if label != reason:
            continue
        for phrase in phrases:
            if phrase in n and not _negative(n, phrase):
                return phrase
    for phrase in (
        "blood in stool", "blood in my stool", "blood in the stool", "rectal bleeding",
        "bleeding while pooping", "black stool", "black tarry stool", "fainted", "fainting",
        "dizzy", "dizziness", "lightheaded", "passed out",
    ):
        if phrase in n and not _negative(n, phrase):
            return phrase
    return None


def derive_red_flags(state):
    """Promote structured questionnaire answers into the same safety gate."""
    # Weight loss is still recorded and assessed as a clinical detail, but it
    # must not by itself trigger the urgent red-flag stop path. Filter the old
    # reason too, so a session carrying a previously derived flag can resume.
    flags = [
        flag for flag in (state.red_flags or [])
        if flag != "unexplained significant weight loss"
    ]
    if state.vomiting is True or getattr(state, "persistent_vomiting", False) is True:
        flags.append("persistent vomiting")
    if getattr(state, "vomiting_blood", False) is True:
        flags.append("vomiting blood")
    if getattr(state, "difficulty_swallowing", False) is True:
        flags.append("difficulty swallowing")
    if state.abdominal_distension is True:
        flags.append("severe abdominal distension")
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
