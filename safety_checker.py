"""Universal red-flag and product-safety gate for GutGPT."""
import re

RED_FLAG_PATTERNS = [
    ("vomiting blood", ["vomiting blood", "throwing up blood", "hematemesis"]),
    ("black/tarry stool", ["black stool", "black tarry stool", "tarry stool", "black poop", "stool is black", "stool is black and tarry", "black and tarry stool"]),
    ("severe abdominal pain", ["severe abdominal pain", "excruciating stomach pain", "unbearable stomach pain", "severe stomach pain"]),
    ("persistent vomiting", ["persistent vomiting", "vomiting repeatedly", "can't stop vomiting", "cant stop vomiting", "vomiting continuously"]),
    ("severe abdominal distension", ["severe abdominal swelling", "severe abdominal distension", "abdomen severely swollen"]),
    ("fainting or loss of consciousness", ["fainted", "fainting", "passed out", "loss of consciousness", "lost consciousness"]),
    ("fainting/dizziness with bleeding", ["dizzy with bleeding", "dizziness with bleeding", "passed out with bleeding", "fainting with bleeding"]),
    ("dehydration", ["severe dehydration", "dehydrated and unable to keep fluids", "not urinating and very thirsty"]),
    ("unexplained significant weight loss", ["unexplained weight loss", "losing weight without trying", "weight loss without trying"]),
    ("persistent fever", ["persistent fever", "fever for days"]),
    ("difficulty swallowing", ["difficulty swallowing", "trouble swallowing", "painful swallowing"]),
    ("unable to pass stool and gas", ["cannot pass stool or gas", "can't pass stool or gas", "unable to pass stool and gas", "can't pass gas or stool"]),
]


def _negative(text, phrase):
    """Detect common natural-language negation immediately before a phrase."""
    n = (text or "").lower()
    phrase = phrase.lower()
    # Keep this local and conservative: we only suppress a flag when a
    # negation clearly refers to the same phrase.
    patterns = [
        rf"\b(?:no|not|never|without)\s+(?:any\s+)?{re.escape(phrase)}\b",
        rf"\b(?:do not|dont|don't|does not|doesnt|doesn't)\s+(?:have|has)\s+(?:any\s+)?{re.escape(phrase)}\b",
        rf"\b(?:i am not|im not)\s+{re.escape(phrase)}\b",
    ]
    return any(re.search(p, n) for p in patterns)


def detect_red_flags(text):
    n = (text or "").lower()
    found = []
    for label, phrases in RED_FLAG_PATTERNS:
        if any(p in n and not _negative(n, p) for p in phrases):
            found.append(label)

    # Some warnings are combinations rather than fixed phrases. Detect the
    # concepts independently so wording/order does not matter.
    bleeding = any(p in n and not _negative(n, p) for p in [
        "blood in stool", "blood in my stool", "blood in the stool",
        "blood while passing stool", "blood after stool", "blood after bowel movement",
        "blood on toilet paper", "fresh blood", "rectal bleeding", "bleeding from anus",
        "bleeding while pooping", "blood when i poop", "blood when pooping"
    ])
    dizziness = any(p in n and not _negative(n, p) for p in ["dizzy", "dizziness", "lightheaded", "light headed", "faint", "fainted", "fainting", "passed out"])
    if bleeding and dizziness:
        found.append("fainting/dizziness with bleeding")

    return list(dict.fromkeys(found))


def derive_red_flags(state):
    """Promote structured questionnaire answers into the same safety gate
    used for free-text messages. Only fields whose questionnaire wording
    represents a meaningful warning sign are promoted."""
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

    # Pregnancy/lactation is a product-safety caution, not a disease red flag.
    n = (user_query or "").lower()
    if any(x in n for x in ["pregnant", "pregnancy", "breastfeeding", "breast feeding", "lactating"]):
        return {
            "safe_to_recommend": False,
            "requires_doctor": False,
            "red_flag": False,
            "reasons": ["pregnancy/lactation product caution"],
            "message": "Because pregnancy or breastfeeding was mentioned, I won't recommend a Guttify product without appropriate professional guidance.",
        }

    return {"safe_to_recommend": True, "requires_doctor": False, "red_flag": False, "reasons": [], "message": ""}
