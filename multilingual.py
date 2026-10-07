"""Multilingual input/output layer for GutGPT.

The deterministic clinical engine remains English-based. This module translates
user input to English before the engine runs and translates the final response
back to the user's selected language.
"""
import os
from functools import lru_cache

from langchain_groq import ChatGroq

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_TRANSLATION_MODEL", "openai/gpt-oss-20b")

SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "hinglish": "Hinglish",
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
    value = (language or "en").strip().lower()
    return value if value in SUPPORTED_LANGUAGES else "en"


@lru_cache(maxsize=1)
def _llm():
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set.")
    return ChatGroq(
        model=GROQ_MODEL,
        temperature=0,
        max_tokens=900,
        api_key=GROQ_API_KEY,
    )


def _invoke(prompt: str) -> str:
    response = _llm().invoke(prompt)
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content).strip()


def translate_to_english(text: str, language: str) -> str:
    language = normalize_language(language)
    if language == "en" or not text.strip():
        return text

    language_name = SUPPORTED_LANGUAGES[language]
    return _invoke(f"""
Translate the user's message from {language_name} to clear, natural English.
This translation will be used by a deterministic gut-health symptom parser.
Preserve the exact meaning of symptoms, yes/no answers, numbers, durations,
severity scores, medicine names, and body-part references.
Do not answer the user. Do not add, remove, diagnose, or interpret anything.
For Hinglish, understand Hindi written in Roman script as well as mixed Hindi/English.
Return ONLY the English translation.

USER MESSAGE:
{text}
""")


def translate_from_english(text: str, language: str) -> str:
    language = normalize_language(language)
    if language == "en" or not text.strip():
        return text

    language_name = SUPPORTED_LANGUAGES[language]
    if language == "hinglish":
        target_instruction = (
            "Write natural Indian Hinglish in Roman script. Mix Hindi and English "
            "the way an Indian user would naturally chat; do not use Devanagari."
        )
    else:
        target_instruction = f"Write natural, easy-to-understand {language_name}."

    return _invoke(f"""
Translate the GutGPT response from English into {language_name}.
{target_instruction}
Keep the meaning, medical caution, structure, bullet points, numbers, and
question intent exactly the same. Do not add new medical claims.
NEVER translate or alter product names, brand names, URLs, or email addresses.
Do not add a disclaimer that is not present in the source.
Return ONLY the translated response.

ENGLISH RESPONSE:
{text}
""")
