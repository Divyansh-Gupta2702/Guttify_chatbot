"""Deterministic clinical-pattern screening for GutGPT.

This module does not invent diagnoses. It selects the most supported
preliminary pattern from the structured answers, records the evidence, and
separates that assessment from product eligibility.
"""
import re


def _duration_days(duration):
    if not duration or duration == "unknown":
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(day|days|week|weeks|month|months|year|years)", duration.lower())
    if not m:
        return None
    n = float(m.group(1))
    u = m.group(2)
    return n * (1 if u.startswith("day") else 7 if u.startswith("week") else 30 if u.startswith("month") else 365)


def _result(pattern, confidence, evidence, differentials, action, product_allowed, message):
    return {
        "pattern": pattern,
        "likely_condition": pattern,
        "confidence": confidence,
        "evidence": evidence,
        "differentials": differentials,
        "action": action,
        "product_allowed": product_allowed,
        "message": message,
    }


def evaluate(s):
    if s.red_flags:
        return _result(
            "Red-flag presentation", "high", s.red_flags, [],
            "urgent_medical_evaluation", False,
            "This symptom combination needs prompt medical evaluation rather than only self-treatment."
        )

    if s.blood_colour == "black":
        return _result(
            "Possible gastrointestinal bleeding", "high", ["black/tarry stool"],
            ["upper gastrointestinal bleeding", "other gastrointestinal bleeding"],
            "urgent_medical_evaluation", False,
            "Black or tarry stool can indicate gastrointestinal bleeding and needs prompt medical evaluation."
        )

    if s.blood_present:
        if s.blood_colour is None or s.sharp_pain_during_stool is None:
            return _result(
                "Rectal bleeding — pattern not yet distinguishable", "low",
                ["rectal bleeding reported"],
                ["anal fissure", "hemorrhoids", "other causes of rectal bleeding"],
                "clarify_bleeding", False,
                "The bleeding needs a few distinguishing details before I can identify the most likely pattern."
            )
        if s.blood_colour == "bright_red" and s.sharp_pain_during_stool:
            return _result(
                "Possible anal fissure pattern", "moderate",
                ["bright-red blood", "sharp/tearing pain during or after stool"],
                ["hemorrhoids", "other causes of rectal bleeding"],
                "medical_review", True,
                "Your responses show a pattern that can be seen with an anal fissure. A suitable Guttify topical product may provide supportive care, but persistent, recurrent, heavy, or worsening bleeding should be medically assessed."
            )
        if s.blood_colour == "bright_red" and s.sharp_pain_during_stool is False and s.lump_or_prolapse is True:
            return _result(
                "Possible hemorrhoid pattern", "moderate",
                ["bright-red blood", "lump/prolapse", "no sharp tearing pain"],
                ["anal fissure", "other causes of rectal bleeding"],
                "medical_review", True,
                "Your responses show a pattern that can be seen with hemorrhoids. A suitable Guttify hemorrhoid-support product may be relevant, but persistent or recurrent rectal bleeding should be medically assessed rather than assumed to be hemorrhoids."
            )
        return _result(
            "Rectal bleeding of unclear cause", "low", ["rectal bleeding"],
            ["hemorrhoids", "anal fissure", "other gastrointestinal causes"],
            "medical_review", False,
            "The bleeding pattern is not specific enough to attribute it to one cause. Medical assessment is appropriate."
        )

    primary = s.primary_symptom
    symptoms = {primary, *(s.secondary_symptoms or [])}
    days = _duration_days(s.duration)
    chronic = days is not None and days >= 90

    constipation = (
        primary in ("constipation", "hard stools")
        or "constipation" in symptoms
        or (s.bowel_frequency_per_week is not None and s.bowel_frequency_per_week < 3)
        or s.stool_form in (1, 2)
    )
    diarrhea = (
        primary == "diarrhea"
        or "diarrhea" in symptoms
        or s.diarrhea is True
        or (s.bowel_frequency_per_day is not None and s.bowel_frequency_per_day >= 3)
    )

    # IBS-style patterns require recurrent abdominal pain plus a bowel-related
    # change and a persistent time course. Warning features are excluded.
    no_warning_features = not any([
        s.weight_loss is True,
        s.fever is True,
        s.family_history_gi is True,
        s.night_time_symptoms is True,
    ])
    if s.abdominal_pain and s.pain_related_to_bowel_movement and chronic and no_warning_features:
        if constipation and not diarrhea:
            return _result(
                "IBS-C pattern", "moderate",
                ["recurrent abdominal pain", "pain related to bowel movements", "constipation-predominant bowel pattern", f"symptoms for {s.duration}"],
                ["functional constipation", "medication-associated constipation"],
                "clinical_review", True,
                "Your responses show a pattern that can be seen with IBS-C. This is a preliminary pattern assessment; a clinician can determine whether IBS-C is actually present."
            )
        if diarrhea and not constipation:
            return _result(
                "IBS-D pattern", "moderate",
                ["recurrent abdominal pain", "pain related to bowel movements", "diarrhea-predominant bowel pattern", f"symptoms for {s.duration}"],
                ["infection-related diarrhea", "food-triggered diarrhea", "medication-associated diarrhea"],
                "clinical_review", False,
                "Your responses show a pattern that can be seen with IBS-D. This is a preliminary pattern assessment; a clinician can determine whether IBS-D is actually present."
            )
        if constipation and diarrhea:
            return _result(
                "IBS-M (mixed) pattern", "moderate",
                ["recurrent abdominal pain", "pain related to bowel movements", "both constipation and diarrhea patterns", f"symptoms for {s.duration}"],
                ["functional bowel disorder", "food-triggered symptoms"],
                "clinical_review", False,
                "Your responses show a pattern that can be seen with mixed-type IBS. This is a preliminary pattern assessment; a clinician can determine whether IBS-M is actually present."
            )

    if constipation:
        evidence = []
        if s.bowel_frequency_per_week is not None and s.bowel_frequency_per_week < 3:
            evidence.append("fewer than 3 bowel movements per week")
        if s.stool_form in (1, 2):
            evidence.append("hard/lumpy stool pattern")
        if s.straining:
            evidence.append("straining to pass stool")
        if s.incomplete_evacuation:
            evidence.append("feeling of incomplete evacuation")
        if s.fibre_intake == "low":
            evidence.append("low reported fibre intake")
        if s.water_intake:
            evidence.append(f"reported water intake: {s.water_intake}")

        if s.medications == "reported":
            return _result(
                "Possible medication-associated constipation pattern", "moderate",
                evidence + ["regular medicines/supplements reported"],
                ["functional constipation", "IBS-C"],
                "review_medications", True,
                "Your responses fit constipation, and medication or supplement use could be contributing. Do not stop a prescribed medicine without discussing it with a clinician or pharmacist."
            )

        if not evidence:
            evidence = ["constipation symptoms reported"]
        return _result(
            "Functional constipation pattern", "high" if len(evidence) >= 3 else "moderate",
            evidence,
            ["IBS-C", "medication-associated constipation"],
            "lifestyle_support", True,
            "Your responses fit a functional constipation pattern. The next step is to work on bowel regularity, fibre/fluid intake and activity while monitoring the response."
        )

    if diarrhea:
        if s.recent_infection:
            return _result(
                "Recent-infection or food-related diarrhea pattern", "moderate",
                ["loose/watery stools", "recent infection or food-poisoning association"],
                ["IBS-D", "medication-associated diarrhea"],
                "hydration_and_monitoring", False,
                "Your responses fit a recent-infection or food-related diarrhea pattern. Focus on hydration and monitor the course; persistent or worsening symptoms need assessment."
            )
        return _result(
            "Diarrhea pattern", "moderate", ["loose/watery stools"],
            ["food-related illness", "IBS-D", "medication-associated diarrhea"],
            "hydration_and_monitoring", False,
            "Your responses fit a diarrhea pattern. The information does not yet distinguish a specific cause such as IBS, infection, or medication effect."
        )

    if primary in ("acidity", "heartburn"):
        evidence = ["heartburn/acidity symptoms"]
        if s.food_related: evidence.append("associated with food/meals")
        if s.night_time_symptoms: evidence.append("worse at night/lying down")
        if s.food_trigger: evidence.append(f"associated with {s.food_trigger}")
        return _result(
            "Reflux/GERD-like symptom pattern", "high" if len(evidence) >= 2 else "moderate",
            evidence, ["dyspepsia", "gastritis-like symptoms"],
            "lifestyle_support", True,
            "Your symptoms fit a reflux/GERD-like pattern. This is a symptom-pattern assessment rather than a confirmed diagnosis."
        )

    if primary == "indigestion":
        return _result(
            "Dyspepsia/indigestion pattern", "moderate",
            ["upper-digestive discomfort/fullness/indigestion"],
            ["reflux/GERD-like symptoms", "food-related indigestion"],
            "lifestyle_support", True,
            "Your responses fit a dyspepsia/indigestion pattern."
        )

    if primary in ("bloating", "gas"):
        if s.food_trigger:
            return _result(
                "Food-triggered gas/bloating pattern", "moderate",
                ["gas/bloating", f"repeated association with {s.food_trigger}"],
                ["lactose intolerance", "other food intolerance", "functional bloating"],
                "food_trigger_management", True,
                "Your answers fit a food-triggered gas/bloating pattern. The repeated food association is more informative than the symptom alone."
            )
        if constipation:
            return _result(
                "Constipation-associated bloating pattern", "moderate",
                ["bloating/gas", "constipation features"],
                ["functional bloating", "food-triggered symptoms"],
                "lifestyle_support", True,
                "Your answers fit bloating associated with constipation."
            )
        return _result(
            "Functional gas/bloating pattern", "moderate", ["recurrent gas/bloating"],
            ["food intolerance", "functional bowel disorder"],
            "lifestyle_support", True,
            "Your answers fit a functional gas/bloating pattern; food triggers and bowel habits are the main things to monitor."
        )

    if primary == "food intolerance":
        if s.food_trigger:
            return _result(
                "Possible food-triggered intolerance pattern", "moderate",
                [f"repeated symptoms associated with {s.food_trigger}"],
                ["lactose intolerance", "other food sensitivity", "functional bowel symptoms"],
                "food_trigger_management", True,
                "Your answers show a repeated food-associated symptom pattern. This does not by itself prove a specific intolerance; the trigger and response should be tracked."
            )
        return _result(
            "Possible food-triggered symptom pattern", "low", ["food-associated symptoms"],
            ["food intolerance", "food-triggered functional symptoms"],
            "food_trigger_management", True,
            "Your symptoms appear food-associated, but the specific trigger is not clear yet."
        )

    if primary == "stomach pain":
        if s.food_related and s.pain_location == "upper abdomen":
            return _result(
                "Upper-abdominal meal-related dyspepsia pattern", "moderate",
                ["upper-abdominal pain/discomfort", "meal association"],
                ["reflux/GERD-like symptoms", "gastritis-like symptoms"],
                "lifestyle_support", True,
                "Your answers fit an upper-abdominal, meal-related dyspepsia pattern."
            )
        if s.pain_related_to_bowel_movement and (constipation or diarrhea):
            return _result(
                "Bowel-related abdominal pain pattern", "moderate",
                ["abdominal pain related to bowel movements", "associated bowel-habit change"],
                ["IBS", "functional constipation/diarrhea"],
                "clinical_review", False,
                "Your symptoms show a bowel-related abdominal pain pattern. IBS is one possibility, but this chat alone does not establish that diagnosis."
            )
        return _result(
            "Nonspecific abdominal pain pattern", "moderate", ["abdominal pain reported"],
            ["dyspepsia", "reflux", "functional bowel disorder", "other gastrointestinal causes"],
            "clinical_review", False,
            "Your symptoms fit a nonspecific abdominal-pain pattern. The location, severity and associated symptoms determine what should be considered next."
        )

    return _result(
        "Insufficiently characterized gut symptom pattern", "low",
        [primary or "gut symptoms reported"],
        ["constipation", "diarrhea", "reflux", "functional bowel symptoms"],
        "targeted_questions", False,
        "I need one targeted detail about the symptom pattern before making a useful preliminary assessment."
    )
