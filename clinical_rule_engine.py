"""Deterministic gut-health clinical pattern engine.

This module does the actual structured reasoning.  The LLM is only used to
explain the already-selected assessment in natural language.
"""
import re


def _duration_days(duration):
    if not duration or duration == "unknown":
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(day|days|week|weeks|month|months|year|years)", duration.lower())
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2)
    if unit.startswith("day"):
        return n
    if unit.startswith("week"):
        return n * 7
    if unit.startswith("month"):
        return n * 30
    return n * 365


def _result(pattern, confidence, evidence, differentials, action, product_allowed, message=None):
    return {
        "pattern": pattern,
        "likely_condition": pattern,
        "confidence": confidence,
        "evidence": evidence,
        "differentials": differentials,
        "action": action,
        "product_allowed": product_allowed,
        "message": message or "",
    }


def evaluate(state):
    """Return the most supported *likely pattern* from the structured state.

    It intentionally does not claim a confirmed diagnosis. Confirmed medical
    diagnoses may require examination, testing, or exclusion of alternatives.
    """
    # 1. Safety always wins.
    if state.red_flags:
        return _result(
            "Red-flag presentation", "high", state.red_flags, [],
            "urgent_medical_evaluation", False,
            "This needs medical evaluation rather than only self-treatment."
        )
    if state.blood_colour == "black":
        return _result(
            "Possible gastrointestinal bleeding", "high",
            ["black/tarry stool"], ["upper gastrointestinal bleeding"],
            "urgent_medical_evaluation", False,
            "Black or tarry stool needs prompt medical evaluation rather than a supplement recommendation."
        )

    # Rectal bleeding is deliberately never converted directly into piles.
    if state.blood_present:
        if state.blood_colour is None or state.blood_location is None or state.sharp_pain_during_stool is None:
            return _result(
                "Rectal bleeding requiring clarification", "insufficient",
                ["rectal bleeding reported"], ["hemorrhoids", "anal fissure", "other gastrointestinal causes"],
                "clarify_bleeding", False,
                "Because you reported rectal bleeding, I need a few details before identifying the most likely pattern."
            )
        if state.sharp_pain_during_stool and state.blood_colour == "bright_red":
            return _result(
                "Possible anal fissure pattern", "moderate",
                ["bright-red bleeding", "sharp pain during bowel movement"],
                ["hemorrhoids", "other causes of rectal bleeding"],
                "medical_review", False,
                "Your responses fit a pattern that can be seen with an anal fissure. Persistent or significant bleeding should be medically assessed."
            )
        if state.blood_colour == "bright_red" and state.lump_or_prolapse and not state.sharp_pain_during_stool:
            return _result(
                "Possible hemorrhoid pattern", "moderate",
                ["bright-red bleeding", "lump or prolapse", "no sharp pain during stool"],
                ["anal fissure", "other causes of rectal bleeding"],
                "medical_review", False,
                "Your responses fit a pattern that can be seen with hemorrhoids. Rectal bleeding should be evaluated if it persists, worsens, or is significant."
            )
        return _result(
            "Rectal bleeding of unclear cause", "low",
            ["rectal bleeding reported"],
            ["hemorrhoids", "anal fissure", "other gastrointestinal causes"],
            "medical_review", False,
            "The bleeding pattern is not specific enough to safely attribute it to piles or a fissure. Medical evaluation is appropriate."
        )

    primary = state.primary_symptom
    symptom_set = set([primary] + list(state.secondary_symptoms or []))
    has_constipation = "constipation" in symptom_set
    has_diarrhea = "diarrhea" in symptom_set
    days = _duration_days(state.duration)

    # 2. IBS requires a symptom pattern, not simply constipation/diarrhea.
    ibs_features = []
    if state.abdominal_pain:
        ibs_features.append("recurrent abdominal pain")
    if state.pain_related_to_bowel_movement:
        ibs_features.append("pain related to bowel movements")
    if state.bowel_frequency_per_week is not None:
        ibs_features.append("change in bowel frequency")
    if state.stool_form is not None:
        ibs_features.append("change in stool form")
    if state.bloating:
        ibs_features.append("bloating")
    if state.mucus:
        ibs_features.append("mucus in stool")

    ibs_duration_support = days is not None and days >= 180
    ibs_current_frequency_support = days is not None and days >= 90
    ibs_red_flags_absent = not any([
        state.blood_present, state.weight_loss, state.fever,
        state.night_time_symptoms, state.family_history_gi
    ])

    if has_constipation:
        if (state.abdominal_pain and state.pain_related_to_bowel_movement and
                state.bowel_frequency_per_week is not None and state.bowel_frequency_per_week < 3 and
                ibs_current_frequency_support and ibs_duration_support and ibs_red_flags_absent):
            return _result(
                "IBS-C pattern", "moderate",
                ibs_features + ["constipation-predominant bowel pattern"],
                ["functional constipation", "medication-associated constipation"],
                "medical_review", False,
                "Your responses show a pattern that can be seen with IBS-C. A clinician can determine whether IBS is actually present and whether testing is needed."
            )
        if state.medications:
            return _result(
                "Medication-associated constipation pattern", "moderate",
                ["constipation", "regular medicines or supplements reported"],
                ["functional constipation", "IBS-C"],
                "review_medications", False,
                "Your responses may fit a medication-associated constipation pattern. Do not stop prescribed medicine on your own; discuss it with your clinician or pharmacist."
            )
        evidence = ["infrequent and/or difficult bowel movements"]
        if state.stool_form in (1, 2): evidence.append("hard/lumpy stool pattern")
        if state.straining: evidence.append("straining")
        if state.incomplete_evacuation: evidence.append("incomplete evacuation")
        if state.fibre_intake and any(x in state.fibre_intake.lower() for x in ["low", "poor", "little"]): evidence.append("low fibre intake")
        return _result(
            "Functional constipation pattern", "moderate",
            evidence,
            ["IBS-C", "medication-associated constipation"],
            "lifestyle_support", True,
            "Your responses show a pattern consistent with functional constipation."
        )

    if has_diarrhea:
        if state.recent_infection:
            return _result(
                "Recent-infection or food-related diarrhea pattern", "moderate",
                ["loose stools", "recent infection/food-poisoning association"],
                ["IBS-D", "medication-associated diarrhea"],
                "hydration_and_medical_review_if_persistent", False,
                "Your responses may fit a recent-infection or food-related diarrhea pattern. Hydration is important, and persistent or severe symptoms should be assessed."
            )
        if (state.abdominal_pain and state.pain_related_to_bowel_movement and
                ibs_current_frequency_support and ibs_duration_support and ibs_red_flags_absent):
            return _result(
                "IBS-D pattern", "moderate",
                ibs_features + ["diarrhea-predominant bowel pattern"],
                ["infection-related diarrhea", "food-triggered diarrhea", "medication-associated diarrhea"],
                "medical_review", False,
                "Your responses show a pattern that can be seen with IBS-D. A clinician can determine whether IBS is actually present."
            )
        return _result(
            "Acute or nonspecific diarrhea pattern", "moderate",
            ["loose/watery stools"],
            ["infection-related diarrhea", "food-related illness", "IBS-D", "medication-associated diarrhea"],
            "hydration_and_monitoring", False,
            "Your responses show a diarrhea pattern, but there is not enough information to identify a specific cause safely."
        )

    if primary in ("acidity", "heartburn"):
        evidence = []
        if state.food_related: evidence.append("symptoms associated with meals/food")
        if state.night_time_symptoms: evidence.append("worse at night or when lying down")
        if state.primary_symptom == "heartburn": evidence.append("heartburn/burning sensation")
        if state.primary_symptom == "acidity": evidence.append("acid-reflux/acidity symptoms")
        return _result(
            "Reflux/GERD-like symptom pattern", "moderate" if len(evidence) >= 2 else "low",
            evidence or ["heartburn/acidity symptoms"],
            ["gastritis-like symptoms", "dyspepsia"],
            "lifestyle_support", True,
            "Your responses show a reflux/GERD-like symptom pattern. This is a symptom-based assessment, not a confirmed diagnosis."
        )

    if primary == "indigestion":
        return _result(
            "Dyspepsia/indigestion pattern", "moderate",
            ["indigestion or upper-abdominal digestive discomfort"],
            ["reflux/GERD-like symptoms", "food-related indigestion"],
            "lifestyle_support", True,
            "Your responses fit an indigestion/dyspepsia-type symptom pattern."
        )

    if primary in ("bloating", "gas"):
        if state.food_trigger in ("dairy", "wheat_gluten", "legumes"):
            label = {
                "dairy": "Possible food-triggered bloating/gas pattern (dairy-associated)",
                "wheat_gluten": "Possible food-triggered bloating/gas pattern (wheat-associated)",
                "legumes": "Possible food-triggered bloating/gas pattern (legume-associated)",
            }[state.food_trigger]
            return _result(
                label, "moderate",
                [f"symptoms associated with {state.food_trigger.replace('_', ' ')}"],
                ["food intolerance", "IBS", "constipation-related bloating"],
                "dietary_review", False,
                "Your responses show a recurring food-associated pattern. That does not by itself establish a food-intolerance diagnosis."
            )
        return _result(
            "Functional/diet-related gas or bloating pattern", "low",
            ["gas/bloating reported"],
            ["constipation", "IBS", "food-triggered symptoms"],
            "dietary_review", True,
            "Your responses fit a common functional/diet-related gas or bloating pattern."
        )

    if primary == "food intolerance":
        return _result(
            "Possible food-intolerance pattern", "low",
            ["food intolerance/sensitivity reported"],
            ["IBS", "food-triggered functional symptoms"],
            "dietary_review", False,
            "Your responses suggest a possible food-associated pattern, but a specific intolerance cannot be confirmed from chat alone."
        )

    if primary == "stomach pain":
        if state.abdominal_pain and state.food_related:
            return _result(
                "Food-associated abdominal pain pattern", "low",
                ["abdominal pain", "food association"],
                ["indigestion", "reflux/GERD-like symptoms", "IBS"],
                "medical_review", False,
                "Your abdominal-pain pattern needs more clinical context before a specific cause can be identified."
            )
        return _result(
            "Nonspecific abdominal-pain pattern", "low",
            ["abdominal pain reported"],
            ["indigestion", "IBS", "reflux", "other causes"],
            "medical_review", False,
            "Abdominal pain has several possible causes, so I would not attribute it to a specific condition from these responses alone."
        )

    if primary in ("piles", "anal fissures"):
        return _result(
            "Anorectal symptom pattern requiring examination", "low",
            [primary],
            ["hemorrhoids", "anal fissure", "other anorectal causes"],
            "medical_review", False,
            "These symptoms are better assessed with an appropriate medical examination rather than assuming the cause from chat alone."
        )

    return _result(
        "Insufficient information for a specific pattern", "insufficient", [], [],
        "ask_more", False,
        "I need a little more information before I can identify the most likely pattern."
    )
