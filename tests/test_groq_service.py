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
    import groq_service
    client = Client(error=RuntimeError("provider down"))
    with pytest.raises(RuntimeError):
        invoke_groq(client, "prompt", reason="test")
    assert client.calls == 1
    assert groq_service._breaker_failures == 1
    assert not groq_service._breaker_probe_active

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
    monkeypatch.setattr(groq_service, "_shared_capacity_reserve", lambda *args, **kwargs: None)
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
    monkeypatch.setattr(groq_service, "_shared_capacity_reserve", lambda *args, **kwargs: None)
    from groq_service import message_call_budget
    one = Client()
    two = Client()
    with message_call_budget("message-one", max_calls=1):
        invoke_groq(one, "prompt", reason="test")
    with message_call_budget("message-two", max_calls=1):
        invoke_groq(two, "prompt", reason="test")
    assert one.calls == two.calls == 1


def test_default_message_budget_allows_one_english_call_but_stays_bounded(monkeypatch):
    import groq_service
    monkeypatch.delenv("GROQ_MAX_CALLS_PER_MESSAGE", raising=False)
    monkeypatch.setattr(groq_service, "_shared_capacity_reserve", lambda *args, **kwargs: None)
    from groq_service import message_call_budget, GroqBudgetExceeded
    clients = [Client(), Client()]
    # GutGPT is English-only: no input/output translation calls exist, so a
    # single per-message budget covers the turn (essential NLU only).
    with message_call_budget("english-turn", max_calls=1):
        invoke_groq(clients[0], "contextual nlu resolution", reason="nlu_extraction")
        with pytest.raises(GroqBudgetExceeded):
            invoke_groq(clients[1], "unexpected second call", reason="reply")
    assert [client.calls for client in clients] == [1, 0]


def test_configured_budget_has_minimum_of_one(monkeypatch):
    import groq_service
    monkeypatch.setenv("GROQ_MAX_CALLS_PER_MESSAGE", "1")
    try:
        assert groq_service.configured_message_budget() == 1
    finally:
        monkeypatch.delenv("GROQ_MAX_CALLS_PER_MESSAGE", raising=False)
    assert groq_service.configured_message_budget() == 2  # default
    monkeypatch.setenv("GROQ_MAX_CALLS_PER_MESSAGE", "4")
    try:
        assert groq_service.configured_message_budget() == 4
    finally:
        monkeypatch.delenv("GROQ_MAX_CALLS_PER_MESSAGE", raising=False)


def test_hinglish_budget_reserves_translation_calls_without_changing_english_budget(monkeypatch):
    import groq_service

    monkeypatch.setenv("GROQ_MAX_CALLS_PER_MESSAGE", "2")
    monkeypatch.delenv("GROQ_MAX_HINGLISH_CALLS_PER_MESSAGE", raising=False)
    assert groq_service.configured_message_budget("en") == 2
    assert groq_service.configured_message_budget("hinglish") == 4

    monkeypatch.setenv("GROQ_MAX_HINGLISH_CALLS_PER_MESSAGE", "3")
    assert groq_service.configured_message_budget("hinglish") == 3


def _put_breaker_half_open(groq_service):
    with groq_service._breaker_lock:
        groq_service._breaker_failures = groq_service._BREAKER_THRESHOLD
        groq_service._breaker_open_until = time.monotonic() - 0.01
        groq_service._breaker_probe_active = False


def test_half_open_success_resets_breaker(monkeypatch):
    import groq_service
    _put_breaker_half_open(groq_service)
    client = Client()

    assert invoke_groq(client, "prompt", reason="general_knowledge_answer") is client.result
    assert groq_service._breaker_failures == 0
    assert groq_service._breaker_open_until == 0
    assert not groq_service._breaker_probe_active


def test_half_open_provider_failure_releases_probe_and_reopens_breaker():
    import groq_service
    _put_breaker_half_open(groq_service)
    client = Client(error=RuntimeError("provider down"))

    with pytest.raises(RuntimeError):
        invoke_groq(client, "prompt", reason="general_knowledge_answer")

    assert client.calls == 1
    assert groq_service._breaker_probe_active is False
    assert groq_service._breaker_open_until > time.monotonic()


def test_half_open_database_reservation_failure_releases_probe(monkeypatch):
    import groq_service
    from groq_service import message_call_budget
    _put_breaker_half_open(groq_service)
    monkeypatch.setenv("DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/gutgpt_test")
    monkeypatch.setenv("GROQ_SHARED_LIMITER_ENABLED", "true")
    client = Client()

    with message_call_budget("half-open-db", max_calls=1), pytest.raises(GroqBusyError):
        invoke_groq(client, "prompt", reason="nlu_extraction")

    assert client.calls == 0
    assert groq_service._breaker_probe_active is False
    assert groq_service._breaker_failures == groq_service._BREAKER_THRESHOLD


def test_reservation_uses_the_actual_client_output_limit_and_task(monkeypatch):
    import groq_service
    observed = {}

    class TaskClient(Client):
        max_tokens = 900
        model = "test-model"

    def reserve(prompt, request_id, **kwargs):
        observed.update(kwargs)
        return None

    monkeypatch.setattr(groq_service, "_shared_capacity_reserve", reserve)
    monkeypatch.setattr(groq_service, "_shared_capacity_release", lambda *a, **k: None)
    invoke_groq(TaskClient(), "prompt", reason="research_summary_answer")

    assert observed == {"reason": "research_summary_answer", "output_tokens": 900}


def test_truncation_is_logged_without_response_content(caplog):
    import groq_service

    class TruncatedResponse(Response):
        response_metadata = {"finish_reason": "MAX_TOKENS"}

    class TruncatedClient(Client):
        model = "gpt-oss-test"
        def __init__(self):
            super().__init__(result=TruncatedResponse())

    with caplog.at_level(logging.INFO, logger="gutgpt.groq"):
        invoke_groq(TruncatedClient(), "private patient prompt", reason="general_knowledge_answer", request_id="trace-123")

    assert "event=llm_truncated" in caplog.text
    assert "task=general_knowledge_answer" in caplog.text
    assert "model=gpt-oss-test" in caplog.text
    assert "request_id=trace-123" in caplog.text
    assert "private patient prompt" not in caplog.text


def test_half_open_local_semaphore_timeout_refunds_unstarted_reservation(monkeypatch):
    import groq_service
    from groq_service import message_call_budget
    _put_breaker_half_open(groq_service)
    releases = []

    class TimedOutSemaphore:
        def acquire(self, timeout):
            return False
        def release(self):
            raise AssertionError("unacquired semaphore must not be released")

    monkeypatch.setattr(groq_service, "_shared_capacity_reserve", lambda *a, **k: "lease-1")
    monkeypatch.setattr(groq_service, "_shared_capacity_release", lambda *a, **k: releases.append((a, k)))
    monkeypatch.setattr(groq_service, "_SEMAPHORE", TimedOutSemaphore())
    client = Client()

    with message_call_budget("half-open-queue", max_calls=1), pytest.raises(GroqBusyError):
        invoke_groq(client, "prompt", reason="research_summary_answer")

    assert client.calls == 0
    assert groq_service._breaker_probe_active is False
    assert releases[0][0] == ("lease-1",)
    assert releases[0][1]["actual_tokens"] == 0


def test_concurrent_half_open_recovery_attempts_allow_only_one_probe():
    import groq_service
    _put_breaker_half_open(groq_service)
    entered = threading.Event()
    finish = threading.Event()

    class BlockingClient(Client):
        def invoke(self, prompt):
            self.calls += 1
            entered.set()
            assert finish.wait(2)
            return self.result

    client = BlockingClient()
    results = []

    def first_attempt():
        try:
            results.append(invoke_groq(client, "prompt", reason="test", request_id="probe-one"))
        except Exception as exc:
            results.append(exc)

    worker = threading.Thread(target=first_attempt)
    worker.start()
    assert entered.wait(2)
    with pytest.raises(groq_service.GroqCircuitOpen):
        invoke_groq(Client(), "prompt", reason="test", request_id="probe-two")
    finish.set()
    worker.join(2)

    assert not worker.is_alive()
    assert client.calls == 1
    assert results == [client.result]
