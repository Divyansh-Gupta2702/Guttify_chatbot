"""Adaptive clinical screening questions for GutGPT.

Questions are branch-specific and answerable in normal language. The agent
records the exact field it asked, so replies like "5 months", "23", "no", or
"yes, hard stools" are never treated as unrelated messages.
"""
import logging

from clinical_rule_engine import _duration_days
from question_schema import question_has_answer, question_has_progressed

logger = logging.getLogger("gutgpt.questionnaire")


def next_question(state):
    asked = set(state.asked_fields or [])

    def q(name, text, condition=True):
        # Show the Bristol chart immediately before any Bristol stool-type
        # question. The widget replaces this marker with its embedded chart,
        # so the image works on Shopify without a separately hosted asset.
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
        # `asked_fields` is history, not evidence that a question was answered.
        # If a prior state merge or interrupted turn left a required field empty,
        # it must remain eligible to be asked. Explicitly accepted "unknown" is
        # a valid conversational outcome and is tracked separately.
        unknown_fields = set(getattr(state, "answered_unknown_fields", []) or [])
        has_answer = question_has_progressed(state, name)
        if condition and name not in unknown_fields and (name not in asked or not has_answer):
            return name, text
        if name in {"blood_colour", "blood_location", "anal_pain", "lump", "constipation"}:
            if not condition:
                logger.info("[QUESTION][BLEEDING][SKIP] field=%s reason=not_required", name)
            elif has_answer or name in unknown_fields:
                logger.info("[QUESTION][BLEEDING][SKIP] field=%s reason=answered", name)
        return None

    # Safety-critical bleeding owns the assessment whenever bleeding has been
    # positively established, regardless of which symptom was detected first.
    # Keep all other symptoms in state; this only changes question priority.
    if state.blood_present is True:
        logger.info(
            "[QUESTION][BRANCH] bleeding_present=true selected_branch=bleeding reason=bleeding_priority"
        )
        branch = "bleeding"
    else:
        branch = state.primary_symptom

    # If the user has supplied enough information up front, these are skipped.
    # First ask duration, then conditionally ask weight-loss if duration >= 1 month,
    # then ask age.
    if state.duration == "unknown":
        return q("duration", "How long has this been happening?", True)

    # Duration is known - check if we should ask the conditional weight-loss question
    if (state.weight_loss is None
            and not state.weight_loss_duration_asked
            and state.duration != "unknown"):
        days = _duration_days(state.duration)
        if days is not None and days >= 30:
            return q("weight_loss_duration", "Have you lost any significant weight?", True)

    # Age is a demographic gate, not a symptom discriminator. Keep it before
    # the branch questions so the existing clinical assessment gates remain
    # deterministic, but never allow it to replace the branch-specific
    # questionnaire below.
    if state.age is None:
        return q("age", "What is your age?", True)

    if branch == "bleeding":
        bleeding_qs = [
            q("blood_colour", "Is the blood bright/fresh red, or dark/black/tarry?", state.blood_colour is None),
            q(
                "blood_location",
                "If it is bright red, is it on tissue, dripping into the toilet, or mixed into the stool?",
                state.blood_colour == "bright_red" and state.blood_location is None,
            ),
            q("sharp_pain_during_stool", "Is there sharp or tearing pain during or just after a bowel movement?", state.sharp_pain_during_stool is None),
            q("lump", "Is there a lump or something protruding from the anus?", state.lump_or_prolapse is None),
            q("hard_stools", "Are you experiencing hard stools or lumpy stools?", state.stool_form is None and state.hard_stools is None),
            q("straining", "Do you need to strain to pass stool?", state.straining is None),
        ]
        missing_fields = []
        if state.blood_colour is None:
            missing_fields.append("blood_colour")
        elif state.blood_colour == "bright_red" and state.blood_location is None:
            missing_fields.append("blood_location")
        if state.sharp_pain_during_stool is None:
            missing_fields.append("anal_pain")
        if state.lump_or_prolapse is None:
            missing_fields.append("lump")
        if state.stool_form is None or state.straining is None:
            missing_fields.append("constipation")
        answered_fields = [
            f for f, value in (
                ("blood_colour", state.blood_colour),
                ("blood_location", state.blood_location),
                ("anal_pain", state.sharp_pain_during_stool),
                ("lump", state.lump_or_prolapse),
                ("constipation", state.stool_form if state.stool_form is not None else state.straining),
            ) if value is not None
        ]
        for item in bleeding_qs:
            if item:
                logger.info(
                    "[QUESTION][BLEEDING] answered_fields=%s missing_fields=%s next=%s",
                    answered_fields, missing_fields, item[0],
                )
                return item
        logger.info("[QUESTION][BLEEDING][COMPLETE]")
        return None

    if branch in ("constipation", "hard stools"):
        # If bleeding is reported during the constipation interview, switch
        # temporarily to the bleeding differentiator before making the
        # constipation assessment. This prevents every bleed from becoming
        # an automatic piles label.
        if state.blood_present:
            bleeding_qs = [
                q("blood_colour", "Is the blood bright/fresh red, or dark/black/tarry?", state.blood_colour is None),
                q("blood_location", "If it is bright red, is it on tissue, dripping into the toilet, or mixed into the stool?", state.blood_location is None),
                q("sharp_pain_during_stool", "Is there sharp or tearing pain during or just after a bowel movement?", state.sharp_pain_during_stool is None),
                q("lump", "Is there a lump or something protruding from the anus?", state.lump_or_prolapse is None),
            ]
            for item in bleeding_qs:
                if item:
                    return item

        # This mirrors the requested constipation assessment while allowing
        # the engine to stop early once a useful pattern is established.
        qs = [
            q("bowel_frequency", "How many bowel movements do you usually have per week?", state.bowel_frequency_per_week is None),
            q("hard_stools", "Are your stools hard or lumpy?", state.stool_form is None and state.hard_stools is None),
            q("straining", "Do you need to strain to pass stool?", state.straining is None),
            q("incomplete_evacuation", "Do you often feel that your bowel has not completely emptied after passing stool?", state.incomplete_evacuation is None),
            q("bloating", "Are you experiencing abdominal bloating?", state.bloating is None),
            q("abdominal_pain", "Are you experiencing recurring abdominal pain?", state.abdominal_pain is None),
            q("pain_bowel_relation", "If you have abdominal pain, does it change after you pass stool?", state.abdominal_pain is True and state.pain_related_to_bowel_movement is None),
            q("blood", "Have you noticed any blood in or around the stool?", state.blood_present is None),
            q("sharp_pain_during_stool", "Do you have severe or sharp anal pain during or just after a bowel movement?", state.sharp_pain_during_stool is None),
            q("vomiting", "Have you had repeated vomiting?", state.vomiting is None),
            q("fever", "Have you had a fever?", state.fever is None),
            q("abdominal_distension", "Have you had severe abdominal swelling?", state.abdominal_distension is None),
            q("water", "Roughly how much water do you drink each day?", state.water_intake is None),
            q("fibre", "Would you describe your fibre/fruit/vegetable intake as low, average, or high?", state.fibre_intake is None),
            q("medications", "Do you regularly take any medicines or supplements?", state.medications is None),
        ]
    elif branch == "diarrhea":
        qs = [
            q("daily_frequency", "How many loose or watery stools are you having per day?", state.bowel_frequency_per_day is None),
            q("stool_form", "If you know it, what Bristol Stool Scale type is it (1–7)?", not question_has_answer(state, "stool_form")),
            q("abdominal_pain", "Are you experiencing abdominal pain or cramps?", state.abdominal_pain is None),
            q("pain_bowel_relation", "If you have abdominal pain, does it change after passing stool?", state.abdominal_pain is True and state.pain_related_to_bowel_movement is None),
            q("infection", "Did this begin after food poisoning, a stomach infection, travel, or antibiotics?", state.recent_infection is None),
            q("blood", "Have you noticed any blood in your stool?", state.blood_present is None),
            q("mucus", "Have you noticed mucus in your stool?", state.mucus is None),
            q("night_time_symptoms", "Do your symptoms wake you at night?", state.night_time_symptoms is None),
            q("weight_loss", "Have you had unexplained weight loss?", state.weight_loss is None),
            q("fever", "Have you had a fever?", state.fever is None),
            q("medications", "Did you start or change any medicine or supplement around the time this began?", state.medications is None),
        ]
    elif branch in ("acidity", "heartburn"):
        qs = [
            q("reflux", "Do you get a sour taste or acid/food coming back up?", getattr(state, "reflux_present", None) is None),
            q("food_relation", "Is it worse after meals?", state.food_related is None),
            q("trigger_food", "Which food or drink seems to trigger it?", state.food_trigger is None and state.food_related is not False),
            q("food_relation", "Does it happen repeatedly after the same food or drink?", state.food_trigger is not None and state.food_related is None),
            q("difficulty_swallowing", "Do you have difficulty or pain swallowing?", state.difficulty_swallowing is None),
            q("persistent_vomiting", "Have you had persistent vomiting?", state.persistent_vomiting is None),
            q("vomiting_blood", "Have you vomited blood?", state.vomiting_blood is None),
        ]
    elif branch in ("bloating", "gas"):
        qs = [
            q("constipation_symptom", "Are you experiencing constipation?", state.constipation_explicit is None),
            q("diarrhea_symptom", "Are you experiencing diarrhea or loose motions?", state.diarrhea is None),
            q("trigger_food", "Which food seems to trigger it?", state.food_trigger is None and state.food_related is not False),
            q("food_relation", "Does it happen repeatedly after the same food?", state.food_trigger is not None and state.food_related is None),
            q("abdominal_pain", "Are you experiencing recurring abdominal pain?", state.abdominal_pain is None),
            q("pain_bowel_relation", "If you have pain, does it change with bowel movements?", state.abdominal_pain is True and state.pain_related_to_bowel_movement is None),
            q("stool_form", "What is your usual Bristol stool type, if you know it?", not question_has_answer(state, "stool_form")),
        ]
    elif branch == "stomach pain":
        qs = [
            q("pain_location", "Where exactly is the pain: upper abdomen, around the navel, lower abdomen, right side, or left side?", state.pain_location is None),
            q("severity", "How severe is it from 0–10?", state.severity == "unknown"),
            q("recent_worsening", "Has the pain been getting worse recently?", state.recent_worsening is None),
            q("food_relation", "Is the pain triggered or worsened by meals?", state.food_related is None),
            q("pain_bowel_relation", "Does the pain change after a bowel movement?", state.pain_related_to_bowel_movement is None),
            q("constipation_symptom", "Are you experiencing constipation?", state.constipation_explicit is None),
            q("diarrhea_symptom", "Are you experiencing diarrhea or loose motions?", state.diarrhea is None),
            q("mucus", "Have you noticed mucus in your stool?", state.mucus is None),
            q("blood", "Have you noticed blood in your stool?", state.blood_present is None),
            q("vomiting", "Have you had vomiting?", state.vomiting is None),
            q("fever", "Have you had a fever?", state.fever is None),
        ]
    elif branch == "indigestion":
        qs = [
            q("upper_symptoms", "What upper-abdominal symptom are you experiencing?", state.abdominal_pain is None),
            q("food_relation", "Is it triggered or worsened by meals?", state.food_related is None),
            q("reflux", "Any heartburn or acid/food coming back up?", state.secondary_symptoms is None or "heartburn" not in state.secondary_symptoms),
            q("weight_loss", "Have you had unexplained weight loss?", state.weight_loss is None),
            q("difficulty_swallowing", "Do you have difficulty or pain swallowing?", state.difficulty_swallowing is None),
            q("persistent_vomiting", "Have you had persistent vomiting?", state.persistent_vomiting is None),
            q("vomiting_blood", "Have you vomited blood?", state.vomiting_blood is None),
        ]
    elif branch == "food intolerance":
        qs = [
            q("trigger_food", "Which food seems to trigger it?", state.food_trigger is None and state.food_related is not False),
            q("food_relation", "Does it happen repeatedly after the same food?", state.food_trigger is not None and state.food_related is None),
            q("food_onset_timing", "How soon after eating does it start?", state.symptom_onset_after_food is None),
            q("food_symptom", "What symptom do you notice after eating that food?", not state.other_symptoms),
        ]
    elif branch == "anal burning":
        qs = [
            q("blood", "Have you noticed any bleeding or blood around/after a bowel movement?", state.blood_present is None),
            q("sharp_pain_during_stool", "Is there sharp or tearing pain during or just after a bowel movement?", state.sharp_pain_during_stool is None),
            q("lump", "Is there a lump or something protruding from the anus?", state.lump_or_prolapse is None),
            q("hard_stools", "Are your stools hard or lumpy?", state.stool_form is None and state.hard_stools is None),
            q("straining", "Do you need to strain to pass stool?", state.straining is None),
        ]
    elif branch in ("piles", "anal fissures", "bleeding"):
        qs = [
            q("blood", "Have you noticed any bleeding or blood around/after a bowel movement?", state.blood_present is None),
            q("blood_colour", "Is the blood bright/fresh red, or dark/black/tarry?", state.blood_present is True and state.blood_colour is None),
            q("blood_location", "If it is bright red, is it on tissue, dripping into the toilet, or mixed into the stool?", state.blood_present is True and state.blood_colour == "bright_red" and state.blood_location is None),
            q("sharp_pain_during_stool", "Is there sharp or tearing pain during or just after a bowel movement?", state.sharp_pain_during_stool is None),
            q("lump", "Is there a lump or something protruding from the anus?", state.lump_or_prolapse is None),
            q("hard_stools", "Are your stools hard or lumpy?", state.stool_form is None and state.hard_stools is None),
            q("straining", "Do you need to strain to pass stool?", state.straining is None),
        ]
    else:
        qs = [
            q("constipation_symptom", "Are you experiencing constipation?", state.constipation_explicit is None),
            q("diarrhea_symptom", "Are you experiencing diarrhea or loose motions?", state.diarrhea is None),
            q("abdominal_pain", "Are you experiencing abdominal pain?", state.abdominal_pain is None),
            q("pain_bowel_relation", "If you have pain, does it change with bowel movements?", state.abdominal_pain is True and state.pain_related_to_bowel_movement is None),
        ]

    for item in qs:
        if item:
            return item
    return None
