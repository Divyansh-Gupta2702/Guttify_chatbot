import json

import pytest
from fastapi import HTTPException

import app as gutgpt_app


def make_session():
    return gutgpt_app.new_session()["session_id"]


def test_customer_registration_persists_json_and_is_idempotent(tmp_path, monkeypatch):
    data_file = tmp_path / "customer_data.json"
    monkeypatch.setattr(gutgpt_app, "CUSTOMER_DATA_FILE", data_file)
    session_id = make_session()
    payload = gutgpt_app.CustomerRegistrationRequest(
        session_id=session_id,
        name="  Test   Customer ",
        age=29,
        contact="test@example.com",
        city=" New Delhi ",
        consent=True,
    )

    first = gutgpt_app.register_customer(payload)
    second = gutgpt_app.register_customer(payload)
    records = json.loads(data_file.read_text(encoding="utf-8"))

    assert first["status"] == "REGISTERED"
    assert second["customer_id"] == first["customer_id"]
    assert len(records) == 1
    assert records[0]["name"] == "Test Customer"
    assert records[0]["age"] == 29
    assert records[0]["contact"] == "test@example.com"
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
            contact="test@example.com", city="Delhi", consent=False,
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


def test_returning_customer_restore_is_disabled_until_secure_auth_exists():
    """Do not regress to the prior insecure customer-ID-only restore behavior."""
    with pytest.raises(HTTPException) as error:
        gutgpt_app.restore_customer(gutgpt_app.CustomerRestoreRequest(
            session_id="fresh-session", customer_id="known-customer-id"
        ))
    assert error.value.status_code == 501



def test_customer_restore_rejects_customer_id_as_identity():
    """Customer IDs are identifiers, not credentials; legacy recovery must fail closed."""
    with pytest.raises(HTTPException) as error:
        gutgpt_app.restore_customer(gutgpt_app.CustomerRestoreRequest(
            session_id="any-session", customer_id="known-customer-id"
        ))
    assert error.value.status_code == 501
    assert "SECURE_CUSTOMER_RECOVERY_NOT_CONFIGURED" in error.value.detail


def test_registration_rejects_invalid_contact_format(tmp_path, monkeypatch):
    monkeypatch.setattr(gutgpt_app, "CUSTOMER_DATA_FILE", tmp_path / "customer_data.json")
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
