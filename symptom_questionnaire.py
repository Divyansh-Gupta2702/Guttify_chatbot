"""Adaptive, one-question-at-a-time clinical screening for GutGPT.

The questionnaire remains deterministic. A branch is selected from the
explicitly detected primary and secondary symptoms; completed fields are
reused, and compound legacy question IDs are expanded into their existing
component prompts by the contextual resolver.
"""
import logging

from clinical_rule_engine import _duration_days
from question_schema import question_has_answer, question_has_progressed

logger = logging.getLogger("gutgpt.questionnaire")


def next_question(state):
    asked = set(state.asked_fields or [])
    unknown_fields = set(getattr(state, "answered_unknown_fields", []) or [])
    refused_fields = set(getattr(state, "refused_fields", []) or [])

    def q(name, text, condition=True):
        # The chart is bound to the stool-form question ID, not to a diagnosis
        # or wording match. The marker is preserved through API/widget render.
        if name == "stool_form":
            text = (
                "[[BRISTOL_STOOL_CHART]]\n"
                "**How to identify your type:**\n"
                "1 — Hard separate pellets; difficult to pass.\n"
                "2 — Lumpy, sausage-shaped stool.\n"
                "3 — Sausage-shaped with cracks on the surface.\n"
                "4 — Smooth, soft sausage or snake shape (generally considered ideal).\n"
                "5 — Soft blobs that pass easily.\n"
                "6 — Mushy stool with ragged edges.\n"
                "7 — Entirely liquid, with no solid pieces.\n\n"
                f"{text} Please reply with a number from **1 to 7**, or say **I don't know**."
            )
        has_answer = question_has_progressed(state, name)
        if condition and name not in unknown_fields and name not in refused_fields and (name not in asked or not has_answer):
            return name, text
        return None

    # Preserve the established global gates. A valid profile age is reconciled
    # into state during registration/restore; this gate asks only when absent.
    if state.duration == "unknown":
        return q("duration", "How long have you been experiencing your symptoms?", True)

    if (state.weight_loss is None and not state.weight_loss_duration_asked
            and state.duration != "unknown"):
        days = _duration_days(state.duration)
        if days is not None and days >= 30:
            return q("weight_loss_duration", "Have you lost any significant weight?", True)

    if state.age is None:
        return q("age", "What is your age?", True)

    # Build a stable branch queue. Bleeding remains first whenever positively
    # established, then all other explicitly reported symptoms are assessed.
    branch_aliases = {
        "constipation": "constipation", "hard stools": "constipation",
        "diarrhea": "diarrhea", "diarrhoea": "diarrhea", "loose motions": "diarrhea", "loose stools": "diarrhea",
        "acidity": "acidity", "heartburn": "acidity", "acid reflux": "acidity",
        "bloating": "gas_bloating", "abdominal bloating": "gas_bloating", "gas": "gas_bloating", "flatulence": "gas_bloating",
        "stomach pain": "stomach pain", "abdominal pain": "stomach pain",
        "indigestion": "indigestion", "food intolerance": "food intolerance",
        "nausea": "nausea", "fatigue": "fatigue", "sluggishness": "fatigue",
        "anal burning": "anal burning", "anal pain": "anal burning", "anal discomfort": "anal burning", "piles": "piles",
        "fissure": "anal fissures", "anal fissure": "anal fissures", "anal fissures": "anal fissures",
        "bleeding": "bleeding", "blood in stool": "bleeding",
    }
    reported = []
    reported_labels = {
        str(symptom or "").strip().casefold()
        for symptom in [state.primary_symptom, *(state.secondary_symptoms or [])]
        if str(symptom or "").strip()
    }
    constipation_reported = bool(reported_labels & {"constipation", "hard stools"}) or state.constipation_explicit is True
    diarrhea_reported = bool(reported_labels & {"diarrhea", "diarrhoea", "loose motions"}) or state.diarrhea_explicit is True or state.diarrhea is True
    gas_reported = "gas" in reported_labels or state.gas is True
    bloating_reported = "bloating" in reported_labels or state.bloating is True
    if state.blood_present is True:
        reported.append("bleeding")
    for symptom in [state.primary_symptom, *(state.secondary_symptoms or [])]:
        label = str(symptom or "").strip().casefold()
        branch_name = branch_aliases.get(label)
        if branch_name and branch_name not in reported:
            reported.append(branch_name)
    if not reported:
        reported.append("general")

    def branch_questions(branch):
        if branch == "bleeding":
            return [
                q("blood", "Have you noticed any blood in or around your stool?", state.blood_present is None),
                q("blood_colour", "Is the blood bright/fresh red, or dark/black/tarry?", state.blood_present is True and not question_has_answer(state, "blood_colour")),
                q("blood_location", "If it is bright red, where do you notice it?", state.blood_present is True and state.blood_colour == "bright_red" and not question_has_answer(state, "blood_location")),
                q("anal_discomfort_screen", "Do you have anal pain or discomfort?", state.anal_pain is None),
                q("sharp_pain_during_stool", "Do you have sharp or tearing pain during or just after a bowel movement?", state.anal_pain is not False and state.sharp_pain_during_stool is None),
                q("lump", "Is there a lump or something protruding from the anus?", state.lump_or_prolapse is None),
                q("straining", "Do you need to strain to pass stool?", state.straining is None),
            ]
        if branch == "constipation":
            return [
                q("bowel_frequency", "How many bowel movements do you usually have per week?", state.bowel_frequency_per_week is None),
                q("stool_form", "What Bristol Stool Scale type best matches your stool?", not question_has_answer(state, "stool_form")),
                q("straining", "Do you need to strain to pass stool?", state.straining is None),
                q("incomplete_evacuation", "After passing stool, do you often feel that your bowel has not completely emptied?", state.incomplete_evacuation is None),
                q("bloating_screen", "Do you experience abdominal bloating?", state.bloating is None),
                q("abdominal_pain_screen", "Do you experience abdominal pain or cramps?", state.abdominal_pain is None),
                q("food_relation", "Is your abdominal pain related to meals or eating?", state.abdominal_pain is True and state.food_related is None),
                q("pain_bowel_relation", "Does the pain change after a bowel movement?", state.abdominal_pain is True and state.pain_related_to_bowel_movement is None),
                q("blood", "Have you noticed any blood in or around the stool?", state.blood_present is None),
                q("anal_discomfort_screen", "Do you have anal pain or discomfort?", state.anal_pain is None),
                q("sharp_pain_during_stool", "Do you have severe or sharp pain during or just after a bowel movement?", state.anal_pain is not False and state.sharp_pain_during_stool is None),
                q("vomiting", "Have you had repeated vomiting?", state.vomiting is None),
                q("fever", "Have you had a fever?", state.fever is None),
                q("abdominal_distension", "Do you have severe abdominal swelling?", state.abdominal_distension is None),
                q("water", "Roughly how much water do you drink each day?", state.water_intake is None),
                q("fibre", "Would you describe your fibre/fruit/vegetable intake as low, average, or high?", state.fibre_intake is None),
                q("medications", "Do you regularly take any medicines or supplements?", state.medications is None),
            ]
        if branch == "diarrhea":
            return [
                q("daily_frequency", "How many loose or watery stools are you having per day?", state.bowel_frequency_per_day is None),
                q("stool_form", "What Bristol Stool Scale type best matches your stool, if you know it?", not question_has_answer(state, "stool_form")),
                q("abdominal_pain_screen", "Do you have abdominal pain or cramps?", state.abdominal_pain is None),
                q("pain_bowel_relation", "Does the pain change after a bowel movement?", state.abdominal_pain is True and state.pain_related_to_bowel_movement is None),
                q("infection", "Did this begin after food poisoning, a stomach infection, travel, or antibiotics?", state.recent_infection is None),
                q("blood", "Have you noticed blood in your stool?", state.blood_present is None),
                q("mucus", "Have you noticed mucus in your stool?", state.mucus is None),
                q("night_time_symptoms", "Do your symptoms wake you at night?", state.night_time_symptoms is None),
                q("weight_loss", "Have you had unexplained weight loss?", state.weight_loss is None),
                q("fever", "Have you had a fever?", state.fever is None),
                q("medications", "Did you start or change any medicine or supplement around the time this began?", state.medications is None),
            ]
        if branch == "acidity":
            return [
                q("reflux", "Do you get a sour taste or acid/food coming back up?", state.reflux_present is None),
                q("timing", "When do you notice the acidity most often?", state.timing_relation is None),
                q("triggers", "Do particular foods or drinks trigger it?", state.food_trigger is None and state.food_related is not False),
                q("difficulty_swallowing", "Do you have difficulty or pain when swallowing?", state.difficulty_swallowing is None),
                q("persistent_vomiting", "Have you had persistent or repeated vomiting?", state.persistent_vomiting is None),
                q("vomiting_blood", "Have you vomited blood?", state.vomiting_blood is None),
            ]
        if branch == "gas_bloating":
            return [
                q("gas_screen", "Do you also experience excessive gas or flatulence?", state.gas is None and not gas_reported),
                q("bloating_screen", "Do you also experience abdominal bloating or a swollen feeling?", state.bloating is None and not bloating_reported),
                q("constipation_screen", "Do you also experience constipation?", state.constipation_explicit is None and not constipation_reported and not diarrhea_reported),
                q("diarrhea_screen", "Do you also experience loose motions or diarrhea?", state.diarrhea_explicit is None and not diarrhea_reported and not constipation_reported),
                q("food_trigger", "Is the symptom repeatedly linked to a particular food?", state.food_trigger is None and state.food_related is not False),
                q("abdominal_pain_screen", "Do you have recurring abdominal pain?", state.abdominal_pain is None),
                q("pain_bowel_relation", "Does the pain change after a bowel movement?", state.abdominal_pain is True and state.pain_related_to_bowel_movement is None),
            ]
        if branch == "stomach pain":
            return [
                q("pain_location", "Where exactly is the pain located?", state.pain_location is None),
                q("severity", "How severe is the pain from 0–10?", state.severity == "unknown"),
                q("food_relation", "Is the pain related to meals or eating?", state.food_related is None),
                q("pain_bowel_relation", "Does the pain change after a bowel movement?", state.abdominal_pain is True and state.pain_related_to_bowel_movement is None),
                q("constipation_screen", "Are you also experiencing constipation?", state.constipation_explicit is None and not constipation_reported and not diarrhea_reported),
                q("diarrhea_screen", "Are you also experiencing loose motions or diarrhea?", state.diarrhea_explicit is None and not diarrhea_reported and not constipation_reported),
                q("blood", "Have you noticed any blood in your stool?", state.blood_present is None),
                q("vomiting", "Have you had vomiting?", state.vomiting is None),
                q("fever", "Have you had a fever?", state.fever is None),
            ]
        if branch == "indigestion":
            return [
                q("upper_symptoms", "What is the main upper-abdominal symptom you notice?", state.upper_symptoms is None),
                q("food_relation", "Is it triggered or worsened by meals?", state.food_related is None),
                q("reflux", "Do you experience heartburn or acid/food coming back up?", state.reflux_present is None),
                q("weight_loss", "Have you had unexplained weight loss?", state.weight_loss is None),
                q("difficulty_swallowing", "Do you have difficulty or pain when swallowing?", state.difficulty_swallowing is None),
                q("persistent_vomiting", "Have you had persistent or repeated vomiting?", state.persistent_vomiting is None),
                q("vomiting_blood", "Have you vomited blood?", state.vomiting_blood is None),
            ]
        if branch == "nausea":
            return [
                q("vomiting", "Have you also been vomiting?", state.vomiting is None),
                q("abdominal_pain_screen", "Do you also have abdominal pain or cramps?", state.abdominal_pain is None),
                q("fever", "Have you had a fever?", state.fever is None),
                q("blood", "Have you noticed any blood in your stool or vomit?", state.blood_present is None),
                q("weight_loss", "Have you had unexplained weight loss?", state.weight_loss is None),
            ]
        if branch == "fatigue":
            return [
                q("upper_symptoms", "What digestive symptoms are you experiencing along with the fatigue?", state.upper_symptoms is None),
                q("weight_loss", "Have you had unexplained weight loss?", state.weight_loss is None),
                q("fever", "Have you had a fever?", state.fever is None),
                q("blood", "Have you noticed any blood in your stool?", state.blood_present is None),
            ]
        if branch == "food intolerance":
            return [
                q("food_trigger", "Which food seems to trigger your symptoms?", state.food_trigger is None),
                q("food_relation", "Do the symptoms reliably occur after eating that food?", state.food_related is None),
                q("timing", "How soon after eating does it start?", state.timing_relation is None),
                q("bloating_screen", "Do you experience abdominal bloating after eating that food?", state.bloating is None),
                q("gas_screen", "Do you experience excessive gas after eating that food?", state.gas is None),
                q("diarrhea_screen", "Do you experience loose motions or diarrhea after eating that food?", state.diarrhea_explicit is None and state.diarrhea is None and not diarrhea_reported and not constipation_reported),
                q("constipation_screen", "Do you experience constipation after eating that food?", state.constipation_explicit is None and not constipation_reported and not diarrhea_reported),
                q("abdominal_pain_screen", "Do you experience abdominal pain or cramps after eating that food?", state.abdominal_pain is None),
                q("pain_bowel_relation", "Does the pain change after a bowel movement?", state.abdominal_pain is True and state.pain_related_to_bowel_movement is None),
            ]
        if branch == "anal burning":
            return [
                q("blood", "Have you noticed any bleeding or blood around/after a bowel movement?", state.blood_present is None),
                q("anal_discomfort_screen", "Do you have anal pain or discomfort?", state.anal_pain is None),
                q("sharp_pain_during_stool", "Is there sharp or tearing pain during or just after a bowel movement?", state.anal_pain is not False and state.sharp_pain_during_stool is None),
                q("lump", "Is there a lump or something protruding from the anus?", state.lump_or_prolapse is None),
                q("straining", "Do you need to strain to pass stool?", state.straining is None),
            ]
        if branch in ("piles", "anal fissures"):
            return [
                q("blood", "Have you noticed any bleeding or blood around/after a bowel movement?", state.blood_present is None),
                q("blood_colour", "Is the blood bright/fresh red, or dark/black/tarry?", state.blood_present is True and not question_has_answer(state, "blood_colour")),
                q("blood_location", "If it is bright red, where do you notice it?", state.blood_present is True and state.blood_colour == "bright_red" and not question_has_answer(state, "blood_location")),
                q("anal_discomfort_screen", "Do you have anal pain or discomfort?", state.anal_pain is None),
                q("sharp_pain_during_stool", "Is there sharp or tearing pain during or just after a bowel movement?", state.anal_pain is not False and state.sharp_pain_during_stool is None),
                q("lump", "Is there a lump or something protruding from the anus?", state.lump_or_prolapse is None),
                q("straining", "Do you need to strain to pass stool?", state.straining is None),
            ]
        return [
            q("constipation_screen", "Are you experiencing constipation?", state.constipation_explicit is None),
            q("diarrhea_screen", "Are you experiencing loose motions or diarrhea?", state.diarrhea_explicit is None),
            q("abdominal_pain_screen", "Do you have abdominal pain?", state.abdominal_pain is None),
            q("pain_bowel_relation", "Does the pain change after a bowel movement?", state.abdominal_pain is True and state.pain_related_to_bowel_movement is None),
        ]

    for branch in reported:
        questions = branch_questions(branch)
        for item in questions:
            if item:
                if branch == "bleeding":
                    logger.info("[QUESTION][BLEEDING] selected_next=%s", item[0])
                return item
    logger.info("[QUESTION][COMPLETE] branches=%s", reported)
    return None
