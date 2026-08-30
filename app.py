"""
Guttify Web App
----------------
Thin FastAPI layer over the existing chatbot logic (recommendation_engine,
safety_checker, guttify_chatbot). No business logic lives here — this file
only handles HTTP, sessions, and serving the static frontend.

Run with:
    uvicorn app:app --reload
"""
import uuid

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from guttify_chatbot import generate_response, load_llm
from recommendation_engine import recommend_product

app = FastAPI(title="Guttify AI Assistant")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Per-session conversation history, held in process memory. Resets whenever
# the server restarts, and a session disappears once the client stops using
# it — there's no persistence to disk or a database here by design.
# NOTE: single-process only. If you deploy with multiple workers, either
# pin sessions to a worker (sticky sessions) or move this dict to something
# shared like Redis.
SESSIONS: dict[str, list[dict]] = {}

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
    SESSIONS[session_id] = []
    return {"session_id": session_id}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    # If the client sends a session_id we haven't seen (server restarted,
    # or the id was never registered), just start tracking it fresh.
    history = SESSIONS.setdefault(req.session_id, [])

    result = recommend_product(req.message)
    status = result["status"]

    if status in ("GIBBERISH", "NOT_RELEVANT"):
        reply = result["message"]

    elif status == "SAFETY_REVIEW":
        reasons = "\n".join(f"- {r}" for r in result["safety"]["reasons"])
        reply = f"{result['safety']['message']}\n\n{reasons}"

    elif status == "RECOMMENDATION_FOUND":
        best_product = result["recommendations"][0]
        reply = generate_response(llm, req.message, history, best_product)

    else:  # NO_MATCH
        reply = result.get("message", "I couldn't identify a relevant Guttify product from the available product information.")

    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})

    return ChatResponse(reply=reply, status=status)
