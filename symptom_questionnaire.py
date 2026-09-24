"""Adaptive, branch-specific questions for GutGPT.

The questionnaire is intentionally short. It stops as soon as the clinical
rule engine has enough information to produce a useful preliminary assessment.
"""

def next_question(state):
    asked=set(state.asked_fields or [])
    def q(name,text,condition=True):
        return (name,text) if condition and name not in asked else None

    # Every branch gets a compact safety screen, but answers are mapped to the
    # exact field by ConversationManager instead of relying on the text parser.
    q0=q("duration","How long has this been happening?",state.duration=="unknown")
    if q0: return q0
    q1=q("age","What is your age?",state.age is None)
    if q1: return q1
    q2=q("red_flag_check","Any severe/worsening pain, repeated vomiting, fever, fainting/dizziness, severe swelling, dehydration, unexplained weight loss, or inability to pass stool and gas?",not state.red_flags)
    if q2: return q2

    branch=state.primary_symptom
    if branch in ("constipation","hard stools"):
        qs=[
            q("bowel_frequency","How many bowel movements do you usually have per week?",state.bowel_frequency_per_week is None),
            q("stool_straining","Are your stools hard/lumpy, and do you need to strain?",state.stool_form is None or state.straining is None),
            q("incomplete_evacuation","Do you often feel you haven't completely emptied your bowel?",state.incomplete_evacuation is None),
            q("ibs_pain","Do you have recurring abdominal pain, and does it improve or worsen after a bowel movement?",state.abdominal_pain is None or state.pain_related_to_bowel_movement is None),
            q("blood","Have you noticed any blood in or around the stool?",state.blood_present is None),
            q("lifestyle","How much water do you drink daily, and is your fibre/fruit/vegetable intake low, average, or high?",state.water_intake is None or state.fibre_intake is None),
            q("medications","Do you regularly take any medicines or supplements?",state.medications is None),
        ]
    elif branch=="diarrhea":
        qs=[
            q("daily_frequency","How many loose/watery stools are you having per day?",state.bowel_frequency_per_day is None),
            q("stool_form","If you know it, what Bristol Stool Scale type is it (1–7)?",state.stool_form is None),
            q("pain","Do you have abdominal pain/cramps, and does it improve or worsen after passing stool?",state.abdominal_pain is None or state.pain_related_to_bowel_movement is None),
            q("infection","Did this start after food poisoning, a stomach infection, travel, or antibiotics?",state.recent_infection is None),
            q("blood","Any blood or mucus in the stool?",state.blood_present is None or state.mucus is None),
            q("night_weight","Does it wake you at night, or have you had weight loss or fever?",state.night_time_symptoms is None or state.weight_loss is None or state.fever is None),
            q("medications","Any medicine or supplement started or changed around when this began?",state.medications is None),
        ]
    elif branch in ("acidity","heartburn"):
        qs=[
            q("reflux","Do you get sour taste or acid/food coming back up?",state.food_related is None),
            q("timing","Is it worse after meals, when lying down, or at night?",state.night_time_symptoms is None),
            q("swallowing","Any difficulty/pain swallowing or persistent vomiting?",state.vomiting is None),
            q("triggers","Do tea/coffee, spicy, oily or particular foods trigger it?",state.food_trigger is None),
            q("weight_loss","Any unexplained weight loss?",state.weight_loss is None),
        ]
    elif branch in ("bloating","gas"):
        qs=[
            q("bowel_pattern","Do you also have constipation, diarrhea, or alternating bowel habits?",state.diarrhea is None),
            q("food_trigger","Is it repeatedly linked to dairy, wheat, beans/lentils, or another particular food?",state.food_trigger is None),
            q("pain","Do you have recurring abdominal pain that changes with bowel movements?",state.abdominal_pain is None or state.pain_related_to_bowel_movement is None),
            q("stool_form","What is your usual Bristol stool type, if you know it?",state.stool_form is None),
        ]
    elif branch=="stomach pain":
        qs=[
            q("pain_location","Where exactly is the pain: upper abdomen, around the navel, lower abdomen, right side, or left side?",state.pain_location is None),
            q("severity","How severe is it from 0–10, and is it getting worse?",state.severity=="unknown"),
            q("pain_relation","Is it related to meals or bowel movements?",state.food_related is None or state.pain_related_to_bowel_movement is None),
            q("bowel_pattern","Any constipation, diarrhea, mucus, or blood in the stool?",state.diarrhea is None or state.mucus is None or state.blood_present is None),
            q("vomiting_fever","Any vomiting or fever?",state.vomiting is None or state.fever is None),
        ]
    elif branch=="indigestion":
        qs=[
            q("upper_symptoms","Is it mainly upper-abdominal fullness, early fullness, burning, nausea, or belching?",state.abdominal_pain is None),
            q("food_relation","Is it triggered or worsened by meals?",state.food_related is None),
            q("reflux","Any heartburn or acid/food coming back up?",state.primary_symptom is None),
            q("weight_swallow","Any unexplained weight loss, difficulty swallowing, persistent vomiting, or vomiting blood?",state.weight_loss is None or state.vomiting is None),
        ]
    elif branch=="food intolerance":
        qs=[
            q("trigger","Which food triggers it, and does it happen repeatedly after the same food?",state.food_trigger is None),
            q("timing","How soon after eating does it start?",state.food_related is None),
            q("symptoms","What happens after the food: bloating, gas, diarrhea, cramps, constipation, or something else?",state.abdominal_pain is None or state.diarrhea is None),
        ]
    elif branch in ("piles","anal fissures","bleeding"):
        qs=[
            q("blood_colour","Is the blood bright/fresh red, or dark/black/tarry?",state.blood_colour is None),
            q("blood_location","If bright red, is it on tissue, dripping into the toilet, or mixed into the stool?",state.blood_location is None),
            q("anal_pain","Is there sharp/tearing pain during or just after a bowel movement?",state.sharp_pain_during_stool is None),
            q("lump","Is there a lump or something protruding from the anus?",state.lump_or_prolapse is None),
            q("constipation","Do you have hard stools or strain when passing stool?",state.stool_form is None or state.straining is None),
        ]
    else:
        qs=[
            q("bowel_pattern","Do you mainly have constipation, diarrhea, or both at different times?",state.diarrhea is None),
            q("pain","Do you have abdominal pain, and is it related to bowel movements?",state.abdominal_pain is None or state.pain_related_to_bowel_movement is None),
        ]
    for item in qs:
        if item: return item
    return None
