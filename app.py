"""
GutGPT FastAPI backend.

The diagnosis/recommendation business logic remains in the existing Python
modules. This layer handles HTTP, sessions, CORS, and serves
the single embeddable JavaScript widget.

Run locally:
    uvicorn app:app --reload --host 0.0.0.0 --port 8000
"""
from pathlib import Path
from contextlib import asynccontextmanager
import os
import uuid
import time
import logging
import subprocess
import json
import re
import secrets
import hashlib
import hmac
import jwt
from jwt import InvalidTokenError
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from dotenv import load_dotenv
load_dotenv()
INDIA_TZ = ZoneInfo("Asia/Kolkata")
from threading import RLock

from fastapi import FastAPI, HTTPException, Header, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("gutgpt.performance")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

from guttify_agent import ConversationManager, SessionState
from intent_parser import SymptomState
from dataclasses import asdict
from symptom_questionnaire import next_question
from symptom_summary import build_symptom_summary
from guttify_chatbot import _deterministic_product_reply, _deterministic_screening_reply
BASE_DIR = Path(__file__).resolve().parent
WIDGET_FILE = BASE_DIR / "gutgpt-widget.js"
VERSION_FILE = BASE_DIR / "VERSION.txt"
QUESTION_FLOW_SCHEMA_VERSION = "v18.1"

from support_footer import append_human_support_footer
from groq_service import message_call_budget, configured_message_budget, GroqBudgetExceeded, GroqCircuitOpen, GroqBusyError
MAX_MESSAGE_LENGTH = max(256, min(10000, int(os.getenv("MAX_MESSAGE_LENGTH", "4000"))))
MAX_HISTORY_MESSAGES = 100

# GutGPT communicates exclusively in English. There is no language detection,
# no automatic translation, and no multilingual response rendering. Messages
# that are clearly not in English (Hindi, Hinglish, other scripts, or
# non-English confirmation words) receive a fixed English notice and are never
# run through the clinical engine, so a non-English "yes"/"no" can never
# advance an assessment as though it were English.
ENGLISH_ONLY_FALLBACK = (
    "I can assist you in English only. Please describe your symptoms in English so I can help you."
)
NON_ENGLISH_STATUS = "NON_ENGLISH"

# Non-Latin scripts are never part of an English GutGPT message.
_NON_LATIN_SCRIPT_RANGES = (
    (0x0900, 0x097F),  # Devanagari (Hindi, Marathi, Sanskrit, ...)
    (0x0980, 0x09FF),  # Bengali
    (0x0A00, 0x0A7F),  # Gurmukhi (Punjabi)
    (0x0A80, 0x0AFF),  # Gujarati
    (0x0B00, 0x0B7F),  # Odia
    (0x0B80, 0x0BFF),  # Tamil
    (0x0C00, 0x0C7F),  # Telugu
    (0x0C80, 0x0CFF),  # Kannada
    (0x0D00, 0x0D7F),  # Malayalam
)

# Conservative Roman-script Hindi/Hinglish marker words. Ordinary English
# words are deliberately excluded (for example "gas", "hi", "me", "no",
# "daily", "ok") so English messages with product names, medical terms,
# abbreviations or spelling mistakes are never mistaken for another language.
_HINDI_HINGLISH_MARKERS = {
    "haan", "han", "haa", "ji", "nahi", "nahin", "nhi", "nah",
    "bilkul", "kya", "kaise", "kab", "kyun", "kitna", "kitni",
    "raat", "subah", "shaam", "sham", "dopahar", "hafta", "mahina", "mahino",
    "saal", "din", "kal", "aaj", "mujhe", "mujhko", "mera", "meri", "mere",
    "mein", "se", "ko", "ka", "ki", "ke", "aur", "lekin", "par", "abhi",
    "dard", "jalan", "phoolna", "kabz", "dast", "patla", "potty", "khoon",
    "ulti", "matli", "zyada", "thoda", "bahut", "kam", "baar", "hoga", "hogi",
    "sakta", "sakti", "sakte", "chahiye", "batao", "batayein", "matlab",
    "kabhi", "roz", "hoti", "hote", "hota", "hai", "hain", "ho", "raha",
    "rahi", "rahe", "fulna", "takleef", "pareshani", "qabz", "dakaar",
    "khana", "khane", "baad", "pehle",
}

# Short Roman-script answers that are Hinglish/Hindi rather than English.
# English "yes"/"no" are intentionally absent: they remain valid confirmations.
_NON_ENGLISH_SHORT_ANSWERS = {"haan", "han", "haa", "ji", "bilkul", "nahi", "nahin", "nhi", "nah"}


def _is_non_english(text: str) -> bool:
    """Return True when a message is clearly not English.

    Detection is conservative and English-biased: non-Latin script is always
    non-English, and Roman-script text is flagged only when it contains
    Hindi/Hinglish marker words. Short messages (three tokens or fewer) need
    one marker; longer messages need two, so a lone English word that happens
    to resemble a marker (for example "gas") never triggers the fallback.
    """
    if not text:
        return False
    for ch in text:
        code = ord(ch)
        for lo, hi in _NON_LATIN_SCRIPT_RANGES:
            if lo <= code <= hi:
                return True
    normalized = re.sub(r"[^a-z0-9\s']", " ", text.lower())
    tokens = normalized.split()
    joined = " ".join(tokens)
    if joined in _NON_ENGLISH_SHORT_ANSWERS:
        return True
    marker_count = sum(1 for token in tokens if token in _HINDI_HINGLISH_MARKERS)
    if len(tokens) <= 3:
        return marker_count >= 1
    return marker_count >= 2

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
GUEST_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
GUEST_COOKIE_NAME = "gutgpt_guest_token"
JWT_ALGORITHM = "HS256"
JWT_ISSUER = os.getenv("JWT_ISSUER", "gutgpt-api")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "gutgpt-guest-session")


def _jwt_signing_key() -> str:
    """Return the configured JWT signing key; never use an insecure fallback."""
    key = os.getenv("JWT_SECRET_KEY", "")
    # 32 arbitrary UTF-8 bytes do not establish 256 bits of entropy. Require
    # the 43-character URL-safe representation produced by token_urlsafe(32).
    if len(key) < 43 or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise HTTPException(
            status_code=503,
            detail="Guest sessions are temporarily unavailable. Server authentication is not configured.",
        )
    return key


def _issue_guest_jwt(customer_id: str) -> tuple[str, str, str]:
    """Return signed JWT, JTI hash, and ISO expiry timestamp."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=GUEST_TOKEN_TTL_SECONDS)
    jti = secrets.token_urlsafe(32)
    claims = {
        "sub": customer_id,
        "typ": "guest_access",
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": jti,
    }
    token = jwt.encode(claims, _jwt_signing_key(), algorithm=JWT_ALGORITHM)
    return token, hashlib.sha256(jti.encode("utf-8")).hexdigest(), expires.isoformat()


def _request_is_secure(request: Request | None) -> bool:
    """Honor TLS termination at a trusted reverse proxy."""
    if request is None:
        return False
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return request.url.scheme == "https" or forwarded_proto == "https"


def _uses_partitioned_guest_cookie(request: Request | None, secure: bool) -> bool:
    """Use CHIPS for allowlisted HTTPS storefront embeds on a different host.

    Partitioned cookies remain HttpOnly and are scoped to the top-level Shopify
    site. This helps browsers that block unpartitioned third-party cookies; it
    does not promise cross-browser persistence where partitioned cookies are
    unsupported or disabled. First-party frontend requests keep the normal
    host-only cookie behavior.
    """
    if request is None or not secure:
        return False
    origin = request.headers.get("origin", "").strip().rstrip("/")
    if not origin or origin not in allowed_origins:
        return False
    try:
        origin_host = urlparse(origin).hostname
    except ValueError:
        return False
    return bool(origin_host and origin_host.lower() != (request.url.hostname or "").lower())


def _mark_last_guest_cookie_partitioned(response: Response, enabled: bool) -> None:
    """Append the CHIPS attribute without requiring a newer Starlette version."""
    if not enabled:
        return
    cookie_prefix = f"{GUEST_COOKIE_NAME}=".encode("ascii")
    for index in range(len(response.raw_headers) - 1, -1, -1):
        name, value = response.raw_headers[index]
        if name.lower() == b"set-cookie" and value.startswith(cookie_prefix):
            if b"; partitioned" not in value.lower():
                response.raw_headers[index] = (name, value + b"; Partitioned")
            return


def _set_guest_cookie(response: Response | None, request: Request | None, token: str, max_age: int) -> None:
    """Set a persistent, HttpOnly guest credential; partition it for embeds.

    HTTPS requests use SameSite=None; Secure. For allowlisted cross-host
    Shopify requests, Partitioned additionally enables CHIPS-capable browsers
    to retain the credential without making it readable to JavaScript.
    """
    if response is None or not token:
        return
    secure = _request_is_secure(request)
    response.set_cookie(
        key=GUEST_COOKIE_NAME,
        value=token,
        max_age=max(0, int(max_age)),
        httponly=True,
        secure=secure,
        samesite="none" if secure else "lax",
        path="/",
    )
    _mark_last_guest_cookie_partitioned(response, _uses_partitioned_guest_cookie(request, secure))


def _delete_guest_cookie(response: Response | None, request: Request | None) -> None:
    if response is None:
        return
    secure = _request_is_secure(request)
    response.delete_cookie(
        key=GUEST_COOKIE_NAME, path="/", httponly=True, secure=secure,
        samesite="none" if secure else "lax",
    )
    _mark_last_guest_cookie_partitioned(response, _uses_partitioned_guest_cookie(request, secure))


def _decode_guest_jwt(token: str) -> dict:
    """Verify signature and all required guest-session JWT claims."""
    try:
        claims = jwt.decode(
            token,
            _jwt_signing_key(),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti", "typ"]},
        )
    except HTTPException:
        raise
    except (InvalidTokenError, TypeError, ValueError) as exc:
        # Log only the exception class, never the JWT or its claims.
        logger.warning("Guest JWT validation failed reason=%s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="GUEST_SESSION_INVALID. Please register again.") from exc
    if claims.get("typ") != "guest_access":
        logger.warning("Guest JWT validation failed reason=wrong_token_type")
        raise HTTPException(status_code=401, detail="GUEST_SESSION_INVALID. Please register again.")
    if not isinstance(claims.get("sub"), str) or not claims.get("sub"):
        logger.warning("Guest JWT validation failed reason=missing_subject")
        raise HTTPException(status_code=401, detail="GUEST_SESSION_INVALID. Please register again.")
    return claims


def validate_production_configuration():
    """Fail fast when required final-site configuration is missing."""
    missing = []
    if not os.getenv("GROQ_API_KEY"):
        missing.append("GROQ_API_KEY")
    if not DATABASE_URL:
        missing.append("DATABASE_URL (PostgreSQL is required; JSON-file storage is disabled)")
    if not allowed_origins:
        missing.append("ALLOWED_ORIGINS")
    else:
        try:
            _validate_allowed_origins(allowed_origins)
        except ValueError as exc:
            raise RuntimeError(f"Invalid ALLOWED_ORIGINS configuration: {exc}") from exc
    jwt_secret = os.getenv("JWT_SECRET_KEY", "")
    if len(jwt_secret) < 43 or not re.fullmatch(r"[A-Za-z0-9_-]+", jwt_secret):
        missing.append("JWT_SECRET_KEY (at least 43 URL-safe characters generated from 32 random bytes)")
    if missing:
        raise RuntimeError(
            "Missing required production environment variable(s): "
            + ", ".join(missing)
        )
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "unknown"
    except Exception:
        version = "unknown"
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR, stderr=subprocess.DEVNULL,
            text=True, timeout=2,
        ).strip() or "not-a-git-checkout"
    except Exception:
        git_sha = os.getenv("GIT_SHA", "unknown")
    logger.info(
        "GutGPT build fingerprint: version=%s git_sha=%s question_flow_schema=%s",
        version, git_sha, QUESTION_FLOW_SCHEMA_VERSION,
    )
    logger.info(
        "GutGPT production configuration validated: origins=%d session_ttl=%ss max_sessions=%d",
        len(allowed_origins), SESSION_TTL_SECONDS, MAX_SESSIONS,
    )


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Validate required configuration when the application starts."""
    validate_production_configuration()
    # Safe diagnostic: log the selected storage backend without exposing credentials.
    logger.info("Customer storage backend: PostgreSQL (required)")
    workers = os.getenv("WEB_CONCURRENCY", "1").strip()
    try:
        worker_count = int(workers)
    except ValueError:
        worker_count = 1
    if worker_count > 1:
        raise RuntimeError(
            "GutGPT diagnostic sessions are currently in-memory and require one worker. "
            "Do not set WEB_CONCURRENCY above 1 until a shared session backend is implemented."
        )
    _init_postgres()
    yield


app = FastAPI(title="GutGPT API", version="18.3-jwt-guest-30d-diag", lifespan=lifespan)


# Shopify storefront origins are supplied as a comma-separated environment
# variable, for example:
# ALLOWED_ORIGINS=https://www.guttify.com,https://guttify.com
def _configured_origins():
    return [
        origin.strip().rstrip("/")
        for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]


def _validate_allowed_origins(origins: list[str]) -> None:
    """Reject wildcard, malformed, and insecure non-local CORS origins."""
    for origin in origins:
        if origin == "*":
            raise ValueError("wildcard origins are not allowed")
        parsed = urlparse(origin)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            raise ValueError(f"{origin!r} must be an absolute HTTP(S) origin")
        if parsed.username or parsed.password or parsed.path or parsed.params or parsed.query or parsed.fragment:
            raise ValueError(f"{origin!r} must contain only scheme and host (no credentials, path, query, or fragment)")
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError(f"non-local origin {origin!r} must use HTTPS")


allowed_origins = _configured_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def security_response_headers(request, call_next):
    """Apply conservative browser security headers and prevent sensitive API caching."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    # Customer profiles, health-related chat, and admin exports must not be
    # retained by shared proxies or browser HTTP caches.
    if request.url.path.startswith("/api/") or request.url.path == "/admin":
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response

def _cleanup_sessions(now: float | None = None):
    """Expire abandoned sessions and cap total in-memory session count."""
    now = time.monotonic() if now is None else now
    cutoff = now - SESSION_TTL_SECONDS
    with _SESSION_LOCK:
        expired = [
            sid for sid, last_access in HISTORY_LAST_ACCESS.items()
            if last_access < cutoff
        ]
        for sid in expired:
            HISTORY.pop(sid, None)
            HISTORY_LAST_ACCESS.pop(sid, None)
            conversation_manager.remove(sid)
            SESSION_CUSTOMER_IDS.pop(sid, None)
            SESSION_ASSESSMENT_IDS.pop(sid, None)
            with CUSTOMER_LOCK:
                REGISTERED_CUSTOMER_SESSIONS.discard(sid)

        if len(HISTORY_LAST_ACCESS) > MAX_SESSIONS:
            excess = len(HISTORY_LAST_ACCESS) - MAX_SESSIONS
            oldest = sorted(HISTORY_LAST_ACCESS.items(), key=lambda item: item[1])[:excess]
            for sid, _ in oldest:
                HISTORY.pop(sid, None)
                HISTORY_LAST_ACCESS.pop(sid, None)
                conversation_manager.remove(sid)
                SESSION_CUSTOMER_IDS.pop(sid, None)
                SESSION_ASSESSMENT_IDS.pop(sid, None)
                with CUSTOMER_LOCK:
                    REGISTERED_CUSTOMER_SESSIONS.discard(sid)

# Session state is kept in-process for the single-worker deployment used by
# the widget. Sessions are bounded by TTL and a hard maximum so abandoned
# browser sessions cannot grow memory without limit. Multi-worker deployment
# should use a shared store such as Redis.
SESSION_TTL_SECONDS = max(300, int(os.getenv("SESSION_TTL_SECONDS", "3600")))
MAX_SESSIONS = max(100, int(os.getenv("MAX_SESSIONS", "10000")))
MAX_MESSAGE_LENGTH = max(256, min(10000, int(os.getenv("MAX_MESSAGE_LENGTH", "4000"))))
MAX_HISTORY_MESSAGES = 100
HISTORY: dict[str, list[dict]] = {}
HISTORY_LAST_ACCESS: dict[str, float] = {}
_SESSION_LOCK = RLock()
conversation_manager = ConversationManager()
CUSTOMER_LOCK = RLock()
# Rate-limit counters are stored in PostgreSQL and shared across application workers.
_RATE_LIMIT_CLEANUP_LOCK = RLock()
_RATE_LIMIT_CLEANUP_LAST: float | None = None
_RATE_LIMIT_CLEANUP_INTERVAL_SECONDS = 600.0
REGISTERED_CUSTOMER_SESSIONS: set[str] = set()
# Maps each active diagnostic session to its persistent customer profile.
SESSION_CUSTOMER_IDS: dict[str, str] = {}
# Stable assessment identity survives browser refreshes and session-token rotation.
SESSION_ASSESSMENT_IDS: dict[str, str] = {}


def _postgres_connect():
    """Open a PostgreSQL connection. JSON/file fallback is intentionally unsupported."""
    if not DATABASE_URL:
        logger.critical("DATABASE_URL is required; refusing to use file-based customer storage")
        raise HTTPException(status_code=503, detail="PostgreSQL storage is not configured.")
    try:
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=8)
    except Exception as exc:
        logger.exception("PostgreSQL connection failed")
        raise HTTPException(status_code=503, detail="Customer storage is temporarily unavailable.") from exc


def _init_postgres() -> None:
    """Create/upgrade PostgreSQL tables and migrate legacy customer JSON safely."""
    conn = _postgres_connect()
    try:
        with conn, conn.cursor() as cur:
            # The customer profile table intentionally contains only profile fields.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id TEXT PRIMARY KEY,
                    name VARCHAR(150) NOT NULL,
                    age INTEGER NOT NULL CHECK (age BETWEEN 1 AND 120),
                    contact VARCHAR(100) NOT NULL,
                    location VARCHAR(150) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    likely_assessment TEXT
                )
            """)
            # Session credentials, bindings, chat history and resumable checkpoint data
            # live separately from customer profile data. JSONB is used only for the
            # structured, evolving conversation state, never as a customer record.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS customer_chat_state (
                    customer_id TEXT PRIMARY KEY REFERENCES customers(customer_id) ON DELETE CASCADE,
                    registration_session_id TEXT UNIQUE,
                    consent_to_store BOOLEAN NOT NULL DEFAULT FALSE,
                    guest_token_jti_hash TEXT,
                    guest_token_expires_at TIMESTAMPTZ,
                    bound_session_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                    last_session_id TEXT,
                    active_assessment_id TEXT,
                    active_checkpoint JSONB,
                    chat_state JSONB NOT NULL DEFAULT '{}'::jsonb,
                    chat_history JSONB NOT NULL DEFAULT '[]'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS customer_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
                    session_id VARCHAR(150) UNIQUE,
                    assessment TEXT,
                    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','abandoned')),
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS assessment_messages (
                    message_id BIGSERIAL PRIMARY KEY,
                    assessment_id TEXT NOT NULL REFERENCES customer_assessments(assessment_id) ON DELETE CASCADE,
                    sequence_no BIGINT NOT NULL,
                    turn_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (assessment_id, sequence_no),
                    UNIQUE (assessment_id, turn_id, role)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS assessment_state (
                    assessment_id TEXT PRIMARY KEY REFERENCES customer_assessments(assessment_id) ON DELETE CASCADE,
                    checkpoint JSONB NOT NULL,
                    checkpoint_version INTEGER NOT NULL DEFAULT 1,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            # Upgrade installations created by the short-lived schema that used
            # assessment_sessions + assessment_session_bindings. customer_assessments
            # is now the single canonical assessment/lifecycle table.
            cur.execute("""
                DO $$ BEGIN
                    IF to_regclass(current_schema() || '.assessment_sessions') IS NOT NULL THEN
                        INSERT INTO customer_assessments (assessment_id, customer_id, status, started_at, updated_at, completed_at)
                        SELECT assessment_id, customer_id, status, started_at, updated_at, completed_at
                        FROM assessment_sessions
                        ON CONFLICT (assessment_id) DO UPDATE SET
                            status=EXCLUDED.status,
                            started_at=LEAST(customer_assessments.started_at, EXCLUDED.started_at),
                            updated_at=GREATEST(customer_assessments.updated_at, EXCLUDED.updated_at),
                            completed_at=COALESCE(customer_assessments.completed_at, EXCLUDED.completed_at);
                    END IF;
                END $$;
            """)
            cur.execute("""
                DO $$ DECLARE c RECORD; BEGIN
                    FOR c IN SELECT conname FROM pg_constraint
                        WHERE conrelid='assessment_messages'::regclass AND contype='f'
                    LOOP EXECUTE format('ALTER TABLE assessment_messages DROP CONSTRAINT %I', c.conname); END LOOP;
                    FOR c IN SELECT conname FROM pg_constraint
                        WHERE conrelid='assessment_state'::regclass AND contype='f'
                    LOOP EXECUTE format('ALTER TABLE assessment_state DROP CONSTRAINT %I', c.conname); END LOOP;
                    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='assessment_messages_assessment_id_fkey') THEN
                        ALTER TABLE assessment_messages ADD CONSTRAINT assessment_messages_assessment_id_fkey
                            FOREIGN KEY (assessment_id) REFERENCES customer_assessments(assessment_id) ON DELETE CASCADE;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='assessment_state_assessment_id_fkey') THEN
                        ALTER TABLE assessment_state ADD CONSTRAINT assessment_state_assessment_id_fkey
                            FOREIGN KEY (assessment_id) REFERENCES customer_assessments(assessment_id) ON DELETE CASCADE;
                    END IF;
                END $$;
            """)
            cur.execute("DROP TABLE IF EXISTS assessment_session_bindings")
            cur.execute("DROP TABLE IF EXISTS assessment_sessions")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_customer_assessments_customer_status ON customer_assessments(customer_id, status, updated_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_assessment_messages_history ON assessment_messages(assessment_id, sequence_no)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_rate_limits (
                    rate_key TEXT PRIMARY KEY,
                    window_started_at TIMESTAMPTZ NOT NULL,
                    request_count INTEGER NOT NULL CHECK (request_count >= 0),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_api_rate_limits_updated_at ON api_rate_limits(updated_at)")
            cur.execute("""CREATE TABLE IF NOT EXISTS chat_idempotency (
                request_key TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('processing','complete','failed')),
                response_json JSONB,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_idempotency_updated_at ON chat_idempotency(updated_at)")
            cur.execute("""CREATE TABLE IF NOT EXISTS groq_shared_usage_window (
                singleton SMALLINT PRIMARY KEY CHECK (singleton = 1),
                window_started_at TIMESTAMPTZ NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                reserved_tokens BIGINT NOT NULL DEFAULT 0,
                cooldown_until TIMESTAMPTZ
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS groq_shared_leases (
                lease_id TEXT PRIMARY KEY,
                expires_at TIMESTAMPTZ NOT NULL
            )""")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_groq_shared_leases_expiry ON groq_shared_leases(expires_at)")
            # Drop any legacy FK definitions and recreate the expected customer FK.
            cur.execute("""
                DO $$ DECLARE constraint_row RECORD; BEGIN
                    FOR constraint_row IN
                        SELECT conname FROM pg_constraint
                        WHERE conrelid = 'customer_assessments'::regclass AND contype = 'f'
                    LOOP
                        EXECUTE format('ALTER TABLE customer_assessments DROP CONSTRAINT %I', constraint_row.conname);
                    END LOOP;
                END $$;
            """)
            cur.execute("ALTER TABLE customers ALTER COLUMN customer_id DROP DEFAULT")
            cur.execute("ALTER TABLE customers ALTER COLUMN customer_id TYPE TEXT USING customer_id::text")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS name VARCHAR(150) NOT NULL DEFAULT 'Customer'")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS age INTEGER NOT NULL DEFAULT 1")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS contact VARCHAR(100) NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS location VARCHAR(150) NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS likely_assessment TEXT")
            cur.execute("ALTER TABLE customers ALTER COLUMN contact TYPE VARCHAR(100) USING contact::text")
            cur.execute("UPDATE customers SET created_at = COALESCE(created_at, NOW()), updated_at = COALESCE(updated_at, created_at, NOW())")
            cur.execute("ALTER TABLE customers ALTER COLUMN created_at SET NOT NULL")
            cur.execute("ALTER TABLE customers ALTER COLUMN updated_at SET NOT NULL")
            cur.execute("ALTER TABLE customer_assessments ALTER COLUMN assessment_id DROP DEFAULT")
            cur.execute("ALTER TABLE customer_assessments ALTER COLUMN assessment_id TYPE TEXT USING assessment_id::text")
            cur.execute("ALTER TABLE customer_assessments ALTER COLUMN customer_id TYPE TEXT USING customer_id::text")
            cur.execute("ALTER TABLE customer_assessments ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ")
            cur.execute("ALTER TABLE customer_assessments ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed'")
            cur.execute("ALTER TABLE customer_assessments ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
            cur.execute("ALTER TABLE customer_assessments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
            cur.execute("ALTER TABLE customer_assessments ALTER COLUMN session_id DROP NOT NULL")
            cur.execute("ALTER TABLE customer_assessments ALTER COLUMN assessment DROP NOT NULL")
            cur.execute("ALTER TABLE customer_assessments ALTER COLUMN completed_at DROP NOT NULL")
            cur.execute("ALTER TABLE customer_assessments ALTER COLUMN completed_at DROP DEFAULT")
            cur.execute("ALTER TABLE customer_chat_state ADD COLUMN IF NOT EXISTS active_assessment_id TEXT")
            cur.execute("ALTER TABLE customer_assessments ADD CONSTRAINT customer_assessments_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE CASCADE")

            # Migrate legacy JSONB record fields into dedicated session columns before
            # dropping the old column. This is idempotent and preserves checkpoint,
            # authentication, consent and session-binding data across upgrades.
            cur.execute("""
                DO $$ BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema() AND table_name = 'customers' AND column_name = 'record_json'
                    ) THEN
                        EXECUTE $migrate$
                            INSERT INTO customer_chat_state (
                                customer_id, registration_session_id, consent_to_store,
                                guest_token_jti_hash, guest_token_expires_at,
                                bound_session_ids, last_session_id, active_checkpoint,
                                chat_state, chat_history, updated_at
                            )
                            SELECT c.customer_id,
                                   COALESCE(c.registration_session_id, NULLIF(c.record_json->>'session_id','')),
                                   COALESCE(c.consent_to_store, (c.record_json->>'consent_to_store')::boolean, FALSE),
                                   COALESCE(c.guest_token_jti_hash, NULLIF(c.record_json->>'guest_token_jti_hash','')),
                                   COALESCE(c.guest_token_expires_at, NULLIF(c.record_json->>'guest_token_expires_at','')::timestamptz),
                                   COALESCE(ARRAY(SELECT jsonb_array_elements_text(
                                       CASE WHEN jsonb_typeof(c.record_json->'bound_session_ids') = 'array'
                                            THEN c.record_json->'bound_session_ids' ELSE '[]'::jsonb END)), ARRAY[]::text[]),
                                   NULLIF(c.record_json->>'session_id',''),
                                   c.record_json->'active_checkpoint',
                                   COALESCE(c.record_json - ARRAY['customer_id','name','age','contact','location','city','created_at','updated_at','likely_assessment','assessments','session_id','consent_to_store','guest_token_jti_hash','guest_token_expires_at','bound_session_ids','active_checkpoint'], '{}'::jsonb),
                                   COALESCE(c.record_json->'active_checkpoint'->'history', '[]'::jsonb),
                                   COALESCE(c.updated_at, NOW())
                            FROM customers c
                            ON CONFLICT (customer_id) DO UPDATE SET
                                registration_session_id = COALESCE(customer_chat_state.registration_session_id, EXCLUDED.registration_session_id),
                                consent_to_store = customer_chat_state.consent_to_store OR EXCLUDED.consent_to_store,
                                guest_token_jti_hash = COALESCE(customer_chat_state.guest_token_jti_hash, EXCLUDED.guest_token_jti_hash),
                                guest_token_expires_at = COALESCE(customer_chat_state.guest_token_expires_at, EXCLUDED.guest_token_expires_at),
                                bound_session_ids = ARRAY(SELECT DISTINCT unnest(customer_chat_state.bound_session_ids || EXCLUDED.bound_session_ids)),
                                last_session_id = COALESCE(customer_chat_state.last_session_id, EXCLUDED.last_session_id),
                                active_checkpoint = COALESCE(customer_chat_state.active_checkpoint, EXCLUDED.active_checkpoint),
                                chat_state = customer_chat_state.chat_state || EXCLUDED.chat_state,
                                updated_at = GREATEST(customer_chat_state.updated_at, EXCLUDED.updated_at)
                        $migrate$;
                        -- Move assessment rows embedded in the old JSON record to the normalized history table.
                        EXECUTE $assessments$
                            INSERT INTO customer_assessments (assessment_id, customer_id, session_id, assessment, completed_at)
                            SELECT COALESCE(NULLIF(a.item->>'assessment_id',''), md5(c.customer_id || ':' || a.item->>'session_id')),
                                   c.customer_id, a.item->>'session_id',
                                   COALESCE(a.item->>'assessment', 'Insufficient information'),
                                   COALESCE(NULLIF(a.item->>'completed_at','')::timestamptz, NOW())
                            FROM customers c
                            CROSS JOIN LATERAL jsonb_array_elements(
                                CASE WHEN jsonb_typeof(c.record_json->'assessments') = 'array'
                                     THEN c.record_json->'assessments' ELSE '[]'::jsonb END) AS a(item)
                            WHERE NULLIF(a.item->>'session_id','') IS NOT NULL
                            ON CONFLICT (session_id) DO NOTHING
                        $assessments$;
                        EXECUTE 'ALTER TABLE customers DROP COLUMN record_json';
                    END IF;
                END $$;
            """)
            # Move legacy auth/session columns off customers after their values are in
            # customer_chat_state. DROP COLUMN is metadata-only and leaves all migrated data intact.
            cur.execute("ALTER TABLE customers DROP COLUMN IF EXISTS registration_session_id")
            cur.execute("ALTER TABLE customers DROP COLUMN IF EXISTS consent_to_store")
            cur.execute("ALTER TABLE customers DROP COLUMN IF EXISTS guest_token_jti_hash")
            cur.execute("ALTER TABLE customers DROP COLUMN IF EXISTS guest_token_expires_at")
            # Enforce the requested minimal customer schema even if the DB came from
            # an older manual setup with extra columns (e.g. city or legacy id fields).
            cur.execute("""
                DO $$ DECLARE col RECORD; BEGIN
                    FOR col IN
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = current_schema() AND table_name = 'customers'
                          AND column_name NOT IN ('customer_id','name','age','contact','location','created_at','updated_at','likely_assessment')
                    LOOP
                        EXECUTE format('ALTER TABLE customers DROP COLUMN %I', col.column_name);
                    END LOOP;
                END $$;
            """)
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_chat_registration_session ON customer_chat_state(registration_session_id) WHERE registration_session_id IS NOT NULL")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_customer_assessments_customer_id ON customer_assessments(customer_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_customer_assessments_completed_at ON customer_assessments(completed_at)")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_assessments_session_id ON customer_assessments(session_id)")
    finally:
        conn.close()


def _to_utc_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _read_customer_records() -> list[dict]:
    """Assemble the legacy in-process record shape from normalized PostgreSQL tables."""
    conn = _postgres_connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT c.customer_id, c.name, c.age, c.contact, c.location,
                       c.created_at, c.updated_at, c.likely_assessment,
                       s.registration_session_id, s.consent_to_store,
                       s.guest_token_jti_hash, s.guest_token_expires_at,
                       s.bound_session_ids, s.last_session_id, s.active_checkpoint,
                       s.chat_state, s.chat_history
                FROM customers c
                LEFT JOIN customer_chat_state s ON s.customer_id = c.customer_id
                ORDER BY c.created_at DESC
            """)
            records = []
            for row in cur.fetchall():
                record = {
                    "customer_id": row["customer_id"], "name": row["name"], "age": row["age"],
                    "contact": row["contact"], "location": row["location"],
                    "created_at": row["created_at"].astimezone(INDIA_TZ).isoformat() if row["created_at"] else None,
                    "updated_at": row["updated_at"].astimezone(INDIA_TZ).isoformat() if row["updated_at"] else None,
                    "likely_assessment": row["likely_assessment"],
                    "session_id": row["registration_session_id"] or row["last_session_id"],
                    "consent_to_store": bool(row["consent_to_store"]),
                    "guest_token_jti_hash": row["guest_token_jti_hash"],
                    "guest_token_expires_at": row["guest_token_expires_at"].astimezone(timezone.utc).isoformat() if row["guest_token_expires_at"] else None,
                    "bound_session_ids": list(row["bound_session_ids"] or []),
                    "active_checkpoint": row["active_checkpoint"],
                }
                # Keep this dict only as a compatibility adapter for existing business logic;
                # it is never stored as a monolithic customer JSON record.
                for key, value in (row["chat_state"] or {}).items():
                    record.setdefault(key, value)
                record["chat_history"] = row["chat_history"] or []
                cur.execute("SELECT assessment_id, session_id, assessment, completed_at, status, started_at, updated_at FROM customer_assessments WHERE customer_id=%s ORDER BY started_at", (record["customer_id"],))
                history = cur.fetchall()
                record["assessments"] = [{
                    "assessment_id": item["assessment_id"], "session_id": item["session_id"],
                    "assessment": item["assessment"],
                    "completed_at": item["completed_at"].astimezone(INDIA_TZ).isoformat() if item["completed_at"] else None,
                    "status": item["status"],
                    "started_at": item["started_at"].astimezone(INDIA_TZ).isoformat(),
                    "updated_at": item["updated_at"].astimezone(INDIA_TZ).isoformat(),
                } for item in history]
                if history:
                    record["likely_assessment"] = history[-1]["assessment"]
                records.append(record)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not read customer records from PostgreSQL")
        raise HTTPException(status_code=503, detail="Customer records are temporarily unavailable.") from exc
    finally:
        conn.close()
    for record in records:
        record.pop("final_symptom_summary", None)
    return records


def _write_customer_records(records: list[dict]) -> None:
    """Persist profile, chat/session state and assessment history in separate PostgreSQL tables."""
    conn = _postgres_connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('gutgpt_customer_store'))")
            for record in records:
                cid = str(record["customer_id"])
                created_at = _to_utc_datetime(record.get("created_at")) or datetime.now(timezone.utc)
                updated_at = _to_utc_datetime(record.get("updated_at")) or datetime.now(timezone.utc)
                expires_at = _to_utc_datetime(record.get("guest_token_expires_at"))
                location = str(record.get("location", record.get("city", "")))
                cur.execute("""
                    INSERT INTO customers (customer_id, name, age, contact, location, created_at, updated_at, likely_assessment)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (customer_id) DO UPDATE SET
                        name=EXCLUDED.name, age=EXCLUDED.age, contact=EXCLUDED.contact,
                        location=EXCLUDED.location, updated_at=EXCLUDED.updated_at,
                        likely_assessment=COALESCE(EXCLUDED.likely_assessment, customers.likely_assessment)
                """, (cid, str(record.get("name", "Customer")), int(record.get("age") or 1),
                      str(record.get("contact", "")), location, created_at, updated_at, record.get("likely_assessment")))
                bound_sessions = record.get("bound_session_ids", [])
                if not isinstance(bound_sessions, list):
                    bound_sessions = []
                session_id = record.get("session_id")
                if session_id and session_id not in bound_sessions:
                    bound_sessions.append(session_id)
                # Preserve other evolving session metadata in the dedicated state table.
                chat_state = {k: v for k, v in record.items() if k not in {
                    "customer_id", "name", "age", "contact", "location", "city", "created_at", "updated_at",
                    "likely_assessment", "assessments", "session_id", "consent_to_store", "guest_token_jti_hash",
                    "guest_token_expires_at", "bound_session_ids", "active_checkpoint", "chat_history", "final_symptom_summary"
                }}
                cur.execute("""
                    INSERT INTO customer_chat_state (
                        customer_id, registration_session_id, consent_to_store, guest_token_jti_hash,
                        guest_token_expires_at, bound_session_ids, last_session_id, active_checkpoint,
                        chat_state, chat_history, updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s)
                    ON CONFLICT (customer_id) DO UPDATE SET
                        registration_session_id=COALESCE(customer_chat_state.registration_session_id, EXCLUDED.registration_session_id),
                        consent_to_store=EXCLUDED.consent_to_store,
                        guest_token_jti_hash=EXCLUDED.guest_token_jti_hash,
                        guest_token_expires_at=EXCLUDED.guest_token_expires_at,
                        bound_session_ids=ARRAY(SELECT DISTINCT unnest(customer_chat_state.bound_session_ids || EXCLUDED.bound_session_ids)),
                        last_session_id=COALESCE(EXCLUDED.last_session_id, customer_chat_state.last_session_id),
                        active_checkpoint=EXCLUDED.active_checkpoint,
                        chat_state=customer_chat_state.chat_state || EXCLUDED.chat_state,
                        chat_history=EXCLUDED.chat_history,
                        updated_at=EXCLUDED.updated_at
                """, (cid, record.get("session_id"), bool(record.get("consent_to_store")),
                      record.get("guest_token_jti_hash"), expires_at, bound_sessions, session_id,
                      json.dumps(record.get("active_checkpoint"), ensure_ascii=False, default=str) if record.get("active_checkpoint") is not None else None,
                      json.dumps(chat_state, ensure_ascii=False, default=str),
                      json.dumps(record.get("chat_history", []), ensure_ascii=False, default=str), updated_at))
                for item in record.get("assessments", []) if isinstance(record.get("assessments", []), list) else []:
                    if not isinstance(item, dict) or not item.get("session_id"):
                        continue
                    completed = _to_utc_datetime(item.get("completed_at")) or datetime.now(timezone.utc)
                    cur.execute("""
                        INSERT INTO customer_assessments (assessment_id, customer_id, session_id, assessment, status, started_at, updated_at, completed_at)
                        VALUES (%s,%s,%s,%s,'completed',%s,%s,%s)
                        ON CONFLICT (session_id) DO UPDATE SET
                            assessment=EXCLUDED.assessment,
                            customer_id=EXCLUDED.customer_id,
                            -- The legacy history writer must not override normalized
                            -- assessment lifecycle state. _persist_assessment_checkpoint()
                            -- owns status/completed_at based on assessment_state.checkpoint.
                            updated_at=GREATEST(customer_assessments.updated_at, EXCLUDED.updated_at)
                    """, (str(item.get("assessment_id") or uuid.uuid4()), cid, str(item["session_id"]),
                          str(item.get("assessment", "Insufficient information")), completed, completed, completed))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not write customer records to PostgreSQL")
        raise HTTPException(status_code=503, detail="Customer records could not be saved.") from exc
    finally:
        conn.close()


def _persist_assessment_checkpoint(session_id: str, completed: bool = False, turn_id: str | None = None) -> None:
    """Persist a per-assessment checkpoint and newly appended messages in PostgreSQL.

    The rule engine remains the source of truth; this function only stores its state.
    """
    customer_id = SESSION_CUSTOMER_IDS.get(session_id)
    if not customer_id:
        return
    with conversation_manager._lock:
        state = conversation_manager.sessions.get(session_id)
        if state is None:
            return
        history = list(HISTORY.get(session_id, []))
        checkpoint = {
            "state": asdict(state),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "active": not bool(completed or state.diagnosis_complete or state.ended),
        }
    turn_id = str(turn_id or uuid.uuid4().hex)
    conn = _postgres_connect()
    assessment_id = SESSION_ASSESSMENT_IDS.get(session_id)
    try:
        with conn, conn.cursor() as cur:
            # Serialize writes for the same customer so parallel tabs cannot create
            # competing active assessments or interleave sequence numbers.
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"gutgpt_assessment:{customer_id}",))
            if assessment_id:
                cur.execute("SELECT assessment_id FROM customer_assessments WHERE assessment_id=%s AND customer_id=%s FOR UPDATE", (assessment_id, customer_id))
                if cur.fetchone() is None:
                    cur.execute("""
                        INSERT INTO customer_assessments (assessment_id, customer_id, session_id, status, started_at, updated_at)
                        VALUES (%s,%s,%s,'active',NOW(),NOW()) ON CONFLICT (assessment_id) DO NOTHING
                    """, (assessment_id, customer_id, session_id))
            else:
                cur.execute("SELECT active_assessment_id FROM customer_chat_state WHERE customer_id=%s FOR UPDATE", (customer_id,))
                active_row = cur.fetchone()
                active_id = active_row["active_assessment_id"] if active_row else None
                if active_id:
                    cur.execute("SELECT assessment_id FROM customer_assessments WHERE assessment_id=%s AND customer_id=%s AND status='active'", (active_id, customer_id))
                    active_exists = cur.fetchone()
                else:
                    active_exists = None
                if active_exists:
                    assessment_id = active_id
                else:
                    assessment_id = str(uuid.uuid4())
                    cur.execute("""
                        INSERT INTO customer_assessments (assessment_id, customer_id, session_id, status, started_at, updated_at)
                        VALUES (%s,%s,%s,'active',NOW(),NOW())
                    """, (assessment_id, customer_id, session_id))
            cur.execute("""
                UPDATE customer_assessments SET session_id=COALESCE(session_id,%s), updated_at=NOW()
                WHERE assessment_id=%s AND customer_id=%s
            """, (session_id, assessment_id, customer_id))
            cur.execute("""
                UPDATE customer_chat_state SET active_assessment_id=%s, last_session_id=%s, updated_at=NOW()
                WHERE customer_id=%s
            """, (assessment_id, session_id, customer_id))
            # Lock the assessment row before allocating message sequence numbers.
            cur.execute("SELECT status FROM customer_assessments WHERE assessment_id=%s FOR UPDATE", (assessment_id,))
            cur.fetchone()
            cur.execute("SELECT COALESCE(MAX(sequence_no),0) AS max_seq FROM assessment_messages WHERE assessment_id=%s", (assessment_id,))
            sequence_no = int(cur.fetchone()["max_seq"])
            # Each /api/chat turn appends exactly a user message and an assistant reply.
            # Persist only this turn, not the bounded in-memory history snapshot.
            for item in history[-2:]:
                if not isinstance(item, dict) or item.get("role") not in ("user", "assistant") or not isinstance(item.get("content"), str):
                    continue
                cur.execute("""
                    INSERT INTO assessment_messages (assessment_id, sequence_no, turn_id, role, content)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (assessment_id, turn_id, role) DO NOTHING
                """, (assessment_id, sequence_no + 1, turn_id, item["role"], item["content"]))
                if cur.rowcount:
                    sequence_no += 1
            cur.execute("""
                INSERT INTO assessment_state (assessment_id, checkpoint, checkpoint_version, updated_at)
                VALUES (%s,%s::jsonb,1,NOW())
                ON CONFLICT (assessment_id) DO UPDATE SET
                    checkpoint=EXCLUDED.checkpoint, checkpoint_version=EXCLUDED.checkpoint_version, updated_at=NOW()
            """, (assessment_id, json.dumps(checkpoint, ensure_ascii=False, default=str)))
            cur.execute("""
                UPDATE customer_assessments SET status=%s, updated_at=NOW(),
                    completed_at=CASE WHEN %s THEN COALESCE(completed_at,NOW()) ELSE completed_at END
                WHERE assessment_id=%s AND customer_id=%s
            """, ("completed" if not checkpoint["active"] else "active", not checkpoint["active"], assessment_id, customer_id))
            # Keep the old columns empty for compatibility; new message/checkpoint
            # data lives only in assessment_messages and assessment_state.
            cur.execute("""
                UPDATE customer_chat_state SET active_checkpoint=NULL, chat_history='[]'::jsonb, updated_at=NOW()
                WHERE customer_id=%s
            """, (customer_id,))
        SESSION_ASSESSMENT_IDS[session_id] = assessment_id
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Normalized assessment checkpoint persistence failed session=%s", session_id[:8])
        raise HTTPException(status_code=503, detail="Assessment progress could not be saved.") from exc
    finally:
        conn.close()



def _restore_assessment_checkpoint(customer_id: str, new_session_id: str) -> dict | None:
    """Restore the latest unfinished assessment, including its normalized message log."""
    checkpoint = None
    assessment_id = None
    updated_at = None
    active_assessment_found = False
    conn = _postgres_connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT a.assessment_id, st.checkpoint, st.updated_at
                FROM customer_assessments a
                LEFT JOIN assessment_state st ON st.assessment_id=a.assessment_id
                WHERE a.customer_id=%s AND a.status='active'
                  AND (st.assessment_id IS NULL OR COALESCE((st.checkpoint->>'active')::boolean, FALSE)=TRUE)
                ORDER BY a.updated_at DESC LIMIT 1
                FOR UPDATE OF a
            """, (customer_id,))
            row = cur.fetchone()
            if row:
                active_assessment_found = True
                assessment_id, checkpoint, updated_at = row["assessment_id"], row["checkpoint"], row["updated_at"]
                cur.execute("""
                    UPDATE customer_chat_state SET active_assessment_id=%s, last_session_id=%s, updated_at=NOW()
                    WHERE customer_id=%s
                """, (assessment_id, new_session_id, customer_id))
                cur.execute("""
                    SELECT role, content FROM (
                        SELECT sequence_no, role, content FROM assessment_messages
                        WHERE assessment_id=%s ORDER BY sequence_no DESC LIMIT %s
                    ) recent ORDER BY sequence_no ASC
                """, (assessment_id, MAX_HISTORY_MESSAGES))
                message_rows = cur.fetchall()
            else:
                message_rows = []
    except HTTPException:
        raise
    except Exception:
        logger.exception("Normalized assessment restore lookup failed customer=%s", customer_id[:8])
        raise
    finally:
        conn.close()

    if active_assessment_found and not isinstance(checkpoint, dict):
        # The assessment is known to be active, but its durable checkpoint is absent.
        # Never misreport this as NO_ACTIVE_ASSESSMENT: the widget must pause safely.
        logger.error("Active assessment has no checkpoint customer=%s assessment=%s", customer_id[:8], assessment_id)
        return {"status": "ASSESSMENT_CHECKPOINT_UNAVAILABLE", "messages": [], "assessment_id": assessment_id}

    if not isinstance(checkpoint, dict):
        # Backwards compatibility for a checkpoint created before normalized storage.
        # This path is only for legacy records, not an active normalized assessment.
        with CUSTOMER_LOCK:
            records = _read_customer_records()
            record = next((r for r in records if r.get("customer_id") == customer_id), None)
            checkpoint = (record or {}).get("active_checkpoint")
        if not isinstance(checkpoint, dict) or not checkpoint.get("active"):
            return None
        history = checkpoint.get("history", [])
    else:
        history = [{"role": r["role"], "content": r["content"]} for r in message_rows]

    payload = checkpoint.get("state")
    if not isinstance(payload, dict) or not isinstance(payload.get("symptom_state"), dict):
        logger.warning("Ignoring malformed assessment checkpoint customer=%s", customer_id[:8])
        return {"status": "ASSESSMENT_CHECKPOINT_INVALID", "messages": [], "assessment_id": assessment_id} if active_assessment_found else None
    try:
        payload = dict(payload)
        payload["symptom_state"] = SymptomState(**payload["symptom_state"])
        restored_state = SessionState(**payload)
        if not isinstance(history, list):
            history = []
        restored_history = [m for m in history if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)][-MAX_HISTORY_MESSAGES:]
    except (TypeError, ValueError) as exc:
        logger.warning("Ignoring incompatible assessment checkpoint: %s", exc)
        # If the database already confirmed an active assessment, a state
        # reconstruction failure is NOT evidence that no assessment exists.
        # Tell the caller to pause safely instead of inviting a fresh assessment.
        if active_assessment_found:
            return {
                "status": "ASSESSMENT_CHECKPOINT_INVALID",
                "messages": [],
                "assessment_id": assessment_id,
            }
        return None
    with conversation_manager._lock:
        conversation_manager.sessions[new_session_id] = restored_state
        conversation_manager.last_access[new_session_id] = time.monotonic()
        conversation_manager._session_locks.setdefault(new_session_id, RLock())
    with _SESSION_LOCK:
        HISTORY[new_session_id] = restored_history
        HISTORY_LAST_ACCESS[new_session_id] = time.monotonic()
    with CUSTOMER_LOCK:
        SESSION_CUSTOMER_IDS[new_session_id] = customer_id
        REGISTERED_CUSTOMER_SESSIONS.add(new_session_id)
    if assessment_id:
        SESSION_ASSESSMENT_IDS[new_session_id] = assessment_id
    return {"status": "RESUMED", "messages": restored_history, "updated_at": updated_at or checkpoint.get("updated_at"), "assessment_id": assessment_id}

def _persist_completed_assessment(session_id: str, result: dict) -> None:
    """Store only the likely assessment value on the matching customer row."""
    with conversation_manager._lock:
        session = conversation_manager.sessions.get(session_id)
        if session is None:
            logger.error("Assessment persistence skipped: conversation missing session=%s", session_id[:8])
            return
        # Endpoint status alone is not proof of completion: guard persistence
        # against stale/ambiguous completion paths and missing required fields.
        pending_question = next_question(session.symptom_state)
        urgent_safety_outcome = bool(
            result.get("status") == "SAFETY_REVIEW"
            and (result.get("screening") or {}).get("action") == "urgent_medical_evaluation"
        )
        if not urgent_safety_outcome and (session.awaiting_summary_confirmation or not session.diagnosis_complete or pending_question):
            logger.warning(
                "Assessment persistence blocked: incomplete session=%s summary_pending=%s diagnosis_complete=%s pending_question=%s",
                session_id[:8], session.awaiting_summary_confirmation,
                session.diagnosis_complete, pending_question[0] if pending_question else None,
            )
            return
        screening = result.get("screening") or getattr(session, "screening", None) or {}

    likely_assessment = screening.get("likely_condition") or screening.get("pattern") or "Insufficient information"
    with CUSTOMER_LOCK:
        records = _read_customer_records()
        customer_id = SESSION_CUSTOMER_IDS.get(session_id)
        customer = next((r for r in records if r.get("customer_id") == customer_id), None) if customer_id else None
        # Compatibility for sessions created before the session-to-customer map existed.
        if customer is None:
            customer = next((r for r in records if r.get("session_id") == session_id), None)
        if not customer or not customer.get("customer_id"):
            logger.error("Assessment persistence skipped: customer record missing session=%s", session_id[:8])
            return
        now = datetime.now(INDIA_TZ).isoformat()
        history = customer.setdefault("assessments", [])
        if not isinstance(history, list):
            history = customer["assessments"] = []
        # The chat endpoint may be retried by a browser/proxy. Treat persistence
        # as idempotent per diagnostic session while still allowing a customer to
        # have many assessments across different sessions.
        existing = next(
            (item for item in history
             if isinstance(item, dict) and item.get("session_id") == session_id),
            None,
        )
        if existing is None:
            assessment_id = SESSION_ASSESSMENT_IDS.setdefault(session_id, str(uuid.uuid4()))
            history.append({
                "assessment_id": assessment_id,
                "session_id": session_id,
                "assessment": str(likely_assessment),
                "completed_at": now,
            })
        else:
            # Repair/update a legacy or partial record without creating a duplicate.
            existing["assessment"] = str(likely_assessment)
            assessment_id = SESSION_ASSESSMENT_IDS.setdefault(session_id, str(existing.get("assessment_id") or uuid.uuid4()))
            existing["assessment_id"] = assessment_id
            existing.setdefault("completed_at", now)
        # Keep the dashboard's Assessment column useful by showing the latest result.
        customer["likely_assessment"] = str(likely_assessment)
        customer.pop("final_symptom_summary", None)
        _write_customer_records(records)
    logger.info("Assessment history saved in PostgreSQL customer_id=%s session=%s",
                customer["customer_id"], session_id[:8])


class CustomerRegistrationRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    age: int = Field(ge=1, le=120)
    contact: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    consent: bool


class CustomerRestoreRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    guest_token: str = Field(default="", max_length=2048)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    # Keep Pydantic above the production UX limit so we can return a friendly
    # application-level message instead of an opaque 422 validation error.
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    # Accepted for backward-compatible widget payloads; GutGPT is English-only
    # and this value never changes how a message is processed or answered.
    language: str = Field(default="en", max_length=16)
    message_id: str = Field(default="", max_length=128)


class ChatResponse(BaseModel):
    reply: str
    status: str
    recommendations: list[dict] = Field(default_factory=list)
    # True when the current assessment has reached a terminal outcome, including
    # urgent red-flag safety outcomes that must not continue in this session.
    assessment_complete: bool = False


def _request_client_key(request: Request) -> str:
    """Use the ASGI peer address; do not trust arbitrary X-Forwarded-For input."""
    host = request.client.host if request.client and request.client.host else "unknown-client"
    return host[:128]


def _should_cleanup_rate_limits() -> bool:
    """Run shared rate-limit-table housekeeping at most once per 10 minutes per worker."""
    global _RATE_LIMIT_CLEANUP_LAST
    now = time.monotonic()
    with _RATE_LIMIT_CLEANUP_LOCK:
        if (_RATE_LIMIT_CLEANUP_LAST is not None
                and now - _RATE_LIMIT_CLEANUP_LAST < _RATE_LIMIT_CLEANUP_INTERVAL_SECONDS):
            return False
        _RATE_LIMIT_CLEANUP_LAST = now
        return True


def _enforce_rate_limit(request: Request, *, scope: str, identity: str,
                        limit: int, window_seconds: int) -> None:
    """Enforce a fixed-window rate limit using PostgreSQL only.

    The raw identity is never persisted: keys are SHA-256 hashes. PostgreSQL
    errors fail closed rather than silently disabling protection in DB mode.
    """
    raw_key = f"{scope}:{identity}"
    rate_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    conn = _postgres_connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO api_rate_limits (rate_key, window_started_at, request_count, updated_at)
                VALUES (%s, NOW(), 1, NOW())
                ON CONFLICT (rate_key) DO UPDATE SET
                    request_count = CASE
                        WHEN api_rate_limits.window_started_at <= NOW() - (%s * INTERVAL '1 second') THEN 1
                        ELSE api_rate_limits.request_count + 1
                    END,
                    window_started_at = CASE
                        WHEN api_rate_limits.window_started_at <= NOW() - (%s * INTERVAL '1 second') THEN NOW()
                        ELSE api_rate_limits.window_started_at
                    END,
                    updated_at = NOW()
                RETURNING request_count, GREATEST(0, CEIL(EXTRACT(EPOCH FROM
                    (window_started_at + (%s * INTERVAL '1 second') - NOW()))))::integer AS retry_after
            """, (rate_key, window_seconds, window_seconds, window_seconds))
            row = cur.fetchone()
            count = int(row["request_count"] if isinstance(row, dict) else row[0])
            retry_after = int(row["retry_after"] if isinstance(row, dict) else row[1])
            if _should_cleanup_rate_limits():
                cur.execute("DELETE FROM api_rate_limits WHERE updated_at < NOW() - INTERVAL '2 days'")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PostgreSQL rate-limit check failed")
        raise HTTPException(status_code=503, detail="Request protection is temporarily unavailable.") from exc
    finally:
        conn.close()
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait before trying again.",
            headers={"Retry-After": str(max(1, retry_after))},
        )


@app.get("/")
def api_root():
    """Expose backend status only; the customer-facing UI is the Shopify widget."""
    return {
        "service": "GutGPT API",
        "status": "ok",
        "widget_script": "/gutgpt-widget.js",
        "health": "/api/health",
    }


@app.get("/api/health", response_model=str)
def health():
    """Simple backend health response."""
    return "GutGPT chatbot backend is running."


@app.get("/gutgpt-widget.js")
def widget():
    """Serve the one-file Shopify embeddable widget."""
    if not WIDGET_FILE.exists():
        # This should never happen in a valid deployment, but gives a useful
        # HTTP error rather than an opaque filesystem exception.
        raise HTTPException(status_code=500, detail="GutGPT widget is not installed.")
    return FileResponse(
        WIDGET_FILE,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.post("/api/session")
def new_session(request: Request = None):
    """Create a new conversation session for a visitor.

    FastAPI injects the request for HTTP calls. The optional default also keeps
    direct Python calls used by legacy unit tests backwards-compatible; those
    calls are not HTTP traffic and therefore do not use the request rate limiter.
    """
    if request is not None:
        _enforce_rate_limit(request, scope="session-create", identity=_request_client_key(request), limit=20, window_seconds=600)
    _cleanup_sessions()
    session_id = str(uuid.uuid4())
    now = time.monotonic()
    with _SESSION_LOCK:
        HISTORY[session_id] = []
        HISTORY_LAST_ACCESS[session_id] = now
        conversation_manager.reset(session_id)
    return {"session_id": session_id}


@app.post("/api/customer")
def register_customer(req: CustomerRegistrationRequest, request: Request = None, response: Response = None):
    """Save customer details to required PostgreSQL storage; file-based fallback is disabled.

    FastAPI injects the request for HTTP calls. The optional default preserves
    direct-call compatibility for unit tests; all real HTTP requests still pass
    through both IP/client and session registration rate limits.
    """
    if request is not None:
        _enforce_rate_limit(request, scope="customer-register-ip", identity=_request_client_key(request), limit=10, window_seconds=600)
        _enforce_rate_limit(request, scope="customer-register-session", identity=req.session_id, limit=5, window_seconds=600)
    if not req.consent:
        raise HTTPException(status_code=400, detail="Please consent to storing these details to continue.")

    name = " ".join(req.name.split())
    contact = req.contact.strip()
    city = " ".join(req.city.split())
    if not name or not contact or not city:
        raise HTTPException(status_code=400, detail="Please complete all customer details.")
    # Registration contact is digits only; reject spaces, plus signs, and punctuation.
    if not re.fullmatch(r"[0-9]{7,15}", contact):
        raise HTTPException(status_code=400, detail="Enter a contact number using digits only (7–15 digits).")

    with _SESSION_LOCK:
        if req.session_id not in HISTORY or req.session_id not in conversation_manager.sessions:
            raise HTTPException(status_code=410, detail="SESSION_EXPIRED")

    with CUSTOMER_LOCK:
        records = _read_customer_records()
        # Idempotent profile creation for registration retries. A retry rotates
        # the guest credential and invalidates any previously issued token.
        existing = next((item for item in records if item.get("session_id") == req.session_id), None)
        _assert_registration_customer_binding(req.session_id, existing)
        if existing is None:
            record = {
                "customer_id": str(uuid.uuid4()),
                "session_id": req.session_id,
                "name": name,
                "age": req.age,
                "contact": contact,
                "city": city,
                "consent_to_store": True,
                "created_at": datetime.now(INDIA_TZ).isoformat(),
            }
            records.append(record)
        else:
            record = existing
            record.update({"name": name, "age": req.age, "contact": contact, "city": city,
                           "consent_to_store": True})
        # A retried registration rotates the JWT and revokes the previous JTI.
        guest_token, token_jti_hash, token_expires_at = _issue_guest_jwt(record["customer_id"])
        record.pop("guest_token_hash", None)  # retire legacy opaque credential hash
        record["guest_token_jti_hash"] = token_jti_hash
        record["guest_token_expires_at"] = token_expires_at
        record["updated_at"] = datetime.now(INDIA_TZ).isoformat()
        bound_sessions = record.setdefault("bound_session_ids", [])
        if not isinstance(bound_sessions, list):
            bound_sessions = record["bound_session_ids"] = []
        if req.session_id not in bound_sessions:
            bound_sessions.append(req.session_id)
        _write_customer_records(records)
        REGISTERED_CUSTOMER_SESSIONS.add(req.session_id)
        SESSION_CUSTOMER_IDS[req.session_id] = record["customer_id"]

    # Reuse the age already collected by the registration form throughout the
    # diagnostic questionnaire. This makes the existing age question resolve
    # as answered without bypassing any other assessment or safety questions.
    with conversation_manager._lock:
        session_state = conversation_manager.sessions.get(req.session_id)
        if session_state is not None:
            session_state.symptom_state.age = record.get("age")

    _set_guest_cookie(response, request, guest_token, GUEST_TOKEN_TTL_SECONDS)
    logger.info("Customer registration saved session=%s", req.session_id[:8])
    # Keep the response field temporarily for API compatibility with older clients;
    # the updated first-party frontends do not persist or read this value.
    return {"status": "REGISTERED", "customer_id": record["customer_id"], "guest_token": guest_token, "token_expires_at": token_expires_at}


def _require_admin(authorization: str | None, request: Request) -> None:
    """Require a strong bearer token and throttle admin traffic and failed authentication."""
    _enforce_rate_limit(
        request, scope="admin-api", identity=_request_client_key(request),
        limit=120, window_seconds=60,
    )
    configured_token = os.getenv("GUTGPT_ADMIN_TOKEN", "").strip()
    if len(configured_token.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=503,
            detail="Admin access is not securely configured. Set GUTGPT_ADMIN_TOKEN to a random secret of at least 32 bytes.",
        )
    supplied = authorization or ""
    expected = f"Bearer {configured_token}"
    # compare_digest avoids timing-sensitive token comparisons. Only failed
    # attempts consume the brute-force budget, so normal admin refreshes work.
    if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        _enforce_rate_limit(
            request, scope="admin-auth-failure", identity=_request_client_key(request),
            limit=10, window_seconds=900,
        )
        raise HTTPException(status_code=401, detail="Invalid or missing admin token.")


def _persisted_session_customer_id(session_id: str) -> str | None:
    """Resolve a session binding from durable customer storage after process restart."""
    for record in _read_customer_records():
        bound_sessions = record.get("bound_session_ids", [])
        if record.get("session_id") == session_id or (
            isinstance(bound_sessions, list) and session_id in bound_sessions
        ):
            customer_id = record.get("customer_id")
            return str(customer_id) if customer_id else None
    return None


def _assert_session_customer_binding(session_id: str, customer_id: str) -> None:
    """Prevent a restore token from switching an already-bound session to another profile."""
    bound_customer_id = SESSION_CUSTOMER_IDS.get(session_id)
    if bound_customer_id is None:
        bound_customer_id = _persisted_session_customer_id(session_id)
    if bound_customer_id is not None and not hmac.compare_digest(bound_customer_id, customer_id):
        logger.warning("Guest restore rejected reason=session_customer_binding_mismatch session=%s", session_id[:8])
        raise HTTPException(status_code=409, detail="SESSION_CUSTOMER_MISMATCH. Start a new session to restore this profile.")


def _assert_registration_customer_binding(session_id: str, existing_record: dict | None) -> None:
    """Prevent registration from rebinding a restored session to another profile."""
    bound_customer_id = SESSION_CUSTOMER_IDS.get(session_id)
    if bound_customer_id is None:
        bound_customer_id = _persisted_session_customer_id(session_id)
    if bound_customer_id is not None and (
        existing_record is None or existing_record.get("customer_id") != bound_customer_id
    ):
        logger.warning("Registration rejected reason=session_customer_binding_mismatch session=%s", session_id[:8])
        raise HTTPException(
            status_code=409,
            detail="SESSION_CUSTOMER_MISMATCH. Start a new session before registering a different profile.",
        )


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_dashboard():
    """Serve the authenticated customer dashboard, including assessment summary columns."""
    return HTMLResponse(content="""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GutGPT Admin</title><style>
:root{color-scheme:light dark}body{font:16px system-ui,sans-serif;max-width:1400px;margin:32px auto;padding:0 16px}h1{margin-bottom:4px}.muted{opacity:.75}form,.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}input,button{font:inherit;padding:10px;border-radius:8px;border:1px solid #888}input{min-width:250px;flex:1}button{cursor:pointer}table{width:100%;border-collapse:collapse;margin-top:16px}th,td{text-align:left;padding:10px;border-bottom:1px solid #8886;overflow-wrap:anywhere;vertical-align:top;min-width:120px}th{position:sticky;top:0;background:Canvas}.status{margin:12px 0}.hidden{display:none}.tablewrap{overflow:auto;margin-bottom:28px}@media(max-width:600px){body{margin-top:18px}th,td{padding:7px;font-size:14px}}
</style></head><body><h1>GutGPT Admin</h1><p class="muted">Sign in with GUTGPT_ADMIN_TOKEN configured on the server. Customer and assessment information is sensitive.</p>
<form id="login"><label for="token">Admin token</label><input id="token" type="password" autocomplete="current-password" required placeholder="Enter admin token"><button type="submit">Sign in</button></form>
<div id="panel" class="hidden"><h2>Customers</h2><p id="summary" class="status"></p><div class="toolbar"><button id="refresh">Refresh records</button><button id="download">Download customer JSON</button><button id="logout">Sign out</button></div><div class="tablewrap"><table><thead><tr><th>Name</th><th>Age</th><th>Contact</th><th>Location</th><th>Assessment</th><th>Registered at (IST)</th><th>Session ID</th></tr></thead><tbody id="rows"></tbody></table></div></div>
<p id="status" class="status" role="status" aria-live="polite"></p>
<script>
(()=>{let token='';const $=id=>document.getElementById(id);const status=m=>{$('status').textContent=m};
async function api(path){const r=await fetch(path,{headers:{Authorization:'Bearer '+token},cache:'no-store'});if(!r.ok){let msg='Request failed ('+r.status+')';try{const j=await r.json();if(j.detail)msg=j.detail}catch{}throw Error(msg)}return r}
function cell(tr,value){const td=document.createElement('td');td.textContent=value==null?'':String(value);tr.appendChild(td)}
async function load(){status('Loading customer records…');try{const r=await api('/api/admin/customers');const data=await r.json();$('rows').replaceChildren();for(const c of data.customers||[]){const tr=document.createElement('tr');cell(tr,c.name);cell(tr,c.age);cell(tr,c.contact);cell(tr,c.location ?? c.city);cell(tr,c.likely_assessment);cell(tr,c.created_at);cell(tr,c.session_id);$('rows').appendChild(tr)}$('summary').textContent=(data.count??(data.customers||[]).length)+' customer record(s)';$('panel').classList.remove('hidden');status('Records loaded.')}catch(e){$('panel').classList.add('hidden');status(e.message);if(/token|unauthorized|admin access/i.test(e.message))$('token').focus()}}
async function download(){try{const r=await api('/api/admin/customers/download');const blob=await r.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='gutgpt_customer_records.json';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);status('Customer records download started.')}catch(e){status(e.message)}}
$('login').addEventListener('submit',async e=>{e.preventDefault();token=$('token').value.trim();if(!token){status('Enter the admin token.');return}await load()});$('refresh').addEventListener('click',load);$('download').addEventListener('click',download);$('logout').addEventListener('click',()=>{token='';$('token').value='';$('rows').replaceChildren();$('panel').classList.add('hidden');status('Signed out.');$('token').focus()});
})();</script></body></html>""")


@app.get("/api/admin/customers")
def admin_list_customers(request: Request, authorization: str | None = Header(default=None)):
    """Return customer records only to an authenticated admin."""
    _require_admin(authorization, request)
    with CUSTOMER_LOCK:
        records = _read_customer_records()
    return {"count": len(records), "customers": records}


@app.get("/api/admin/customers/download")
def admin_download_customers(request: Request, authorization: str | None = Header(default=None)):
    """Download customer records as JSON after admin authentication."""
    _require_admin(authorization, request)
    with CUSTOMER_LOCK:
        records = _read_customer_records()
    payload = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="gutgpt_customer_records.json"',
                 "Cache-Control": "no-store"},
    )




@app.post("/api/customer/restore")
def restore_customer(req: CustomerRestoreRequest, request: Request = None, response: Response = None):
    """Restore a profile using a signed 30-day JWT, with one-time legacy upgrade.

    Request is optional only to preserve direct Python-call compatibility in unit
    tests. FastAPI supplies it for every HTTP request, so endpoint rate limits
    remain enforced for network callers.
    """
    if request is not None:
        _enforce_rate_limit(request, scope="customer-restore-ip", identity=_request_client_key(request), limit=30, window_seconds=600)
        _enforce_rate_limit(request, scope="customer-restore-session", identity=req.session_id, limit=10, window_seconds=600)
    with _SESSION_LOCK:
        if req.session_id not in HISTORY or req.session_id not in conversation_manager.sessions:
            raise HTTPException(status_code=410, detail="SESSION_EXPIRED")

    # A widget may temporarily hold a newer body token while the browser still
    # sends an older HttpOnly cookie (or vice versa). Validate both credentials
    # against the signed JWT and persisted customer record; never trust either
    # token merely because it was supplied by the client.
    cookie_token = request.cookies.get(GUEST_COOKIE_NAME, "") if request is not None else ""
    token_candidates = []
    for candidate in (req.guest_token, cookie_token):
        if candidate and candidate not in token_candidates:
            token_candidates.append(candidate)
    if not token_candidates:
        _delete_guest_cookie(response, request)
        raise HTTPException(status_code=401, detail="GUEST_SESSION_INVALID. Please register again.")

    now = datetime.now(timezone.utc)
    claims = None
    supplied_token = ""
    record = None
    last_rejection_reason = "guest_credential_not_found"
    with CUSTOMER_LOCK:
        records = _read_customer_records()
        for candidate in token_candidates:
            candidate_claims = None
            try:
                candidate_claims = _decode_guest_jwt(candidate)
            except HTTPException as token_error:
                # Never reinterpret a malformed JWT as a legacy opaque token.
                if token_error.status_code != 401:
                    raise
                if candidate.count(".") == 2:
                    last_rejection_reason = "jwt_validation_failed"
                    continue
                logger.info("Guest restore using legacy credential path session=%s", req.session_id[:8])

            if candidate_claims is not None:
                candidate_jti_hash = hashlib.sha256(candidate_claims["jti"].encode("utf-8")).hexdigest()
                candidate_record = next((item for item in records
                    if item.get("customer_id") == candidate_claims.get("sub")
                    and item.get("guest_token_jti_hash")
                    and hmac.compare_digest(item["guest_token_jti_hash"], candidate_jti_hash)), None)
                candidate_reason = "jwt_customer_record_mismatch"
            else:
                legacy_hash = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
                candidate_record = next((item for item in records
                    if item.get("guest_token_hash")
                    and hmac.compare_digest(item["guest_token_hash"], legacy_hash)), None)
                candidate_reason = "legacy_credential_not_found"

            if candidate_record is not None:
                supplied_token = candidate
                claims = candidate_claims
                record = candidate_record
                break
            last_rejection_reason = candidate_reason

        if record is None:
            logger.warning("Guest restore rejected reason=%s session=%s", last_rejection_reason, req.session_id[:8])
            raise HTTPException(status_code=401, detail="GUEST_SESSION_INVALID. Please register again.")
        try:
            expires = datetime.fromisoformat(record.get("guest_token_expires_at", "").replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            expires = datetime.min.replace(tzinfo=timezone.utc)
        if expires <= now:
            logger.warning("Guest restore rejected reason=customer_token_expired session=%s", req.session_id[:8])
            raise HTTPException(status_code=401, detail="GUEST_SESSION_EXPIRED. Please register again.")

        # A restore may bind a fresh session to a customer, but must not silently
        # switch a session that is already authenticated as a different customer.
        _assert_session_customer_binding(req.session_id, record["customer_id"])

        # Upgrade legacy opaque credentials on first successful restoration.
        rotated_token = None
        if claims is None:
            rotated_token, new_jti_hash, new_expiry = _issue_guest_jwt(record["customer_id"])
            record.pop("guest_token_hash", None)
            record["guest_token_jti_hash"] = new_jti_hash
            record["guest_token_expires_at"] = new_expiry
            record["updated_at"] = now.isoformat()
            _write_customer_records(records)

        bound_sessions = record.setdefault("bound_session_ids", [])
        if not isinstance(bound_sessions, list):
            bound_sessions = record["bound_session_ids"] = []
        if req.session_id not in bound_sessions:
            bound_sessions.append(req.session_id)
            record["updated_at"] = now.isoformat()
            _write_customer_records(records)
        REGISTERED_CUSTOMER_SESSIONS.add(req.session_id)
        SESSION_CUSTOMER_IDS[req.session_id] = record["customer_id"]
        with conversation_manager._lock:
            state = conversation_manager.sessions.get(req.session_id)
            if state is not None:
                state.symptom_state.age = record.get("age")
        HISTORY_LAST_ACCESS[req.session_id] = time.monotonic()
        logger.info("Guest profile restored session=%s", req.session_id[:8])
        result = {
            "status": "RESTORED",
            "customer": {"name": record.get("name", "Customer"), "age": record.get("age"), "city": record.get("city", "")},
            "customer_id": record["customer_id"],
        }
        active_token = rotated_token or supplied_token
        try:
            cookie_expiry = datetime.fromisoformat(record.get("guest_token_expires_at", "").replace("Z", "+00:00"))
            if cookie_expiry.tzinfo is None:
                cookie_expiry = cookie_expiry.replace(tzinfo=timezone.utc)
            cookie_max_age = max(0, int((cookie_expiry - now).total_seconds()))
        except (ValueError, TypeError):
            cookie_max_age = GUEST_TOKEN_TTL_SECONDS
        _set_guest_cookie(response, request, active_token, cookie_max_age)
        if rotated_token:
            result["guest_token"] = rotated_token
            result["token_expires_at"] = record["guest_token_expires_at"]
        return result


@app.post("/api/customer/resume")
def resume_customer_assessment(req: CustomerRestoreRequest, request: Request = None):
    """Resume an unfinished assessment only after the customer session is authenticated."""
    if request is not None:
        _enforce_rate_limit(request, scope="customer-resume-ip", identity=_request_client_key(request), limit=30, window_seconds=600)
    with _SESSION_LOCK:
        if req.session_id not in HISTORY or req.session_id not in conversation_manager.sessions:
            raise HTTPException(status_code=410, detail="SESSION_EXPIRED")
    # Reuse the authenticated customer binding created by /api/customer/restore.
    customer_id = SESSION_CUSTOMER_IDS.get(req.session_id)
    if not customer_id or req.session_id not in REGISTERED_CUSTOMER_SESSIONS:
        raise HTTPException(status_code=403, detail="CUSTOMER_REGISTRATION_REQUIRED")
    resumed = _restore_assessment_checkpoint(customer_id, req.session_id)
    # Only an explicit absence of an active assessment permits a fresh assessment.
    return resumed if resumed is not None else {"status": "NO_ACTIVE_ASSESSMENT", "messages": []}



def _begin_chat_idempotency(session_id: str, message_id: str) -> dict | None:
    """Reserve a session-scoped widget message ID; return cached response on replay."""
    if not message_id:
        return None
    key = hashlib.sha256(f"{session_id}:{message_id}".encode("utf-8")).hexdigest()
    conn = _postgres_connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))
            cur.execute("SELECT status, response_json, updated_at FROM chat_idempotency WHERE request_key=%s FOR UPDATE", (key,))
            row = cur.fetchone()
            if row:
                status = row["status"] if isinstance(row, dict) else row[0]
                response = row["response_json"] if isinstance(row, dict) else row[1]
                updated = row["updated_at"] if isinstance(row, dict) else row[2]
                if status == "complete" and response:
                    logger.info("event=chat_idempotent_replay session=%s", session_id[:8])
                    return response if isinstance(response, dict) else json.loads(response)
                if status == "processing" and updated and (datetime.now(timezone.utc) - updated).total_seconds() < 120:
                    raise HTTPException(status_code=409, detail="This message is already being processed. Please wait briefly.", headers={"Retry-After":"2"})
                cur.execute("UPDATE chat_idempotency SET status='processing', response_json=NULL, updated_at=NOW() WHERE request_key=%s", (key,))
            else:
                cur.execute("INSERT INTO chat_idempotency(request_key, session_id, status) VALUES (%s,%s,'processing')", (key, session_id))
    finally:
        conn.close()
    return None


def _complete_chat_idempotency(session_id: str, message_id: str, response: dict) -> None:
    if not message_id:
        return
    key = hashlib.sha256(f"{session_id}:{message_id}".encode("utf-8")).hexdigest()
    conn = _postgres_connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("UPDATE chat_idempotency SET status='complete', response_json=%s::jsonb, updated_at=NOW() WHERE request_key=%s", (json.dumps(response, ensure_ascii=False), key))
    finally:
        conn.close()


def _fail_chat_idempotency(session_id: str, message_id: str) -> None:
    if not message_id:
        return
    key = hashlib.sha256(f"{session_id}:{message_id}".encode("utf-8")).hexdigest()
    try:
        conn = _postgres_connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("UPDATE chat_idempotency SET status='failed', updated_at=NOW() WHERE request_key=%s AND status='processing'", (key,))
        finally:
            conn.close()
    except Exception:
        logger.warning("event=chat_idempotency_fail_mark_failed")

def _chat_impl(req: ChatRequest, request: Request = None):
    """Process one user message through the existing GutGPT logic.

    Request is optional only for existing direct Python-call tests. FastAPI
    supplies it for HTTP calls, where rate limiting remains mandatory.
    """
    if request is not None:
        _enforce_rate_limit(request, scope="chat-session", identity=req.session_id, limit=30, window_seconds=60)
        _enforce_rate_limit(request, scope="chat-ip", identity=_request_client_key(request), limit=120, window_seconds=60)
    request_id = uuid.uuid4().hex[:8]
    turn_id = uuid.uuid4().hex
    total_start = time.perf_counter()
    original_message = req.message.strip()
    # Pydantic rejects an empty string before reaching here, but keep the
    # guard because whitespace-only input becomes empty after stripping.
    if not original_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    logger.info(
        "[PERF][%s] REQUEST received session=%s message_len=%d",
        request_id, req.session_id[:8], len(original_message)
    )
    _cleanup_sessions()

    logic_start = time.perf_counter()
    # Validate the active session and customer registration before reserving a
    # message ID or mutating conversation state. Cached replies must never bypass
    # authorization, and replayed messages must never execute the rule engine.
    with _SESSION_LOCK:
        if req.session_id not in HISTORY or req.session_id not in conversation_manager.sessions:
            raise HTTPException(status_code=410, detail="SESSION_EXPIRED")

    with CUSTOMER_LOCK:
        if req.session_id not in REGISTERED_CUSTOMER_SESSIONS:
            raise HTTPException(status_code=403, detail="CUSTOMER_REGISTRATION_REQUIRED")

    # Reserve/check idempotency before any NLU, rule-engine, or LLM work.
    # A completed replay returns its original response without advancing state.
    cached = _begin_chat_idempotency(req.session_id, req.message_id)
    if cached is not None:
        return ChatResponse(**cached)

    # GutGPT communicates exclusively in English. The message is processed as
    # English exactly as written; it is never translated. Clearly non-English
    # input receives a fixed English notice and never enters the clinical engine.
    if _is_non_english(original_message):
        reply = ENGLISH_ONLY_FALLBACK
        status = NON_ENGLISH_STATUS
        result = None
    else:
        message = original_message
        result = conversation_manager.handle_message(req.session_id, message)
        logic_ms = (time.perf_counter() - logic_start) * 1000
        status = result["status"]
        logger.info(
            "[PERF][%s] Rule engine handle_message: %.2f ms status=%s",
            request_id, logic_ms, status
        )

    history_start = time.perf_counter()
    with _SESSION_LOCK:
        history = HISTORY[req.session_id]
        HISTORY_LAST_ACCESS[req.session_id] = time.monotonic()
    # Measure the session/history lookup separately. Checkpoint persistence
    # happens after the rule engine has produced this turn's result and after
    # the updated conversation history has been appended below.
    history_ms = (time.perf_counter() - history_start) * 1000
    logger.info("[PERF][%s] Session/history lookup: %.2f ms", request_id, history_ms)

    # Non-English turns already have their English-only fallback reply and
    # skip the rule-engine reply selection entirely (result is None).
    if result is not None:
        if status in (
            "GIBBERISH",
            "IRRELEVANT",
            "SAFETY_REVIEW",
            "SCREENING_REVIEW",
            "SUMMARY_REVIEW",
            "ASK",
            "NO_MATCH",
            "GREETING",
            "ACKNOWLEDGEMENT",
            "DIAGNOSIS_COMPLETE",
            "RECOMMENDATION_COMPLETE",
            "SESSION_ENDED",
        ):
            reply = result["message"]

        elif status == "DIAGNOSIS":
            # The diagnosis has already been selected by the deterministic rule
            # engine. Do not send this request through the LLM; doing so adds a
            # network round trip without adding diagnostic value.
            reply = _deterministic_screening_reply(result.get("screening"))

        elif status == "PRODUCT_INFO_FOUND":
            # Product data is already structured and validated. Answer directly
            # from that data instead of waiting for an LLM generation call.
            reply = _deterministic_product_reply(result["product"], message)

        elif status in ("RECOMMENDATION_FOUND", "AMBIGUOUS"):
            # Preserve the exact rule-engine recommendation. The LLM is not used
            # to rewrite or reinterpret the approved diagnosis/product routing.
            products = result.get("recommendations") or []
            reply = _deterministic_screening_reply(result.get("screening"), products)

        else:
            reply = "Sorry, something went wrong. Could you rephrase that?"

    # Add contact details only when the assessment has actually produced a
    # completed diagnosis/screening result. Do not append to intermediate
    # questions, safety reviews, greetings, or later acknowledgements.
    if status in ("DIAGNOSIS", "RECOMMENDATION_FOUND", "AMBIGUOUS"):
        reply = append_human_support_footer(reply)

    # Persist urgent safety outcomes as well as completed routine assessments.
    if status in ("DIAGNOSIS", "RECOMMENDATION_FOUND", "AMBIGUOUS") or (
        status == "SAFETY_REVIEW" and (result.get("screening") or {}).get("action") == "urgent_medical_evaluation"
    ):
        try:
            _persist_completed_assessment(req.session_id, result)
        except Exception:
            # Persistence failure must be visible in logs but must not change
            # the deterministic assessment response already produced.
            logger.exception("Completed assessment persistence failed session=%s", req.session_id[:8])

    response_build_ms = (time.perf_counter() - logic_start) * 1000
    logger.info(
        "[PERF][%s] Reply selection/formatting cumulative: %.2f ms",
        request_id, response_build_ms
    )

    history_start = time.perf_counter()

    with _SESSION_LOCK:
        history.append({"role": "user", "content": original_message})
        history.append({"role": "assistant", "content": reply})
        # Keep per-session memory bounded even for a continuously active client.
        if len(history) > MAX_HISTORY_MESSAGES:
            del history[:-MAX_HISTORY_MESSAGES]
        HISTORY_LAST_ACCESS[req.session_id] = time.monotonic()
    try:
        completed_turn = status in ("DIAGNOSIS", "RECOMMENDATION_FOUND", "AMBIGUOUS", "DIAGNOSIS_COMPLETE", "RECOMMENDATION_COMPLETE", "SESSION_ENDED") or (
            status == "SAFETY_REVIEW" and (result.get("screening") or {}).get("action") == "urgent_medical_evaluation"
        )
        _persist_assessment_checkpoint(req.session_id, completed=completed_turn, turn_id=turn_id)
    except Exception:
        # Do not silently claim a successful durable save. The reply remains
        # available, but logs make the checkpoint failure observable.
        logger.exception("Assessment checkpoint persistence failed session=%s", req.session_id[:8])
    history_ms = (time.perf_counter() - history_start) * 1000
    logger.info("[PERF][%s] History append: %.2f ms", request_id, history_ms)

    total_ms = (time.perf_counter() - total_start) * 1000
    logger.info("[PERF][%s] TOTAL backend chat: %.2f ms", request_id, total_ms)

    urgent_safety_outcome = bool(
        result
        and status == "SAFETY_REVIEW"
        and (result.get("screening") or {}).get("action") == "urgent_medical_evaluation"
    )
    assessment_complete = bool(
        status in ("DIAGNOSIS", "RECOMMENDATION_FOUND", "AMBIGUOUS", "DIAGNOSIS_COMPLETE", "RECOMMENDATION_COMPLETE")
        or urgent_safety_outcome
    )
    response = ChatResponse(
        reply=reply,
        status=status,
        recommendations=(result.get("recommendations") if result else None) or [],
        assessment_complete=assessment_complete,
    )
    _complete_chat_idempotency(req.session_id, req.message_id, response.model_dump())
    return response


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request = None):
    """Apply one shared Groq-call budget to the entire incoming chat turn."""
    request_id = uuid.uuid4().hex[:8]
    # GutGPT is English-only: no input or output translation calls are made, so
    # a single per-message budget covers the turn (NLU model resolution when the
    # contextual resolver requires it; the deterministic reply path uses none).
    budget = configured_message_budget()
    try:
        with message_call_budget(request_id, max_calls=budget):
            return _chat_impl(req, request)
    except Exception as exc:
        _fail_chat_idempotency(req.session_id, req.message_id)
        if isinstance(exc, GroqBudgetExceeded):
            logger.warning("[GROQ][%s] per-message call budget exhausted", request_id)
            raise HTTPException(
                status_code=503,
                detail="GutGPT could not safely process this message within the current model-call budget. Please try a shorter or clearer answer.",
                headers={"Retry-After": "2"},
            ) from exc
        if isinstance(exc, (GroqCircuitOpen, GroqBusyError)):
            logger.warning("[GROQ][%s] provider unavailable reason=%s", request_id, type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="GutGPT is temporarily busy. Your assessment has not been intentionally restarted; please retry shortly.",
                headers={"Retry-After": "5"},
            ) from exc
        raise


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
