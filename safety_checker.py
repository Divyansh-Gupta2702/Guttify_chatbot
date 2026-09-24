"""Conservative universal red-flag gate for the Guttify screening flow."""
import re

RED_FLAG_PATTERNS = [
    ("vomiting blood", ["vomiting blood","throwing up blood","hematemesis"]),
    ("black/tarry stool", ["black stool","black tarry stool","tarry stool","black poop"]),
    ("severe abdominal pain", ["severe abdominal pain","excruciating stomach pain","unbearable stomach pain","severe stomach pain"]),
    ("persistent vomiting", ["persistent vomiting","vomiting repeatedly","can't stop vomiting","cant stop vomiting","vomiting continuously"]),
    ("severe abdominal distension", ["severe abdominal swelling","severe abdominal distension","abdomen severely swollen"]),
    ("fainting/dizziness with bleeding", ["fainting with bleeding","dizzy with bleeding","dizziness with bleeding","passed out with bleeding"]),
    ("dehydration", ["severe dehydration","dehydrated and unable to keep fluids","not urinating and very thirsty"]),
    ("unexplained significant weight loss", ["unexplained weight loss","losing weight without trying","weight loss without trying"]),
    ("persistent fever", ["persistent fever","fever for days"]),
    ("difficulty swallowing", ["difficulty swallowing","trouble swallowing","painful swallowing"]),
    ("unable to pass stool and gas", ["cannot pass stool or gas","can't pass stool or gas","unable to pass stool and gas","can't pass gas or stool"]),
]

def _negative(text, phrase):
    n=text.lower()
    for prefix in ["no ","not ","without ","don't have ","dont have "]:
        if prefix+phrase in n: return True
    return False

def detect_red_flags(text):
    n=text.lower()
    found=[]
    for label,phrases in RED_FLAG_PATTERNS:
        if any(p in n and not _negative(n,p) for p in phrases): found.append(label)
    return found

def check_safety(user_query):
    flags=detect_red_flags(user_query)
    if flags:
        return {"safe_to_recommend":False,"requires_doctor":True,"red_flag":True,"reasons":flags,"message":"This needs medical evaluation rather than only self-treatment. I won't recommend a Guttify product for these symptoms."}
    # Blood is not automatically labelled as piles, but it blocks product sales
    # until the bleeding details have been screened by the rule engine.
    n=user_query.lower()
    blood=any(x in n for x in ["blood in stool","blood after stool","blood on toilet paper","fresh blood","rectal bleeding","bleeding from anus"])
    if blood and not any(x in n for x in ["no blood","no bleeding","without blood"]):
        return {"safe_to_recommend":True,"requires_doctor":False,"red_flag":False,"reasons":["rectal bleeding reported — requires clarification"],"message":""}
    return {"safe_to_recommend":True,"requires_doctor":False,"red_flag":False,"reasons":[],"message":""}
