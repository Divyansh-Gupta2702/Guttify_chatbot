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
import tempfile
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

from guttify_agent import ConversationManager
from symptom_questionnaire import next_question
from symptom_summary import build_symptom_summary
from guttify_chatbot import _deterministic_product_reply, _deterministic_screening_reply
BASE_DIR = Path(__file__).resolve().parent
WIDGET_FILE = BASE_DIR / "gutgpt-widget.js"
VERSION_FILE = BASE_DIR / "VERSION.txt"
QUESTION_FLOW_SCHEMA_VERSION = "v18.1"

from support_footer import append_human_support_footer
MAX_MESSAGE_LENGTH = max(256, min(10000, int(os.getenv("MAX_MESSAGE_LENGTH", "4000"))))
MAX_HISTORY_MESSAGES = 100
FRONTEND_FILE = BASE_DIR / "index.html"
CUSTOMER_DATA_FILE = Path(os.getenv("CUSTOMER_DATA_FILE", str(BASE_DIR / "customer_data.json")))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
GUEST_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
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
    logger.info(
        "Customer storage backend: %s",
        "PostgreSQL" if DATABASE_URL else "JSON fallback",
    )
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
    if DATABASE_URL:
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
            with CUSTOMER_LOCK:
                REGISTERED_CUSTOMER_SESSIONS.discard(sid)

        if len(HISTORY_LAST_ACCESS) > MAX_SESSIONS:
            excess = len(HISTORY_LAST_ACCESS) - MAX_SESSIONS
            oldest = sorted(HISTORY_LAST_ACCESS.items(), key=lambda item: item[1])[:excess]
            for sid, _ in oldest:
                HISTORY.pop(sid, None)
                HISTORY_LAST_ACCESS.pop(sid, None)
                conversation_manager.remove(sid)
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
# Local fallback is for development/JSON mode only. When DATABASE_URL is set,
# rate-limit counters are stored in PostgreSQL so multiple workers share limits.
_RATE_LIMIT_LOCK = RLock()
_RATE_LIMIT_BUCKETS: dict[str, tuple[float, int]] = {}
_RATE_LIMIT_LOCAL_MAX_KEYS = 20000
_RATE_LIMIT_CLEANUP_LOCK = RLock()
_RATE_LIMIT_CLEANUP_LAST: float | None = None
_RATE_LIMIT_CLEANUP_INTERVAL_SECONDS = 600.0
REGISTERED_CUSTOMER_SESSIONS: set[str] = set()
# Maps each active diagnostic session to its persistent customer profile.
SESSION_CUSTOMER_IDS: dict[str, str] = {}


def _read_json_records(path: Path, label: str) -> list[dict]:
    """Read a JSON-array store; a missing file means no records yet."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            records = json.load(handle)
        if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
            raise ValueError(f"{path.name} must contain a JSON array of objects")
        return records
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.exception("Could not read %s JSON", label)
        raise HTTPException(status_code=500, detail=f"{label} records are temporarily unavailable.") from exc


def _write_json_records(path: Path, records: list[dict]) -> None:
    """Atomically replace a JSON-array store to avoid partially-written files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # A fixed ``.tmp`` name can collide when multiple worker processes write
    # concurrently. Use a unique temporary file in the destination directory
    # so os.replace remains atomic on the same filesystem.
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(records, handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name and os.path.exists(temporary_name):
            try:
                os.unlink(temporary_name)
            except OSError:
                logger.warning("Could not remove temporary JSON file %s", temporary_name)


def _postgres_connect():
    """Open a PostgreSQL connection only when DATABASE_URL is configured."""
    if not DATABASE_URL:
        return None
    try:
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=8)
    except Exception as exc:
        logger.exception("PostgreSQL connection failed")
        raise HTTPException(status_code=503, detail="Customer storage is temporarily unavailable.") from exc


def _init_postgres() -> None:
    """Create the durable customer and assessment tables if needed."""
    if not DATABASE_URL:
        return
    conn = _postgres_connect()
    if conn is None:
        return
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id TEXT PRIMARY KEY,
                    registration_session_id TEXT UNIQUE,
                    name VARCHAR(150) NOT NULL,
                    age INTEGER NOT NULL CHECK (age BETWEEN 1 AND 120),
                    contact VARCHAR(15) NOT NULL,
                    location VARCHAR(150) NOT NULL,
                    consent_to_store BOOLEAN NOT NULL DEFAULT FALSE,
                    guest_token_jti_hash TEXT,
                    guest_token_expires_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ,
                    likely_assessment TEXT,
                    record_json JSONB NOT NULL DEFAULT '{}'::jsonb
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS customer_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
                    session_id VARCHAR(150) UNIQUE NOT NULL,
                    assessment TEXT NOT NULL,
                    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_rate_limits (
                    rate_key TEXT PRIMARY KEY,
                    window_started_at TIMESTAMPTZ NOT NULL,
                    request_count INTEGER NOT NULL CHECK (request_count >= 0),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_api_rate_limits_updated_at ON api_rate_limits(updated_at)")
            # Upgrade the simple tables created during the manual local setup.
            # The app's stable customer IDs are UUID strings, not serial integers.
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
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS registration_session_id TEXT")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS guest_token_jti_hash TEXT")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS guest_token_expires_at TIMESTAMPTZ")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS likely_assessment TEXT")
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS record_json JSONB NOT NULL DEFAULT '{}'::jsonb")
            cur.execute("ALTER TABLE customers ALTER COLUMN record_json DROP DEFAULT")
            cur.execute("ALTER TABLE customer_assessments ALTER COLUMN assessment_id DROP DEFAULT")
            cur.execute("ALTER TABLE customer_assessments ALTER COLUMN assessment_id TYPE TEXT USING assessment_id::text")
            cur.execute("ALTER TABLE customer_assessments ALTER COLUMN customer_id TYPE TEXT USING customer_id::text")
            cur.execute("ALTER TABLE customer_assessments ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
            cur.execute("ALTER TABLE customer_assessments ADD CONSTRAINT customer_assessments_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE CASCADE")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_registration_session_id ON customers(registration_session_id) WHERE registration_session_id IS NOT NULL")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_assessments_session_id ON customer_assessments(session_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_customer_assessments_customer_id ON customer_assessments(customer_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_customer_assessments_completed_at ON customer_assessments(completed_at)")
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
    """Read customer profiles and their assessment history from configured storage."""
    if DATABASE_URL:
        conn = _postgres_connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("SELECT record_json FROM customers ORDER BY created_at DESC")
                records = [dict(row["record_json"] or {}) for row in cur.fetchall()]
                for record in records:
                    cid = str(record.get("customer_id", ""))
                    cur.execute("SELECT assessment_id, session_id, assessment, completed_at FROM customer_assessments WHERE customer_id=%s ORDER BY completed_at", (cid,))
                    history = cur.fetchall()
                    if history:
                        record["assessments"] = [{
                            "assessment_id": row["assessment_id"], "session_id": row["session_id"],
                            "assessment": row["assessment"],
                            "completed_at": row["completed_at"].astimezone(INDIA_TZ).isoformat(),
                        } for row in history]
                        record["likely_assessment"] = history[-1]["assessment"]
        except Exception as exc:
            logger.exception("Could not read customer records from PostgreSQL")
            raise HTTPException(status_code=503, detail="Customer records are temporarily unavailable.") from exc
        finally:
            conn.close()
    else:
        records = _read_json_records(CUSTOMER_DATA_FILE, "Customer")
    for record in records:
        record.pop("final_symptom_summary", None)
    return records


def _write_customer_records(records: list[dict]) -> None:
    """Persist customer profiles and assessment history to PostgreSQL or JSON dev storage."""
    if not DATABASE_URL:
        _write_json_records(CUSTOMER_DATA_FILE, records)
        return
    conn = _postgres_connect()
    try:
        with conn, conn.cursor() as cur:
            # Serialize whole-store read/modify/write operations across workers.
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('gutgpt_customer_store'))")
            keep_ids = []
            for record in records:
                cid = str(record["customer_id"])
                keep_ids.append(cid)
                created_at = _to_utc_datetime(record.get("created_at")) or datetime.now(timezone.utc)
                updated_at = _to_utc_datetime(record.get("updated_at"))
                expires_at = _to_utc_datetime(record.get("guest_token_expires_at"))
                payload = dict(record)
                payload.pop("final_symptom_summary", None)
                cur.execute("""
                    INSERT INTO customers (customer_id, registration_session_id, name, age, contact, location,
                        consent_to_store, guest_token_jti_hash, guest_token_expires_at, created_at, updated_at,
                        likely_assessment, record_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (customer_id) DO UPDATE SET
                        registration_session_id=EXCLUDED.registration_session_id,
                        name=EXCLUDED.name, age=EXCLUDED.age, contact=EXCLUDED.contact,
                        location=EXCLUDED.location, consent_to_store=EXCLUDED.consent_to_store,
                        guest_token_jti_hash=EXCLUDED.guest_token_jti_hash,
                        guest_token_expires_at=EXCLUDED.guest_token_expires_at,
                        updated_at=EXCLUDED.updated_at, likely_assessment=EXCLUDED.likely_assessment,
                        record_json=EXCLUDED.record_json
                """, (cid, record.get("session_id"), record.get("name", "Customer"), int(record.get("age") or 1),
                      str(record.get("contact", "")), str(record.get("location", record.get("city", ""))),
                      bool(record.get("consent_to_store")), record.get("guest_token_jti_hash"), expires_at,
                      created_at, updated_at, record.get("likely_assessment"), json.dumps(payload, ensure_ascii=False, default=str)))
                for item in record.get("assessments", []) if isinstance(record.get("assessments", []), list) else []:
                    if not isinstance(item, dict) or not item.get("session_id"):
                        continue
                    completed = _to_utc_datetime(item.get("completed_at")) or datetime.now(timezone.utc)
                    cur.execute("""
                        INSERT INTO customer_assessments (assessment_id, customer_id, session_id, assessment, completed_at)
                        VALUES (%s,%s,%s,%s,%s)
                        ON CONFLICT (session_id) DO UPDATE SET assessment=EXCLUDED.assessment,
                            customer_id=EXCLUDED.customer_id, completed_at=EXCLUDED.completed_at
                    """, (str(item.get("assessment_id") or uuid.uuid4()), cid, str(item["session_id"]),
                          str(item.get("assessment", "Insufficient information")), completed))
            # Do not delete rows absent from this in-memory snapshot: another worker may have
            # registered a customer after the snapshot was read. This API has no customer-delete route.
    except Exception as exc:
        logger.exception("Could not write customer records to PostgreSQL")
        raise HTTPException(status_code=503, detail="Customer records could not be saved.") from exc
    finally:
        conn.close()


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
            history.append({
                "assessment_id": str(uuid.uuid4()),
                "session_id": session_id,
                "assessment": str(likely_assessment),
                "completed_at": now,
            })
        else:
            # Repair/update a legacy or partial record without creating a duplicate.
            existing["assessment"] = str(likely_assessment)
            existing.setdefault("assessment_id", str(uuid.uuid4()))
            existing.setdefault("completed_at", now)
        # Keep the dashboard's Assessment column useful by showing the latest result.
        customer["likely_assessment"] = str(likely_assessment)
        customer.pop("final_symptom_summary", None)
        _write_customer_records(records)
    logger.info("Assessment history saved on customer JSON customer_id=%s session=%s",
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


class ChatResponse(BaseModel):
    reply: str
    status: str
    recommendations: list[dict] = Field(default_factory=list)


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
    """Enforce a fixed-window limit, shared through PostgreSQL when configured.

    The raw identity is never persisted: keys are SHA-256 hashes. PostgreSQL
    errors fail closed rather than silently disabling protection in DB mode.
    """
    raw_key = f"{scope}:{identity}"
    rate_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    if DATABASE_URL:
        conn = _postgres_connect()
        if conn is None:
            raise HTTPException(status_code=503, detail="Request protection is temporarily unavailable.")
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
                # Deterministic housekeeping avoids random latency spikes and
                # cleans stale rows at the first request and periodically thereafter.
                if _should_cleanup_rate_limits():
                    cur.execute("DELETE FROM api_rate_limits WHERE updated_at < NOW() - INTERVAL '2 days'")
        finally:
            conn.close()
    else:
        # Development fallback: per-process only. Production should configure
        # DATABASE_URL to enable shared enforcement across instances/workers.
        now = time.monotonic()
        with _RATE_LIMIT_LOCK:
            bucket = _RATE_LIMIT_BUCKETS.get(rate_key)
            if bucket is None or now - bucket[0] >= window_seconds:
                bucket = (now, 0)
            count = bucket[1] + 1
            _RATE_LIMIT_BUCKETS[rate_key] = (bucket[0], count)
            if len(_RATE_LIMIT_BUCKETS) > _RATE_LIMIT_LOCAL_MAX_KEYS:
                oldest = sorted(_RATE_LIMIT_BUCKETS.items(), key=lambda item: item[1][0])
                for old_key, _ in oldest[:len(_RATE_LIMIT_BUCKETS) - _RATE_LIMIT_LOCAL_MAX_KEYS]:
                    _RATE_LIMIT_BUCKETS.pop(old_key, None)
            retry_after = max(1, int(window_seconds - (now - bucket[0])))
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait before trying again.",
            headers={"Retry-After": str(max(1, retry_after))},
        )


@app.get("/")
def frontend():
    """Serve the basic browser chat frontend at the backend root."""
    if not FRONTEND_FILE.exists():
        raise HTTPException(status_code=500, detail="GutGPT frontend is not installed.")
    return FileResponse(FRONTEND_FILE, media_type="text/html")


@app.get("/bristol-stool-chart.png")
def bristol_stool_chart():
    """Serve the Bristol chart used by the browser-based frontend."""
    chart_file = BASE_DIR / "Bristol Stool Chart Infographic.png"
    if not chart_file.exists():
        raise HTTPException(status_code=404, detail="Bristol stool chart image is not installed.")
    return FileResponse(chart_file, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


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
def register_customer(req: CustomerRegistrationRequest, request: Request = None):
    """Save customer details to configured PostgreSQL storage (or local JSON when DATABASE_URL is unset).

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

    logger.info("Customer registration saved session=%s", req.session_id[:8])
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
</style></head><body><h1>GutGPT Admin</h1><p class="muted">Sign in with GUTGPT_ADMIN_TOKEN configured in Render. Customer and assessment information is sensitive.</p>
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
def restore_customer(req: CustomerRestoreRequest, request: Request = None):
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

    now = datetime.now(timezone.utc)
    claims = None
    try:
        claims = _decode_guest_jwt(req.guest_token)
    except HTTPException as token_error:
        # A three-segment value is JWT-shaped. Do not hide a JWT validation
        # failure by treating it as a legacy opaque credential.
        if token_error.status_code != 401:
            raise
        if req.guest_token.count(".") == 2:
            logger.warning("Guest restore rejected reason=jwt_validation_failed session=%s", req.session_id[:8])
            raise
        # Compatibility path for older releases that stored opaque tokens.
        logger.info("Guest restore using legacy credential path session=%s", req.session_id[:8])

    with CUSTOMER_LOCK:
        records = _read_customer_records()
        record = None
        if claims is not None:
            supplied_jti_hash = hashlib.sha256(claims["jti"].encode("utf-8")).hexdigest()
            record = next((item for item in records
                           if item.get("customer_id") == claims.get("sub")
                           and item.get("guest_token_jti_hash")
                           and hmac.compare_digest(item["guest_token_jti_hash"], supplied_jti_hash)), None)
        else:
            legacy_hash = hashlib.sha256(req.guest_token.encode("utf-8")).hexdigest()
            record = next((item for item in records
                           if item.get("guest_token_hash")
                           and hmac.compare_digest(item["guest_token_hash"], legacy_hash)), None)

        if record is None:
            reason = "jwt_customer_record_mismatch" if claims is not None else "legacy_credential_not_found"
            logger.warning("Guest restore rejected reason=%s session=%s", reason, req.session_id[:8])
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
        if rotated_token:
            result["guest_token"] = rotated_token
            result["token_expires_at"] = record["guest_token_expires_at"]
        return result


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request = None):
    """Process one user message through the existing GutGPT logic.

    Request is optional only for existing direct Python-call tests. FastAPI
    supplies it for HTTP calls, where rate limiting remains mandatory.
    """
    if request is not None:
        _enforce_rate_limit(request, scope="chat-session", identity=req.session_id, limit=30, window_seconds=60)
        _enforce_rate_limit(request, scope="chat-ip", identity=_request_client_key(request), limit=120, window_seconds=60)
    request_id = uuid.uuid4().hex[:8]
    total_start = time.perf_counter()
    message = req.message.strip()
    logger.info(
        "[PERF][%s] REQUEST received session=%s message_len=%d",
        request_id, req.session_id[:8], len(message)
    )
    _cleanup_sessions()
    if not message:
        # Pydantic rejects an empty string before reaching here, but keep the
        # guard because whitespace-only input becomes empty after stripping.
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Never silently turn an expired/unknown session into a brand-new chat.
    # The widget can explicitly create a new session when this happens.
    with _SESSION_LOCK:
        if req.session_id not in HISTORY or req.session_id not in conversation_manager.sessions:
            raise HTTPException(status_code=410, detail="SESSION_EXPIRED")


    with CUSTOMER_LOCK:
        if req.session_id not in REGISTERED_CUSTOMER_SESSIONS:
            raise HTTPException(status_code=403, detail="CUSTOMER_REGISTRATION_REQUIRED")

    history_start = time.perf_counter()
    with _SESSION_LOCK:
        history = HISTORY[req.session_id]
        HISTORY_LAST_ACCESS[req.session_id] = time.monotonic()
    history_ms = (time.perf_counter() - history_start) * 1000
    logger.info("[PERF][%s] Session/history lookup: %.2f ms", request_id, history_ms)

    logic_start = time.perf_counter()
    result = conversation_manager.handle_message(req.session_id, message)
    logic_ms = (time.perf_counter() - logic_start) * 1000
    status = result["status"]
    logger.info(
        "[PERF][%s] Rule engine handle_message: %.2f ms status=%s",
        request_id, logic_ms, status
    )

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
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        # Keep per-session memory bounded even for a continuously active client.
        if len(history) > MAX_HISTORY_MESSAGES:
            del history[:-MAX_HISTORY_MESSAGES]
        HISTORY_LAST_ACCESS[req.session_id] = time.monotonic()
    history_ms = (time.perf_counter() - history_start) * 1000
    logger.info("[PERF][%s] History append: %.2f ms", request_id, history_ms)

    total_ms = (time.perf_counter() - total_start) * 1000
    logger.info("[PERF][%s] TOTAL backend chat: %.2f ms", request_id, total_ms)

    return ChatResponse(
        reply=reply,
        status=status,
        recommendations=result.get("recommendations") or [],
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
