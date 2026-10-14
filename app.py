"""
GutGPT FastAPI backend.

The diagnosis/recommendation business logic remains in the existing Python
modules. This layer handles HTTP, sessions, CORS, and serves
the single embeddable JavaScript widget.

Run locally:
    uvicorn app:app --reload --host 0.0.0.0 --port 8000
"""
from pathlib import Path
import os
import uuid
import time
import logging
import subprocess
import json
from datetime import datetime, timezone
from threading import RLock

from fastapi import FastAPI, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("gutgpt.performance")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

from guttify_agent import ConversationManager
from guttify_chatbot import _deterministic_product_reply, _deterministic_screening_reply
BASE_DIR = Path(__file__).resolve().parent
WIDGET_FILE = BASE_DIR / "gutgpt-widget.js"
VERSION_FILE = BASE_DIR / "VERSION.txt"
QUESTION_FLOW_SCHEMA_VERSION = "v18.1"

from support_footer import append_human_support_footer
MAX_MESSAGE_LENGTH = max(256, min(10000, int(os.getenv("MAX_MESSAGE_LENGTH", "4000"))))
MAX_HISTORY_MESSAGES = 100
FRONTEND_FILE = BASE_DIR / "index.html"
CUSTOMER_DATA_FILE = BASE_DIR / "customer_data.json"

app = FastAPI(title="GutGPT API", version="18.1.0")

# Shopify storefront origins are supplied as a comma-separated environment
# variable, for example:
# ALLOWED_ORIGINS=https://www.guttify.com,https://guttify.com
def _configured_origins():
    return [
        origin.strip().rstrip("/")
        for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]


allowed_origins = _configured_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

@app.on_event("startup")
def validate_production_configuration():
    """Fail fast when required final-site configuration is missing."""
    missing = []
    if not os.getenv("GROQ_API_KEY"):
        missing.append("GROQ_API_KEY")
    if not allowed_origins:
        missing.append("ALLOWED_ORIGINS")
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
REGISTERED_CUSTOMER_SESSIONS: set[str] = set()


def _read_customer_records() -> list[dict]:
    """Read customer records, treating a missing file as an empty JSON list."""
    if not CUSTOMER_DATA_FILE.exists():
        return []
    try:
        with CUSTOMER_DATA_FILE.open("r", encoding="utf-8") as handle:
            records = json.load(handle)
        if not isinstance(records, list):
            raise ValueError("customer_data.json must contain a JSON array")
        return records
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.exception("Could not read customer data JSON")
        raise HTTPException(status_code=500, detail="Customer records are temporarily unavailable.") from exc


def _write_customer_records(records: list[dict]) -> None:
    """Atomically persist records so interrupted writes do not corrupt the JSON file."""
    temporary = CUSTOMER_DATA_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, CUSTOMER_DATA_FILE)


class CustomerRegistrationRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    age: int = Field(ge=1, le=120)
    contact: str = Field(min_length=3, max_length=150)
    city: str = Field(min_length=1, max_length=100)
    consent: bool


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    # Keep Pydantic above the production UX limit so we can return a friendly
    # application-level message instead of an opaque 422 validation error.
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)


class ChatResponse(BaseModel):
    reply: str
    status: str
    recommendations: list[dict] = Field(default_factory=list)


@app.get("/")
def frontend():
    """Serve the basic browser chat frontend at the backend root."""
    if not FRONTEND_FILE.exists():
        raise HTTPException(status_code=500, detail="GutGPT frontend is not installed.")
    return FileResponse(FRONTEND_FILE, media_type="text/html")


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
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.post("/api/session")
def new_session():
    """Create a new conversation session for a visitor."""
    _cleanup_sessions()
    session_id = str(uuid.uuid4())
    now = time.monotonic()
    with _SESSION_LOCK:
        HISTORY[session_id] = []
        HISTORY_LAST_ACCESS[session_id] = now
        conversation_manager.reset(session_id)
    return {"session_id": session_id}


@app.post("/api/customer")
def register_customer(req: CustomerRegistrationRequest):
    """Save customer details to a local JSON file before allowing assessment."""
    if not req.consent:
        raise HTTPException(status_code=400, detail="Please consent to storing these details to continue.")

    name = " ".join(req.name.split())
    contact = req.contact.strip()
    city = " ".join(req.city.split())
    if not name or not contact or not city:
        raise HTTPException(status_code=400, detail="Please complete all customer details.")
    if len(contact) < 3:
        raise HTTPException(status_code=400, detail="Enter a valid phone number or email address.")

    with _SESSION_LOCK:
        if req.session_id not in HISTORY or req.session_id not in conversation_manager.sessions:
            raise HTTPException(status_code=410, detail="SESSION_EXPIRED")

    with CUSTOMER_LOCK:
        records = _read_customer_records()
        # Idempotent retry: do not create duplicate rows if the browser retries.
        existing = next((item for item in records if item.get("session_id") == req.session_id), None)
        if existing is None:
            record = {
                "customer_id": str(uuid.uuid4()),
                "session_id": req.session_id,
                "name": name,
                "age": req.age,
                "contact": contact,
                "city": city,
                "consent_to_store": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            records.append(record)
            _write_customer_records(records)
        else:
            record = existing
        REGISTERED_CUSTOMER_SESSIONS.add(req.session_id)

    logger.info("Customer registration saved session=%s customer_id=%s", req.session_id[:8], record["customer_id"])
    return {"status": "REGISTERED", "customer_id": record["customer_id"]}


def _require_admin(authorization: str | None) -> None:
    """Require a configured bearer token; never expose customer data publicly."""
    configured_token = os.getenv("GUTGPT_ADMIN_TOKEN", "").strip()
    if not configured_token:
        raise HTTPException(
            status_code=503,
            detail="Admin access is not configured. Set GUTGPT_ADMIN_TOKEN in the service environment.",
        )
    supplied = authorization or ""
    expected = f"Bearer {configured_token}"
    # compare_digest avoids timing-sensitive token comparisons.
    import hmac
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token.")


@app.get("/api/admin/customers")
def admin_list_customers(authorization: str | None = Header(default=None)):
    """Return customer records only to an authenticated admin."""
    _require_admin(authorization)
    with CUSTOMER_LOCK:
        records = _read_customer_records()
    return {"count": len(records), "customers": records}


@app.get("/api/admin/customers/download")
def admin_download_customers(authorization: str | None = Header(default=None)):
    """Download the JSON records as an attachment after admin authentication."""
    _require_admin(authorization)
    with CUSTOMER_LOCK:
        records = _read_customer_records()
    payload = json.dumps(records, ensure_ascii=False, indent=2) + "\\n"
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="customer_data.json"',
                 "Cache-Control": "no-store"},
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Process one user message through the existing GutGPT logic."""
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
