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

from fastapi import FastAPI
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
from multilingual import normalize_language, translate_to_english, translate_from_english

BASE_DIR = Path(__file__).resolve().parent
WIDGET_FILE = BASE_DIR / "gutgpt-widget.js"
FRONTEND_FILE = BASE_DIR / "index.html"

app = FastAPI(title="GutGPT API", version="1.0.0")

# Shopify storefront origins are supplied as a comma-separated environment
# variable, for example:
# ALLOWED_ORIGINS=https://www.guttify.com,https://guttify.com
allowed_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# Session state is intentionally kept in process memory to preserve the
# existing chatbot behavior. Use one Uvicorn worker unless session state is
# moved to a shared store such as Redis.
HISTORY: dict[str, list[dict]] = {}
conversation_manager = ConversationManager()



class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    language: str = Field(default="en", max_length=20)


class ChatResponse(BaseModel):
    reply: str
    status: str
    recommendations: list[dict] = Field(default_factory=list)


@app.get("/")
def frontend():
    """Serve the basic browser chat frontend at the backend root."""
    if not FRONTEND_FILE.exists():
        from fastapi import HTTPException
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
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="GutGPT widget is not installed.")
    return FileResponse(
        WIDGET_FILE,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.post("/api/session")
def new_session():
    """Create a new conversation session for a visitor."""
    session_id = str(uuid.uuid4())
    HISTORY[session_id] = []
    conversation_manager.reset(session_id)
    return {"session_id": session_id}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Process one user message through the existing GutGPT logic."""
    request_id = uuid.uuid4().hex[:8]
    total_start = time.perf_counter()
    message = req.message.strip()
    language = normalize_language(req.language)
    logger.info(
        "[PERF][%s] REQUEST received session=%s message_len=%d",
        request_id, req.session_id[:8], len(message)
    )
    if not message:
        # Pydantic rejects an empty string before reaching here, but keep the
        # guard because whitespace-only input becomes empty after stripping.
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Translate only at the HTTP boundary. The deterministic engine always
    # receives English, so its existing diagnosis/question logic is unchanged.
    translation_start = time.perf_counter()
    engine_message = translate_to_english(message, language)
    translation_ms = (time.perf_counter() - translation_start) * 1000
    logger.info("[PERF][%s] Input translation language=%s: %.2f ms", request_id, language, translation_ms)

    history_start = time.perf_counter()
    history = HISTORY.setdefault(req.session_id, [])
    history_ms = (time.perf_counter() - history_start) * 1000
    logger.info("[PERF][%s] Session/history lookup: %.2f ms", request_id, history_ms)

    logic_start = time.perf_counter()
    result = conversation_manager.handle_message(req.session_id, engine_message)
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
        reply = _deterministic_product_reply(result["product"], engine_message)

    elif status in ("RECOMMENDATION_FOUND", "AMBIGUOUS"):
        # Preserve the exact rule-engine recommendation. The LLM is not used
        # to rewrite or reinterpret the approved diagnosis/product routing.
        products = result.get("recommendations") or []
        reply = _deterministic_screening_reply(result.get("screening"), products)

    else:
        reply = "Sorry, something went wrong. Could you rephrase that?"

    response_build_ms = (time.perf_counter() - logic_start) * 1000
    logger.info(
        "[PERF][%s] Reply selection/formatting cumulative: %.2f ms",
        request_id, response_build_ms
    )

    history_start = time.perf_counter()
    # Translate the final deterministic response only after the engine has
    # completed. Product names/URLs are preserved by the translation prompt.
    output_translation_start = time.perf_counter()
    reply = translate_from_english(reply, language)
    output_translation_ms = (time.perf_counter() - output_translation_start) * 1000
    logger.info("[PERF][%s] Output translation language=%s: %.2f ms", request_id, language, output_translation_ms)

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
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
