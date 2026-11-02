"""Small provider boundary for GutGPT's non-clinical language tasks.

Clinical interpretation, safety decisions, and product eligibility remain in
their deterministic modules. Provider selection is configuration-only.
"""
from __future__ import annotations

import logging
import os
from types import SimpleNamespace

from groq_service import invoke_groq

logger = logging.getLogger("gutgpt.llm_provider")


def selected_provider() -> str:
    name = os.getenv("GUTGPT_LLM_PROVIDER", "groq").strip().lower()
    return name if name in {"groq", "gemini"} else "groq"


def _nlu_schema():
    # Compact and permissive at the schema boundary. nlu_extractor performs
    # the stricter field-by-field validation before any state update.
    from nlu_extractor import BOOL_FIELDS, LIST_FIELDS, SCHEMA_KEYS

    properties = {}
    for key in SCHEMA_KEYS:
        if key in LIST_FIELDS:
            properties[key] = {"type": "array", "items": {"type": "string"}}
        elif key in BOOL_FIELDS:
            properties[key] = {"type": "boolean"}
        elif key in {"age", "confidence"}:
            properties[key] = {"type": "number"}
        else:
            properties[key] = {"type": "string"}
    return {"type": "object", "properties": properties, "additionalProperties": False}


class _GeminiClient:
    """Adapt google-genai's generate_content API to the existing invoke shape."""

    _gutgpt_provider = "gemini"

    def __init__(self, model: str, max_output_tokens: int, output_mode: str):
        from google import genai

        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        self.client = genai.Client(api_key=key, http_options={"timeout": int(float(os.getenv("GEMINI_TIMEOUT_SECONDS", "12")) * 1000)})
        self.model_name = model
        self.max_output_tokens = max_output_tokens
        self.output_mode = output_mode

    def invoke(self, prompt):
        from google.genai import types

        config = {
            "temperature": 0,
            "max_output_tokens": self.max_output_tokens,
            "thinking_config": types.ThinkingConfig(thinking_level="LOW"),
        }
        if self.output_mode == "json":
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = _nlu_schema()
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(**config),
        )
        candidates = getattr(response, "candidates", None) or []
        finish = getattr(candidates[0], "finish_reason", None) if candidates else None
        finish_name = getattr(finish, "name", str(finish)) if finish is not None else None
        if finish_name and finish_name.upper().endswith("MAX_TOKENS"):
            finish_name = "length"
        elif finish_name and finish_name.upper().endswith("STOP"):
            finish_name = "stop"
        usage = getattr(response, "usage_metadata", None)
        return SimpleNamespace(
            content=getattr(response, "text", None) or "",
            response_metadata={"finish_reason": finish_name},
            usage_metadata={
                "input_tokens": getattr(usage, "prompt_token_count", None),
                "output_tokens": getattr(usage, "candidates_token_count", None),
                "thinking_tokens": getattr(usage, "thoughts_token_count", None),
            } if usage else {},
        )


def create_client(max_output_tokens: int, *, output_mode: str = "text"):
    """Create the configured provider client; absent providers fail closed."""
    provider = selected_provider()
    if provider == "gemini":
        model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        return _GeminiClient(model, max(96, min(600, int(max_output_tokens))), output_mode)

    from langchain_groq import ChatGroq

    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    model = os.getenv("GROQ_CONVERSATION_MODEL") or os.getenv("GROQ_NLU_MODEL", "openai/gpt-oss-20b")
    options = {"model": model, "temperature": 0, "max_tokens": max(96, min(600, int(max_output_tokens))),
               "timeout": float(os.getenv("GROQ_NLU_TIMEOUT_SECONDS", "12")),
               "max_retries": 0, "api_key": key}
    if output_mode == "json":
        options["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatGroq(**options)


def invoke_provider(client, prompt, *, reason: str):
    """Retain the existing request budget, concurrency and circuit boundary."""
    if client is None:
        raise RuntimeError("LLM provider is not configured")
    # The existing invocation guard is shared by both configured backends so
    # provider switching cannot bypass the per-message call budget or breaker.
    try:
        return invoke_groq(client, prompt, reason=reason)
    except Exception:
        if getattr(client, "_gutgpt_provider", "groq") != "gemini":
            raise
        fallback = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite").strip()
        if not fallback or fallback == getattr(client, "model_name", None):
            raise
        logger.warning("event=llm_fallback provider=gemini reason=%s model=%s", reason, fallback)
        backup = _GeminiClient(fallback, client.max_output_tokens, client.output_mode)
        return invoke_groq(backup, prompt, reason=f"{reason}_fallback")


def provider_health_fields(response):
    """Return safe response diagnostics; never include prompt or output text."""
    content = getattr(response, "content", None)
    metadata = getattr(response, "response_metadata", None) or {}
    usage = getattr(response, "usage_metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    if not isinstance(usage, dict):
        usage = {}
    return {
        "provider": selected_provider(),
        "content_available": bool(content.strip()) if isinstance(content, str) else False,
        "content_length": len(content) if isinstance(content, str) else 0,
        "finish_reason": str(metadata.get("finish_reason") or metadata.get("stop_reason") or "unknown"),
        "reasoning_tokens_present": bool(usage.get("thinking_tokens") or usage.get("reasoning_tokens")),
    }

