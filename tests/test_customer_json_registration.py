import json

import pytest
import jwt
from datetime import datetime, timezone
from fastapi import HTTPException

import app as gutgpt_app


@pytest.fixture(autouse=True)
def configured_test_jwt_secret(monkeypatch):
    # These tests explicitly exercise the JSON backend, regardless of a developer's or CI runner's DATABASE_URL environment variable.
    monkeypatch.setattr(gutgpt_app, "DATABASE_URL", "")
    # Unit tests inject a fake storage adapter; production code has no JSON-file fallback.
    store = []
    monkeypatch.setattr(gutgpt_app, "_read_customer_records", lambda: store)
    monkeypatch.setattr(gutgpt_app, "_write_customer_records", lambda records: store.__setitem__(slice(None), records))
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-that-is-at-least-32-bytes-long")
    monkeypatch.setenv("JWT_ISSUER", "gutgpt-api")
    monkeypatch.setenv("JWT_AUDIENCE", "gutgpt-guest-session")


def make_session():
    return gutgpt_app.new_session()["session_id"]


def test_customer_registration_persists_json_and_is_idempotent(tmp_path, monkeypatch):
    session_id = make_session()
    payload = gutgpt_app.CustomerRegistrationRequest(
        session_id=session_id,
        name="  Test   Customer ",
        age=29,
        contact="919876543210",
        city=" New Delhi ",
        consent=True,
    )

    first = gutgpt_app.register_customer(payload)
    second = gutgpt_app.register_customer(payload)
    records = gutgpt_app._read_customer_records()

    assert first["status"] == "REGISTERED"
    assert second["customer_id"] == first["customer_id"]
    assert len(records) == 1
    assert records[0]["name"] == "Test Customer"
    assert records[0]["age"] == 29
    assert records[0]["contact"] == "919876543210"
    assert records[0]["city"] == "New Delhi"
    assert records[0]["consent_to_store"] is True
    assert records[0]["created_at"]
    # The registration age is also copied into the live diagnostic state, so
    # the questionnaire must not ask the customer for age a second time.
    assert gutgpt_app.conversation_manager.sessions[session_id].symptom_state.age == 29
    gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.discard(session_id)
    gutgpt_app.HISTORY.pop(session_id, None)
    gutgpt_app.HISTORY_LAST_ACCESS.pop(session_id, None)
    gutgpt_app.conversation_manager.remove(session_id)


def test_registration_requires_storage_consent():
    with pytest.raises(HTTPException) as error:
        gutgpt_app.register_customer(gutgpt_app.CustomerRegistrationRequest(
            session_id="not-used", name="Test", age=29,
            contact="919876543210", city="Delhi", consent=False,
        ))
    assert error.value.status_code == 400


def test_chat_is_blocked_until_customer_registration():
    session_id = make_session()
    try:
        with pytest.raises(HTTPException) as error:
            gutgpt_app.chat(gutgpt_app.ChatRequest(session_id=session_id, message="I have bloating"))
        assert error.value.status_code == 403
        assert error.value.detail == "CUSTOMER_REGISTRATION_REQUIRED"
    finally:
        gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.discard(session_id)
        gutgpt_app.HISTORY.pop(session_id, None)
        gutgpt_app.HISTORY_LAST_ACCESS.pop(session_id, None)
        gutgpt_app.conversation_manager.remove(session_id)


def test_returning_customer_restores_with_guest_token_and_fresh_diagnostic_state(tmp_path, monkeypatch):
    first_session = make_session()
    try:
        registered = gutgpt_app.register_customer(gutgpt_app.CustomerRegistrationRequest(
            session_id=first_session, name="Returning Customer", age=34,
            contact="919876543211", city="Delhi", consent=True,
        ))
        assert registered["guest_token"]
        records = gutgpt_app._read_customer_records()
        assert "guest_token_jti_hash" in records[0]
        assert "guest_token_hash" not in records[0]
        assert registered["guest_token"] not in records[0].values()
        claims = jwt.decode(registered["guest_token"], "test-only-secret-that-is-at-least-32-bytes-long", algorithms=["HS256"], issuer="gutgpt-api", audience="gutgpt-guest-session")
        assert claims["typ"] == "guest_access"
        assert claims["sub"] == registered["customer_id"]
        assert claims["exp"] - claims["iat"] == 30 * 24 * 60 * 60

        # A page refresh/new diagnosis creates a new, empty diagnostic session.
        fresh_session = make_session()
        restored = gutgpt_app.restore_customer(gutgpt_app.CustomerRestoreRequest(
            session_id=fresh_session, guest_token=registered["guest_token"]
        ))
        assert restored["status"] == "RESTORED"
        assert restored["customer"]["name"] == "Returning Customer"
        assert fresh_session in gutgpt_app.REGISTERED_CUSTOMER_SESSIONS
        assert gutgpt_app.conversation_manager.sessions[fresh_session].symptom_state.age == 34
        assert gutgpt_app.HISTORY[fresh_session] == []
        gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.discard(fresh_session)
        gutgpt_app.HISTORY.pop(fresh_session, None)
        gutgpt_app.HISTORY_LAST_ACCESS.pop(fresh_session, None)
        gutgpt_app.conversation_manager.remove(fresh_session)
    finally:
        gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.discard(first_session)
        gutgpt_app.HISTORY.pop(first_session, None)
        gutgpt_app.HISTORY_LAST_ACCESS.pop(first_session, None)
        gutgpt_app.conversation_manager.remove(first_session)


def test_customer_restore_rejects_invalid_guest_token(tmp_path, monkeypatch):
    sid = make_session()
    try:
        with pytest.raises(HTTPException) as error:
            gutgpt_app.restore_customer(gutgpt_app.CustomerRestoreRequest(
                session_id=sid, guest_token="x" * 48
            ))
        assert error.value.status_code == 401
    finally:
        gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.discard(sid)
        gutgpt_app.HISTORY.pop(sid, None)
        gutgpt_app.HISTORY_LAST_ACCESS.pop(sid, None)
        gutgpt_app.conversation_manager.remove(sid)


def test_registration_rejects_invalid_contact_format(tmp_path, monkeypatch):
    sid = make_session()
    try:
        req = gutgpt_app.CustomerRegistrationRequest(
            session_id=sid, name="Test Customer", age=29,
            contact="not a phone or email", city="Delhi", consent=True,
        )
        with pytest.raises(HTTPException) as error:
            gutgpt_app.register_customer(req)
        assert error.value.status_code == 400
    finally:
        gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.discard(sid)
        gutgpt_app.HISTORY.pop(sid, None)
        gutgpt_app.HISTORY_LAST_ACCESS.pop(sid, None)
        gutgpt_app.conversation_manager.remove(sid)


def test_guest_jwt_tampering_and_wrong_audience_are_rejected(tmp_path, monkeypatch):
    sid = make_session()
    try:
        registered = gutgpt_app.register_customer(gutgpt_app.CustomerRegistrationRequest(
            session_id=sid, name="JWT Customer", age=31,
            contact="919876543212", city="Delhi", consent=True,
        ))
        token = registered["guest_token"]
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        with pytest.raises(HTTPException) as error:
            gutgpt_app.restore_customer(gutgpt_app.CustomerRestoreRequest(session_id=make_session(), guest_token=tampered))
        assert error.value.status_code == 401

        now = int(datetime.now(timezone.utc).timestamp())
        wrong_audience_token = jwt.encode({
            "sub": registered["customer_id"], "typ": "guest_access",
            "iss": "gutgpt-api", "aud": "wrong-audience",
            "iat": now, "nbf": now,
            "exp": now + 30 * 24 * 60 * 60, "jti": "different-jti",
        }, "test-only-secret-that-is-at-least-32-bytes-long", algorithm="HS256")
        with pytest.raises(HTTPException) as error:
            gutgpt_app.restore_customer(gutgpt_app.CustomerRestoreRequest(session_id=make_session(), guest_token=wrong_audience_token))
        assert error.value.status_code == 401
    finally:
        gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.discard(sid)
        gutgpt_app.HISTORY.pop(sid, None)
        gutgpt_app.HISTORY_LAST_ACCESS.pop(sid, None)
        gutgpt_app.conversation_manager.remove(sid)


def test_registration_rotation_revokes_previous_jwt(tmp_path, monkeypatch):
    sid = make_session()
    try:
        req = gutgpt_app.CustomerRegistrationRequest(
            session_id=sid, name="JWT Customer", age=31,
            contact="919876543212", city="Delhi", consent=True,
        )
        first = gutgpt_app.register_customer(req)
        second = gutgpt_app.register_customer(req)
        fresh_session = make_session()
        with pytest.raises(HTTPException) as error:
            gutgpt_app.restore_customer(gutgpt_app.CustomerRestoreRequest(
                session_id=fresh_session, guest_token=first["guest_token"]
            ))
        assert error.value.status_code == 401
        restored = gutgpt_app.restore_customer(gutgpt_app.CustomerRestoreRequest(
            session_id=fresh_session, guest_token=second["guest_token"]
        ))
        assert restored["status"] == "RESTORED"
    finally:
        for cleanup_sid in list(gutgpt_app.HISTORY):
            if cleanup_sid == sid or cleanup_sid not in gutgpt_app.REGISTERED_CUSTOMER_SESSIONS:
                gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.discard(cleanup_sid)
                gutgpt_app.HISTORY.pop(cleanup_sid, None)
                gutgpt_app.HISTORY_LAST_ACCESS.pop(cleanup_sid, None)
                gutgpt_app.conversation_manager.remove(cleanup_sid)
