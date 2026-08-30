"""
Guttify Safety Checker
----------------------
Conservative prototype safety layer based on caution information in the
Guttify Product Guide. This is NOT a medical diagnosis or a complete
medical triage system.
"""

# Each rule: (keywords that trigger it, the reason shown to the user)
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


def check_safety(user_query):
    """
    Check the user's message for safety conditions that should prevent an
    automatic Guttify product recommendation.

    Returns:
        {
            "safe_to_recommend": bool,
            "requires_doctor": bool,
            "reasons": [str, ...],
            "message": str,
        }
    """
    query = user_query.lower().strip()

    reasons = [reason for keywords, reason in SAFETY_RULES if any(k in query for k in keywords)]

    if any(k in query for k in PILES_KEYWORDS) and any(k in query for k in PILES_WARNING_KEYWORDS):
        reasons.append(PILES_REASON)

    if not reasons:
        return {"safe_to_recommend": True, "requires_doctor": False, "reasons": [], "message": ""}

    return {
        "safe_to_recommend": False,
        "requires_doctor": True,
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
    else:
        print("SAFETY STATUS: MEDICAL REVIEW RECOMMENDED")
        print("\nReason(s):")
        for reason in result["reasons"]:
            print(f"- {reason}")
        print("\n" + result["message"])
    print("-" * 60)
