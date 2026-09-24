"""GutGPT conversation manager.

The manager keeps the original symptom branch, maps answers to the question
that was actually asked, and only asks another question when the clinical
pattern is still genuinely under-specified.
"""
from dataclasses import dataclass, field
from gibberish_checker import is_gibberish, random_gibberish_response
from greeting_checker import is_greeting, random_greeting_response
from satisfaction_checker import is_satisfied_closing, random_closing_response
from intent_parser import SymptomState, merge_state, extract_duration, extract_age, extract_bowel_frequency, extract_bowel_frequency_per_day, extract_severity, extract_lifestyle, extract_medications, extract_bool, normalize
from symptom_questionnaire import next_question
from clinical_rule_engine import evaluate as evaluate_screening
from safety_checker import check_safety, detect_red_flags
from recommendation_engine import evaluate as evaluate_product, find_named_product, has_domain_overlap, IRRELEVANT_MESSAGE

SESSION_ENDED_MESSAGE = "This conversation has already wrapped up. Please start a new chat if you'd like help with another question."
MAX_QUESTIONS = 8

@dataclass
class SessionState:
    symptom_state: SymptomState = field(default_factory=SymptomState)
    questions_asked: int = 0
    last_question: str | None = None
    awaiting_close: bool = False
    ended: bool = False
    screening: dict | None = None

class ConversationManager:
    def __init__(self): self.sessions={}
    def _get_session(self,sid): return self.sessions.setdefault(sid,SessionState())
    def reset(self,sid): self.sessions[sid]=SessionState()

    def _apply_answer(self, session, text):
        """Interpret the answer in the context of the last question.

        This fixes the main V3 bug: answers such as 'no' or 'yes, hard stools'
        have no meaning unless we know which field the bot just asked for.
        """
        field=session.last_question
        s=session.symptom_state
        n=normalize(text)
        updates={}

        if field=="duration":
            v=extract_duration(text)
            if v: updates["duration"]=v
        elif field=="age":
            v=extract_age(text)
            if v is not None: updates["age"]=v
        elif field=="red_flag_check":
            # A negative answer is the normal path; a positive answer is
            # converted into concrete red flags when possible.
            if not any(x in n for x in ["no", "none", "nah", "not really"]):
                flags=detect_red_flags(text)
                if flags: updates["red_flags"]=list(dict.fromkeys((s.red_flags or [])+flags))
                else:
                    danger=["severe/worsening pain","repeated vomiting","fever","fainting/dizziness","severe swelling","dehydration","unexplained weight loss","inability to pass stool and gas"]
                    if any(x in n for x in danger): updates["red_flags"]=list(dict.fromkeys((s.red_flags or [])+[x for x in danger if x in n]))
        elif field=="bowel_frequency":
            v=extract_bowel_frequency(text)
            if v is not None: updates["bowel_frequency_per_week"]=v
        elif field=="daily_frequency":
            v=extract_bowel_frequency_per_day(text)
            if v is not None: updates["bowel_frequency_per_day"]=v
        elif field in ("stool_straining","constipation"):
            # The generic merger handles hard/lumpy/pellet wording and strain.
            pass
        elif field=="incomplete_evacuation":
            v=extract_bool(text,["incomplete","not completely empty","not fully empty","still feel like i need to go"],["complete","completely empty","fully empty"])
            if v is not None: updates["incomplete_evacuation"]=v
        elif field in ("ibs_pain","pain"):
            # Answer may contain both pain and its relation to bowel movement.
            v=extract_bool(text,["abdominal pain","stomach pain","belly pain","cramps","cramping","yes","yeah","yep","i do"],["no abdominal pain","no stomach pain","no pain","none"])
            if v is not None and any(x in n for x in ["pain","cramp","yes","yeah","yep","i do","no pain"]): updates["abdominal_pain"]=v
            rel=extract_bool(text,["improves after bowel movement","improves after stool","better after bowel movement","better after stool","relieved after bowel movement","worse after bowel movement","related to bowel movement","changes with bowel movement"],["not related to bowel movement","not related to stool"])
            if rel is not None: updates["pain_related_to_bowel_movement"]=rel
        elif field=="blood":
            v=extract_bool(text,["blood","bleeding","yes","yeah","yep"],["no blood","no bleeding","without blood","no"])
            if v is not None and ("blood" in n or "bleed" in n or n in {"yes","yeah","yep","no"}): updates["blood_present"]=v
        elif field=="blood_colour":
            if any(x in n for x in ["black","tarry","dark"]): updates["blood_colour"]="black"
            elif any(x in n for x in ["bright red","fresh red","fresh blood","red"]): updates["blood_colour"]="bright_red"
        elif field=="blood_location":
            if any(x in n for x in ["tissue","toilet paper"]): updates["blood_location"]="tissue"
            elif "dripping" in n: updates["blood_location"]="dripping"
            elif "mixed" in n: updates["blood_location"]="mixed"
        elif field in ("anal_pain",):
            v=extract_bool(text,["sharp","tearing","anal pain","pain during stool","yes","yeah","yep"],["no sharp pain","no pain","no"])
            if v is not None: updates["sharp_pain_during_stool"]=v; updates["anal_pain"]=v
        elif field=="lump":
            v=extract_bool(text,["lump","prolapse","comes out","yes","yeah","yep"],["no lump","no prolapse","no"])
            if v is not None: updates["lump_or_prolapse"]=v
        elif field in ("lifestyle",):
            water,fibre=extract_lifestyle(text)
            if water: updates["water_intake"]=water
            if fibre: updates["fibre_intake"]=fibre
        elif field=="medications":
            v=extract_medications(text)
            if v: updates["medications"]=v
        elif field in ("infection",):
            v=extract_bool(text,["food poisoning","stomach infection","gut infection","gastroenteritis","after an infection","yes","yeah","yep"],["no recent infection","no infection","no"])
            if v is not None: updates["recent_infection"]=v
        elif field in ("night_weight",):
            for name,pos,neg in [
                ("night_time_symptoms",["wakes me at night","wake me at night","at night"],["not at night","doesn't wake me","does not wake me"]),
                ("weight_loss",["weight loss","losing weight"],["no weight loss","not losing weight"]),
                ("fever",["fever"],["no fever"]),
            ]:
                v=extract_bool(text,pos,neg)
                if v is not None: updates[name]=v
        elif field=="weight_loss":
            v=extract_bool(text,["weight loss","losing weight"],["no weight loss","not losing weight","no"])
            if v is not None: updates["weight_loss"]=v
        elif field=="swallowing":
            v=extract_bool(text,["difficulty swallowing","pain swallowing","persistent vomiting","vomiting","yes","yeah","yep"],["no difficulty swallowing","no vomiting","no"])
            if v is not None: updates["vomiting"]=v
        elif field in ("reflux","timing","triggers","food_trigger","food_relation","trigger"):
            # General merge captures food/reflux phrases.
            pass
        elif field=="stool_form":
            pass
        elif field=="severity":
            v=extract_severity(text)
            if v is not None: updates["severity"]=v
        elif field=="pain_location":
            if "upper" in n: updates["pain_location"]="upper abdomen"
            elif "lower" in n: updates["pain_location"]="lower abdomen"
            elif "right" in n: updates["pain_location"]="right side"
            elif "left" in n: updates["pain_location"]="left side"
            elif "navel" in n or "belly button" in n: updates["pain_location"]="around navel"
        elif field=="bowel_pattern":
            # Preserve constipation/diarrhea flags from the answer.
            if any(x in n for x in ["constipation","constipated","hard stool"]): updates["secondary_symptoms"]=list(dict.fromkeys((s.secondary_symptoms or [])+["constipation"]))
            if any(x in n for x in ["diarrhea","diarrhoea","loose stool","loose motion"]): updates["diarrhea"]=True; updates["secondary_symptoms"]=list(dict.fromkeys((s.secondary_symptoms or [])+["diarrhea"]))

        # First apply contextual fields, then generic extraction for details.
        merged=merge_state(s,text,[])
        data=merged.to_dict()
        for k,v in updates.items():
            if k=="secondary_symptoms":
                data[k]=v
            elif v is not None: data[k]=v
        session.symptom_state=SymptomState(**data)

    def _ready_to_assess(self, session, screening):
        s=session.symptom_state
        if session.questions_asked < 4: return False
        if screening["pattern"]=="Insufficiently characterized gut symptom pattern": return False
        if screening.get("action") == "clarify_bleeding": return False
        # Bleeding is handled immediately once the essential distinguishing
        # features have been collected.
        if s.blood_present and s.blood_colour:
            if s.sharp_pain_during_stool is None: return False
            if s.blood_colour == "bright_red" and s.sharp_pain_during_stool is False and s.lump_or_prolapse is None: return False
            return True
        # Constipation needs a quick blood check before we label it. For a
        # chronic case, collect abdominal-pain/bowel-movement relation so an
        # IBS-C pattern is not mistaken for ordinary constipation.
        if s.primary_symptom in ("constipation", "hard stools"):
            if s.blood_present is None: return False
            from clinical_rule_engine import _duration_days
            days=_duration_days(s.duration)
            if days is not None and days >= 90 and (s.abdominal_pain is None or s.pain_related_to_bowel_movement is None):
                return False
        # IBS needs its defining pain/bowel pattern, not merely constipation.
        if screening["pattern"].startswith("IBS"):
            return bool(s.abdominal_pain and s.pain_related_to_bowel_movement and s.duration!="unknown")
        return True

    def handle_message(self,sid,user_message):
        session=self._get_session(sid)
        if session.ended: return {"status":"SESSION_ENDED","message":SESSION_ENDED_MESSAGE,"recommendations":[]}
        if session.awaiting_close and is_satisfied_closing(user_message):
            session.ended=True; return {"status":"SESSION_ENDED","message":random_closing_response(),"recommendations":[]}
        if is_greeting(user_message): return {"status":"GREETING","message":random_greeting_response(),"recommendations":[]}
        if is_gibberish(user_message): return {"status":"GIBBERISH","message":random_gibberish_response(),"recommendations":[]}

        safety=check_safety(user_message)
        if safety["red_flag"]:
            screening={"pattern":"Red-flag presentation","likely_condition":"Red-flag presentation","confidence":"high","evidence":safety["reasons"],"differentials":[],"action":"urgent_medical_evaluation","product_allowed":False,"message":safety["message"]}
            return {"status":"DIAGNOSIS","message":safety["message"],"recommendations":[],"safety":safety,"screening":screening}

        named=find_named_product(user_message)
        if named and not session.symptom_state.primary_symptom:
            session.awaiting_close=True; return {"status":"PRODUCT_INFO_FOUND","message":"","product":named,"recommendations":[named]}

        # Apply the answer to the field we just asked before generic extraction.
        if session.last_question:
            self._apply_answer(session,user_message)
        else:
            session.symptom_state=merge_state(session.symptom_state,user_message,[])

        if not session.symptom_state.primary_symptom and not has_domain_overlap(user_message):
            return {"status":"IRRELEVANT","message":IRRELEVANT_MESSAGE,"recommendations":[]}

        screening=evaluate_screening(session.symptom_state)
        session.screening=screening

        if self._ready_to_assess(session,screening):
            if not screening["product_allowed"]:
                return {"status":"DIAGNOSIS","message":screening["message"],"recommendations":[],"safety":safety,"screening":screening}
            result=evaluate_product(session.symptom_state,user_message)
            result["screening"]=screening; result["safety"]=safety
            # Never let a product-engine ambiguity hide the clinical assessment.
            # The user should see the likely pattern first.
            if result.get("status") == "AMBIGUOUS":
                return {"status":"DIAGNOSIS","message":screening["message"],"recommendations":[],"safety":safety,"screening":screening}
            if result["status"]=="RECOMMENDATION_FOUND": session.awaiting_close=True
            return result

        if session.questions_asked < MAX_QUESTIONS:
            q=next_question(session.symptom_state)
            if q:
                name,text=q
                session.symptom_state.asked_fields.append(name)
                session.last_question=name
                session.questions_asked += 1
                return {"status":"ASK","message":text,"recommendations":[],"safety":safety}

        # Never loop with "I need more information". Give the best available
        # preliminary pattern and explicitly state what remains uncertain.
        screening=evaluate_screening(session.symptom_state)
        if screening["pattern"]=="Insufficiently characterized gut symptom pattern":
            screening["pattern"]="Preliminary gut-symptom assessment"
            screening["likely_condition"]="Preliminary gut-symptom assessment"
            screening["message"]="The information points to a gut-symptom pattern, but it is not specific enough to label one condition confidently yet."
        return {"status":"DIAGNOSIS","message":screening["message"],"recommendations":[],"safety":safety,"screening":screening}
