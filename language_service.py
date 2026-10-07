"""
GutGPT multilingual language bridge.

The clinical/routing engine remains English-rule based. This module only:
1. Converts a supported Indian-language user message into concise English.
2. Converts the engine's English response back into the user's selected language.

No diagnosis, product selection, or medical reasoning is performed here.
"""
import os
from functools import lru_cache
from langchain_groq import ChatGroq

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_TRANSLATION_MODEL", "openai/gpt-oss-20b")

SUPPORTED_LANGUAGES = {
    "en": "English", "hi": "Hindi", "hinglish": "Hinglish", "bn": "Bengali",
    "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "gu": "Gujarati",
    "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi", "or": "Odia",
}

def language_name(code: str) -> str:
    return SUPPORTED_LANGUAGES.get(code, "English")

def normalize_language(code: str | None) -> str:
    code = (code or "en").strip().lower()
    return code if code in SUPPORTED_LANGUAGES else "en"

@lru_cache(maxsize=1)
def _translator():
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set.")
    return ChatGroq(model=GROQ_MODEL, temperature=0, max_tokens=900, api_key=GROQ_API_KEY)

def _invoke(prompt: str) -> str:
    result = _translator().invoke(prompt)
    text = getattr(result, "content", result)
    if isinstance(text, list):
        text = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in text)
    return str(text).strip()

def to_english(text: str, language: str) -> str:
    language = normalize_language(language)
    if language == "en":
        return text
    name = language_name(language)
    prompt = f"""
You are a medical-language translation layer for GutGPT.
Translate the user's message from {name} into clear, literal English for a
deterministic symptom parser.

Translate only. Do not diagnose, summarize, explain, add, remove, or infer.
Preserve every symptom, duration, number, yes/no answer, severity, body part,
medication name, food name, uncertainty, and negation exactly.
Convert local-language number words into Arabic numerals when appropriate.
Hinglish means Hindi written in Latin script mixed with English.
Return ONLY the English translation. No quotes or commentary.

USER MESSAGE:
{text}
"""
    return _invoke(prompt)

def to_language(text: str, language: str) -> str:
    language = normalize_language(language)
    if language == "en":
        return text
    name = language_name(language)
    prompt = f"""
You are the final language-rendering layer for GutGPT.
Translate the assistant response below into natural {name}.

Translate only. Do not change the medical assessment, evidence, warnings,
instructions, or product recommendation. Do not add medical claims, diagnosis,
dosage, reassurance, or advice.
Preserve product names, URLs, and numbers exactly.
Preserve headings, structure, and bullet points.
For Hinglish, use natural conversational Hindi written in Latin/English script,
keeping common technical/medical terms in English where natural.
Return ONLY the translated response.

ASSISTANT RESPONSE:
{text}
"""
    return _invoke(prompt)
