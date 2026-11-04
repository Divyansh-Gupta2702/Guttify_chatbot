import logging
from types import SimpleNamespace

import pytest

import groq_service
import llm_provider
from guttify_agent import SessionState, ConversationManager


def test_groq_gpt_oss_json_mode_sets_hidden_reasoning_format(monkeypatch):
    captured = {}

    class FakeChatGroq:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("GUTGPT_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("GROQ_NLU_MODEL", "openai/gpt-oss-20b")
    monkeypatch.setitem(__import__("sys").modules, "langchain_groq", SimpleNamespace(ChatGroq=FakeChatGroq))

    llm_provider.create_client(350, output_mode="json")

    assert captured["model_kwargs"]["response_format"] == {"type": "json_object"}
    assert captured["model_kwargs"]["reasoning_format"] == "hidden"


def test_non_gpt_oss_json_client_does_not_receive_gpt_oss_reasoning_parameter(monkeypatch):
    captured = {}

    class FakeChatGroq:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("GUTGPT_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("GROQ_NLU_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setitem(__import__("sys").modules, "langchain_groq", SimpleNamespace(ChatGroq=FakeChatGroq))

    llm_provider.create_client(350, output_mode="json")

    assert captured["model_kwargs"] == {"response_format": {"type": "json_object"}}


def test_provider_error_diagnostics_are_sanitized_and_do_not_log_prompt(caplog, monkeypatch):
    class Response:
        status_code = 400
        headers = {}

    class ProviderError(RuntimeError):
        response = Response()
        body = {"error": {
            "code": "invalid_request", "type": "invalid_request_error",
            "param": "reasoning_format",
            "message": "Bad request with Bearer secret-value and gsk_abcdef123456",
        }}

    class Client:
        model = "openai/gpt-oss-20b"
        max_tokens = 350
        def invoke(self, prompt):
            raise ProviderError("request failed")

    monkeypatch.setattr(groq_service, "_shared_capacity_reserve", lambda *a, **k: None)
    monkeypatch.setattr(groq_service, "_shared_capacity_release", lambda *a, **k: None)
    with caplog.at_level(logging.WARNING, logger="gutgpt.groq"):
        with pytest.raises(ProviderError):
            groq_service.invoke_groq(Client(), "private symptom text", reason="nlu_extraction")

    assert "api_error_code=invalid_request" in caplog.text
    assert "api_error_param=reasoning_format" in caplog.text
    assert "[REDACTED]" in caplog.text
    assert "secret-value" not in caplog.text
    assert "gsk_abcdef123456" not in caplog.text
    assert "private symptom text" not in caplog.text


def test_unanswered_safety_review_is_assessment_scoped_not_customer_scoped():
    session = SessionState()
    result = {
        "status": "SAFETY_REVIEW",
        "safety": {
            "red_flag": False,
            "reason_code": "unanswered_safety_question",
            "reasons": ["blood_colour"],
        },
    }

    attached = ConversationManager._attach_safety_metadata(session, result)

    assert attached["safety"]["scope"] == "assessment"
    assert attached["safety"]["reason_code"] == "unanswered_safety_question"
    assert attached["safety"]["flag_provenance"] == []


def test_real_red_flag_remains_assessment_scoped():
    session = SessionState()
    session.symptom_state.red_flags = ["black_stool"]
    session.safety_flag_provenance = [{
        "reason": "black_stool", "source": "user_text_span",
        "evidence": "black tarry stool", "scope": "assessment",
        "assessment_id": None,
    }]
    result = {"status": "SAFETY_REVIEW", "safety": {
        "red_flag": True, "reason_code": "urgent_red_flag",
        "reasons": ["black_stool"],
    }}

    attached = ConversationManager._attach_safety_metadata(session, result)

    assert attached["safety"]["scope"] == "assessment"
    assert attached["safety"]["flag_provenance"][0]["scope"] == "assessment"
