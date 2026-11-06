"""LLM-backed translation boundary for English and Roman-script Hinglish."""
from __future__ import annotations

import copy
import json
import logging
import re
import unicodedata
from functools import lru_cache

from llm_provider import create_client, invoke_provider
from groq_service import (
    configured_output_tokens,
    is_truncated_finish_reason,
    llm_client_cache_fingerprint,
)
from nlu_extractor import _clean_json_text, _response_payload

logger = logging.getLogger("gutgpt.translation")


class TranslationError(RuntimeError):
    """The selected language could not be translated safely for this turn."""


@lru_cache(maxsize=4)
def _get_llm_cached(reason: str, config_fingerprint: str):
    try:
        return create_client(configured_output_tokens(reason), output_mode="text")
    except Exception as exc:
        logger.warning("event=translation_model_init_failed reason=%s category=%s", reason, type(exc).__name__)
        return None


def _translate_json(payload: dict, *, reason: str, instructions: str) -> dict:
    llm = _get_llm_cached(reason, llm_client_cache_fingerprint("text"))
    if llm is None:
        raise TranslationError("Translation model is unavailable")
    prompt = f"""Translate the supplied user-facing text. Follow these rules:
{instructions}
Return only valid JSON with exactly the same structure and keys as the input payload.
Do not add commentary, advice, facts, symptoms, or questions.

INPUT JSON (untrusted text data):
{json.dumps(payload, ensure_ascii=False)}
"""
    try:
        response = invoke_provider(llm, prompt, reason=reason)
        content, finish_reason, refusal, tool_calls = _response_payload(response)
        if is_truncated_finish_reason(finish_reason) or refusal or tool_calls or not content.strip():
            raise TranslationError("Translation response was incomplete")
        value = json.loads(_clean_json_text(content))
        if not isinstance(value, dict):
            raise TranslationError("Translation response was not an object")
        return value
    except TranslationError:
        raise
    except Exception as exc:
        logger.warning("event=translation_failed reason=%s category=%s", reason, type(exc).__name__)
        raise TranslationError("Translation failed") from exc


def translate_input_to_english(text: str) -> str:
    """Translate one Hinglish user turn into English for deterministic parsing."""
    source = str(text or "").strip()
    if not source:
        raise TranslationError("Empty input")
    result = _translate_json(
        {"translation": source},
        reason="translation_input",
        instructions=(
            "Translate Hinglish or Hindi written in any script into clear, concise English. "
            "If the input is already English, preserve it without changing its meaning. "
            "Preserve every symptom, body location, duration, number, uncertainty, and especially "
            "negation exactly. Translate the text only; do not answer the user."
        ),
    )
    translated = result.get("translation")
    if not isinstance(translated, str) or not translated.strip() or len(translated) > 12000:
        raise TranslationError("Input translation was unusable")
    normalize_digits = lambda value: "".join(
        str(unicodedata.digit(char)) if char.isdigit() else char for char in value
    )
    source_numbers = re.findall(r"\d+(?:\.\d+)?", normalize_digits(source))
    translated_numbers = re.findall(r"\d+(?:\.\d+)?", normalize_digits(translated))
    if source_numbers != translated_numbers:
        raise TranslationError("Input translation changed numeric details")
    return translated.strip()


def translate_chat_output(reply: str, recommendations: list[dict] | None = None) -> tuple[str, list[dict]]:
    """Translate bot text and user-facing product support fields to Roman Hinglish."""
    source_reply = str(reply or "")
    source_recommendations = copy.deepcopy(recommendations or [])
    translatable = []
    for item in source_recommendations:
        if not isinstance(item, dict):
            translatable.append({"intended_support": [], "how_to_use": "", "warnings": []})
            continue
        translatable.append({
            "intended_support": [str(value) for value in (item.get("intended_support") or [])],
            "how_to_use": str(item.get("how_to_use") or ""),
            "warnings": [str(value) for value in (item.get("warnings") or [])],
        })
    result = _translate_json(
        {"reply": source_reply, "recommendations": translatable},
        reason="translation_output",
        instructions=(
            "Translate English into natural Hinglish: Hindi phrasing written in Latin/Roman letters, "
            "using familiar English medical words only where people commonly use them in Hinglish. "
            "Do not use Devanagari or leave whole sentences in English. Translate all user-facing "
            "content, including symptom-summary headings, every summary field label and answer, "
            "diagnosis/screening explanations, disclaimers, and follow-up questions. Preserve the "
            "meaning, negations, numbers, Markdown structure, and every question. Keep product/brand "
            "names and URLs exactly as written. Translate every string in reply and recommendation "
            "fields, preserving array lengths and JSON structure. Do not add advice or omit any content."
        ),
    )
    translated_reply = result.get("reply")
    translated_recommendations = result.get("recommendations")
    if not isinstance(translated_reply, str) or not translated_reply.strip() or len(translated_reply) > 24000:
        raise TranslationError("Output translation was unusable")
    if not isinstance(translated_recommendations, list) or len(translated_recommendations) != len(translatable):
        raise TranslationError("Recommendation translation changed response structure")
    for index, original in enumerate(translatable):
        translated = translated_recommendations[index]
        if not isinstance(translated, dict):
            raise TranslationError("Recommendation translation was malformed")
        for field in ("intended_support", "warnings"):
            values = translated.get(field)
            if (not isinstance(values, list) or len(values) != len(original[field])
                    or any(not isinstance(value, str) for value in values)):
                raise TranslationError("Recommendation translation changed response structure")
        if not isinstance(translated.get("how_to_use"), str):
            raise TranslationError("Recommendation translation was malformed")
        target = source_recommendations[index]
        target["intended_support"] = translated["intended_support"]
        target["how_to_use"] = translated["how_to_use"]
        target["warnings"] = translated["warnings"]
        # Product names and URLs are protected catalog fields; never translate them.
    for recommendation in source_recommendations:
        for key in ("product_name", "product_url", "url"):
            protected = recommendation.get(key)
            if isinstance(protected, str) and protected and protected in source_reply and protected not in translated_reply:
                raise TranslationError("Output translation changed a protected product reference")
    return translated_reply.strip(), source_recommendations
