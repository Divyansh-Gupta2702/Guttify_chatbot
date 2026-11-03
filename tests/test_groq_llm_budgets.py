import sys
from types import SimpleNamespace

import pytest

import conversation_intelligence as ci
import groq_service
import llm_provider
import nlu_extractor

_REAL_CI_GET_LLM = ci._get_llm
_REAL_NLU_GET_LLM = nlu_extractor._get_llm


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("conversation_intent", 260),
        ("nlu_extraction", 350),
        ("general_knowledge_answer", 800),
        ("company_knowledge_answer", 800),
        ("research_summary_answer", 900),
    ],
)
def test_task_budget_is_the_actual_groq_max_tokens(monkeypatch, reason, expected):
    captured = {}

    class FakeChatGroq:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.max_tokens = kwargs["max_tokens"]
            self.model = kwargs["model"]

    monkeypatch.setenv("GUTGPT_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("GROQ_OUTPUT_TOKEN_HARD_MAX", "1200")
    monkeypatch.setitem(sys.modules, "langchain_groq", SimpleNamespace(ChatGroq=FakeChatGroq))

    requested = groq_service.configured_output_tokens(reason)
    client = llm_provider.create_client(requested)

    assert requested == expected
    assert client.max_tokens == expected
    assert captured["max_tokens"] == expected
    assert captured["max_retries"] == 0


def test_output_budget_overrides_are_bounded_and_nlu_keeps_its_own_clamp(monkeypatch):
    monkeypatch.setenv("GROQ_OUTPUT_TOKEN_HARD_MAX", "850")
    monkeypatch.setenv("GROQ_RESEARCH_ANSWER_MAX_OUTPUT_TOKENS", "1400")
    monkeypatch.setenv("GROQ_INTENT_MAX_OUTPUT_TOKENS", "1")
    monkeypatch.setenv("GROQ_NLU_MAX_TOKENS", "900")

    assert groq_service.configured_output_tokens("research_summary_answer") == 850
    assert groq_service.configured_output_tokens("conversation_intent") == 96
    assert groq_service.configured_output_tokens("nlu_extraction") == 400


def test_installed_langchain_groq_client_keeps_the_requested_limit(monkeypatch):
    from langchain_groq import ChatGroq

    monkeypatch.setenv("GUTGPT_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-no-network-key")
    client = llm_provider.create_client(900)

    assert isinstance(client, ChatGroq)
    assert client.max_tokens == 900
    assert client.max_retries == 0


def test_cached_conversation_client_changes_when_runtime_configuration_changes(monkeypatch):
    calls = []

    def create(tokens, *, output_mode):
        calls.append((tokens, output_mode))
        return object()

    monkeypatch.setattr(ci, "_get_llm", _REAL_CI_GET_LLM)
    monkeypatch.setattr(ci, "create_client", create)
    monkeypatch.setenv("GROQ_CONVERSATION_MODEL", "model-a")
    ci._get_llm.cache_clear()
    first = ci._get_llm(800)
    assert ci._get_llm(800) is first
    monkeypatch.setenv("GROQ_CONVERSATION_MODEL", "model-b")
    second = ci._get_llm(800)

    assert second is not first
    assert calls == [(800, "text"), (800, "text")]
    ci._get_llm.cache_clear()


def test_cached_nlu_client_reloads_when_budget_configuration_changes(monkeypatch):
    calls = []

    def create(tokens, *, output_mode):
        calls.append((tokens, output_mode))
        return object()

    monkeypatch.setattr(nlu_extractor, "_get_llm", _REAL_NLU_GET_LLM)
    monkeypatch.setattr(nlu_extractor, "create_client", create)
    monkeypatch.setenv("GROQ_NLU_MAX_TOKENS", "350")
    nlu_extractor._get_llm.cache_clear()
    first = nlu_extractor._get_llm()
    assert nlu_extractor._get_llm() is first
    monkeypatch.setenv("GROQ_NLU_MAX_TOKENS", "370")
    second = nlu_extractor._get_llm()

    assert second is not first
    assert calls == [(350, "json"), (370, "json")]
    nlu_extractor._get_llm.cache_clear()


@pytest.mark.parametrize(
    ("reason", "answer_kind", "expected"),
    [
        ("general_knowledge_answer", "general", 800),
        ("company_knowledge_answer", "company", 800),
        ("research_summary_answer", "research", 900),
    ],
)
def test_answer_handlers_use_task_budget_and_keep_complete_long_answer(monkeypatch, reason, answer_kind, expected):
    captured = {}
    answer = "A well-formed educational answer. " * 80  # > 2,200 chars: never slice a valid answer mid-sentence.

    class Response:
        content = answer
        response_metadata = {"finish_reason": "stop"}

    monkeypatch.setattr(ci, "_get_llm", lambda tokens: captured.setdefault("tokens", tokens) or object())
    monkeypatch.setattr(ci, "invoke_groq", lambda *args, **kwargs: Response())
    if answer_kind == "company":
        monkeypatch.setattr(ci, "retrieve_company_context", lambda *_a, **_k: {"verified": "context"})
        result = ci.answer_company_question("What does the website say?")
    elif answer_kind == "research":
        monkeypatch.setattr(ci, "search_pubmed", lambda *_a, **_k: [{"pmid": "1", "title": "Test paper"}])
        monkeypatch.setattr(ci, "format_research_sources", lambda _records: "PMID: 1, https://pubmed.test/1")
        result = ci.answer_research_question("Summarize this research")
    else:
        result = ci.answer_general_question("Explain a science concept")

    assert captured["tokens"] == expected
    assert result == answer.strip()
    assert reason in {"general_knowledge_answer", "company_knowledge_answer", "research_summary_answer"}


@pytest.mark.parametrize("finish_reason", ["length", "MAX_TOKENS", "FinishReason.LENGTH", "max_output_tokens"])
def test_all_truncation_finish_reason_variants_use_safe_fallback(monkeypatch, finish_reason):
    class Response:
        content = "This answer is incomplete"
        response_metadata = {"finish_reason": finish_reason}

    monkeypatch.setattr(ci, "_get_llm", lambda _tokens: object())
    monkeypatch.setattr(ci, "invoke_groq", lambda *args, **kwargs: Response())
    assert ci.answer_general_question("Explain digestion") == ci.SAFE_GENERAL_FALLBACK


def test_general_answer_rejects_oversize_output_instead_of_slicing(monkeypatch):
    class Response:
        content = "complete-looking content " * 250
        response_metadata = {"finish_reason": "stop"}

    monkeypatch.setattr(ci, "_get_llm", lambda _tokens: object())
    monkeypatch.setattr(ci, "invoke_groq", lambda *args, **kwargs: Response())
    assert ci.answer_general_question("Explain digestion") == ci.SAFE_GENERAL_FALLBACK


def test_nlu_rejects_parseable_but_truncated_json_without_an_extra_attempt(monkeypatch):
    calls = []

    class Response:
        content = '{"intent":"assessment","symptoms":["gas"]}'
        response_metadata = {"finish_reason": "MAX_TOKENS"}

    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: object())
    monkeypatch.setattr(nlu_extractor, "invoke_groq", lambda *args, **kwargs: calls.append(1) or Response())

    result = nlu_extractor._llm_extract("I have gas", None, __import__("intent_parser").SymptomState(), None)

    assert result is None
    assert calls == [1]


def test_provider_health_uses_actual_response_provider_not_selection_environment(monkeypatch):
    class Response:
        content = "answer"
        response_metadata = {"provider": "groq", "finish_reason": "stop"}
        usage_metadata = {}

    monkeypatch.setenv("GUTGPT_LLM_PROVIDER", "gemini")
    assert llm_provider.provider_health_fields(Response())["provider"] == "groq"
