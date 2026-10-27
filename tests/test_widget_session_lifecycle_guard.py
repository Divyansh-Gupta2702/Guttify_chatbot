"""Regression checks for the Shopify widget's refresh-safe session lifecycle.

These source-contract tests complement browser/API integration tests. They verify
that initialization validates a stored session before requesting a replacement.
"""
from pathlib import Path

WIDGET = Path(__file__).resolve().parents[1] / "gutgpt-widget.js"


def _source():
    return WIDGET.read_text(encoding="utf-8")


def test_session_id_is_persisted_in_tab_storage():
    source = _source()
    assert 'const SESSION_ID_STORAGE_KEY = "gutgpt_session_id_v1"' in source
    assert "window.sessionStorage.getItem(SESSION_ID_STORAGE_KEY)" in source
    assert "window.sessionStorage.setItem(SESSION_ID_STORAGE_KEY, value)" in source


def test_existing_session_restore_precedes_new_session_creation():
    source = _source()
    init = source[source.index("async function _initSession()"):source.index("function initSession()")]
    assert init.index("const existingSessionId = getStoredSessionId()") < init.index('fetchJson("/api/session"')
    assert init.index("restored = await restoreForSession(sessionId)") < init.index('fetchJson("/api/session"')


def test_only_authoritative_expiry_allows_session_replacement():
    source = _source()
    init = source[source.index("async function _initSession()"):source.index("function initSession()")]
    assert 'restoreError?.status === 410' in init
    assert "Network errors, rate limits, server errors and DB failures are not" in init
    assert "throw restoreError;" in init


def test_initialization_calls_share_one_in_flight_operation():
    source = _source()
    init = source[source.index("function initSession()"):source.index("const contactInput")]
    assert "if (initSessionPromise) return initSessionPromise" in init
    assert "_initSession().finally(() => { initSessionPromise = null; })" in init


def test_session_restore_keeps_existing_authentication_contract():
    source = _source()
    assert 'fetchJson("/api/customer/restore"' in source
    assert "clearLegacyGuestToken();" in source
    assert 'restoreError?.status === 401' in source
    assert 'fetchJson("/api/customer/resume"' in source


def test_no_refresh_cooldown_or_groq_call_added_to_initialization():
    source = _source()
    init = source[source.index("async function _initSession()"):source.index("function initSession()")]
    assert "Groq" not in init
    assert "cooldown" not in init.lower()
