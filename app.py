"""
GutGPT FastAPI backend.

The diagnosis/recommendation business logic remains in the existing Python
modules. This layer handles HTTP, sessions, CORS, LLM invocation, and serves
the single embeddable JavaScript widget.

Run locally:
    uvicorn app:app --reload --host 0.0.0.0 --port 8000
"""
from pathlib import Path
import os
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from guttify_agent import ConversationManager
from guttify_chatbot import generate_response, load_llm

BASE_DIR = Path(__file__).resolve().parent
WIDGET_FILE = BASE_DIR / "gutgpt-widget.js"

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

# The LLM is initialized once when the application starts.
llm = load_llm()


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    reply: str
    status: str
    recommendations: list[dict] = Field(default_factory=list)


@app.get("/", response_model=str)
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
    message = req.message.strip()
    if not message:
        # Pydantic rejects an empty string before reaching here, but keep the
        # guard because whitespace-only input becomes empty after stripping.
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    history = HISTORY.setdefault(req.session_id, [])

    result = conversation_manager.handle_message(req.session_id, message)
    status = result["status"]

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
        reply = generate_response(
            llm, message, history, None, result.get("screening")
        )

    elif status == "PRODUCT_INFO_FOUND":
        # Product-information questions are intentionally isolated from prior
        # clinical screening, preserving the existing behavior.
        reply = generate_response(
            llm,
            message,
            history,
            result["product"],
            None,
            mode="PRODUCT_INFO",
        )

    elif status in ("RECOMMENDATION_FOUND", "AMBIGUOUS"):
        products = result.get("recommendations") or []
        reply = generate_response(
            llm,
            message,
            history,
            products,
            result.get("screening"),
        )

    else:
        reply = "Sorry, something went wrong. Could you rephrase that?"

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})

    return ChatResponse(
        reply=reply,
        status=status,
        recommendations=result.get("recommendations") or [],
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
