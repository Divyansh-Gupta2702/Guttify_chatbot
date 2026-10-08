"""Backward-compatible aliases for the single GutGPT language service.

The live application uses :mod:`multilingual`. This module remains only so
older integrations importing ``language_service`` do not break.
"""
from multilingual import (
    SUPPORTED_LANGUAGES,
    normalize_language,
    translate_to_english as to_english,
    translate_from_english as to_language,
)


def language_name(code: str) -> str:
    return SUPPORTED_LANGUAGES.get(normalize_language(code), "English")
