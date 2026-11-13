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
import hashlib
import json
from contextlib import contextmanager
import uuid
from typing import Any, Iterator

logger = logging.getLogger("gutgpt.groq")
_MAX_CONCURRENT = max(1, min(64, int(os.getenv("GROQ_MAX_CONCURRENT_PER_WORKER", "4"))))
_ACQUIRE_TIMEOUT = max(0.05, min(10.0, float(os.getenv("GROQ_QUEUE_TIMEOUT_SECONDS", "1.0"))))
_SEMAPHORE = threading.BoundedSemaphore(_MAX_CONCURRENT)

class GroqBusyError(RuntimeError):
    """The local Groq request queue is full; callers should use safe fallback."""

    def __init__(self, message: str, *, reason: str = "capacity"):
        super().__init__(message)
        self.reason = reason


class GroqBudgetExceeded(RuntimeError):
    """The incoming message has already consumed its configured Groq-call budget."""


class SessionTokenLimitExceeded(RuntimeError):
    """The session has exhausted its cumulative LLM token allowance."""


def session_token_limit_reached() -> bool:
    """Whether the current chat request hit its cumulative session token cap."""
    budget = _budget.get()
    return bool(budget and budget.get("session_limit_hit"))


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
def message_call_budget(
    request_id: str, max_calls: int | None = None, session_id: str | None = None,
) -> Iterator[None]:
    """Set request and session budgets shared by all model calls in a turn."""
    limit = max_calls if max_calls is not None else int(os.getenv("GROQ_MAX_CALLS_PER_MESSAGE", "2"))
    token = _budget.set({
        "request_id": request_id, "limit": max(0, limit), "used": 0,
        "session_id": str(session_id or "").strip() or None,
    })
    try:
        yield
    finally:
        _budget.reset(token)


def configured_message_budget(language: str = "en") -> int:
    """Return the bounded per-message Groq call budget.

    English turns retain the existing default. Hinglish turns reserve enough
    calls for input translation, optional NLU/intent resolution, and output
    translation. An explicit environment setting remains authoritative.
    """
    normalized_language = str(language).strip().lower()
    if normalized_language == "hinglish":
        configured = os.getenv("GROQ_MAX_HINGLISH_CALLS_PER_MESSAGE")
        default = 5
    else:
        configured = os.getenv("GROQ_MAX_CALLS_PER_MESSAGE")
        default = 3
    return max(1, int(configured if configured is not None else default))


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def configured_output_token_cap() -> int:
    """Provider-wide ceiling for actual Groq max_tokens configuration."""
    return _bounded_int_env("GROQ_OUTPUT_TOKEN_HARD_MAX", 1200, 160, 1600)


def configured_output_tokens(reason: str) -> int:
    """Return the bounded output allowance for a named Groq task."""
    configured = {
        "conversation_intent": ("GROQ_INTENT_MAX_OUTPUT_TOKENS", 260, 96),
        "nlu_extraction": ("GROQ_NLU_MAX_TOKENS", 500, 160),
        "translation_input": ("GROQ_TRANSLATION_INPUT_MAX_TOKENS", 700, 160),
        "translation_output": ("GROQ_TRANSLATION_OUTPUT_MAX_TOKENS", 1000, 160),
        "general_knowledge_answer": ("GROQ_GENERAL_ANSWER_MAX_OUTPUT_TOKENS", 800, 96),
        "company_knowledge_answer": ("GROQ_COMPANY_ANSWER_MAX_OUTPUT_TOKENS", 800, 96),
        "research_summary_answer": ("GROQ_RESEARCH_ANSWER_MAX_OUTPUT_TOKENS", 900, 96),
        "assessment_response": ("GROQ_ASSESSMENT_RESPONSE_MAX_OUTPUT_TOKENS", 420, 96),
    }
    env_name, default, minimum = configured.get(
        reason,
        ("GROQ_SHARED_OUTPUT_TOKEN_RESERVE", 500, 1),
    )
    if reason == "nlu_extraction":
        return max(160, min(600, _bounded_int_env(env_name, default, minimum, 600)))
    return _bounded_int_env(env_name, default, minimum, configured_output_token_cap())


def llm_client_cache_fingerprint(output_mode: str) -> str:
    """Hash non-secret provider settings so cached clients expire on config change."""
    names = (
        "GUTGPT_LLM_PROVIDER", "GROQ_API_KEY", "GROQ_CONVERSATION_MODEL",
        "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_FALLBACK_MODEL",
        "GROQ_NLU_MODEL", "GROQ_NLU_TIMEOUT_SECONDS", "GROQ_OUTPUT_TOKEN_HARD_MAX",
        "GROQ_INTENT_MAX_OUTPUT_TOKENS", "GROQ_NLU_MAX_TOKENS",
        "GROQ_TRANSLATION_INPUT_MAX_TOKENS", "GROQ_TRANSLATION_OUTPUT_MAX_TOKENS",
        "GROQ_GENERAL_ANSWER_MAX_OUTPUT_TOKENS",
        "GROQ_COMPANY_ANSWER_MAX_OUTPUT_TOKENS",
        "GROQ_RESEARCH_ANSWER_MAX_OUTPUT_TOKENS",
    )
    payload = {name: os.getenv(name, "") for name in names}
    payload["output_mode"] = output_mode
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def is_truncated_finish_reason(value: Any) -> bool:
    """Recognize Groq/OpenAI/LangChain token-limit finish reason variants."""
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in {"length", "max_tokens", "finishreason.max_tokens", "max_output_tokens"} \
        or normalized.endswith(".length") or normalized.endswith(".max_tokens") \
        or normalized.endswith(".max_output_tokens")


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


def _breaker_before_call(request_id: str) -> bool:
    global _breaker_probe_active
    now = time.monotonic()
    with _breaker_lock:
        if _breaker_open_until > now:
            logger.warning("event=groq_rejected request_id=%s reason=circuit_open", request_id)
            raise GroqCircuitOpen("Groq circuit is temporarily open")
        if _breaker_open_until and not _breaker_probe_active:
            _breaker_probe_active = True
            return True
        elif _breaker_open_until and _breaker_probe_active:
            logger.warning("event=groq_rejected request_id=%s reason=half_open_probe_active", request_id)
            raise GroqCircuitOpen("Groq recovery probe is already in progress")
        return False


def _breaker_probe_aborted(owns_probe: bool) -> None:
    """Release a half-open reservation when preflight fails before Groq is called."""
    global _breaker_probe_active
    if not owns_probe:
        return
    with _breaker_lock:
        if _breaker_open_until and _breaker_probe_active:
            _breaker_probe_active = False


def _breaker_state() -> str:
    with _breaker_lock:
        if _breaker_open_until > time.monotonic():
            return "open"
        if _breaker_open_until and _breaker_probe_active:
            return "half_open_probe"
        return "closed" if not _breaker_open_until else "half_open"


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
    thinking = usage.get("thinking_tokens", usage.get("reasoning_tokens"))
    meta = getattr(response, "response_metadata", None) or {}
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage") or meta.get("usage") or {}
        if isinstance(token_usage, dict):
            prompt = prompt if prompt is not None else token_usage.get("prompt_tokens")
            output = output if output is not None else token_usage.get("completion_tokens")
            thinking = thinking if thinking is not None else token_usage.get("thinking_tokens", token_usage.get("reasoning_tokens"))
    if isinstance(output, (int, float)) and isinstance(thinking, (int, float)):
        output += thinking
    return (int(prompt) if isinstance(prompt, (int, float)) else None,
            int(output) if isinstance(output, (int, float)) else None)


def _session_token_limit() -> int:
    try:
        return max(1000, min(10_000_000, int(os.getenv("GROQ_MAX_TOKENS_PER_SESSION", "60000"))))
    except (TypeError, ValueError):
        return 60000


def _session_token_reserve(prompt: Any, request_id: str, *, reason: str, output_tokens: int) -> str | None:
    """Atomically reserve this call's worst-case tokens against its chat session."""
    budget = _budget.get()
    session_id = budget.get("session_id") if budget else None
    if not session_id:
        return None
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise GroqBusyError("Session token accounting requires DATABASE_URL", reason="session_usage_unavailable")
    prompt_estimate = max(1, (len(str(prompt).encode("utf-8")) + 2) // 3)
    reservation = prompt_estimate + max(1, int(output_tokens))
    limit = _session_token_limit()
    lease_id = uuid.uuid4().hex
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=4) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"gutgpt-session-tokens:{session_id}",))
                cur.execute("""INSERT INTO groq_session_token_usage(session_id, used_tokens)
                    VALUES (%s, 0) ON CONFLICT(session_id) DO NOTHING""", (session_id,))
                cur.execute("SELECT used_tokens FROM groq_session_token_usage WHERE session_id=%s FOR UPDATE", (session_id,))
                used = int(cur.fetchone()["used_tokens"])
                # Stale reservations are charged at their reserved maximum. This
                # prevents a crashed worker from silently restoring token budget.
                cur.execute("""SELECT COALESCE(SUM(reserved_tokens), 0) AS tokens
                    FROM groq_session_token_leases WHERE session_id=%s AND expires_at <= NOW()""", (session_id,))
                stale_tokens = int(cur.fetchone()["tokens"])
                if stale_tokens:
                    cur.execute("UPDATE groq_session_token_usage SET used_tokens=used_tokens+%s WHERE session_id=%s", (stale_tokens, session_id))
                    used += stale_tokens
                    cur.execute("DELETE FROM groq_session_token_leases WHERE session_id=%s AND expires_at <= NOW()", (session_id,))
                cur.execute("""SELECT COALESCE(SUM(reserved_tokens), 0) AS tokens
                    FROM groq_session_token_leases WHERE session_id=%s AND expires_at > NOW()""", (session_id,))
                reserved = int(cur.fetchone()["tokens"])
                if used + reserved + reservation > limit:
                    if budget is not None:
                        budget["session_limit_hit"] = True
                    raise SessionTokenLimitExceeded("This chat session has reached its cumulative AI token limit")
                cur.execute("""INSERT INTO groq_session_token_leases
                    (lease_id, session_id, reserved_tokens, expires_at)
                    VALUES (%s,%s,%s,NOW() + INTERVAL '10 minutes')""", (lease_id, session_id, reservation))
        logger.info("event=session_token_reservation request_id=%s task=%s reserved=%s", request_id, reason, reservation)
        return lease_id
    except SessionTokenLimitExceeded:
        logger.warning("event=session_token_limit_reached request_id=%s session=%s limit=%s", request_id, session_id[:8], limit)
        raise
    except Exception as exc:
        logger.warning("event=session_token_accounting_failed request_id=%s category=%s", request_id, type(exc).__name__)
        raise GroqBusyError("Could not safely account for session token usage", reason="session_usage_unavailable") from exc


def _session_token_release(lease_id: str | None, *, actual_tokens: int | None) -> None:
    if not lease_id:
        return
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=4) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT session_id FROM groq_session_token_leases WHERE lease_id=%s", (lease_id,))
                session_row = cur.fetchone()
                if not session_row:
                    return
                session_id = session_row["session_id"]
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"gutgpt-session-tokens:{session_id}",))
                cur.execute("""DELETE FROM groq_session_token_leases WHERE lease_id=%s
                    RETURNING session_id, reserved_tokens""", (lease_id,))
                lease = cur.fetchone()
                if lease:
                    charged = int(lease["reserved_tokens"]) if actual_tokens is None else max(0, int(actual_tokens))
                    cur.execute("UPDATE groq_session_token_usage SET used_tokens=used_tokens+%s, updated_at=NOW() WHERE session_id=%s", (charged, lease["session_id"]))
    except Exception as exc:
        logger.warning("event=session_token_release_failed category=%s", type(exc).__name__)



def ensure_shared_limiter_schema(cur) -> None:
    """Create or add the lease fields needed for atomic TPM reconciliation."""
    cur.execute("""CREATE TABLE IF NOT EXISTS groq_shared_usage_window (
        singleton SMALLINT PRIMARY KEY CHECK (singleton = 1),
        window_started_at TIMESTAMPTZ NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0,
        reserved_tokens BIGINT NOT NULL DEFAULT 0,
        cooldown_until TIMESTAMPTZ
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS groq_shared_leases (
        lease_id TEXT PRIMARY KEY,
        expires_at TIMESTAMPTZ NOT NULL,
        reserved_tokens BIGINT,
        window_started_at TIMESTAMPTZ
    )""")
    # NULL identifies legacy in-flight leases. Their old aggregate reservation
    # stays charged until the normal 60-second reset, which is conservative.
    cur.execute("ALTER TABLE groq_shared_leases ADD COLUMN IF NOT EXISTS reserved_tokens BIGINT")
    cur.execute("ALTER TABLE groq_shared_leases ADD COLUMN IF NOT EXISTS window_started_at TIMESTAMPTZ")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_groq_shared_leases_expiry ON groq_shared_leases(expires_at)")
    cur.execute("""CREATE TABLE IF NOT EXISTS groq_session_token_usage (
        session_id TEXT PRIMARY KEY,
        used_tokens BIGINT NOT NULL DEFAULT 0 CHECK (used_tokens >= 0),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS groq_session_token_leases (
        lease_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        reserved_tokens BIGINT NOT NULL CHECK (reserved_tokens > 0),
        expires_at TIMESTAMPTZ NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_groq_session_token_leases_session_expiry ON groq_session_token_leases(session_id, expires_at)")


def _shared_capacity_reserve(
    prompt: Any,
    request_id: str,
    *,
    reason: str,
    output_tokens: int,
) -> str | None:
    """Reserve shared RPM/TPM/concurrency capacity in PostgreSQL atomically.

    Chat production requests run inside message_call_budget and therefore require
    the shared limiter by default. Standalone unit tests/out-of-request calls do
    not require a database reservation.
    """
    if _budget.get() is None:
        return None
    enabled = os.getenv("GROQ_SHARED_LIMITER_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
    if not enabled:
        raise GroqBusyError("Shared Groq limiter is disabled", reason="disabled")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise GroqBusyError("Shared Groq limiter requires DATABASE_URL", reason="database_unavailable")
    rpm_limit = max(1, int(os.getenv("GROQ_SHARED_RPM_LIMIT", "30")))
    tpm_limit = max(1, int(os.getenv("GROQ_SHARED_TPM_LIMIT", "20000")))
    concurrency_limit = max(1, int(os.getenv("GROQ_SHARED_MAX_CONCURRENT", "8")))
    output_reserve = max(1, int(output_tokens))
    prompt_text = str(prompt)
    prompt_estimate = max(1, (len(prompt_text.encode("utf-8")) + 2) // 3)
    token_reserve = prompt_estimate + output_reserve
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
                    WHERE singleton=1 RETURNING request_count, reserved_tokens, cooldown_until, window_started_at""")
                row = cur.fetchone()
                cur.execute("SELECT COUNT(*) AS active FROM groq_shared_leases WHERE expires_at > NOW()")
                active = int(cur.fetchone()["active"])
                if row["cooldown_until"] is not None:
                    cur.execute("SELECT (cooldown_until > NOW()) AS active FROM groq_shared_usage_window WHERE singleton=1")
                    if cur.fetchone()["active"]:
                        raise GroqCircuitOpen("Shared Groq cooldown is active")
                if int(row["request_count"]) >= rpm_limit:
                    raise GroqBusyError("Shared Groq request limit reached", reason="rpm")
                if int(row["reserved_tokens"]) + token_reserve > tpm_limit:
                    raise GroqBusyError("Shared Groq token limit reached", reason="tpm")
                if active >= concurrency_limit:
                    raise GroqBusyError("Shared Groq concurrency limit reached", reason="concurrency")
                cur.execute("UPDATE groq_shared_usage_window SET request_count=request_count+1, reserved_tokens=reserved_tokens+%s WHERE singleton=1", (token_reserve,))
                cur.execute("""INSERT INTO groq_shared_leases
                    (lease_id, expires_at, reserved_tokens, window_started_at)
                    VALUES (%s, NOW() + INTERVAL '90 seconds', %s, %s)""",
                    (lease_id, token_reserve, row["window_started_at"]))
        logger.info("event=groq_shared_reservation provider=groq request_id=%s task=%s reserved_tokens=%s output_tokens=%s",
                    request_id, reason, token_reserve, output_reserve)
        return lease_id
    except (GroqBusyError, GroqCircuitOpen) as exc:
        logger.warning("event=groq_shared_rejected provider=groq request_id=%s task=%s reason=%s breaker_state=%s",
                       request_id, reason, getattr(exc, "reason", "shared_cooldown"), _breaker_state())
        raise
    except Exception as exc:
        logger.warning("event=groq_shared_limiter_error request_id=%s category=%s", request_id, type(exc).__name__)
        logger.warning("event=groq_shared_rejected provider=groq request_id=%s task=%s reason=database_unavailable breaker_state=%s",
                       request_id, reason, _breaker_state())
        raise GroqBusyError("Shared Groq limiter is unavailable; failing closed") from exc


def _shared_capacity_release(lease_id: str | None, *, actual_tokens: int | None = None, request_id: str = "unknown") -> None:
    if not lease_id:
        return
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=4) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('gutgpt-groq-shared-limiter'))")
                cur.execute("""DELETE FROM groq_shared_leases WHERE lease_id=%s
                    RETURNING reserved_tokens, window_started_at""", (lease_id,))
                lease = cur.fetchone()
                if lease and actual_tokens is not None and lease["reserved_tokens"] is not None and lease["window_started_at"] is not None:
                    cur.execute("""UPDATE groq_shared_usage_window
                        SET reserved_tokens=GREATEST(0, reserved_tokens - %s + %s)
                        WHERE singleton=1 AND window_started_at=%s""",
                        (int(lease["reserved_tokens"]), max(0, int(actual_tokens)), lease["window_started_at"]))
                    logger.info("event=groq_shared_reconciled provider=groq request_id=%s reserved_tokens=%s actual_tokens=%s current_window=%s",
                                request_id, lease["reserved_tokens"], actual_tokens, bool(cur.rowcount))
    except Exception as exc:
        logger.warning("event=groq_shared_lease_release_failed provider=groq request_id=%s category=%s",
                       request_id, type(exc).__name__)


def _shared_cooldown(seconds: int = 10) -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return
    try:
        import psycopg
        with psycopg.connect(database_url, connect_timeout=4) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('gutgpt-groq-shared-limiter'))")
                cur.execute("""UPDATE groq_shared_usage_window SET cooldown_until=GREATEST(COALESCE(cooldown_until, NOW()), NOW() + (%s * INTERVAL '1 second')) WHERE singleton=1""", (max(1, seconds),))
    except Exception:
        logger.warning("event=groq_shared_cooldown_update_failed")


def _safe_provider_error_details(exc: Exception) -> dict[str, str]:
    """Extract non-sensitive provider diagnostics without logging request data."""
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        body = {}
    error = body.get("error") if isinstance(body.get("error"), dict) else body

    def safe_value(value: Any, limit: int = 180) -> str:
        if value is None:
            return "unknown"
        text = " ".join(str(value).split())
        # Defensive redaction in case an SDK error ever echoes credentials.
        import re
        text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", text)
        text = re.sub(r"\bgsk_[A-Za-z0-9_-]+", "[REDACTED]", text)
        text = re.sub(r"\bAIza[A-Za-z0-9_-]+", "[REDACTED]", text)
        text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED_JWT]", text)
        return text[:limit]

    message = error.get("message") if isinstance(error, dict) else None
    return {
        "api_error_code": safe_value(error.get("code") if isinstance(error, dict) else None, 80),
        "api_error_type": safe_value(error.get("type") if isinstance(error, dict) else None, 80),
        "api_error_param": safe_value(error.get("param") if isinstance(error, dict) else None, 80),
        "api_error_message": safe_value(message, 180),
    }


def invoke_groq(client: Any, prompt: Any, *, reason: str, request_id: str = "unknown") -> Any:
    """Invoke a configured LangChain Groq client once, with bounded waiting.

    Retries are intentionally not performed here. Client construction should
    set max_retries=0, so one invocation cannot hide an SDK retry loop.
    """
    request_id = _reserve_budget(request_id)
    owns_probe = _breaker_before_call(request_id)
    started = time.monotonic()
    model_name = getattr(client, "model_name", None) or getattr(client, "model", None) or "configured"
    provider_name = getattr(client, "_gutgpt_provider", "groq")
    configured_max = getattr(client, "max_tokens", None)
    if not isinstance(configured_max, int) or configured_max <= 0:
        configured_max = configured_output_tokens(reason)
    lease_id = None
    session_lease_id = None
    actual_tokens = None
    acquired = False
    provider_started = False
    try:
        session_lease_id = _session_token_reserve(
            prompt, request_id, reason=reason, output_tokens=configured_max,
        )
        lease_id = _shared_capacity_reserve(
            prompt, request_id, reason=reason, output_tokens=configured_max,
        )
        try:
            acquired = _SEMAPHORE.acquire(timeout=_ACQUIRE_TIMEOUT)
        except Exception as exc:
            actual_tokens = 0  # The model was not called; this reservation is refundable.
            logger.warning("event=groq_rejected provider=%s request_id=%s task=%s category=local_semaphore_error error_type=%s breaker_state=%s",
                           provider_name, request_id, reason, type(exc).__name__, _breaker_state())
            raise GroqBusyError("Groq local capacity is temporarily unavailable", reason="local_semaphore_error") from exc
        if not acquired:
            logger.warning("event=groq_rejected provider=%s request_id=%s task=%s category=local_queue_full breaker_state=%s",
                           provider_name, request_id, reason, _breaker_state())
            actual_tokens = 0  # No provider request was started; refund this lease.
            raise GroqBusyError("Groq capacity is temporarily busy", reason="local_queue_full")
        try:
            provider_started = True
            response = client.invoke(prompt)
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
            details = _safe_provider_error_details(exc)
            logger.warning(
                "event=llm_failure provider=%s request_id=%s task=%s model=%s category=%s status=%s "
                "api_error_code=%s api_error_type=%s api_error_param=%s api_error_message=%s "
                "latency_ms=%.1f retry_count=0 breaker_state=%s",
                provider_name, request_id, reason, model_name, category, status,
                details["api_error_code"], details["api_error_type"],
                details["api_error_param"], details["api_error_message"],
                (time.monotonic() - started) * 1000, _breaker_state())
            raise
        _breaker_success()
        in_tokens, out_tokens = _usage(response)
        if in_tokens is not None and out_tokens is not None:
            actual_tokens = max(0, in_tokens) + max(0, out_tokens)
        metadata = getattr(response, "response_metadata", None) or {}
        metadata = metadata if isinstance(metadata, dict) else {}
        finish_reason = str(metadata.get("finish_reason") or metadata.get("stop_reason") or "unknown")
        truncated = is_truncated_finish_reason(finish_reason)
        latency_ms = (time.monotonic() - started) * 1000
        if truncated:
            logger.warning("event=llm_truncated provider=%s request_id=%s task=%s model=%s finish_reason=%s latency_ms=%.1f breaker_state=%s",
                           provider_name, request_id, reason, model_name, finish_reason, latency_ms, _breaker_state())
        logger.info(
            "event=llm_call provider=%s request_id=%s task=%s model=%s latency_ms=%.1f input_tokens=%s output_tokens=%s finish_reason=%s truncated=%s retry_count=0 result=model breaker_state=%s shared_limiter=%s",
            provider_name, request_id, reason, model_name, latency_ms, in_tokens, out_tokens,
            finish_reason, truncated, _breaker_state(), "reserved" if lease_id else "not_required",
        )
        return response
    finally:
        if not acquired:
            _breaker_probe_aborted(owns_probe)
        else:
            _SEMAPHORE.release()
        if session_lease_id and not provider_started and actual_tokens is None:
            actual_tokens = 0
        _session_token_release(session_lease_id, actual_tokens=actual_tokens)
        _shared_capacity_release(lease_id, actual_tokens=actual_tokens, request_id=request_id)
