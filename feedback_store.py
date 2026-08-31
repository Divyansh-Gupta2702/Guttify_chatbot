"""
Guttify Feedback Store
-----------------------
Minimal, dependency-free storage for the post-chat rating popup.

The project has no database anywhere else in its stack (product data
itself is a flat `products.json` file, and conversation state lives only
in process memory — see app.py). To match that, feedback is appended as
one JSON object per line to `feedback_log.jsonl` in the project root:
plain-text, human-inspectable, append-only, and trivial to later import
into a real database or spreadsheet if the project grows one.

Each stored record has exactly the fields asked for:
    {"session_id": "...", "rating": 1-5, "timestamp": "<ISO-8601 UTC>"}

A tiny in-memory guard (`_RATED_SESSIONS`) additionally prevents a second
rating from being written for a session that's already submitted one,
mirroring the same "single-process, in-memory bookkeeping" approach the
rest of the app already uses for session/conversation state.
"""
import json
import os
import threading
from datetime import datetime, timezone

FEEDBACK_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feedback_log.jsonl")

_write_lock = threading.Lock()
_RATED_SESSIONS: set[str] = set()


class DuplicateFeedbackError(Exception):
    """Raised when a session tries to submit feedback more than once."""


def has_submitted_feedback(session_id: str) -> bool:
    return session_id in _RATED_SESSIONS


def save_feedback(session_id: str, rating: int) -> dict:
    """Append one feedback record for `session_id`. Raises
    DuplicateFeedbackError if this session already submitted a rating."""
    if session_id in _RATED_SESSIONS:
        raise DuplicateFeedbackError(f"Feedback already recorded for session {session_id!r}")

    record = {
        "session_id": session_id,
        "rating": rating,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with _write_lock:
        # Re-check inside the lock in case of a race between two requests
        # for the same session arriving at nearly the same time.
        if session_id in _RATED_SESSIONS:
            raise DuplicateFeedbackError(f"Feedback already recorded for session {session_id!r}")
        with open(FEEDBACK_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        _RATED_SESSIONS.add(session_id)

    return record
