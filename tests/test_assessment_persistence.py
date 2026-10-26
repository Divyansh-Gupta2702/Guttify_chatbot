import json

import app as gutgpt_app
import pytest

@pytest.fixture(autouse=True)
def configured_test_jwt_secret(monkeypatch):
    # This test verifies JSON persistence, even when the developer has PostgreSQL configured.
    monkeypatch.setattr(gutgpt_app, "DATABASE_URL", "")
    store = []
    monkeypatch.setattr(gutgpt_app, "_read_customer_records", lambda: store)
    monkeypatch.setattr(gutgpt_app, "_write_customer_records", lambda records: store.__setitem__(slice(None), records))
    monkeypatch.setenv(
        "JWT_SECRET_KEY",
        "test-only-secret-that-is-at-least-32-bytes-long",
    )
    monkeypatch.setenv("JWT_ISSUER", "gutgpt-api")
    monkeypatch.setenv("JWT_AUDIENCE", "gutgpt-guest-session")

def test_completed_assessment_is_saved_on_customer_record(tmp_path, monkeypatch):
    sid = gutgpt_app.new_session()["session_id"]
    try:
        registered = gutgpt_app.register_customer(gutgpt_app.CustomerRegistrationRequest(
            session_id=sid,
            name="Assessment Test",
            age=29,
            contact="919876543210",
            city="Delhi",
            consent=True,
        ))
        state = gutgpt_app.conversation_manager.sessions[sid].symptom_state
        state.primary_symptom = "bloating"
        state.secondary_symptoms = ["gas"]
        state.duration = "3 days"
        state.stool_form = 2
        # Simulate the state after the real question engine has completed the
        # assessment. The production guard must remain enabled and is tested
        # separately for incomplete/ambiguous sessions.
        session = gutgpt_app.conversation_manager.sessions[sid]
        session.diagnosis_complete = True
        session.awaiting_summary_confirmation = False
        monkeypatch.setattr(gutgpt_app, "next_question", lambda _state: None)

        result = {
            "status": "DIAGNOSIS",
            "message": "Assessment completed",
            "recommendations": [],
            "screening": {
                "likely_condition": "Functional constipation pattern",
                "pattern": "Functional constipation pattern",
                "action": "self_care_and_monitor",
                "message": "Assessment completed",
                "evidence": ["Bristol Stool Chart type 2"],
            },
        }
        gutgpt_app._persist_completed_assessment(sid, result)

        rows = gutgpt_app._read_customer_records()
        assert len(rows) == 1
        record = rows[0]
        assert record["customer_id"] == registered["customer_id"]
        assert record["session_id"] == sid
        assert record["likely_assessment"] == "Functional constipation pattern"
        assert "final_symptom_summary" not in record
        assert "symptom_state" not in record
        assert "recommendations" not in record
        assert not (tmp_path / "assessment_data.json").exists()
    finally:
        gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.discard(sid)
        gutgpt_app.HISTORY.pop(sid, None)
        gutgpt_app.HISTORY_LAST_ACCESS.pop(sid, None)
        gutgpt_app.conversation_manager.remove(sid)
