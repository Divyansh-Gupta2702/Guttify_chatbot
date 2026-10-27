"""Keep process-wide Groq circuit-breaker state isolated between tests.

The breaker is intentionally global in production so concurrent requests share
its health state. Unit tests must not inherit an open circuit from an earlier
provider-error test, or unrelated mock-based tests never exercise their target
code path.
"""
import pytest


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
