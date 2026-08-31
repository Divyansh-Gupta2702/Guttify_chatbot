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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from feedback_store import DuplicateFeedbackError, save_feedback
from guttify_agent import ConversationManager
from guttify_chatbot import generate_response, load_llm

app = FastAPI(title="Guttify AI Assistant")
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


class FeedbackRequest(BaseModel):
    session_id: str
    rating: int = Field(ge=1, le=5)


class FeedbackResponse(BaseModel):
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
        "ASK",
        "NO_MATCH",
        "AMBIGUOUS",
        "GREETING",
        "SESSION_ENDED",
    ):
        reply = result["message"]

    elif status == "PRODUCT_INFO_FOUND":
        reply = generate_response(llm, req.message, history, result["product"])

    elif status == "RECOMMENDATION_FOUND":
        best_product = result["recommendations"][0]
        reply = generate_response(llm, req.message, history, best_product)

    else:
        reply = "Sorry, something went wrong. Could you rephrase that?"

    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})

    return ChatResponse(reply=reply, status=status)


@app.post("/api/feedback", response_model=FeedbackResponse)
def feedback(req: FeedbackRequest):
    """
    Called by the post-chat rating popup once the conversation has ended.
    Stores exactly one rating per session — a repeat call for a session
    that already submitted one is rejected with 409 rather than silently
    overwriting it, so an accidental double-submit from the UI can't
    corrupt the log.
    """
    try:
        save_feedback(req.session_id, req.rating)
    except DuplicateFeedbackError:
        raise HTTPException(status_code=409, detail="Feedback already submitted for this session.")
    return FeedbackResponse(status="ok")
