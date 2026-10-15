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
import re
import secrets
import hashlib
import hmac
import jwt
from jwt import InvalidTokenError
from datetime import datetime, timezone, timedelta
from threading import RLock

from fastapi import FastAPI, HTTPException, Header, Response
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
GUEST_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
JWT_ALGORITHM = "HS256"
JWT_ISSUER = os.getenv("JWT_ISSUER", "gutgpt-api")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "gutgpt-guest-session")


def _jwt_signing_key() -> str:
    """Return the configured JWT signing key; never use an insecure fallback."""
    key = os.getenv("JWT_SECRET_KEY", "")
    if len(key.encode("utf-8")) < 32:
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

app = FastAPI(title="GutGPT API", version="18.3-jwt-guest-30d-diag")

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
    if len(os.getenv("JWT_SECRET_KEY", "").encode("utf-8")) < 32:
        missing.append("JWT_SECRET_KEY (at least 32 UTF-8 bytes)")
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
    # Accept international phone numbers and email addresses; do not assume a
    # single country's numbering plan. Reject control characters and obvious junk.
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in contact):
        raise HTTPException(status_code=400, detail="Enter a valid phone number or email address.")
    is_email = bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", contact))
    phone_digits = sum(ch.isdigit() for ch in contact)
    is_phone = phone_digits >= 7 and bool(re.fullmatch(r"[+()\d .-]+", contact))
    if not (is_email or is_phone):
        raise HTTPException(status_code=400, detail="Enter a valid phone number or email address.")

    with _SESSION_LOCK:
        if req.session_id not in HISTORY or req.session_id not in conversation_manager.sessions:
            raise HTTPException(status_code=410, detail="SESSION_EXPIRED")

    with CUSTOMER_LOCK:
        records = _read_customer_records()
        # Idempotent profile creation for registration retries. A retry rotates
        # the guest credential and invalidates any previously issued token.
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
        else:
            record = existing
            record.update({"name": name, "age": req.age, "contact": contact, "city": city,
                           "consent_to_store": True})
        # A retried registration rotates the JWT and revokes the previous JTI.
        guest_token, token_jti_hash, token_expires_at = _issue_guest_jwt(record["customer_id"])
        record.pop("guest_token_hash", None)  # retire legacy opaque credential hash
        record["guest_token_jti_hash"] = token_jti_hash
        record["guest_token_expires_at"] = token_expires_at
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_customer_records(records)
        REGISTERED_CUSTOMER_SESSIONS.add(req.session_id)

    # Reuse the age already collected by the registration form throughout the
    # diagnostic questionnaire. This makes the existing age question resolve
    # as answered without bypassing any other assessment or safety questions.
    with conversation_manager._lock:
        session_state = conversation_manager.sessions.get(req.session_id)
        if session_state is not None:
            session_state.symptom_state.age = record.get("age")

    logger.info("Customer registration saved session=%s", req.session_id[:8])
    return {"status": "REGISTERED", "customer_id": record["customer_id"], "guest_token": guest_token, "token_expires_at": token_expires_at}


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


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_dashboard():
    """Serve a same-origin admin dashboard; token is entered by the admin."""
    return HTMLResponse(content='<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>GutGPT Customer Admin</title><style>\n:root{color-scheme:light dark}body{font:16px system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 16px}h1{margin-bottom:4px}.muted{opacity:.75}form,.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}input,button{font:inherit;padding:10px;border-radius:8px;border:1px solid #888}input{min-width:250px;flex:1}button{cursor:pointer}table{width:100%;border-collapse:collapse;margin-top:16px}th,td{text-align:left;padding:10px;border-bottom:1px solid #8886;overflow-wrap:anywhere}th{position:sticky;top:0;background:Canvas}.status{margin:12px 0}.hidden{display:none}.tablewrap{overflow:auto}@media(max-width:600px){body{margin-top:18px}th,td{padding:7px;font-size:14px}}\n</style></head><body><h1>GutGPT Customer Admin</h1><p class="muted">Sign in with the GUTGPT_ADMIN_TOKEN configured in Render. Customer information is sensitive; do not share this page or downloaded files.</p>\n<form id="login"><label for="token">Admin token</label><input id="token" type="password" autocomplete="current-password" required placeholder="Enter admin token"><button type="submit">Sign in &amp; load records</button></form>\n<div id="panel" class="hidden"><p id="summary" class="status"></p><div class="toolbar"><button id="refresh">Refresh records</button><button id="download">Download JSON</button><button id="logout">Sign out</button></div><div class="tablewrap"><table><thead><tr><th>Name</th><th>Age</th><th>Contact</th><th>City</th><th>Created at (UTC)</th><th>Session ID</th></tr></thead><tbody id="rows"></tbody></table></div></div>\n<p id="status" class="status" role="status" aria-live="polite"></p>\n<script>\n(()=>{let token=\'\';const $=id=>document.getElementById(id);const status=m=>{$(\'status\').textContent=m};\nasync function api(path){const r=await fetch(path,{headers:{Authorization:\'Bearer \'+token},cache:\'no-store\'});if(!r.ok){let msg=\'Request failed (\'+r.status+\')\';try{const j=await r.json();if(j.detail)msg=j.detail}catch{}throw Error(msg)}return r}\nfunction cell(tr,value){const td=document.createElement(\'td\');td.textContent=value==null?\'\':String(value);tr.appendChild(td)}\nasync function load(){status(\'Loading customer records…\');try{const r=await api(\'/api/admin/customers\');const data=await r.json();$(\'rows\').replaceChildren();for(const c of data.customers||[]){const tr=document.createElement(\'tr\');cell(tr,c.name);cell(tr,c.age);cell(tr,c.contact);cell(tr,c.city);cell(tr,c.created_at);cell(tr,c.session_id);$(\'rows\').appendChild(tr)}$(\'summary\').textContent=(data.count??(data.customers||[]).length)+\' customer record(s)\';$(\'panel\').classList.remove(\'hidden\');status(\'Records loaded.\')}catch(e){$(\'panel\').classList.add(\'hidden\');status(e.message);if(/token|unauthorized|admin access/i.test(e.message))$(\'token\').focus()}}\n$(\'login\').addEventListener(\'submit\',async e=>{e.preventDefault();token=$(\'token\').value.trim();if(!token){status(\'Enter the admin token.\');return}await load()});$(\'refresh\').addEventListener(\'click\',load);$(\'logout\').addEventListener(\'click\',()=>{token=\'\';$(\'token\').value=\'\';$(\'rows\').replaceChildren();$(\'panel\').classList.add(\'hidden\');status(\'Signed out.\');$(\'token\').focus()});$(\'download\').addEventListener(\'click\',async()=>{try{status(\'Preparing download…\');const r=await api(\'/api/admin/customers/download\');const blob=await r.blob();const url=URL.createObjectURL(blob);const a=document.createElement(\'a\');a.href=url;a.download=\'customer_data.json\';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);status(\'JSON download started.\')}catch(e){status(e.message)}});\n})();</script></body></html>')


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


@app.post("/api/customer/restore")
def restore_customer(req: CustomerRestoreRequest):
    """Restore a profile using a signed 30-day JWT, with one-time legacy upgrade."""
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

        # Upgrade legacy opaque credentials on first successful restoration.
        rotated_token = None
        if claims is None:
            rotated_token, new_jti_hash, new_expiry = _issue_guest_jwt(record["customer_id"])
            record.pop("guest_token_hash", None)
            record["guest_token_jti_hash"] = new_jti_hash
            record["guest_token_expires_at"] = new_expiry
            record["updated_at"] = now.isoformat()
            _write_customer_records(records)

        REGISTERED_CUSTOMER_SESSIONS.add(req.session_id)
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
