"""Adaptive clinical-style questionnaire.

Questions are selected from the user's symptom branch rather than using one
fixed generic questionnaire. The rule engine decides the final pattern.
"""

def next_question(state):
    s = state.primary_symptom
    asked = set(state.asked_fields or [])

    def q(name, text, condition=True):
        return (name, text) if condition and name not in asked else None

    # Universal first-pass screening.
    candidates = [
        q("duration", "How long has this been happening?", state.duration == "unknown"),
        q("age", "What is your age?", state.age is None),
        q("red_flag_check", "Any severe/worsening pain, repeated vomiting, fever, fainting/dizziness, severe swelling, dehydration, unexplained weight loss, or inability to pass stool and gas?", not state.red_flags),
    ]

    branches = {
        "constipation": [
            q("bowel_frequency", "How many bowel movements do you usually have per week?", state.bowel_frequency_per_week is None),
            q("stool_and_straining", "Are your stools hard/lumpy (Bristol 1–2), and do you need to strain?", state.stool_form is None or state.straining is None),
            q("incomplete_evacuation", "Do you often feel you haven't completely emptied your bowel?", state.incomplete_evacuation is None),
            q("ibs_pain", "Do you have recurring abdominal pain, and does it improve or worsen after a bowel movement?", state.abdominal_pain is None or state.pain_related_to_bowel_movement is None),
            q("bloating", "Do you also have recurring bloating?", state.bloating is None),
            q("blood", "Have you noticed any blood in or around the stool?", state.blood_present is None),
            q("lifestyle", "How much water do you drink daily, and is your fibre/fruit/vegetable intake low, average, or high?", state.water_intake is None or state.fibre_intake is None),
            q("medications", "Do you regularly take any medicines or supplements?", state.medications is None),
            q("family_history", "Any family history of colorectal cancer, inflammatory bowel disease, or other significant digestive disease?", state.family_history_gi is None),
        ],
        "diarrhea": [
            q("stool_frequency_day", "How many loose/watery stools are you having per day?", state.bowel_frequency_per_week is None),
            q("stool_form", "If you know it, what Bristol Stool Scale type is it (1–7)?", state.stool_form is None),
            q("pain", "Do you have abdominal pain/cramps, and does it improve or worsen after passing stool?", state.abdominal_pain is None or state.pain_related_to_bowel_movement is None),
            q("mucus", "Any mucus in the stool?", state.mucus is None),
            q("blood", "Any blood in the stool?", state.blood_present is None),
            q("infection", "Did this start after food poisoning, a stomach infection, travel, or antibiotics?", state.recent_infection is None),
            q("night_weight", "Does it wake you at night, or have you had weight loss or fever?", state.night_time_symptoms is None or state.weight_loss is None or state.fever is None),
            q("medications", "Any medicines or supplements that were started or changed around the time this began?", state.medications is None),
            q("family_history", "Any family history of IBD, colorectal cancer, or other major digestive disease?", state.family_history_gi is None),
        ],
        "acidity": [
            q("heartburn", "Do you get chest/throat burning, a sour taste, or acid/food coming back up?", state.abdominal_pain is None),
            q("timing", "Is it worse after meals, when lying down, or at night?", state.food_related is None or state.night_time_symptoms is None),
            q("swallowing", "Any difficulty or pain swallowing, persistent vomiting, or vomiting blood?", state.vomiting is None),
            q("triggers", "Do tea/coffee, spicy, oily, fatty, or particular foods trigger it?", state.food_trigger is None),
            q("duration_frequency", "How often does this happen, and for how many weeks or months?", state.duration == "unknown" or state.frequency is None),
            q("weight_loss", "Any unexplained weight loss?", state.weight_loss is None),
        ],
        "heartburn": [
            q("reflux", "Do you also get sour taste or food/acid coming back into your mouth?", state.food_related is None),
            q("timing", "Is it worse after meals, when lying down, or at night?", state.night_time_symptoms is None),
            q("swallowing", "Any difficulty swallowing, persistent vomiting, or vomiting blood?", state.vomiting is None),
            q("duration", "How long has this been happening and how often?", state.duration == "unknown"),
            q("weight_loss", "Any unexplained weight loss?", state.weight_loss is None),
        ],
        "bloating": [
            q("food_trigger", "Is the bloating repeatedly linked to dairy, wheat, beans/lentils, or another particular food?", state.food_trigger is None),
            q("bowel_pattern", "Do you also have constipation, diarrhea, or alternating bowel habits?", state.bloating is not None),
            q("pain", "Do you have recurring abdominal pain that changes with bowel movements?", state.abdominal_pain is None or state.pain_related_to_bowel_movement is None),
            q("stool_form", "What is your usual stool form on the Bristol scale, if you know it?", state.stool_form is None),
            q("duration", "How long has the bloating been recurring?", state.duration == "unknown"),
            q("night_weight", "Does it wake you at night, or have you had weight loss or fever?", state.night_time_symptoms is None or state.weight_loss is None or state.fever is None),
        ],
        "gas": [
            q("food_trigger", "Does the gas repeatedly follow dairy, wheat, beans/lentils, or another particular food?", state.food_trigger is None),
            q("bowel_pattern", "Do you also have constipation, diarrhea, or alternating bowel habits?", True),
            q("pain", "Do you have recurring abdominal pain that changes with bowel movements?", state.abdominal_pain is None or state.pain_related_to_bowel_movement is None),
            q("bloating", "Do you also get significant bloating?", state.bloating is None),
            q("duration", "How long has this been recurring?", state.duration == "unknown"),
            q("night_weight", "Does it wake you at night, or have you had weight loss or fever?", state.night_time_symptoms is None or state.weight_loss is None or state.fever is None),
        ],
        "stomach pain": [
            q("pain_location", "Where exactly is the pain: upper abdomen, around the navel, lower abdomen, right side, or left side?", state.pain_location is None),
            q("pain_severity", "How severe is it from 0–10, and is it getting worse?", state.severity == "unknown"),
            q("pain_relation", "Is it related to meals or bowel movements?", state.food_related is None or state.pain_related_to_bowel_movement is None),
            q("bowel_pattern", "Any constipation, diarrhea, mucus, or blood in the stool?", state.diarrhea is None or state.mucus is None or state.blood_present is None),
            q("vomiting_fever", "Any vomiting or fever?", state.vomiting is None or state.fever is None),
            q("duration", "How long has the pain been present?", state.duration == "unknown"),
            q("night_weight", "Does it wake you at night or come with unexplained weight loss?", state.night_time_symptoms is None or state.weight_loss is None),
        ],
        "indigestion": [
            q("upper_symptoms", "Is it mainly upper-abdominal fullness, early fullness, burning, nausea, or belching?", state.abdominal_pain is None),
            q("food_relation", "Is it triggered or worsened by meals?", state.food_related is None),
            q("reflux", "Any heartburn or acid/food coming back up?", state.primary_symptom is None),
            q("duration", "How long has this been happening?", state.duration == "unknown"),
            q("weight_swallow", "Any unexplained weight loss, difficulty swallowing, persistent vomiting, or vomiting blood?", state.weight_loss is None or state.vomiting is None),
        ],
        "food intolerance": [
            q("trigger", "Which food triggers it, and does it happen repeatedly after the same food?", state.food_trigger is None),
            q("timing", "How soon after eating does it start?", state.food_related is None),
            q("symptoms", "What happens after the food: bloating, gas, diarrhea, cramps, constipation, or something else?", state.abdominal_pain is None or state.diarrhea is None),
            q("duration", "How long has this food association been happening?", state.duration == "unknown"),
        ],
        "piles": [
            q("blood", "If there is bleeding, is it bright red or black/tarry?", state.blood_present is None or state.blood_colour is None),
            q("blood_location", "If bright red, is it on tissue, dripping into the toilet, or mixed into the stool?", state.blood_present and state.blood_location is None),
            q("anal_pain", "Is there sharp pain during or after a bowel movement?", state.anal_pain is None or state.sharp_pain_during_stool is None),
            q("lump", "Is there a lump or something protruding from the anus?", state.lump_or_prolapse is None),
            q("constipation", "Do you strain or have hard stools/constipation?", state.straining is None or state.stool_form is None),
        ],
        "anal fissures": [
            q("anal_pain", "Is the pain sharp/tearing during or after a bowel movement?", state.sharp_pain_during_stool is None),
            q("blood", "Is any blood bright red?", state.blood_present is None or state.blood_colour is None),
            q("constipation", "Do you have hard stools or strain?", state.stool_form is None or state.straining is None),
            q("lump", "Any lump or prolapse?", state.lump_or_prolapse is None),
        ],
    }

    for item in candidates:
        if item:
            return item
    for item in branches.get(s, []):
        if item:
            return item
    return None
