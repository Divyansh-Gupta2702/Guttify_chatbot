"""Multilingual input/output layer for GutGPT.

The deterministic clinical engine remains English-based. This module translates
user input to English before the engine runs and translates the final response
back to the user's selected language.
"""
import os
from functools import lru_cache
import re

from langchain_groq import ChatGroq
from groq_service import invoke_groq

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_TRANSLATION_MODEL", "openai/gpt-oss-20b")


class TranslationUnavailableError(RuntimeError):
    """Raised when a non-English translation cannot be produced reliably."""


TRANSLATION_ERROR_MESSAGES = {
    "hi-latn": "Abhi jawab taiyar nahi ho pa raha hai. Kripya thodi der baad dobara try karein.",
    "bn": "এই মুহূর্তে আপনার নির্বাচিত ভাষায় উত্তর তৈরি করা যাচ্ছে না। অনুগ্রহ করে একটু পরে আবার চেষ্টা করুন।",
    "mr": "सध्या तुमच्या निवडलेल्या भाषेत उत्तर तयार करता येत नाही. कृपया थोड्या वेळाने पुन्हा प्रयत्न करा.",
    "ta": "தற்போது நீங்கள் தேர்ந்தெடுத்த மொழியில் பதிலை உருவாக்க முடியவில்லை. சிறிது நேரம் கழித்து மீண்டும் முயற்சிக்கவும்.",
    "te": "ప్రస్తుతం మీరు ఎంచుకున్న భాషలో సమాధానం రూపొందించలేకపోతున్నాము. కొంతసేపటి తర్వాత మళ్లీ ప్రయత్నించండి.",
    "gu": "હાલમાં તમારી પસંદ કરેલી ભાષામાં જવાબ તૈયાર કરી શકાતો નથી. કૃપા કરીને થોડા સમય પછી ફરી પ્રયાસ કરો.",
    "kn": "ಈ ಸಮಯದಲ್ಲಿ ನೀವು ಆಯ್ಕೆ ಮಾಡಿದ ಭಾಷೆಯಲ್ಲಿ ಉತ್ತರವನ್ನು ರಚಿಸಲು ಸಾಧ್ಯವಾಗುತ್ತಿಲ್ಲ. ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
    "ml": "ഇപ്പോൾ നിങ്ങൾ തിരഞ്ഞെടുത്ത ഭാഷയിൽ മറുപടി തയ്യാറാക്കാൻ കഴിയുന്നില്ല. കുറച്ച് കഴിഞ്ഞ് വീണ്ടും ശ്രമിക്കുക.",
    "pa": "ਇਸ ਵੇਲੇ ਤੁਹਾਡੀ ਚੁਣੀ ਹੋਈ ਭਾਸ਼ਾ ਵਿੱਚ ਜਵਾਬ ਤਿਆਰ ਨਹੀਂ ਕੀਤਾ ਜਾ ਸਕਦਾ। ਕਿਰਪਾ ਕਰਕੇ ਕੁਝ ਸਮੇਂ ਬਾਅਦ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
    "or": "ବର୍ତ୍ତମାନ ଆପଣ ବାଛିଥିବା ଭାଷାରେ ଉତ୍ତର ପ୍ରସ୍ତୁତ କରିହେଉନାହିଁ। ଦୟାକରି କିଛି ସମୟ ପରେ ପୁଣି ଚେଷ୍ଟା କରନ୍ତୁ।",
}


def translation_error_message(language: str) -> str:
    return TRANSLATION_ERROR_MESSAGES.get(normalize_language(language), "Translation is temporarily unavailable. Please try again shortly.")

SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi-latn": "Hinglish",
    "bn": "Bengali",
    "mr": "Marathi",
    "ta": "Tamil",
    "te": "Telugu",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "or": "Odia",
}


def normalize_language(language: str | None) -> str:
    value = (language or "en").strip().lower().replace("_", "-")
    aliases = {"hinglish": "hi-latn", "hi-latn-in": "hi-latn", "auto": "en", "hindi": "en", "hi": "en"}
    value = aliases.get(value, value)
    return value if value in SUPPORTED_LANGUAGES else "en"


# Common Roman-script Hindi words and phrases used in everyday Hinglish symptom
# descriptions. Detection is intentionally conservative: a few English words such
# as "gas" or "hai" alone should not flip a message into Hinglish.
_HINGLISH_MARKERS = {
    "mujhe", "mujhko", "mera", "meri", "mere", "mein", "me", "pet",
    "dard", "ho", "raha", "rahi", "rahe", "hai", "hain", "hota",
    "hoti", "hote", "nahi", "nahin", "ni", "kya", "kaise", "kab",
    "kyun", "kitna", "kitni", "se", "ko", "ka", "ki", "ke", "aur",
    "lekin", "par", "abhi", "kal", "aaj", "din", "hafte", "mahine",
    "subah", "raat", "khana", "khane", "baad", "pehle", "jalan",
    "gas", "fulna", "phoolna", "kabz", "dast", "motion", "motions",
    "patla", "potty", "khoon", "toilet", "ulti", "matli", "acidity",
    "zyada", "thoda", "bahut", "kam", "baar", "bar", "hoga", "hogi",
    "sakta", "sakti", "sakte", "chahiye", "batao", "batayein", "please",
    "haan", "han", "haa", "ji", "bilkul", "nah", "matlab", "kabhi",
    "roz", "daily", "dopahar", "shaam", "sham", "hafta", "mahina",
    "mahino", "saal", "dakaar", "takleef", "pareshani", "qabz",
}


def detect_input_language(text: str, requested_language: str | None = "en") -> str:
    """Detect English vs Roman-script Hinglish for each individual message.

    Explicit Hinglish remains supported for API clients, but the Shopify widget
    can always send English and let this detector choose the response language.
    Devanagari Hindi is intentionally not a selectable/output language.
    """
    requested = normalize_language(requested_language)
    if requested == "hi-latn":
        return "hi-latn"
    normalized = re.sub(r"[^a-z0-9\s']", " ", (text or "").lower())
    tokens = set(normalized.split())
    marker_count = len(tokens & _HINGLISH_MARKERS)
    # A phrase like "pet dard" or "mujhe gas hai" is a strong signal;
    # otherwise require multiple markers to avoid false positives in English.
    # Short contextual answers are common in Hinglish and may contain only one
    # marker (e.g. "haan", "ji", "raat ko", "do din se"). Detect these before
    # the conservative general rule so the NLU receives translated input.
    short_answer_patterns = (
        r"^(?:haan|han|haa|ji|bilkul|nahi|nahin|ni|nah|matlab|kabhi|kabhi\s*kabhi)$",
        r"^(?:subah|dopahar|shaam|sham|raat|raat\s*ko|subah\s*ko|khane\s*ke\s*baad|khana\s*khane\s*ke\s*baad)$",
        r"^(?:\d+\s*)?(?:din|dino|hafte|hafta|mahine|mahina|mahino|saal)\s*(?:se|tak)?$",
        r"^(?:roz|daily|har\s*roz|zyada|bahut|thoda|kam)$",
    )
    if any(re.fullmatch(pattern, normalized.strip()) for pattern in short_answer_patterns):
        return "hi-latn"
    strong_phrases = (
        r"\bpet\s+(?:me|mein|ka|ki|ke)?\s*(?:dard|gas|jalan|ful|phool)",
        r"\bmujhe\s+.{0,30}\b(?:hai|hain|ho|raha|rahi|rahe)\b",
        r"\b(?:nahi|nahin)\s+(?:hai|hain|ho|hota|hoti)\b",
        r"\b(?:kabz|dast|potty|khoon|ulti|matli)\b",
    )
    if any(re.search(pattern, normalized) for pattern in strong_phrases):
        return "hi-latn"
    if marker_count >= 2:
        return "hi-latn"
    return "en"


@lru_cache(maxsize=1)
def _llm():
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set.")
    return ChatGroq(
        model=GROQ_MODEL,
        temperature=0,
        max_tokens=int(os.environ.get("GROQ_TRANSLATION_MAX_TOKENS", "500")),
        timeout=float(os.environ.get("GROQ_TRANSLATION_TIMEOUT_SECONDS", "25")),
        max_retries=int(os.environ.get("GROQ_TRANSLATION_MAX_RETRIES", "0")),
        api_key=GROQ_API_KEY,
    )


def _invoke(prompt: str) -> str:
    response = invoke_groq(_llm(), prompt, reason="translation")
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content).strip()


# Deterministic translations for common short Hinglish answers. These must be
# handled before the Groq call so simple contextual answers still work during
# provider rate limits. The question resolver remains responsible for applying
# the normalized answer to the active field.
_HINGLISH_SHORT_ANSWERS = {
    "nahi": "no",
    "nahin": "no",
    "nhi": "no",
    "ni": "no",
    "nah": "no",
    "nahi hai": "no",
    "nahin hai": "no",
    "nhi hai": "no",
    "haan": "yes",
    "han": "yes",
    "haa": "yes",
    "ji": "yes",
    "haan ji": "yes",
    "bilkul": "yes",
    "bilkul nahi": "no",
    "kabhi kabhi": "sometimes",
    "kabhi": "sometimes",
    "raat ko": "at night",
    "raat mein": "at night",
    "subah": "in the morning",
    "subah ko": "in the morning",
    "shaam ko": "in the evening",
    "sham ko": "in the evening",
}

def translate_to_english(text: str, language: str) -> str:
    language = normalize_language(language)
    if language == "en" or not text.strip():
        return text

    # Short contextual replies are common in Hinglish. Normalize these locally
    # before translation so a Groq 429/empty response cannot turn "nahi" into an
    # unresolved safety answer. Keep this exact-match only to avoid altering
    # longer sentences or changing clinical meaning.
    if language == "hi-latn":
        normalized_short = re.sub(r"\\s+", " ", text.strip().lower()).strip(" .,!?:;")
        if normalized_short in _HINGLISH_SHORT_ANSWERS:
            return _HINGLISH_SHORT_ANSWERS[normalized_short]

    language_name = SUPPORTED_LANGUAGES[language]
    source_instruction = (
        "Hinglish written in Roman script (Hindi-English mix)" if language == "hi-latn" else language_name
    )
    try:
        translated = _invoke(f"""
Translate the user's message from {source_instruction} to clear, natural English.
This translation will be used by a deterministic gut-health symptom parser.
Preserve the exact meaning of symptoms, yes/no answers, numbers, durations,
severity scores, medicine names, and body-part references.
Do not answer the user. Do not add, remove, diagnose, or interpret anything.
Return ONLY the English translation.

USER MESSAGE:
{text}
""")
    except Exception as exc:
        raise TranslationUnavailableError("Input translation failed") from exc
    if not translated:
        raise TranslationUnavailableError("Input translation returned no content")
    return translated


def _looks_translated(text: str, source: str, language: str) -> bool:
    """Best-effort guard against the LLM returning the English source unchanged."""
    if not text or not text.strip():
        return False
    if language == "en":
        return True

    # Exact/near-exact English output is the most common failure mode we need
    # to catch. Product names and URLs are allowed to remain in Latin script.
    if text.strip().lower() == source.strip().lower():
        return False

    script_ranges = {
        "hi": ("\u0900", "\u097f"),
        "mr": ("\u0900", "\u097f"),
        "bn": ("\u0980", "\u09ff"),
        "pa": ("\u0a00", "\u0a7f"),
        "gu": ("\u0a80", "\u0aff"),
        "ta": ("\u0b80", "\u0bff"),
        "te": ("\u0c00", "\u0c7f"),
        "kn": ("\u0c80", "\u0cff"),
        "ml": ("\u0d00", "\u0d7f"),
        "or": ("\u0b00", "\u0b7f"),
    }
    if language in script_ranges:
        lo, hi = script_ranges[language]
        script_letters = sum(1 for ch in text if lo <= ch <= hi)
        alphabetic = sum(1 for ch in text if ch.isalpha())
        # Product names/URLs may remain Latin, but a long medical answer should
        # still contain substantial target-script text. The threshold is kept
        # below 100% so brand names and URLs do not cause false failures.
        if script_letters < 4:
            return False
        if alphabetic <= 20:
            return script_letters >= max(4, alphabetic * 0.20)
        return script_letters >= max(6, alphabetic * 0.20)

    return text.strip() != source.strip()


def _translation_prompt(text: str, language: str) -> str:
    language_name = SUPPORTED_LANGUAGES[language]
    target_instruction = (
        "Write the entire user-facing response in natural conversational Hinglish, using Hindi-English "
        "mix in Roman script (Latin letters), as commonly used in India. Do not use Devanagari."
        if language == "hi-latn" else
        f"Write the entire user-facing response in natural, easy-to-understand {language_name}. "
        "Use the native script for normal words and sentences."
    )

    return f"""
You are the final language renderer for GutGPT.

Translate ONLY the response below from English into {language_name}.
{target_instruction}

CRITICAL REQUIREMENTS:
- The output MUST be in {language_name}; do NOT return the English source unchanged.
- Translate headings, explanations, questions, bullet text, warnings, and next steps.
- Preserve the clinical meaning exactly. Do not add, remove, reinterpret, diagnose, or soften claims.
- Keep condition/product names recognizable. Product/brand names may remain unchanged.
- Never translate or alter URLs, email addresses, or product links.
- Preserve Markdown bullets and line breaks.
- Do not add a disclaimer that is not in the source.
- Return ONLY the translated response. No preamble, no quotation marks, no explanation.

ENGLISH RESPONSE:
{text}
"""


def translate_from_english(text: str, language: str) -> str:
    language = normalize_language(language)
    if language == "en" or not text.strip():
        return text

    # First attempt.
    try:
        translated = _invoke(_translation_prompt(text, language))
        if _looks_translated(translated, text, language):
            return translated
    except Exception:
        translated = ""

    # Do not make a second provider call to repair a translation. Repeated
    # calls amplified rate limits during provider degradation; fail closed with
    # the existing controlled translation-unavailable behavior instead.

    # Never silently return English to a non-English user. A translated
    # diagnosis is required for the final website; surface a controlled
    # translation-unavailable error instead of changing the language contract.
    raise TranslationUnavailableError("Output translation failed")
