"""English-only communication regression tests for GutGPT v18.3.

GutGPT now communicates exclusively in English:
- English greetings, symptom descriptions and assessment answers work normally.
- English "yes"/"no" confirmations advance assessments.
- Hindi, Hinglish and other clearly non-English messages (including
  non-English confirmation words such as "haan", "ji", "nahi") receive the
  fixed English-only fallback and are never translated or run through the
  clinical engine, so they can never advance an assessment.
- The multilingual modules (multilingual, language_service) are removed; no
  language detection or translation call exists on the request path.
"""

import app as gutgpt_app
from app import ENGLISH_ONLY_FALLBACK, NON_ENGLISH_STATUS

ENGLISH_FLOW_PREFIX = [
    "I have heartburn and acidity after meals",
    "2 weeks",
    "34",
]


def _no_persistence(monkeypatch):
    """Keep tests hermetic: no real Groq quota or PostgreSQL is consumed here."""
    import nlu_extractor

    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: None)
    monkeypatch.setattr(
        gutgpt_app, "_persist_completed_assessment", lambda session_id, result: None
    )
    monkeypatch.setattr(
        gutgpt_app,
        "_persist_assessment_checkpoint",
        lambda session_id, completed=False, turn_id=None: None,
    )


def _prepare_session(app_module, session_id):
    cm = app_module.conversation_manager
    cm.reset(session_id)
    app_module.HISTORY[session_id] = []
    app_module.REGISTERED_CUSTOMER_SESSIONS.add(session_id)


def _chat(app_module, session_id, message, language="en"):
    return app_module._chat_impl(
        app_module.ChatRequest(
            session_id=session_id, message=message, language=language, message_id=""
        ),
        request=None,
    )


# ---------------------------------------------------------------------------
# Modules removed
# ---------------------------------------------------------------------------
def test_multilingual_modules_are_removed():
    with __import__("pytest").raises(ModuleNotFoundError):
        import multilingual  # noqa: F401
    with __import__("pytest").raises(ModuleNotFoundError):
        import language_service  # noqa: F401


# ---------------------------------------------------------------------------
# Non-English detection
# ---------------------------------------------------------------------------
def test_is_non_english_flags_non_latin_scripts():
    assert gutgpt_app._is_non_english("नमस्ते, मेरा पेट दर्द है") is True  # Devanagari
    assert gutgpt_app._is_non_english("নমস্কার") is True  # Bengali
    assert gutgpt_app._is_non_english("ਸਤ ਸ੍ਰੀ ਅਕਾਲ") is True  # Gurmukhi
    assert gutgpt_app._is_non_english("வணக்கம்") is True  # Tamil


def test_is_non_english_flags_hinglish_sentences_and_answers():
    true_cases = [
        "mujhe pet mein dard hai",
        "mere pet mein dard hai",
        "khana khane ke baad gas hoti hai",
        "pet phool raha hai",
        "mujhe kabz hai",
        "raat ko",
        "subah",
        "do din se",
        "kabhi kabhi",
        "haan", "han", "haa", "ji", "bilkul",
        "nahi", "nahin", "nhi", "nah",
        "haan ji", "bilkul nahi", "nahi hai",
    ]
    for message in true_cases:
        assert gutgpt_app._is_non_english(message) is True, message


def test_is_non_english_keeps_english_messages_english():
    false_cases = [
        "hi", "hi there",
        "I have stomach pain",
        "Yes, sometimes after meals",
        "It started yesterday",
        "yes", "no", "yeah", "nope", "sure",
        "34", "2 weeks", "at night", "after meals",
        "I have acidity",
        "Gas and bloating after meals",
        "Acid Ease",
        "Digest Boost",
        "my stomach pain since yesterday",
        "I feel nausea and vomiting",
        "bright red blood on toilet paper",
        "",
    ]
    for message in false_cases:
        assert gutgpt_app._is_non_english(message) is False, message


# ---------------------------------------------------------------------------
# End-to-end: non-English input gets the English-only fallback
# ---------------------------------------------------------------------------
def test_non_english_opening_message_gets_english_fallback(monkeypatch):
    _no_persistence(monkeypatch)
    _prepare_session(gutgpt_app, "e1")
    resp = _chat(gutgpt_app, "e1", "नमस्ते, मेरा पेट दर्द है")
    assert resp.status == NON_ENGLISH_STATUS
    assert resp.reply == ENGLISH_ONLY_FALLBACK
    assert "नमस्ते" not in resp.reply
    # No clinical state was started by the non-English message.
    assert gutgpt_app.conversation_manager.sessions["e1"].symptom_state.primary_symptom is None


def test_hinglish_opening_message_gets_english_fallback(monkeypatch):
    _no_persistence(monkeypatch)
    _prepare_session(gutgpt_app, "e2")
    resp = _chat(gutgpt_app, "e2", "mujhe acidity hoti hai")
    assert resp.status == NON_ENGLISH_STATUS
    assert resp.reply == ENGLISH_ONLY_FALLBACK


def test_non_english_confirmation_does_not_advance_assessment(monkeypatch):
    _no_persistence(monkeypatch)
    _prepare_session(gutgpt_app, "e3")
    for message in ENGLISH_FLOW_PREFIX:
        _chat(gutgpt_app, "e3", message)
    # Session is now at the reflux yes/no question.
    state = gutgpt_app.conversation_manager.sessions["e3"].symptom_state
    assert state.reflux_present is None

    # A Hinglish "yes" must NOT be treated as an English confirmation.
    resp = _chat(gutgpt_app, "e3", "haan")
    assert resp.status == NON_ENGLISH_STATUS
    assert resp.reply == ENGLISH_ONLY_FALLBACK
    assert (
        gutgpt_app.conversation_manager.sessions["e3"].symptom_state.reflux_present
        is None
    )

    # A Hinglish "no" must not advance either.
    resp = _chat(gutgpt_app, "e3", "nahi")
    assert resp.status == NON_ENGLISH_STATUS
    assert gutgpt_app.conversation_manager.sessions["e3"].symptom_state.reflux_present is None

    # English confirmations still work at the same question.
    resp = _chat(gutgpt_app, "e3", "yes")
    assert resp.status != NON_ENGLISH_STATUS
    assert gutgpt_app.conversation_manager.sessions["e3"].symptom_state.reflux_present is True

    resp = _chat(gutgpt_app, "e3", "no")
    assert resp.status != NON_ENGLISH_STATUS


# ---------------------------------------------------------------------------
# End-to-end: English conversations work exactly as before
# ---------------------------------------------------------------------------
def test_english_greeting_works(monkeypatch):
    _no_persistence(monkeypatch)
    _prepare_session(gutgpt_app, "e4")
    resp = _chat(gutgpt_app, "e4", "hi")
    assert resp.status == "GREETING"
    assert isinstance(resp.reply, str) and resp.reply.strip()


def test_english_symptom_description_starts_assessment(monkeypatch):
    _no_persistence(monkeypatch)
    _prepare_session(gutgpt_app, "e5")
    resp = _chat(gutgpt_app, "e5", "I have stomach pain and bloating after meals")
    assert resp.status != NON_ENGLISH_STATUS
    assert resp.status != "GREETING"


def test_english_confirmation_advances_and_diagnosis_unchanged(monkeypatch):
    _no_persistence(monkeypatch)
    _prepare_session(gutgpt_app, "e6")
    for message in ENGLISH_FLOW_PREFIX + ["yes", "at night", "coffee", "no"]:
        resp = _chat(gutgpt_app, "e6", message)
    assert resp.status == "SUMMARY_REVIEW"

    resp = _chat(gutgpt_app, "e6", "yes")  # confirm the summary
    assert resp.status == "RECOMMENDATION_FOUND"
    assert "Reflux/GERD" in resp.reply
    assert "Acid Ease" in resp.reply
    # The reply is entirely English; no non-English content anywhere.
    assert ENGLISH_ONLY_FALLBACK not in resp.reply


def test_english_reply_never_contains_non_english_content(monkeypatch):
    _no_persistence(monkeypatch)
    _prepare_session(gutgpt_app, "e7")
    resp = _chat(gutgpt_app, "e7", "I have heartburn after meals, it has been 2 weeks, I am 34")
    assert resp.status != NON_ENGLISH_STATUS
    assert all(ord(ch) < 0x0900 or ch > "\u097f" for ch in resp.reply)
