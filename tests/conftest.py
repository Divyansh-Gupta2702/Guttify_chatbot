"""Keep process-wide Groq circuit-breaker state isolated between tests.

The breaker is intentionally global in production so concurrent requests share
its health state. Unit tests must not inherit an open circuit from an earlier
provider-error test, or unrelated mock-based tests never exercise their target
code path.
"""
import pytest
from functools import lru_cache


@pytest.fixture(autouse=True)
def reset_groq_circuit_breaker_between_tests():
    import groq_service

    with groq_service._breaker_lock:
        groq_service._breaker_failures = 0
        groq_service._breaker_open_until = 0.0
        groq_service._breaker_probe_active = False
    yield
    with groq_service._breaker_lock:
        groq_service._breaker_failures = 0
        groq_service._breaker_open_until = 0.0
        groq_service._breaker_probe_active = False


@pytest.fixture(autouse=True)
def disable_live_groq_calls(monkeypatch):
    """Keep tests deterministic; model behavior is covered with explicit mocks."""
    import conversation_intelligence
    import nlu_extractor

    @lru_cache(maxsize=2)
    def no_conversation_model(_tokens):
        return None

    @lru_cache(maxsize=1)
    def no_nlu_model():
        return None

    monkeypatch.setattr(conversation_intelligence, "_get_llm", no_conversation_model)
    monkeypatch.setattr(nlu_extractor, "_get_llm", no_nlu_model)
