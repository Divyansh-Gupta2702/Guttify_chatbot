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
Return ONLY the English translation.

USER MESSAGE:
{text}
""")


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
        # Product names/URLs can be English, so require only a modest amount
        # of target-script text rather than demanding every word be translated.
        return script_letters >= 3 and script_letters >= max(3, alphabetic * 0.08)

    return text.strip() != source.strip()


def _translation_prompt(text: str, language: str) -> str:
    language_name = SUPPORTED_LANGUAGES[language]
    target_instruction = (
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

    # Retry once with an even more explicit instruction. This prevents a model
    # that ignored the target-language instruction from silently returning the
    # English diagnosis.
    retry_prompt = f"""
Translate this GutGPT response into {SUPPORTED_LANGUAGES[language]}.
THIS IS A TRANSLATION TASK. YOUR ANSWER MUST NOT BE IN ENGLISH.
Use the native {SUPPORTED_LANGUAGES[language]} script for the sentences.
Keep product names and URLs unchanged. Preserve the exact medical meaning and formatting.
Output ONLY the translation.

SOURCE:
{text}
"""
    try:
        translated = _invoke(retry_prompt)
        if _looks_translated(translated, text, language):
            return translated
    except Exception:
        pass

    # Never turn a successful diagnosis into a blank response. If translation
    # is unavailable, return the deterministic English response as a last-resort
    # safety fallback.
    return text
