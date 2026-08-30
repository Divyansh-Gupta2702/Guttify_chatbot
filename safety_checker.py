"""
Guttify Safety Checker
----------------------
Conservative prototype safety layer. This is NOT a medical diagnosis or a
complete medical triage system.

Two tiers:

1. RED FLAGS — symptoms serious enough that no supplement should ever be
   recommended, regardless of anything else in the conversation. These
   short-circuit the entire recommendation flow and tell the user to seek
   appropriate medical care.

2. CAUTION RULES — situations (pregnancy, existing conditions, current
   medication, etc.) where a supplement might still be fine, but the user
   should check with a doctor first.
"""

# ---------------------------------------------------------------------
# Tier 1: red flags — never recommend, always advise seeking care.
# ---------------------------------------------------------------------
RED_FLAG_RULES = [
    (["vomiting blood", "throwing up blood", "coughing up blood"],
     "vomiting blood"),
    (["blood in stool", "blood in my stool", "bloody stool", "stools with blood"],
     "blood in stool"),
    (["black stool", "black tarry stool", "tarry stool", "black poop"],
     "black/tarry stool"),
    (["yellow skin", "yellow eyes", "jaundice", "yellowing of skin", "yellowing of eyes"],
     "yellow skin or eyes (possible jaundice)"),
    (["severe abdominal pain", "excruciating stomach pain", "unbearable stomach pain",
      "severe stomach pain", "severe pain in my stomach", "severe pain in my abdomen"],
     "severe abdominal pain"),
    (["persistent vomiting", "vomiting repeatedly", "can't stop vomiting", "cant stop vomiting",
      "vomiting for days", "vomiting continuously"],
     "persistent vomiting"),
    (["severe weakness", "extremely weak", "can barely stand", "collapsing"],
     "severe weakness"),
    (["confusion", "confused and disoriented", "feeling disoriented", "can't think straight"],
     "confusion"),
    (["fainting", "fainted", "passed out", "blacked out", "losing consciousness"],
     "fainting or loss of consciousness"),
    (["difficulty breathing", "trouble breathing", "can't breathe", "shortness of breath",
      "struggling to breathe"],
     "difficulty breathing"),
    (["unexplained weight loss", "losing weight without trying", "lost a lot of weight suddenly",
      "rapid weight loss"],
     "unexplained significant weight loss"),
    (["rapidly worsening", "getting much worse fast", "symptoms are worsening quickly"],
     "rapidly worsening symptoms"),
]

RED_FLAG_MESSAGE = (
    "What you're describing sounds like it could be serious. Please seek "
    "medical care promptly — contact a doctor, urgent care, or emergency "
    "services rather than relying on a supplement. I'm not able to "
    "recommend a Guttify product for this."
)

# ---------------------------------------------------------------------
# Tier 2: caution rules — a supplement may still be fine, check with a doctor.
# ---------------------------------------------------------------------
SAFETY_RULES = [
    (
        ["pregnant", "pregnancy", "expecting", "breastfeeding",
         "breast feeding", "lactating", "nursing baby", "nursing my baby"],
        "Guttify products are not recommended for pregnant or lactating women.",
    ),
    (
        ["liver disease", "liver disorder", "fatty liver", "hepatitis",
         "cirrhosis", "liver condition", "liver problem"],
        "The Guttify Product Guide states that people with an existing "
        "liver condition should consult a doctor before using Liver Lift.",
    ),
    (
        ["diabetes", "diabetic", "chronic condition", "chronic illness",
         "chronic disease", "medical condition", "existing medical condition"],
        "The Guttify Product Guide advises people with existing medical "
        "conditions to check with a doctor before using these supplements.",
    ),
    (
        ["prescription medication", "prescription medicine", "taking medication",
         "taking medicine", "on medication", "on medicines", "regular medication",
         "regular medicines", "medications", "medicine"],
        "The Guttify Product Guide advises people taking regular medication "
        "to consult a doctor before starting these supplements.",
    ),
]

PILES_KEYWORDS = ["piles", "hemorrhoid", "haemorrhoid"]
PILES_WARNING_KEYWORDS = [
    "bleeding", "blood", "worsening", "getting worse",
    "persistent", "not going away", "severe pain",
]
PILES_REASON = (
    "The Guttify Product Guide advises medical evaluation for persistent, "
    "worsening, or bleeding piles rather than relying on a supplement alone."
)


def detect_red_flags(user_query):
    """Return a list of human-readable red-flag descriptions found in text."""
    query = user_query.lower().strip()
    return [label for keywords, label in RED_FLAG_RULES if any(k in query for k in keywords)]


def check_safety(user_query):
    """
    Check the user's message for safety conditions.

    Returns:
        {
            "safe_to_recommend": bool,
            "requires_doctor": bool,
            "red_flag": bool,
            "reasons": [str, ...],
            "message": str,
        }
    """
    query = user_query.lower().strip()

    red_flags = detect_red_flags(user_query)
    if red_flags:
        return {
            "safe_to_recommend": False,
            "requires_doctor": True,
            "red_flag": True,
            "reasons": red_flags,
            "message": RED_FLAG_MESSAGE,
        }

    reasons = [reason for keywords, reason in SAFETY_RULES if any(k in query for k in keywords)]

    if any(k in query for k in PILES_KEYWORDS) and any(k in query for k in PILES_WARNING_KEYWORDS):
        reasons.append(PILES_REASON)

    if not reasons:
        return {
            "safe_to_recommend": True,
            "requires_doctor": False,
            "red_flag": False,
            "reasons": [],
            "message": "",
        }

    return {
        "safe_to_recommend": False,
        "requires_doctor": True,
        "red_flag": False,
        "reasons": reasons,
        "message": (
            "Based on the information you provided, I would recommend "
            "speaking with a healthcare professional before using a "
            "Guttify supplement."
        ),
    }


if __name__ == "__main__":
    print("=" * 60)
    print("          GUTTIFY SAFETY CHECKER TEST")
    print("=" * 60)

    result = check_safety(input("\nDescribe your symptoms or situation:\n> "))

    print("\n" + "-" * 60)
    if result["safe_to_recommend"]:
        print("SAFETY STATUS: SAFE TO CONTINUE")
    elif result["red_flag"]:
        print("SAFETY STATUS: RED FLAG — SEEK MEDICAL CARE")
        print("\nDetected:")
        for reason in result["reasons"]:
            print(f"- {reason}")
        print("\n" + result["message"])
    else:
        print("SAFETY STATUS: MEDICAL REVIEW RECOMMENDED")
        print("\nReason(s):")
        for reason in result["reasons"]:
            print(f"- {reason}")
        print("\n" + result["message"])
    print("-" * 60)
