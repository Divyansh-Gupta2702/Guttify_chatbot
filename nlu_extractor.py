"""
GutGPT contextual natural-language extraction.

This module is deliberately NOT a diagnosis engine. It converts a user's
natural-language message into validated, normalized facts that the existing
deterministic safety/questionnaire/clinical-rule/product layers can consume.

The LLM is used only when contextual extraction can add value. If it is
unavailable, malformed, or uncertain, deterministic extraction remains the
fallback and the conversation must continue safely.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Any

from intent_parser import extract_food_trigger, extract_stool_form


logger = logging.getLogger("gutgpt.nlu")

# These are the only normalized symptom values the existing deterministic
# engine understands. The LLM may not invent new clinical categories.
ALLOWED_SYMPTOMS = {
    "constipation", "hard stools", "bloating", "gas", "acidity",
    "heartburn", "diarrhea", "stomach pain", "piles", "anal fissures",
    "anal burning", "anal swelling", "bleeding", "indigestion",
    "food intolerance",
}

ALLOWED_BLOOD_COLOURS = {"bright_red", "black", "dark", "unknown"}
ALLOWED_BLOOD_LOCATIONS = {"tissue", "dripping", "mixed", "unknown"}
ALLOWED_SEVERITIES = {"mild", "moderate", "severe", "unknown"}

SCHEMA_KEYS = {
    "intent", "symptoms", "body_areas", "duration", "severity", "pain",
    "pain_character", "pain_timing", "bleeding", "blood_type",
    "stool_form", "food_trigger", "food_related",
    "blood_location", "itching", "burning", "swelling", "lump_or_protrusion",
    "stool_pattern", "hard_stools", "straining", "constipation",
    "loose_stools", "weight_loss", "age", "food_triggers",
    "aggravating_factors", "relieving_factors", "red_flags",
    "new_information", "confidence", "recent_worsening", "gas", "meal_relation", "pain_relation", "bowel_pattern",
    "water_intake", "fibre_intake", "medications", "incomplete_evacuation", "pain_related_to_bowel_movement", "reflux_present", "meal_timing", "symptom_onset_after_food", "timing_relation",
}

BOOL_FIELDS = {
    "pain", "bleeding", "itching", "burning", "swelling", "reflux_present",
    "food_related",
    "lump_or_protrusion", "hard_stools", "straining", "constipation",
    "loose_stools", "weight_loss", "recent_worsening", "gas", "meal_relation", "pain_relation", "bowel_pattern",
}

LIST_FIELDS = {
    "symptoms", "body_areas", "food_triggers", "aggravating_factors",
    "relieving_factors", "red_flags", "new_information",
}


def _clean_json_text(content: str) -> str:
    """Return the first valid JSON object from an LLM response.

    Groq can occasionally return fenced JSON, a short preamble, or trailing
    text even when the prompt requests JSON-only output. The NLU layer must
    tolerate those forms without allowing malformed model output to affect the
    deterministic rule engine.
    """
    if not isinstance(content, str):
        return ""
    text = content.strip()
    if not text:
        return ""
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)

    decoder = json.JSONDecoder()
    # Prefer a complete object beginning at any opening brace. raw_decode
    # correctly handles nested objects/strings and ignores trailing prose.
    for match in re.finditer(r"\{", text):
        try:
            _, end = decoder.raw_decode(text[match.start():])
            return text[match.start():match.start() + end]
        except json.JSONDecodeError:
            continue
    return text


def _blank_result(intent="answer_question") -> dict:
    return {
        "intent": intent,
        "symptoms": [],
        "body_areas": [],
        "duration": None,
        "severity": None,
        "pain": None,
        "pain_character": None,
        "pain_timing": None,
        "bleeding": None,
        "blood_type": None,
        "blood_location": None,
        "itching": None,
        "burning": None,
        "swelling": None,
        "lump_or_protrusion": None,
        "stool_pattern": None,
        "stool_form": None,
        "food_trigger": None,
        "food_related": None,
        "hard_stools": None,
        "straining": None,
        "constipation": None,
        "loose_stools": None,
        "weight_loss": None,
        "age": None,
        "food_triggers": [],
        "aggravating_factors": [],
        "relieving_factors": [],
        "red_flags": [],
        "new_information": [],
        "confidence": 0.0,
        "recent_worsening": None,
        "gas": None,
        "meal_relation": None,
        "pain_relation": None,
        "bowel_pattern": None,
        "water_intake": None,
        "fibre_intake": None,
        "medications": None,
        "incomplete_evacuation": None,
        "pain_related_to_bowel_movement": None,
        "reflux_present": None,
        "meal_timing": None,
        "symptom_onset_after_food": None,
        "timing_relation": None,
    }


def _validate(raw: Any, forced_intent: str | None = None) -> dict:
    """Strictly validate/sanitize LLM output; never trust raw model values."""
    if not isinstance(raw, dict):
        return _blank_result(forced_intent or "answer_question")

    out = _blank_result()
    intent = raw.get("intent")
    allowed_intents = {"assessment", "answer_question", "new_symptom",
                       "general_question", "unrelated"}
    out["intent"] = forced_intent if forced_intent in allowed_intents else (
        intent if intent in allowed_intents else "answer_question"
    )

    symptoms = raw.get("symptoms")
    if isinstance(symptoms, list):
        out["symptoms"] = list(dict.fromkeys(
            x for x in symptoms if isinstance(x, str) and x in ALLOWED_SYMPTOMS
        ))
    for key in BOOL_FIELDS:
        value = raw.get(key)
        if isinstance(value, bool):
            out[key] = value

    for key in ("duration", "pain_character", "pain_timing", "stool_pattern", "food_trigger", "meal_relation", "pain_relation", "bowel_pattern", "water_intake", "fibre_intake", "medications", "meal_timing", "symptom_onset_after_food", "timing_relation"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()[:160]

    stool_form = raw.get("stool_form")
    if isinstance(stool_form, int) and 1 <= stool_form <= 7:
        out["stool_form"] = stool_form
    elif isinstance(stool_form, str) and stool_form == "unknown":
        out["stool_form"] = "unknown"

    severity = raw.get("severity")
    if isinstance(severity, (int, float)) and 0 <= float(severity) <= 10:
        out["severity"] = str(int(severity)) if float(severity).is_integer() else str(float(severity))
    elif isinstance(severity, str) and (severity in ALLOWED_SEVERITIES or re.fullmatch(r"(?:10|[0-9])(?:\.\d+)?", severity.strip())):
        try:
            if 0 <= float(severity.strip()) <= 10:
                out["severity"] = severity.strip()
        except ValueError:
            if severity in ALLOWED_SEVERITIES:
                out["severity"] = severity

    for key in ("blood_type", "blood_location"):
        value = raw.get(key)
        allowed = ALLOWED_BLOOD_COLOURS if key == "blood_type" else ALLOWED_BLOOD_LOCATIONS
        if isinstance(value, str) and value in allowed:
            out[key] = value

    age = raw.get("age")
    if isinstance(age, int) and 0 <= age <= 120:
        out["age"] = age
    elif isinstance(age, str) and age.strip().isdigit():
        value = int(age.strip())
        if 0 <= value <= 120:
            out["age"] = value

    for key in LIST_FIELDS:
        if key == "symptoms":
            continue  # symptoms were already strictly allow-listed above
        value = raw.get(key)
        if isinstance(value, list):
            out[key] = [str(x).strip()[:120] for x in value
                        if isinstance(x, (str, int, float)) and str(x).strip()][:12]

    confidence = raw.get("confidence")
    try:
        confidence = float(confidence)
        out["confidence"] = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        out["confidence"] = 0.0

    # "answer_question" is authoritative whenever the caller says a question
    # is pending. This prevents an LLM's generic intent classifier from
    # misclassifying a short answer like "2 days" as unrelated.
    if forced_intent:
        out["intent"] = forced_intent

    return out


def _state_context(state) -> dict:
    # Keep the prompt compact. Existing state is the durable context; the LLM
    # only needs the current normalized facts and the last question.
    try:
        d = state.to_dict()
    except Exception:
        d = {}
    return {
        "primary_symptom": d.get("primary_symptom"),
        "secondary_symptoms": d.get("secondary_symptoms", []),
        "duration": d.get("duration"),
        "age": d.get("age"),
        "severity": d.get("severity"),
        "blood_present": d.get("blood_present"),
        "blood_colour": d.get("blood_colour"),
        "blood_location": d.get("blood_location"),
        "straining": d.get("straining"),
        "stool_form": d.get("stool_form"),
        "weight_loss": d.get("weight_loss"),
        "bloating": d.get("bloating"),
        "diarrhea": d.get("diarrhea"),
        "constipation_explicit": d.get("constipation_explicit"),
        "reflux_present": d.get("reflux_present"),
        "anal_pain": d.get("anal_pain"),
        "sharp_pain_during_stool": d.get("sharp_pain_during_stool"),
        "lump_or_prolapse": d.get("lump_or_prolapse"),
        "red_flags": d.get("red_flags", []),
    }


@lru_cache(maxsize=1)
def _get_llm():
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    try:
        from langchain_groq import ChatGroq
    except ImportError:
        logger.warning("[NLU] langchain-groq is unavailable; using deterministic fallback")
        return None
    model = os.getenv("GROQ_NLU_MODEL", "openai/gpt-oss-20b")
    try:
        return ChatGroq(
            model=model,
            temperature=0,
            max_tokens=500,
            api_key=key,
        )
    except Exception:
        logger.exception("[NLU] failed to initialize extractor")
        return None


def _llm_extract(message: str, last_question: str | None, state, forced_intent: str | None):
    llm = _get_llm()
    if llm is None:
        return None

    prompt = f"""
You are the natural-language extraction layer for GutGPT.

Your ONLY job is to extract facts explicitly stated or strongly implied by
the user's message. You do NOT diagnose, recommend products, or invent facts.

CURRENT QUESTION:
{last_question or "(none)"}

CURRENT STRUCTURED STATE:
{json.dumps(_state_context(state), ensure_ascii=False)}

USER MESSAGE:
{message}

Rules:
1. Interpret the message in the context of CURRENT QUESTION.
2. Extract every relevant fact in the message, including facts volunteered
   beyond the question.
3. A negative answer must be represented as false when the user clearly
   negates that fact ("I haven't lost weight", "stools are normal", etc.).
4. Do not infer a fact merely because it is common for a symptom.
5. If the message says "about two weeks but much worse three days ago",
   duration is "2 weeks" and recent_worsening=true.
6. If the user says "I've actually gained weight" in response to weight loss,
   weight_loss=false.
7. "Mostly normal, maybe slightly harder" means hard_stools=true only if the
   user is actually reporting some hardness; preserve nuance in stool_pattern.
8. Normalize symptom language to ONLY the allowed symptom values.
9. "butt", "back passage", "rectum", "anal area" are body-area descriptions,
   not diagnoses.
10. Do not diagnose. In particular, do NOT output "anal fissures" or "piles"
    merely because symptoms could be compatible with them. Output those
    normalized symptoms only when the user explicitly names the condition
    (e.g. "I have piles" / "I have a fissure").
11. Do not turn "yes"/"no" into unrelated fields. Use the question context.
12. Only return valid JSON, no markdown.

Allowed normalized symptoms:
{sorted(ALLOWED_SYMPTOMS)}

Return exactly one JSON object with these keys:
{sorted(SCHEMA_KEYS)}
"""
    try:
        response = llm.invoke(prompt)
        content = getattr(response, "content", "")
        raw = json.loads(_clean_json_text(content))
        result = _validate(raw, forced_intent=forced_intent)
        # Prevent the extractor from turning a symptom description into a
        # diagnosis-like branch. Conditions such as fissure/piles are allowed
        # only when explicitly named by the user; deterministic rules decide
        # whether the symptom pattern actually supports them.
        explicit_condition = bool(re.search(
            r"\b(piles?|hemorrhoids?|haemorrhoids?|anal fissures?|fissure|fissures|anal tear|tear in (?:the )?anus|cut (?:near|around|in) (?:the )?anus|crack (?:near|around|in) (?:the )?anus)\b",
            message.lower(),
        ))
        if not explicit_condition:
            result["symptoms"] = [
                x for x in result.get("symptoms", [])
                if x not in {"anal fissures", "piles"}
            ]

        # Ground high-impact booleans in the actual message. The model may be
        # semantically useful, but it must not manufacture a pain/bleeding/etc.
        # fact from a vague phrase such as "discomfort". Explicit negatives are
        # preserved; unsupported positives are discarded and the deterministic
        # fallback remains authoritative.
        text = message.lower()
        evidence = {
            "pain": r"\b(pain|hurts?|ache|aching|sore|sharp|tearing|cutting)\b",
            "bleeding": r"\b(blood|bleeding|bleed|bloody)\b",
            "itching": r"\b(itch|itchy|itching)\b",
            "burning": r"\b(burning|burn)\b",
            "swelling": r"\b(swelling|swollen|swell)\b",
            "lump_or_protrusion": r"\b(lump|protrud|prolapse|bulge|bump|comes out)\b",
            "hard_stools": r"\b(hard|lumpy|firm)\s+(?:stools?|poop|stool)\b",
            "straining": r"\b(strain|straining|push hard|pushing hard)\b",
            "constipation": r"\b(constipat(?:ed|ion)|can't\s+(?:poop|poo)|cannot\s+(?:poop|poo)|not\s+able\s+to\s+pass\s+stool|haven't\s+pooped)\b",
            "loose_stools": r"\b(loose\s+(?:stools?|motions?)|watery\s+(?:stools?|poop)|diarrh(?:ea|oea))\b",
            "weight_loss": r"\b(lost|losing|loss\s+of)\s+(?:any\s+)?(?:significant\s+)?weight\b",
            "recent_worsening": r"\b(much\s+worse|getting\s+worse|became\s+worse|worsen(?:ed|ing)|worse\s+now)\b",
            "gas": r"\b(gas|gassy|flatulence|farting|passing\s+gas)\b",
        }
        for key, pattern in evidence.items():
            if result.get(key) is True and not re.search(pattern, text):
                result[key] = None

        # Slot grounding: an LLM cannot manufacture a duration/age/color/etc.
        # simply because the current question asks for it.
        if result.get("duration") is not None and _duration_from_text(text) is None:
            result["duration"] = None
        if result.get("age") is not None and not re.search(
            r"\b(?:i am|i'm|im|age is|aged)\s*\d{1,3}\b|\b\d{1,3}\s*(?:years?\s*old)\b", text
        ):
            result["age"] = None
        if result.get("severity") is not None and not re.search(
            r"\b(mild|moderate|severe|very\s+bad|extreme|worst)\b", text
        ):
            result["severity"] = None
        if result.get("blood_type") is not None and not re.search(
            r"\b(bright\s*red|fresh\s*(?:red|blood)|red\s*blood|black|dark|tarry)\b", text
        ):
            result["blood_type"] = None
        if result.get("blood_location") is not None and not re.search(
            r"\b(tissue|toilet\s*paper|paper|wipe|wiping|drip(?:ping)?|mixed)\b", text
        ):
            result["blood_location"] = None
        if result.get("pain_character") is not None and not re.search(
            r"\b(sharp|tearing|cutting)\b", text
        ):
            result["pain_character"] = None
        if result.get("recent_worsening") is True and not re.search(
            r"\b(much\s+worse|getting\s+worse|became\s+worse|worsen(?:ed|ing)|worse\s+now)\b", text
        ):
            result["recent_worsening"] = None

        # Weight-loss questions are especially prone to semantic inversion.
        if last_question in {"weight_loss", "weight_loss_duration"}:
            if re.search(r"\b(gained|put\s+on)\s+(?:a\s+little\s+)?weight\b", text):
                result["weight_loss"] = False
            elif re.search(r"\b(haven't|have\s+not|didn't|did\s+not|no|not\s+really)\b.*\b(lost|losing|loss)\b|\bnot\s+really\b", text):
                result["weight_loss"] = False

        return result
    except Exception as exc:
        logger.warning("[NLU] model extraction failed: %s", type(exc).__name__)
        return None


def _duration_from_text(n: str):
    number_words = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "couple": 2, "few": 3, "several": 3,
    }
    pattern = r"\b(?:(?:for|about|around|roughly|since|last|the last)\s+)?(?:like\s+)?(\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple|few|several)(?:\s*(?:-|to|or)\s*(\d+(?:\.\d+)?|two|three|four|five))?\s+(hour|hours|day|days|week|weeks|month|months|year|years)\b(?!\s*(?:old|of\s+age)\b)"

    def num(x):
        if x is None:
            return None
        return int(x) if x.isdigit() else number_words.get(x)

    for m in re.finditer(pattern, n):
        prefix = n[max(0, m.start() - 12):m.start()]
        if re.search(r"\b(?:times?|per)\s*$", prefix):
            continue
        n1, n2 = num(m.group(1)), num(m.group(2))
        if n1 is None:
            continue
        if n2 is not None:
            return f"{n1}-{n2} {m.group(3)}"
        return f"{n1} {m.group(3)}"
    return None



def _norm_answer_text(message: str) -> str:
    """Normalize conversational text without destroying semantic negation."""
    n = (message or "").lower()
    n = n.replace("’", "'").replace("–", "-").replace("—", "-")
    n = re.sub(r"\s+", " ", n)
    return n.strip(" \t\r\n.,!?;:")


def _has_negation(text: str) -> bool:
    n = _norm_answer_text(text)
    return bool(re.search(
        r"\b(?:no|nope|nah|not really|not at all|none|neither|nothing|"
        r"i don't|i do not|i haven't|i have not|i didn't|i did not|"
        r"never|without|not that i know of|isn't|is not|hasn't|has not|doesn't|does not|"
        r"don't|dont)\b", n
    ))


def _contextual_yes(text: str) -> bool:
    n = _norm_answer_text(text)
    return n in {
        "yes", "yeah", "yep", "yup", "sure", "definitely", "absolutely",
        "certainly", "of course", "true", "exactly", "correct",
        "that's right", "that is right", "it does", "it is", "i do",
        "i have", "sometimes", "yes sometimes", "pretty much", "for sure",
    }


def _contextual_no(text: str) -> bool:
    n = _norm_answer_text(text)
    return n in {
        "no", "nope", "nah", "not really", "not at all", "none", "never",
        "false", "not usually", "not often", "i don't", "i do not",
        "i haven't", "i have not", "doesn't", "does not", "it doesn't",
        "it does not",
    }


def _extract_number_0_10(text: str):
    n = _norm_answer_text(text)
    patterns = (
        r"\b(?:pain|severity)\s*(?:is|of|around|about)?\s*(10|[0-9])\s*(?:/\s*10)?\b",
        r"\b(10|[0-9])\s*/\s*10\b",
        r"\b(?:around|about|roughly|probably|maybe|i'd say|id say|rate it)\s+(10|[0-9])\b",
    )
    for pat in patterns:
        m = re.search(pat, n)
        if m and 0 <= int(m.group(1)) <= 10:
            return str(int(m.group(1)))
    return None


def _question_specific_fallback(message: str, last_question: str | None, state) -> dict:
    """Deterministic, question-aware extraction.

    This is deliberately conservative: it only fills facts supported by the
    user's wording and never treats a negated keyword as a positive answer.
    """
    n = _norm_answer_text(message)
    out = _blank_result("answer_question" if last_question else "assessment")
    negative = _has_negation(n)
    bare_yes = _contextual_yes(n) or bool(re.search(r"\b(?:yes|yeah|yep|yup|absolutely|definitely|of course|it does|pretty much)\b", n))
    bare_no = _contextual_no(n)

    # Severity + worsening is a combined question in the existing questionnaire.
    if last_question == "severity":
        sev = _extract_number_0_10(n)
        if sev is not None:
            out["severity"] = sev
        worsening_pos = bool(re.search(
            r"\b(?:getting worse|much worse|became worse|worsening|worsened|"
            r"worse now|has gotten worse|got worse)\b", n
        ))
        worsening_neg = bool(re.search(
            r"\b(?:not getting worse|isn't getting worse|is not getting worse|"
            r"hasn't gotten worse|has not gotten worse|not worse|stable|"
            r"staying the same|no change|unchanged)\b", n
        ))
        if worsening_neg:
            out["recent_worsening"] = False
        elif worsening_pos:
            out["recent_worsening"] = True

    elif last_question in {"duration"}:
        duration = _duration_from_text(n)
        if duration:
            out["duration"] = duration
        elif re.search(r"\b(?:since yesterday|from yesterday)\b", n):
            out["duration"] = "1 day"
        elif re.search(r"\b(?:a couple of|couple of)\s+days?\b", n):
            out["duration"] = "2 days"
        elif re.search(r"\b(?:a few|several)\s+days?\b", n):
            out["duration"] = "3 days"

    elif last_question == "age":
        m = re.search(r"\b(?:i am|i'm|im|age is|aged)\s*(\d{1,3})\b|\b(\d{1,3})\s*(?:years?\s*old)\b", n)
        if m:
            v = int(next(x for x in m.groups() if x is not None))
            if 0 <= v <= 120:
                out["age"] = v
        elif re.fullmatch(r"\d{1,3}", n):
            v = int(n)
            if 0 <= v <= 120:
                out["age"] = v

    elif last_question == "incomplete_evacuation":
        if _contextual_no(n) or re.search(r"\b(?:completely|fully|totally)\s+(?:empty|emptied)\b", n):
            out["incomplete_evacuation"] = False
        elif (bare_yes or re.search(r"\b(?:incomplete|not completely empty|not fully empty|still feel like i need to go|sometimes)\b", n)):
            out["incomplete_evacuation"] = True

    elif last_question == "bloating_pain":
        # Accept natural variants such as "does improve after a bowel
        # movement", not only the imperative-looking "improves after".
        if re.search(r"\b(?:does|doesn't|does not|is|isn't|is not)\s+(?:improve|improves|get better|gets better|feel better|feels better)\s+after\s+(?:a\s+)?(?:bowel movement|stool|poop)", n):
            out["pain_related_to_bowel_movement"] = not bool(re.search(r"\b(?:doesn't|does not|isn't|is not)\b", n))
        elif re.search(r"\b(?:improves|gets better|feels better|better|relieved)\s+after\s+(?:a\s+)?(?:bowel movement|stool|poop)", n):
            out["pain_related_to_bowel_movement"] = True

    elif last_question in {"weight_loss", "weight_loss_duration"}:
        if re.search(r"\b(?:gained|put on)\s+(?:a little\s+)?weight\b", n) or negative:
            out["weight_loss"] = False
        elif re.search(r"\b(?:lost|losing|loss of)\s+(?:any\s+|significant\s+|a lot of\s+)?weight\b", n) or bare_yes:
            out["weight_loss"] = True

    elif last_question in {"vomiting_fever", "vomiting_fever_swelling"}:
        # Explicit per-item answers take precedence over a global "no".
        vom_pos = bool(re.search(r"\b(?:vomit(?:ing)?|throwing up)\b", n))
        fever_pos = bool(re.search(r"\b(?:fever|high temperature|temperature)\b", n))
        vom_neg = bool(re.search(r"\b(?:no|not|never|without)\b.{0,35}\b(?:vomit(?:ing)?|throwing up)\b", n))
        fever_neg = bool(re.search(r"\b(?:no|not|never|without)\b.{0,35}\b(?:fever|high temperature)\b", n))
        if vom_neg or re.fullmatch(r"not that i know of", n) or (bare_no and not fever_pos):
            out["vomiting"] = False
        elif vom_pos:
            out["vomiting"] = True
        if fever_neg or re.fullmatch(r"not that i know of", n) or (bare_no and not vom_pos):
            out["fever"] = False
        elif fever_pos:
            out["fever"] = True
        if last_question == "vomiting_fever_swelling":
            swell_pos = bool(re.search(r"\b(?:severe\s+)?(?:abdominal\s+)?(?:swelling|distension|very swollen)\b", n))
            swell_neg = bool(re.search(r"\b(?:no|not|never|without)\b.{0,35}\b(?:swelling|distension|swollen)\b", n))
            if swell_neg or (bare_no and not (vom_pos or fever_pos)):
                out["swelling"] = False
            elif swell_pos:
                out["swelling"] = True

    elif last_question == "bowel_pattern":
        normal = bool(re.search(
            r"\b(?:normal|fine|regular)\s+(?:poops?|stools?|bowel movements?|bowels?)\b|"
            r"\b(?:my|the)\s+(?:poops?|stools?|bowel movements?|bowels?)\s+(?:are|is)\s+(?:normal|fine|regular)\b|"
            r"\beverything\s+is\s+(?:normal|fine|regular)\b|\bnormal\b", n
        ))
        const_pos = bool(re.search(
            r"\b(?:constipat(?:ed|ion)|hard\s+(?:stools?|poop)|trouble\s+passing\s+stool|"
            r"difficulty\s+(?:passing|having)\s+(?:stool|bowel movements?)|"
            r"don't\s+poop\s+regularly|do not\s+poop\s+regularly|haven't\s+been\s+able\s+to\s+poop|"
            r"not\s+able\s+to\s+poop)\b", n
        ))
        diarr_pos = bool(re.search(r"\b(?:diarrh(?:ea|oea)|loose\s+(?:stools?|motions?)|watery\s+(?:stools?|poop))\b", n))
        both = bool(re.search(r"\b(?:both|alternat(?:e|ing)|sometimes\s+constipat(?:ed|ion).{0,50}(?:diarrh|loose\s+stools?)|(?:diarrh|loose\s+stools?).{0,50}sometimes\s+constipat)\b", n))
        const_neg = bool(re.search(r"\b(?:no|not|never|without|don't|dont|do not)\b.{0,35}\b(?:constipat(?:ion|ed)|hard\s+(?:stools?|poop))\b", n))
        diarr_neg = bool(re.search(r"\b(?:no|not|never|without|don't|dont|do not)\b.{0,35}\b(?:diarrh(?:ea|oea)|loose\s+(?:stools?|motions?)|watery)\b", n))
        const_pos = const_pos and not const_neg
        diarr_pos = diarr_pos and not diarr_neg
        if both:
            out["bowel_pattern"] = "mixed"
        elif normal and not const_pos and not diarr_pos:
            out["bowel_pattern"] = "normal"
            out["constipation"] = False
            out["loose_stools"] = False
        elif const_pos and diarr_pos:
            out["bowel_pattern"] = "mixed"
            out["constipation"] = True
            out["loose_stools"] = True
        elif const_pos:
            out["bowel_pattern"] = "constipation"
            out["constipation"] = True
            out["loose_stools"] = False if diarr_neg else None
        elif diarr_pos:
            out["bowel_pattern"] = "diarrhea"
            out["loose_stools"] = True
            out["constipation"] = False if const_neg else None
        elif bare_no or (const_neg and diarr_neg):
            out["bowel_pattern"] = "normal"
            out["constipation"] = False
            out["loose_stools"] = False

    elif last_question == "pain":
        # This question is a single conjunctive proposition in the
        # questionnaire ("Do you have recurring abdominal pain that changes
        # with bowel movements?" / equivalent wording). Therefore a bare
        # "yes" or "no" answers the whole proposition, unlike an OR-style
        # composite safety question where "yes" would be ambiguous.
        pain_neg = bool(re.search(
            r"\b(?:no|not|never|without|don't|dont|do not|doesn't|does not)\b.{0,45}\b(?:abdominal pain|stomach pain|belly pain|cramps?|pain)\b", n
        ))
        bowel_pos = bool(re.search(
            r"\b(?:after\s+(?:a\s+)?(?:bowel movement|stool|poop)|when\s+i\s+poop|related\s+to\s+(?:bowel movements?|stool)|changes?\s+with\s+(?:bowel movements?|stool)|improves?\s+after\s+(?:a\s+)?(?:bowel movement|stool)|worse?\s+after\s+(?:a\s+)?(?:bowel movement|stool))\b", n
        ))
        bowel_neg = bool(re.search(
            r"\b(?:not|isn't|is not|never|without)\b.{0,35}\b(?:related to\s+)?(?:bowel movements?|stool|poop)\b", n
        ))
        pain_pos = bool(re.search(
            r"\b(?:abdominal pain|stomach pain|belly pain|stomach ache|cramps?|cramping|i do have some pain|i have some pain|i have pain)\b", n
        ))

        if bare_yes:
            out["pain"] = True
            out["abdominal_pain"] = True
            out["pain_related_to_bowel_movement"] = True
        elif bare_no:
            out["pain"] = False
            out["abdominal_pain"] = False
            out["pain_related_to_bowel_movement"] = False
        elif pain_neg and not pain_pos:
            out["pain"] = False
            out["abdominal_pain"] = False
            # If the user explicitly denies pain, there is no pain relation
            # to collect for this conjunctive question.
            out["pain_related_to_bowel_movement"] = False
        else:
            if pain_pos:
                out["pain"] = True
                out["abdominal_pain"] = True
            if bowel_pos and not bowel_neg:
                out["pain_related_to_bowel_movement"] = True
            elif bowel_neg:
                out["pain_related_to_bowel_movement"] = False

    elif last_question in {"pain_relation", "food_relation"}:
        meal_pos = bool(re.search(r"\b(?:after\s+(?:meals?|eating|food)|when\s+i\s+eat|whenever\s+i\s+eat|related\s+to\s+meals?|triggered\s+by\s+meals?)\b", n))
        bowel_pos = bool(re.search(r"\b(?:after\s+(?:a\s+)?(?:bowel movement|stool|poop)|when\s+i\s+poop|related\s+to\s+(?:bowel movements?|stool)|changes?\s+with\s+(?:bowel movements?|stool))\b", n))
        meal_neg = bool(re.search(r"\b(?:not|isn't|is not|never)\b.{0,30}\b(?:meals?|eating|food)\b", n))
        bowel_neg = bool(re.search(r"\b(?:not|isn't|is not|never)\b.{0,30}\b(?:bowel movements?|stool|poop)\b", n))
        # Natural short answers to the explicit either/or question are common
        # in chat UI flows (for example: "meals" or "bowel movements").
        # When this question is active, these phrases are unambiguous even
        # without "related to" / "after" wording.
        meal_choice = bool(re.fullmatch(
            r"(?:meals?|food|eating|after meals?|after eating)", n
        ))
        bowel_choice = bool(re.fullmatch(
            r"(?:bowel movements?|bowel movement|stools?|poops?|poop|stool)", n
        ))
        if meal_pos and not meal_neg or meal_choice:
            out["meal_relation"] = True
            out["pain_relation"] = "meals"
            out["food_related"] = True
        elif bowel_pos and not bowel_neg or bowel_choice:
            out["pain_relation"] = "bowel_movements"
        elif bare_no:
            out["meal_relation"] = False
            out["pain_relation"] = "none"
            out["food_related"] = False
        # bare yes is intentionally unresolved: "yes" cannot choose meals vs stool.

    elif last_question == "pain_location":
        if re.search(r"\b(?:upper\s+(?:abdomen|stomach|belly)|upper\s+stomach|upper\s+belly)\b", n):
            out["pain_location"] = "upper abdomen"
        elif re.search(r"\b(?:lower\s+(?:abdomen|stomach|belly)|lower\s+stomach|lower\s+belly)\b", n):
            out["pain_location"] = "lower abdomen"
        elif re.search(r"\b(?:right\s+(?:side|abdomen|stomach|belly))\b", n):
            out["pain_location"] = "right side"
        elif re.search(r"\b(?:left\s+(?:side|abdomen|stomach|belly))\b", n):
            out["pain_location"] = "left side"
        elif re.search(r"\b(?:around\s+(?:the\s+)?navel|belly button)\b", n):
            out["pain_location"] = "around navel"

    elif last_question == "reflux":
        positive = bool(re.search(r"\b(?:sour taste|acid coming back up|acid reflux|food coming back up|regurgitation)\b", n))
        negative_reflux = bool(re.search(r"\b(?:no|not|never|without|don't|dont|do not|doesn't|does not)\b.{0,40}\b(?:acid|reflux|sour taste|food coming back up|that)\b", n))
        if bare_no or negative_reflux:
            out["reflux_present"] = False
        elif positive or bare_yes:
            out["reflux_present"] = True

    elif last_question in {"triggers", "food_trigger", "trigger"}:
        # Food-trigger questions are finite-choice questions. Resolve common
        # food categories deterministically so a short answer such as
        # "dairy" never requires an LLM call.
        trigger = extract_food_trigger(message)
        if trigger:
            out["food_trigger"] = trigger
            out["food_related"] = True
        elif re.search(r"\b(?:no|none|nothing|no particular food|not related to any food|no known trigger)\b", n):
            out["food_related"] = False

    elif last_question == "stool_form":
        # This question is phrased as an optional Bristol-type question.
        # A user who does not know the type has answered the question by
        # explicitly declining/unknowning it; do not trap them in the same
        # question forever. Otherwise accept a numeric Bristol type or a
        # clear consistency description (hard/loose/watery).
        if (
            re.fullmatch(r"(?:i\s+)?(?:dont|don't|do not|don t)\s+know", n)
            or re.fullmatch(r"(?:not sure|unsure|no idea|i have no idea)", n)
            or re.fullmatch(r"i(?:\s+am| m)?\s+not\s+sure", n)
            or re.fullmatch(r"(?:i\s+)?(?:cant|can t)\s+tell", n)
        ):
            out["stool_form"] = "unknown"
        else:
            value = extract_stool_form(message)
            if value is not None:
                out["stool_form"] = value

    elif last_question == "timing":
        m = re.search(r"\b(?:right\s+after|immediately\s+after|straight\s+after)\s+(?:i\s+)?eat(?:ing)?\b", n)
        if m:
            out["meal_timing"] = "immediately_after_eating"
            out["symptom_onset_after_food"] = "immediately after eating"
            out["timing_relation"] = "after_eating"
        else:
            m = re.search(r"\b(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\s*(?:later|after\s+(?:i\s+)?eat(?:ing)?)\b", n)
            if m:
                out["symptom_onset_after_food"] = f"{m.group(1)} {m.group(2)} after eating"
                out["meal_timing"] = "after_eating"
                out["timing_relation"] = "after_eating"
            else:
                word_time = re.search(r"\b(one|two|three|four|five|six)\s+(minutes?|hours?)\s+(?:later|after)\b", n)
                if word_time:
                    out["symptom_onset_after_food"] = f"{word_time.group(1)} {word_time.group(2)} after eating"
                    out["meal_timing"] = "after_eating"
                    out["timing_relation"] = "after_eating"
                elif re.search(r"\b(?:a\s+few|several)\s+hours?\s+(?:later|after)\b", n):
                    out["symptom_onset_after_food"] = "several hours after eating"
                    out["meal_timing"] = "after_eating"
                    out["timing_relation"] = "after_eating"
                elif re.search(r"\b(?:after\s+(?:meals?|eating|food)|after\s+dinner)\b", n):
                    out["meal_timing"] = "after_eating"
                    out["timing_relation"] = "after_eating"
                elif re.search(r"\b(?:when|while)\s+(?:i\s+)?(?:lie|lying)\s+down\b", n):
                    out["meal_timing"] = "when_lying_down"
                    out["timing_relation"] = "lying_down"
                elif re.search(r"\b(?:at|during)\s+night\b", n):
                    out["meal_timing"] = "at_night"
                    out["timing_relation"] = "at_night"
                elif re.search(r"\b(?:not\s+related\s+to\s+meals?|not\s+after\s+(?:meals?|eating)|not\s+meal[- ]related)\b", n):
                    out["meal_timing"] = "not_meal_related"
                    out["timing_relation"] = "not_meal_related"

    # Shared natural facts can be volunteered while answering any question.
    if re.search(r"\b(?:upper\s+(?:abdomen|stomach|belly)|upper\s+stomach|upper\s+belly)\b", n):
        out["pain_location"] = "upper abdomen"
    elif re.search(r"\b(?:lower\s+(?:abdomen|stomach|belly)|lower\s+stomach|lower\s+belly)\b", n):
        out["pain_location"] = "lower abdomen"

    if re.search(r"\b(?:after\s+(?:meals?|eating|food)|when\s+i\s+eat|whenever\s+i\s+eat|related\s+to\s+meals?|triggered\s+by\s+meals?)\b", n):
        if not re.search(r"\b(?:not|isn't|is not|never)\b.{0,30}\b(?:meals?|eating|food)\b", n):
            out["meal_relation"] = True
            out["food_related"] = True

    if re.search(r"\b(?:my|the)\s+(?:bowel movements?|bowels?|stools?|poops?)\s+(?:are|is)\s+(?:normal|fine|regular)\b|\beverything\s+is\s+(?:normal|fine|regular)\b", n):
        out["bowel_pattern"] = "normal"
        out["constipation"] = False
        out["loose_stools"] = False

    duration = _duration_from_text(n)
    if duration and out.get("duration") is None:
        out["duration"] = duration
    age_match = re.search(r"\b(?:i am|i'm|im|age is|aged)\s*(\d{1,3})\b", n)
    if age_match and out.get("age") is None:
        out["age"] = int(age_match.group(1))

    # A bare/approximate number in an active non-severity question must not
    # become a pain score (e.g. "around 3 litres" -> severity 3).
    if last_question == "severity":
        sev = _extract_number_0_10(n)
        if sev is not None and out.get("severity") is None:
            out["severity"] = sev

    # Negated/positive worsening is useful even outside the severity question.
    if out.get("recent_worsening") is None:
        if re.search(r"\b(?:not getting worse|isn't getting worse|is not getting worse|hasn't gotten worse|has not gotten worse|stable|unchanged|no change)\b", n):
            out["recent_worsening"] = False
        elif re.search(r"\b(?:getting worse|much worse|became worse|worsening|worsened|worse now)\b", n):
            out["recent_worsening"] = True

    return out


def _is_generic_negative(n: str) -> bool:
    """Recognize a context-free negative that can only be resolved by the active question."""
    compact = re.sub(r"[\s,.;!?]+", " ", n).strip()
    return bool(re.fullmatch(
        r"(?:no|nope|nah|not really|not at all|none|nothing|"
        r"no i don't|no i do not|i don't|i do not|i dont|i do not|"
        r"i haven't|i have not|i havent|there isn't any|there is not any|"
        r"there isn't|there is not|i don't have it|i don't have that|"
        r"i do not have it|i do not have that|i dont have it|i dont have that|"
        r"i haven't got it|i have not got it|false)",
        compact,
    ))


def _deterministic_context_fallback(message: str, last_question: str | None, state) -> dict:
    """Small high-value fallback for common conversational forms.

    This is intentionally not a giant synonym table. It exists so a temporary
    LLM/API failure never turns a valid answer into IRRELEVANT.
    """
    n = _norm_answer_text(message)
    out = _question_specific_fallback(message, last_question, state)

    # Question-aware yes/no.
    negative = bool(re.search(
        r"\b(?:no|nope|nah|not really|not at all|none|nothing|"
        r"i don't|i do not|i haven't|i have not|i dont|i havent|never)\b",
        n,
    ))
    affirmative = bool(re.search(r"\b(yes|yeah|yep|i do|i have|that's right|correct|definitely)\b", n))
    generic_negative = _is_generic_negative(n)

    if last_question in {"blood", "bleeding"}:
        if generic_negative or re.search(r"\b(?:no|not|never|without|don't|dont|do not|haven't|have not)\b.*\b(?:blood|bleeding)\b", n):
            out["bleeding"] = False
        elif affirmative or re.search(r"\b(blood|bleeding)\b", n):
            out["bleeding"] = True
    elif last_question in {"lump", "lump_or_prolapse"}:
        if generic_negative or re.search(r"\b(?:no|not|never|without|don't|dont|do not|haven't|have not)\b.*\b(?:lump|prolapse|bulge|bump)\b", n):
            out["lump_or_protrusion"] = False
        elif affirmative or re.search(r"\b(lump|prolapse|bulge|bump|comes out|protrud)\b", n):
            out["lump_or_protrusion"] = True
    elif last_question == "age":
        m_age = re.search(r"\b(?:i am|i'm|im|age is|aged)?\s*(\d{1,3})\s*(?:years?\s*old)?\b", n)
        if m_age:
            value = int(m_age.group(1))
            if 0 <= value <= 120:
                out["age"] = value
    elif last_question in {"weight_loss", "weight_loss_duration"}:
        out["weight_loss"] = False if generic_negative or re.search(r"\b(?:no|not|never|without|don't|dont|do not|haven't|have not)\b.*\b(?:weight|lost weight)\b", n) or re.search(r"\bgained\s+(?:a little\s+)?weight\b", n) else True if affirmative or re.search(r"\b(?:lost|losing)\s+(?:a lot of\s+|significant\s+)?weight\b", n) else None
    elif last_question == "anal_pain":
        out["pain"] = False if generic_negative or re.search(r"\b(?:no|not|never|without|don't|dont|do not|haven't|have not)\b.*\b(?:pain|hurt|hurts|tearing|sharp|cutting)\b", n) else True if affirmative or re.search(r"\b(pain|sharp|tearing|cutting)\b", n) else None
        if out["pain"] is True and re.search(r"\b(sharp|tearing|cutting)\b", n):
            out["pain_character"] = "sharp/tearing"
    elif last_question in {"stool_straining", "constipation"}:
        no_answer = n in {"no", "nope", "nah", "none", "false"}
        yes_answer = n in {"yes", "yeah", "yep", "yup", "sure", "true"}
        explicit_no_constipation = bool(re.search(
            r"\b(?:no|not|never|without|dont|don't|do not)\s+"
            r"(?:have\s+)?(?:any\s+)?(?:constipation|constipated)\b", n
        ))
        explicit_constipation = bool(re.search(r"\b(constipation|constipated)\b", n))

        normal_pooping = bool(re.search(r"\b(?:normal|regular|fine)\s+(?:poop(?:ing)?|stools?|bowel movements?)\b", n))
        no_strain = bool(re.search(r"\b(?:no|not|never|don't|dont|do not)\s+(?:have to\s+)?strain(?:ing)?\b", n))
        # This is a combined constipation/stool-straining question. A clear
        # negative therefore answers the combined slot; it is not a global
        # "no means false" rule.
        if no_answer or generic_negative or explicit_no_constipation:
            out["straining"] = False
            out["hard_stools"] = False
            out["constipation"] = False
        elif no_strain:
            out["straining"] = False
        if normal_pooping:
            out["hard_stools"] = False
            if no_strain:
                out["constipation"] = False
        elif re.search(r"\b(no|not|don't|dont|do not|without)\b.*\b(strain|straining)\b", n):
            out["straining"] = False
        elif re.search(r"\b(strain|straining|push hard|pushing hard)\b", n):
            out["straining"] = True

        if re.search(r"\b(no|not|don't|dont|do not|without)\b.*\b(hard|lumpy|firm)\b|\b(normal|soft)\s+(?:stools?|poop|stool)\b", n):
            out["hard_stools"] = False
        elif re.search(r"\b(hard|lumpy|firm)\s+(?:stools?|poop|stool)\b|\b(?:stools?|poop|poo)\s+(?:are|is)\s+(?:hard|lumpy|firm)\b", n):
            out["hard_stools"] = True

        if explicit_constipation or yes_answer:
            out["constipation"] = True

    elif last_question == "hard_stools":
        if generic_negative or re.search(r"\b(?:no|not|never|without|aren't|are not|isn't|is not|don't|dont|do not)\b.*\b(?:hard|lumpy|firm)\b", n) or re.search(r"\b(?:stools?|poop|poo)\s+(?:aren't|are not|isn't|is not)\s+(?:hard|lumpy|firm)\b", n):
            out["hard_stools"] = False
        elif affirmative or re.search(r"\b(?:hard|lumpy|firm)\s+(?:stools?|poop|poo)\b", n):
            out["hard_stools"] = True

    elif last_question == "straining":
        if generic_negative or re.search(r"\b(?:no|not|never|without|don't|dont|do not)\b.*\b(?:strain|straining)\b", n):
            out["straining"] = False
        elif affirmative or re.search(r"\b(?:strain|straining|push hard|pushing hard)\b", n):
            out["straining"] = True

    if last_question == "duration":
        duration = _duration_from_text(n)
        if duration:
            out["duration"] = duration
        elif re.search(r"\b(a couple of|couple of)\s+days\b", n):
            out["duration"] = "2 days"
        elif re.search(r"\b(a few|several)\s+days\b", n):
            out["duration"] = "3 days"
    elif last_question in {"weight_loss", "weight_loss_duration"}:
        out["weight_loss"] = False if generic_negative or re.search(r"\b(?:no|not|never|without|don't|dont|do not|haven't|have not)\b.*\b(?:weight|lost weight)\b", n) or "gained weight" in n else True if affirmative or "lost weight" in n else None
    # stool/strain is handled in the question-aware block above.
    elif last_question in {"anal_pain", "pain_relation"}:
        out["pain"] = False if generic_negative or re.search(r"\b(?:no|not|never|without|don't|dont|do not|haven't|have not)\b.*\b(?:pain|hurt|hurts|tearing|sharp|cutting)\b", n) else True if affirmative or re.search(r"\b(pain|sharp|tearing|cutting)\b", n) else None
        if not negative and re.search(r"\b(sharp|tearing|cutting)\b", n):
            out["pain_character"] = "sharp/tearing"
    elif last_question == "blood_colour":
        if re.search(r"\b(bright|fresh|red)\b", n):
            out["blood_type"] = "bright_red"
        elif re.search(r"\b(black|tarry|dark)\b", n):
            out["blood_type"] = "black"
    elif last_question == "blood_location":
        if re.search(r"\b(tissue|toilet paper|wipe|wiping)\b", n):
            out["blood_location"] = "tissue"
        elif re.search(r"\b(drip|dripping)\b", n):
            out["blood_location"] = "dripping"
        elif re.search(r"\bmixed\b", n):
            out["blood_location"] = "mixed"

    # High-value free-text symptom patterns. These complement, rather than
    # replace, the existing parser.
    if re.search(r"\b(anal area|around my anus|near my rectum|back passage|butt|pain when i poop|pain when i poo)\b", n):
        out["body_areas"].append("anal")
        if not re.search(r"\b(itch(y|ing)|irritat(ed|ion)|discomfort|soreness)\b", n) or re.search(r"\b(pain|hurts?|painful|sharp|tearing|cutting)\b", n):
            out["pain"] = True
        if re.search(r"\b(severe|badly|really painful|a lot of pain)\b", n):
            out["severity"] = "severe"
        # Keep the branch within existing clinical categories. A pain-only
        # anal complaint is assessed as an anal-fissure-compatible symptom,
        # not diagnosed as a fissure.
        if not state.primary_symptom and out.get("pain") is True:
            out["symptoms"].append("anal fissures")
    if (
        not re.search(r"\b(?:no|not|don't|dont|do not)\s+(?:have\s+)?(?:any\s+)?(?:sharp|tearing|cutting)\s+pain\b", n)
        and re.search(r"\b(sharp|tearing|cutting)\b.*\b(po|stool|bowel movement|after i poop|after pooping)\b", n)
    ):
        out["pain_character"] = "sharp/tearing"
        out["pain"] = True
        out["symptoms"].append("anal fissures")
    if re.search(r"\b(bright red|fresh blood|red blood)\b", n):
        out["bleeding"] = True
        out["blood_type"] = "bright_red"
    if re.search(r"\b(on (the )?(toilet )?(paper|tissue)|when i wipe|wiping)\b", n):
        out["bleeding"] = True
        out["blood_location"] = "tissue"
    if re.search(r"\b(blood|bleeding)\b", n) and not re.search(r"\b(?:no|not|never|without|don't|dont|do not|haven't|have not)\b.*\b(?:blood|bleeding)\b", n):
        out["bleeding"] = True
        out["symptoms"].append("bleeding")
    if re.search(r"\bitch(y|ing)\b", n):
        out["itching"] = False if negative else True
        if not negative and re.search(r"\b(anal area|around my anus|near my rectum|back passage|butt)\b", n):
            # Keep this as an irritation/symptom branch. Do not convert
            # itching alone into a fissure or hemorrhoid diagnosis.
            out["symptoms"].append("anal burning")
    if re.search(r"\bbloat(ed|ing)?\b|\bbelly feels swollen\b|\bstomach feels full of air\b", n):
        out["symptoms"].append("bloating")
    if re.search(r"\b(lots of gas|a lot of gas|excess gas|gassy|farting a lot|passing gas)\b", n):
        out["symptoms"].append("gas")
        out["gas"] = True
    if re.search(r"\b(can't|cant|cannot|not able to|haven't|havent|don't|dont|do not).{0,35}\b(po(o)?p|pass stool|bowel movement|go to the toilet)\b", n):
        out["symptoms"].append("constipation")
        out["constipation"] = True
    if re.search(r"\b(no|not|don't|dont|do not|never)\s+(?:have\s+)?(?:hard stools?|hard poop|lumpy stools?)\b", n):
        out["hard_stools"] = False
    elif re.search(r"\b(hard stools?|hard poops?|hard poos?|hard poop|hard poo|lumpy stools?|poops? are hard|stool is hard|poop is hard)\b", n):
        out["hard_stools"] = True
        out["symptoms"].append("hard stools")

    if re.search(r"\b(no|not|don't|dont|do not|without)\s+(?:have to\s+|need to\s+)?strain(?:ing)?\b", n):
        out["straining"] = False
    elif re.search(r"\b(strain|straining|push hard|pushing hard)\b", n):
        out["straining"] = True
    if re.search(r"\b(no|not|don't|dont|do not|never)\s+(?:have\s+)?(?:diarrhea|diarrhoea|loose stools?|loose motions?|watery stools?)\b", n):
        out["loose_stools"] = False
        out["symptoms"] = [x for x in out["symptoms"] if x != "diarrhea"]
    elif re.search(r"\b(loose stools?|loose motions?|watery stools?|diarrh)", n):
        out["symptoms"].append("diarrhea")
        out["loose_stools"] = True
    if re.search(r"\b(heartburn|acid coming up|burning in (my )?(chest|throat)|burning after meals)\b", n):
        out["symptoms"].append("heartburn")
    if re.search(r"\b(acid reflux|acidity|acidic)\b", n):
        out["symptoms"].append("acidity")
    if re.search(r"\b(piles|haemorrhoids|hemorrhoids)\b", n):
        out["symptoms"].append("piles")
    if re.search(r"\b(stomach pain|stomach ache|belly pain|abdominal pain|belly ache)\b", n):
        out["symptoms"].append("stomach pain")

    # Lifestyle/medication answers are contextual facts too. Keep them in
    # NLU so the active-question resolver does not depend on exact spelling.
    water_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:litres?|liters?|litters?|l)\b", n)
    if water_match:
        out["water_intake"] = water_match.group(1) + " L"
    else:
        word_litres = re.fullmatch(r"(one|two|three|four|five|six)\s*(?:litres?|liters?|litters?|l)", n)
        if word_litres:
            out["water_intake"] = {"one":"1", "two":"2", "three":"3", "four":"4", "five":"5", "six":"6"}[word_litres.group(1)] + " L"
    if re.search(r"\b(?:no medicines|no medication|no medications|not taking medicines|not taking medication|no regular medicines|no regular medication|not on medication)\b", n):
        out["medications"] = "none"
    elif re.search(r"\b(?:taking medicine|taking medication|taking medicines|taking supplements|regular medication|regular medicines|on medication|on medicines|i take|i'm taking|im taking)\b", n):
        out["medications"] = "reported"
    if re.search(r"\b(?:low|little|poor)\s+(?:fibre|fiber)\b", n):
        out["fibre_intake"] = "low"
    elif re.search(r"\b(?:high|good)\s+(?:fibre|fiber)\b", n):
        out["fibre_intake"] = "high"
    elif re.search(r"\b(?:average|normal)\s+(?:fibre|fiber)\b", n):
        out["fibre_intake"] = "average"

    # Generic duration extraction anywhere in a long message.
    if out["duration"] is None:
        out["duration"] = _duration_from_text(n)

    if out["age"] is None:
        m_age = re.search(r"\b(?:i am|i'm|im|age is|aged)\s*(\d{1,3})\b", n)
        if m_age:
            out["age"] = int(m_age.group(1))

    if re.search(r"\b(haven't|have not|dont|don't|not|no)\s+(?:really\s+)?(?:lost|lose)\s+(?:any\s+)?(?:significant\s+)?weight\b|\bgained\s+(?:a little\s+)?weight\b", n):
        out["weight_loss"] = False
    elif re.search(r"\b(lost|losing)\s+(?:a lot of\s+|significant\s+)?weight\b", n):
        out["weight_loss"] = True

    if re.search(r"\b(no|not|don't|dont|do not)\s+(?:have\s+)?constipation\b|\bnot constipated\b", n):
        out["constipation"] = False
    elif re.search(r"\b(constipation|constipated|can't|cant|cannot|not able to)\b", n) and re.search(r"\b(po?o?p|poo|stool|bowel|constipat)", n):
        out["constipation"] = True

    if re.search(r"\b(piles|haemorrhoids|hemorrhoids)\b", n):
        if "piles" not in out["symptoms"]:
            out["symptoms"].append("piles")

    if re.search(r"\b(much worse|getting worse|became worse|worsened|worse now)\b", n):
        out["recent_worsening"] = True

    # Active-question extraction is authoritative. Generic keyword rules above
    # may see words such as "diarrhea" or "worse" inside a negated phrase; never
    # let those generic matches overwrite the contextual interpretation.
    qfacts = _question_specific_fallback(message, last_question, state)
    if last_question:
        for key in (
            "severity", "recent_worsening", "duration", "age", "weight_loss",
            "vomiting", "fever", "swelling", "bowel_pattern", "constipation",
            "loose_stools", "meal_relation", "pain_relation", "pain_location",
        ):
            if qfacts.get(key) is not None:
                out[key] = qfacts[key]
        if last_question == "bowel_pattern" and qfacts.get("bowel_pattern") == "normal":
            out["constipation"] = False
            out["loose_stools"] = False
            out["symptoms"] = [x for x in out["symptoms"] if x not in {"constipation", "hard stools", "diarrhea"}]
        if last_question == "vomiting_fever" and qfacts.get("vomiting") is False:
            out["vomiting"] = False
        if last_question == "vomiting_fever" and qfacts.get("fever") is False:
            out["fever"] = False

    # A genuine assessment answer is not "unrelated" merely because it has no
    # product/symptom keyword.
    if last_question:
        out["intent"] = "answer_question"
    elif out["symptoms"] or out["bleeding"] is True or out["pain"] is True:
        out["intent"] = "assessment"
    else:
        out["intent"] = "general_question"

    out["symptoms"] = list(dict.fromkeys(out["symptoms"]))
    out["confidence"] = 0.65 if (out["symptoms"] or any(out[k] is not None for k in BOOL_FIELDS) or out["duration"]) else 0.2
    return out


def _needs_llm(message: str, last_question: str | None, fallback: dict) -> bool:
    """Use the LLM for ambiguity/complexity, not for trivial deterministic answers."""
    n = re.sub(r"\s+", " ", (message or "").lower()).strip()
    if not n:
        return False

    # Very short, unambiguous answers are cheaper and safer to parse locally.
    simple = [
        r"^\d+(?:\.\d+)?\s*(?:days?|weeks?|months?|years?)$",
        r"^(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:days?|weeks?|months?|years?)$",
        r"^\d{1,3}(?:\s*years?\s*old)?$",
        r"^(?:yes|yeah|yep|yup|no|nope|nah|none|true|false)$",
        r"^(?:bright|fresh|bright red|fresh red|red|black|dark|tarry)(?:\s+(?:red|blood|stool))?$",
        r"^(?:on )?(?:tissue|toilet paper|paper|dripping|mixed)$",
        r"^(?:low|average|normal|high|good)(?:\s+(?:fibre|fiber))?$",
    ]
    if last_question and any(re.fullmatch(p, n) for p in simple):
        return False

    # If the pending question has a high-confidence local answer, do not spend
    # an LLM request on a short/medium response. This also avoids malformed
    # model JSON turning an obvious "no" into an empty extraction.
    contextual_fields = {
        "duration": "duration", "age": "age",
        "weight_loss": "weight_loss", "weight_loss_duration": "weight_loss",
        "blood": "bleeding", "blood_colour": "blood_type",
        "blood_location": "blood_location", "anal_pain": "pain",
        "lump": "lump_or_protrusion", "stool_straining": None,
        "constipation": None,
    }
    field = contextual_fields.get(last_question or "")
    if last_question == "stool_straining":
        if fallback.get("hard_stools") is not None or fallback.get("straining") is not None:
            return len(message) > 120
    elif field and fallback.get(field) is not None:
        return len(message) > 120

    # Complex/long messages and messages containing several facts should use
    # the contextual extractor.
    if len(message) > 80 or len(fallback.get("symptoms") or []) > 1:
        return True

    # If deterministic extraction found nothing useful, ask the LLM to
    # understand the natural-language phrasing before giving up.
    useful = (
        fallback.get("duration")
        or fallback.get("age") is not None
        or fallback.get("symptoms")
        or any(fallback.get(k) is not None for k in BOOL_FIELDS)
    )
    if not useful:
        return True

    # Active questions with nuanced prose ("not really, I've gained weight")
    # need contextual interpretation.
    return bool(last_question and len(message) > 25)


def extract_natural_facts(message: str, last_question: str | None, state) -> dict:
    """
    Extract facts with question-aware context.

    Active-question messages are always treated as answers first. The LLM is
    used for ambiguity/complexity; deterministic extraction handles trivial
    answers. If the model fails, the fallback result is returned.
    """
    forced_intent = "answer_question" if last_question else None
    fallback = _deterministic_context_fallback(message, last_question, state)
    llm_result = _llm_extract(message, last_question, state, forced_intent) if _needs_llm(message, last_question, fallback) else None
    if llm_result is None:
        logger.info(
            "[NLU][FALLBACK] model_json_failed_or_unavailable=true deterministic_extraction=true"
        )
        result = fallback
    else:
        result = llm_result
        # Deterministic fallback fills only genuinely missing high-confidence
        # facts. It never overwrites a validated LLM negative with a positive.
        context_fields = {
            "duration": {"duration"},
            "age": {"age"},
            "weight_loss": {"weight_loss"},
            "weight_loss_duration": {"weight_loss"},
            "blood": {"bleeding"},
            "blood_colour": {"blood_type"},
            "blood_location": {"blood_location"},
            "anal_pain": {"pain", "pain_character"},
            "lump": {"lump_or_protrusion"},
            "stool_straining": {"hard_stools", "straining", "constipation"},
            "constipation": {"hard_stools", "straining", "constipation"},
            "timing": {"meal_timing", "symptom_onset_after_food", "timing_relation"},
            "reflux": {"reflux_present"},
            "vomiting_fever": {"vomiting", "fever"},
            "vomiting_fever_swelling": {"vomiting", "fever", "swelling"},
            "swallowing": {"difficulty_swallowing", "persistent_vomiting", "vomiting_blood"},
            "weight_swallow": {"weight_loss", "difficulty_swallowing", "persistent_vomiting", "vomiting_blood"},
            "night_weight_fever": {"weight_loss", "fever"},
        }
        forced_fields = context_fields.get(last_question or "", set())
        for key in ("duration", "blood_type", "blood_location", "age", "severity",
                    "pain_character", "pain_timing", "stool_pattern"):
            if key in forced_fields and fallback.get(key) is not None:
                result[key] = fallback[key]
            elif result.get(key) is None and fallback.get(key) is not None:
                result[key] = fallback[key]
        for key in BOOL_FIELDS:
            if key in forced_fields and fallback.get(key) is not None:
                result[key] = fallback[key]
            elif result.get(key) is None and fallback.get(key) is not None:
                result[key] = fallback[key]
        for key in ("meal_timing", "symptom_onset_after_food", "timing_relation", "reflux_present"):
            if key in forced_fields and fallback.get(key) is not None:
                result[key] = fallback[key]
        for key in ("vomiting", "fever", "swelling", "difficulty_swallowing", "persistent_vomiting", "vomiting_blood"):
            if key in forced_fields and fallback.get(key) is not None:
                result[key] = fallback[key]

        result["symptoms"] = list(dict.fromkeys(
            (result.get("symptoms") or []) + (fallback.get("symptoms") or [])
        ))
        result["new_information"] = list(dict.fromkeys(
            (result.get("new_information") or []) + (fallback.get("new_information") or [])
        ))

    return result
