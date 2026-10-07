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
    """Call the translation model and always return a non-empty string.

    Translation is an enhancement layer, not part of the clinical decision.
    A translation failure must never erase a valid diagnosis/recommendation.
    """
    try:
        response = _llm().invoke(prompt)
        content = getattr(response, "content", response)

        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(str(part.get("text", "")))
                else:
                    parts.append(str(part))
            content = "".join(parts)

        content = str(content or "").strip()
        if not content:
            raise RuntimeError("Translation model returned an empty response.")

        return content
    except Exception:
        # Let the caller decide which safe source text to preserve.
        raise

def translate_to_english(text: str, language: str) -> str:
    """Translate user input to English without breaking the clinical pipeline.

    If translation is unavailable, return the original text. This keeps the
    request alive and lets the existing English parser handle English/mixed
    input instead of turning the response into an empty result.
    """
    language = normalize_language(language)
    if language == "en" or not text.strip():
        return text

    language_name = SUPPORTED_LANGUAGES[language]
    prompt = f"""
Translate the user's message from {language_name} to clear, natural English.

This translation is consumed by a deterministic gut-health symptom parser.
Preserve EXACTLY:
- symptoms and negations
- yes/no meaning
- numbers and severity scores
- durations such as days, weeks, months and years
- medicine/product names
- body parts
- frequency and bowel-movement information

Do not answer the user.
Do not diagnose.
Do not add, remove, summarize, or interpret information.
For Hinglish, understand both Roman Hindi and mixed Hindi/English.

Return ONLY the English translation.

USER MESSAGE:
{text}
"""
    try:
        translated = _invoke(prompt)
        return translated if translated else text
    except Exception:
        return text


def translate_from_english(text: str, language: str) -> str:
    """Translate a completed GutGPT response safely.

    The clinical engine has already produced the answer before this function
    runs. Therefore an unavailable/empty translation must return the original
    English answer rather than an empty string.
    """
    language = normalize_language(language)
    if language == "en" or not text.strip():
        return text

    language_name = SUPPORTED_LANGUAGES[language]
    if language == "hinglish":
        target_instruction = (
            "Write natural Indian Hinglish in Roman script. Mix Hindi and English "
            "the way an Indian user would naturally chat; never use Devanagari."
        )
    else:
        target_instruction = (
            f"Write natural, easy-to-understand {language_name}. "
            "Use the native script where appropriate."
        )

    prompt = f"""
Translate the following completed GutGPT response from English into {language_name}.

{target_instruction}

This is a completed clinical-pattern assessment. Preserve its meaning exactly.
Do NOT change the assessment, diagnosis/pattern, evidence, warnings, questions,
or recommendations.
Keep the same headings, bullet structure, numbers, and medical caution.
Do not add, remove, or invent medical claims.

CRITICAL:
- NEVER translate or alter product names or brand names.
- NEVER translate or alter URLs.
- NEVER translate email addresses.
- Preserve product names exactly as written.
- Preserve every product URL exactly as written.
- Return ONLY the translated response.
- The response MUST NOT be empty.

ENGLISH RESPONSE:
{text}
"""
    try:
        translated = _invoke(prompt)
        return translated if translated else text
    except Exception:
        # Most important safeguard: never lose a valid diagnosis because
        # the optional output-translation call failed.
        return text
