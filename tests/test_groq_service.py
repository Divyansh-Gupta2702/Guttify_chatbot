import logging
import threading
import time
import pytest
from groq_service import invoke_groq, GroqBusyError

class Response:
    content = '{"ok": true}'
    usage_metadata = {"input_tokens": 12, "output_tokens": 4}

class Client:
    def __init__(self, result=None, error=None):
        self.result = result or Response()
        self.error = error
        self.calls = 0
    def invoke(self, prompt):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

def test_gateway_invokes_once_and_returns_response(caplog):
    client = Client()
    with caplog.at_level(logging.INFO, logger="gutgpt.groq"):
        result = invoke_groq(client, "not logged", reason="test", request_id="abc123")
    assert result is client.result
    assert client.calls == 1
    assert "input_tokens=12" in caplog.text
    assert "output_tokens=4" in caplog.text
    assert "not logged" not in caplog.text

def test_gateway_does_not_retry_errors():
    client = Client(error=RuntimeError("provider down"))
    with pytest.raises(RuntimeError):
        invoke_groq(client, "prompt", reason="test")
    assert client.calls == 1

def test_gateway_classifies_429_without_retry(caplog):
    error = RuntimeError("HTTP 429 rate limit")
    client = Client(error=error)
    with caplog.at_level(logging.WARNING, logger="gutgpt.groq"):
        with pytest.raises(RuntimeError):
            invoke_groq(client, "prompt", reason="test")
    assert client.calls == 1
    assert "category=rate_limit" in caplog.text


def test_message_budget_blocks_second_invocation_without_calling_provider(monkeypatch):
    import groq_service
    monkeypatch.setattr(groq_service, "_shared_capacity_reserve", lambda prompt, request_id: None)
    from groq_service import message_call_budget, GroqBudgetExceeded
    first = Client()
    second = Client()
    with message_call_budget("budget-test", max_calls=1):
        invoke_groq(first, "first prompt", reason="test")
        with pytest.raises(GroqBudgetExceeded):
            invoke_groq(second, "second prompt", reason="test")
    assert first.calls == 1
    assert second.calls == 0


def test_message_budget_is_isolated_between_messages(monkeypatch):
    import groq_service
    monkeypatch.setattr(groq_service, "_shared_capacity_reserve", lambda prompt, request_id: None)
    from groq_service import message_call_budget
    one = Client()
    two = Client()
    with message_call_budget("message-one", max_calls=1):
        invoke_groq(one, "prompt", reason="test")
    with message_call_budget("message-two", max_calls=1):
        invoke_groq(two, "prompt", reason="test")
    assert one.calls == two.calls == 1


def test_default_message_budget_allows_bilingual_round_trip_but_stays_bounded(monkeypatch):
    import groq_service
    monkeypatch.delenv("GROQ_MAX_CALLS_PER_MESSAGE", raising=False)
    monkeypatch.setattr(groq_service, "_shared_capacity_reserve", lambda prompt, request_id: None)
    from groq_service import message_call_budget, GroqBudgetExceeded
    clients = [Client(), Client(), Client()]
    with message_call_budget("bilingual-round-trip"):
        invoke_groq(clients[0], "input translation", reason="translation")
        invoke_groq(clients[1], "output translation", reason="translation")
        with pytest.raises(GroqBudgetExceeded):
            invoke_groq(clients[2], "unexpected third call", reason="nlu")
    assert [client.calls for client in clients] == [1, 1, 0]


def test_configured_budget_guarantees_translation_round_trip_even_with_old_cap(monkeypatch):
    import groq_service
    monkeypatch.setenv("GROQ_MAX_CALLS_PER_MESSAGE", "1")
    assert groq_service.configured_message_budget(needs_translation=True) == 2
    assert groq_service.configured_message_budget(needs_translation=False) == 1
    monkeypatch.setenv("GROQ_MAX_CALLS_PER_MESSAGE", "4")
    assert groq_service.configured_message_budget(needs_translation=True) == 4
