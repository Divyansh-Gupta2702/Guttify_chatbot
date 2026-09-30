"""
Guttify Web App
----------------
Thin FastAPI layer over the chatbot logic. No product-decision logic lives
here — that's entirely in guttify_agent / recommendation_engine. This file
only handles HTTP, sessions, and serving the static frontend.

Run with:
    uvicorn app:app --reload
"""
import uuid
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from guttify_agent import ConversationManager
from guttify_chatbot import generate_response, load_llm

app = FastAPI(title="GutGPT")

# CORS: allows the local Shopify/frontend development server to call
# the Render-hosted FastAPI backend.
allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Per-session conversation history + structured symptom state, held in
# process memory. Resets whenever the server restarts, and a session
# disappears once the client stops using it — no persistence to disk or a
# database here by design.
# NOTE: single-process only. If you deploy with multiple workers, either
# pin sessions to a worker (sticky sessions) or move this to something
# shared like Redis.
HISTORY: dict[str, list[dict]] = {}
conversation_manager = ConversationManager()

llm = load_llm()


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    status: str



@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/api/session")
def new_session():
    """Called once when the page loads to get a fresh session id."""
    session_id = str(uuid.uuid4())
    HISTORY[session_id] = []
    conversation_manager.reset(session_id)
    return {"session_id": session_id}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    # If the client sends a session_id we haven't seen (server restarted,
    # or the id was never registered), just start tracking it fresh.
    history = HISTORY.setdefault(req.session_id, [])

    result = conversation_manager.handle_message(req.session_id, req.message)
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
        reply = generate_response(llm, req.message, history, None, result.get("screening"))

    elif status == "PRODUCT_INFO_FOUND":
        # Product-information questions are a separate conversation mode.
        # Never send the previous clinical screening/diagnosis to the LLM,
        # otherwise it can repeat the old diagnosis alongside the answer.
        reply = generate_response(
            llm,
            req.message,
            history,
            result["product"],
            None,
            mode="PRODUCT_INFO",
        )

    elif status in ("RECOMMENDATION_FOUND", "AMBIGUOUS"):
        # Both a single recommendation and a tied/ambiguous recommendation
        # must go through the assessment response layer. This preserves the
        # clinical screening/diagnosis while allowing all approved tied
        # products to be shown together.
        products = result.get("recommendations") or []
        reply = generate_response(
            llm,
            req.message,
            history,
            products,
            result.get("screening"),
        )

    else:
        reply = "Sorry, something went wrong. Could you rephrase that?"

    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})

    return ChatResponse(reply=reply, status=status)

