"""Central Groq invocation boundary for GutGPT.

This module deliberately does not implement clinical logic. It centralizes
bounded in-process concurrency, request telemetry, deadlines and failure
classification. Production-wide quotas should be backed by PostgreSQL/Redis;
this local semaphore is a last-resort per-worker guard, not a distributed quota.
"""
from __future__ import annotations
import logging
import os
import threading
import time
import contextvars
from contextlib import contextmanager
import uuid
from typing import Any, Iterator

logger = logging.getLogger("gutgpt.groq")
_MAX_CONCURRENT = max(1, min(64, int(os.getenv("GROQ_MAX_CONCURRENT_PER_WORKER", "4"))))
_ACQUIRE_TIMEOUT = max(0.05, min(10.0, float(os.getenv("GROQ_QUEUE_TIMEOUT_SECONDS", "1.0"))))
_SEMAPHORE = threading.BoundedSemaphore(_MAX_CONCURRENT)

class GroqBusyError(RuntimeError):
    """The local Groq request queue is full; callers should use safe fallback."""


class GroqBudgetExceeded(RuntimeError):
    """The incoming message has already consumed its configured Groq-call budget."""


class GroqCircuitOpen(RuntimeError):
    """Groq is temporarily disabled after repeated provider failures."""


_budget = contextvars.ContextVar("gutgpt_groq_budget", default=None)
_breaker_lock = threading.Lock()
_breaker_failures = 0
_breaker_open_until = 0.0
_breaker_probe_active = False
_BREAKER_THRESHOLD = max(1, int(os.getenv("GROQ_CIRCUIT_FAILURE_THRESHOLD", "5")))
_BREAKER_COOLDOWN = max(1.0, float(os.getenv("GROQ_CIRCUIT_COOLDOWN_SECONDS", "30")))


@contextmanager
def message_call_budget(request_id: str, max_calls: int | None = None) -> Iterator[None]:
    """Set a request-scoped budget shared by translation, NLU and legacy helpers."""
    limit = max_calls if max_calls is not None else int(os.getenv("GROQ_MAX_CALLS_PER_MESSAGE", "2"))
    token = _budget.set({"request_id": request_id, "limit": max(0, limit), "used": 0})
    try:
        yield
    finally:
        _budget.reset(token)


def configured_message_budget() -> int:
    """Return the bounded per-message Groq call budget.

    GutGPT is English-only: no input or output translation calls are made, so
    one budget covers the turn (NLU model resolution when the contextual
    resolver requires it; the deterministic reply path uses none). The
    configured floor of one call remains available for essential NLU.
    """
    return max(1, int(os.getenv("GROQ_MAX_CALLS_PER_MESSAGE", "2")))


def _reserve_budget(request_id: str) -> str:
    budget = _budget.get()
    if budget is None:
        return request_id
    if budget["used"] >= budget["limit"]:
        logger.warning("event=groq_rejected request_id=%s reason=message_budget_exhausted used=%s limit=%s",
                       budget["request_id"], budget["used"], budget["limit"])
        raise GroqBudgetExceeded("Groq call budget exhausted for this message")
    budget["used"] += 1
    return budget["request_id"]


def _breaker_before_call(request_id: str) -> None:
    global _breaker_probe_active
    now = time.monotonic()
    with _breaker_lock:
        if _breaker_open_until > now:
            logger.warning("event=groq_rejected request_id=%s reason=circuit_open", request_id)
            raise GroqCircuitOpen("Groq circuit is temporarily open")
        if _breaker_open_until and not _breaker_probe_active:
            _breaker_probe_active = True
        elif _breaker_open_until and _breaker_probe_active:
            raise GroqCircuitOpen("Groq recovery probe is already in progress")


def _breaker_success() -> None:
    global _breaker_failures, _breaker_open_until, _breaker_probe_active
    with _breaker_lock:
        _breaker_failures = 0
        _breaker_open_until = 0.0
        _breaker_probe_active = False


def _breaker_failure() -> None:
    global _breaker_failures, _breaker_open_until, _breaker_probe_active
    with _breaker_lock:
        _breaker_failures += 1
        _breaker_probe_active = False
        if _breaker_failures >= _BREAKER_THRESHOLD:
            _breaker_open_until = time.monotonic() + _BREAKER_COOLDOWN


def _usage(response: Any) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage_metadata", None) or {}
    if not isinstance(usage, dict):
        usage = {}
    prompt = usage.get("input_tokens", usage.get("prompt_tokens"))
    output = usage.get("output_tokens", usage.get("completion_tokens"))
    meta = getattr(response, "response_metadata", None) or {}
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage") or meta.get("usage") or {}
        if isinstance(token_usage, dict):
            prompt = prompt if prompt is not None else token_usage.get("prompt_tokens")
            output = output if output is not None else token_usage.get("completion_tokens")
    return (int(prompt) if isinstance(prompt, (int, float)) else None,
            int(output) if isinstance(output, (int, float)) else None)



def _shared_capacity_reserve(prompt: Any, request_id: str) -> str | None:
    """Reserve shared RPM/TPM/concurrency capacity in PostgreSQL atomically.

    Chat production requests run inside message_call_budget and therefore require
    the shared limiter by default. Standalone unit tests/out-of-request calls do
    not require a database reservation.
    """
    if _budget.get() is None:
        return None
    enabled = os.getenv("GROQ_SHARED_LIMITER_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
    if not enabled:
        raise GroqBusyError("Shared Groq limiter is disabled")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise GroqBusyError("Shared Groq limiter requires DATABASE_URL")
    rpm_limit = max(1, int(os.getenv("GROQ_SHARED_RPM_LIMIT", "30")))
    tpm_limit = max(1, int(os.getenv("GROQ_SHARED_TPM_LIMIT", "20000")))
    concurrency_limit = max(1, int(os.getenv("GROQ_SHARED_MAX_CONCURRENT", "8")))
    output_reserve = max(1, int(os.getenv("GROQ_SHARED_OUTPUT_TOKEN_RESERVE", "500")))
    prompt_text = str(prompt)
    token_reserve = max(1, (len(prompt_text) + 3) // 4) + output_reserve
    lease_id = uuid.uuid4().hex
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=4) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('gutgpt-groq-shared-limiter'))")
                cur.execute("DELETE FROM groq_shared_leases WHERE expires_at < NOW()")
                cur.execute("""INSERT INTO groq_shared_usage_window(singleton, window_started_at, request_count, reserved_tokens)
                    VALUES (1, NOW(), 0, 0) ON CONFLICT(singleton) DO NOTHING""")
                cur.execute("""UPDATE groq_shared_usage_window SET
                    request_count = CASE WHEN window_started_at <= NOW() - INTERVAL '60 seconds' THEN 0 ELSE request_count END,
                    reserved_tokens = CASE WHEN window_started_at <= NOW() - INTERVAL '60 seconds' THEN 0 ELSE reserved_tokens END,
                    window_started_at = CASE WHEN window_started_at <= NOW() - INTERVAL '60 seconds' THEN NOW() ELSE window_started_at END
                    WHERE singleton=1 RETURNING request_count, reserved_tokens, cooldown_until""")
                row = cur.fetchone()
                cur.execute("SELECT COUNT(*) AS active FROM groq_shared_leases WHERE expires_at > NOW()")
                active = int(cur.fetchone()["active"])
                if row["cooldown_until"] is not None:
                    cur.execute("SELECT (cooldown_until > NOW()) AS active FROM groq_shared_usage_window WHERE singleton=1")
                    if cur.fetchone()["active"]:
                        raise GroqCircuitOpen("Shared Groq cooldown is active")
                if int(row["request_count"]) >= rpm_limit or int(row["reserved_tokens"]) + token_reserve > tpm_limit or active >= concurrency_limit:
                    raise GroqBusyError("Shared Groq rate or concurrency limit reached")
                cur.execute("UPDATE groq_shared_usage_window SET request_count=request_count+1, reserved_tokens=reserved_tokens+%s WHERE singleton=1", (token_reserve,))
                cur.execute("INSERT INTO groq_shared_leases(lease_id, expires_at) VALUES (%s, NOW() + INTERVAL '90 seconds')", (lease_id,))
        logger.info("event=groq_shared_reservation request_id=%s estimated_tokens=%s", request_id, token_reserve)
        return lease_id
    except (GroqBusyError, GroqCircuitOpen):
        raise
    except Exception as exc:
        logger.warning("event=groq_shared_limiter_error request_id=%s category=%s", request_id, type(exc).__name__)
        raise GroqBusyError("Shared Groq limiter is unavailable; failing closed") from exc


def _shared_capacity_release(lease_id: str | None) -> None:
    if not lease_id:
        return
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return
    try:
        import psycopg
        with psycopg.connect(database_url, connect_timeout=4) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM groq_shared_leases WHERE lease_id=%s", (lease_id,))
    except Exception:
        logger.warning("event=groq_shared_lease_release_failed")


def _shared_cooldown(seconds: int = 10) -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return
    try:
        import psycopg
        with psycopg.connect(database_url, connect_timeout=4) as conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE groq_shared_usage_window SET cooldown_until=GREATEST(COALESCE(cooldown_until, NOW()), NOW() + (%s * INTERVAL '1 second')) WHERE singleton=1""", (max(1, seconds),))
    except Exception:
        logger.warning("event=groq_shared_cooldown_update_failed")


def invoke_groq(client: Any, prompt: Any, *, reason: str, request_id: str = "unknown") -> Any:
    """Invoke a configured LangChain Groq client once, with bounded waiting.

    Retries are intentionally not performed here. Client construction should
    set max_retries=0, so one invocation cannot hide an SDK retry loop.
    """
    request_id = _reserve_budget(request_id)
    _breaker_before_call(request_id)
    started = time.monotonic()
    model_name = getattr(client, "model_name", None) or getattr(client, "model", None) or "configured"
    lease_id = _shared_capacity_reserve(prompt, request_id)
    if not _SEMAPHORE.acquire(timeout=_ACQUIRE_TIMEOUT):
        _shared_capacity_release(lease_id)
        logger.warning("event=groq_rejected request_id=%s reason=%s category=local_queue_full", request_id, reason)
        raise GroqBusyError("Groq capacity is temporarily busy")
    try:
        response = client.invoke(prompt)
        in_tokens, out_tokens = _usage(response)
        _breaker_success()
        logger.info(
            "event=groq_call request_id=%s reason=%s model=%s latency_ms=%.1f input_tokens=%s output_tokens=%s retry_count=0 result=model",
            request_id, reason, model_name,
            (time.monotonic() - started) * 1000, in_tokens, out_tokens,
        )
        return response
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        category = "rate_limit" if status == 429 or "429" in str(exc) else (
            "auth" if status in (401, 403) else "timeout" if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower() else "provider_error")
        _breaker_failure()
        if category == "rate_limit":
            retry_after = getattr(getattr(exc, "response", None), "headers", {}).get("Retry-After") if getattr(exc, "response", None) is not None else None
            try:
                _shared_cooldown(int(retry_after) if retry_after else 10)
            except (TypeError, ValueError):
                _shared_cooldown(10)
        logger.warning("event=groq_failure request_id=%s reason=%s category=%s status=%s latency_ms=%.1f retry_count=0",
                       request_id, reason, category, status, (time.monotonic() - started) * 1000)
        raise
    finally:
        _SEMAPHORE.release()
        _shared_capacity_release(lease_id)
