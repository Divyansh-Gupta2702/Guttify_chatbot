"""Adaptive clinical screening questions for GutGPT.

Questions are branch-specific and answerable in normal language. The agent
records the exact field it asked, so replies like "5 months", "23", "no", or
"yes, hard stools" are never treated as unrelated messages.
"""

def next_question(state):
    asked = set(state.asked_fields or [])

    def q(name, text, condition=True):
        if condition and name not in asked:
            return name, text
        return None

    branch = state.primary_symptom

    # If the user has supplied enough information up front, these are skipped.
    for item in [
        q("duration", "How long has this been happening?", state.duration == "unknown"),
        q("age", "What is your age?", state.age is None),
    ]:
        if item:
            return item

    if branch in ("constipation", "hard stools"):
        # If bleeding is reported during the constipation interview, switch
        # temporarily to the bleeding differentiator before making the
        # constipation assessment. This prevents every bleed from becoming
        # an automatic piles label.
        if state.blood_present:
            bleeding_qs = [
                q("blood_colour", "Is the blood bright/fresh red, or dark/black/tarry?", state.blood_colour is None),
                q("blood_location", "If it is bright red, is it on tissue, dripping into the toilet, or mixed into the stool?", state.blood_location is None),
                q("anal_pain", "Is there sharp or tearing pain during or just after a bowel movement?", state.sharp_pain_during_stool is None),
                q("lump", "Is there a lump or something protruding from the anus?", state.lump_or_prolapse is None),
            ]
            for item in bleeding_qs:
                if item:
                    return item

        # This mirrors the requested constipation assessment while allowing
        # the engine to stop early once a useful pattern is established.
        qs = [
            q("bowel_frequency", "How many bowel movements do you usually have per week?", state.bowel_frequency_per_week is None),
            q("stool_straining", "Are your stools hard or lumpy, and do you need to strain to pass them?", state.stool_form is None or state.straining is None),
            q("incomplete_evacuation", "After passing stool, do you often feel that your bowel has not completely emptied?", state.incomplete_evacuation is None),
            q("bloating_pain", "Do you have bloating or recurring abdominal pain? If you have pain, does it improve or change after a bowel movement?", state.bloating is None or state.abdominal_pain is None),
            q("pain_relation", "If you have abdominal pain, does it improve, worsen, or change after you pass stool?", state.abdominal_pain is True and state.pain_related_to_bowel_movement is None),
            q("blood", "Have you noticed any blood in or around the stool?", state.blood_present is None),
            q("anal_pain", "Do you have severe or sharp anal pain during or just after a bowel movement?", state.sharp_pain_during_stool is None),
            q("weight_loss", "Have you had unexplained weight loss?", state.weight_loss is None),
            q("vomiting_fever_swelling", "Any repeated vomiting, fever, or severe abdominal swelling?", state.vomiting is None or state.fever is None or state.abdominal_distension is None),
            q("water", "Roughly how much water do you drink each day?", state.water_intake is None),
            q("fibre", "Would you describe your fibre/fruit/vegetable intake as low, average, or high?", state.fibre_intake is None),
            q("medications", "Do you regularly take any medicines or supplements?", state.medications is None),
        ]
    elif branch == "diarrhea":
        qs = [
            q("daily_frequency", "How many loose or watery stools are you having per day?", state.bowel_frequency_per_day is None),
            q("stool_form", "If you know it, what Bristol Stool Scale type is it (1–7)?", state.stool_form is None),
            q("pain", "Do you have abdominal pain or cramps, and does it change after passing stool?", state.abdominal_pain is None or state.pain_related_to_bowel_movement is None),
            q("infection", "Did this begin after food poisoning, a stomach infection, travel, or antibiotics?", state.recent_infection is None),
            q("blood_mucus", "Any blood or mucus in the stool?", state.blood_present is None or state.mucus is None),
            q("night_weight_fever", "Does it wake you at night, or have you had weight loss or fever?", state.night_time_symptoms is None or state.weight_loss is None or state.fever is None),
            q("medications", "Did you start or change any medicine or supplement around the time this began?", state.medications is None),
        ]
    elif branch in ("acidity", "heartburn"):
        qs = [
            q("reflux", "Do you get a sour taste or acid/food coming back up?", state.food_related is None),
            q("timing", "Is it worse after meals, when lying down, or at night?", state.night_time_symptoms is None),
            q("triggers", "Do tea/coffee, spicy, oily, or particular foods trigger it?", state.food_trigger is None),
            q("swallowing", "Any difficulty or pain swallowing, persistent vomiting, or vomiting blood?", state.vomiting is None),
            q("weight_loss", "Any unexplained weight loss?", state.weight_loss is None),
        ]
    elif branch in ("bloating", "gas"):
        qs = [
            q("bowel_pattern", "Do you also have constipation, diarrhea, or alternating bowel habits?", state.diarrhea is None or state.bowel_frequency_per_week is None),
            q("food_trigger", "Is it repeatedly linked to dairy, wheat, beans/lentils, or another particular food?", state.food_trigger is None),
            q("pain", "Do you have recurring abdominal pain that changes with bowel movements?", state.abdominal_pain is None or state.pain_related_to_bowel_movement is None),
            q("stool_form", "What is your usual Bristol stool type, if you know it?", state.stool_form is None),
        ]
    elif branch == "stomach pain":
        qs = [
            q("pain_location", "Where exactly is the pain: upper abdomen, around the navel, lower abdomen, right side, or left side?", state.pain_location is None),
            q("severity", "How severe is it from 0–10, and is it getting worse?", state.severity == "unknown"),
            q("pain_relation", "Is it related to meals or bowel movements?", state.food_related is None or state.pain_related_to_bowel_movement is None),
            q("bowel_pattern", "Any constipation, diarrhea, mucus, or blood in the stool?", state.diarrhea is None or state.mucus is None or state.blood_present is None),
            q("vomiting_fever", "Any vomiting or fever?", state.vomiting is None or state.fever is None),
        ]
    elif branch == "indigestion":
        qs = [
            q("upper_symptoms", "Is it mainly upper-abdominal fullness, early fullness, burning, nausea, or belching?", state.abdominal_pain is None),
            q("food_relation", "Is it triggered or worsened by meals?", state.food_related is None),
            q("reflux", "Any heartburn or acid/food coming back up?", state.secondary_symptoms is None or "heartburn" not in state.secondary_symptoms),
            q("weight_swallow", "Any unexplained weight loss, difficulty swallowing, persistent vomiting, or vomiting blood?", state.weight_loss is None or state.vomiting is None),
        ]
    elif branch == "food intolerance":
        qs = [
            q("trigger", "Which food triggers it, and does it happen repeatedly after the same food?", state.food_trigger is None),
            q("timing", "How soon after eating does it start?", state.food_related is None),
            q("symptoms", "What happens after the food: bloating, gas, diarrhea, cramps, constipation, or something else?", state.abdominal_pain is None or state.diarrhea is None),
        ]
    elif branch in ("piles", "anal fissures", "bleeding"):
        qs = [
            q("blood_colour", "Is the blood bright/fresh red, or dark/black/tarry?", state.blood_colour is None),
            q("blood_location", "If bright red, is it on tissue, dripping into the toilet, or mixed into the stool?", state.blood_location is None),
            q("anal_pain", "Is there sharp or tearing pain during or just after a bowel movement?", state.sharp_pain_during_stool is None),
            q("lump", "Is there a lump or something protruding from the anus?", state.lump_or_prolapse is None),
            q("constipation", "Do you have hard stools or strain when passing stool?", state.stool_form is None or state.straining is None),
        ]
    else:
        qs = [
            q("bowel_pattern", "Do you mainly have constipation, diarrhea, or both at different times?", state.diarrhea is None),
            q("pain", "Do you have abdominal pain, and is it related to bowel movements?", state.abdominal_pain is None or state.pain_related_to_bowel_movement is None),
        ]

    for item in qs:
        if item:
            return item
    return None
