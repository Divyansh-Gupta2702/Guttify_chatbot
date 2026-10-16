import json
import sqlite3

import app as gutgpt_app


def test_completed_assessment_is_stored_with_customer_id(tmp_path, monkeypatch):
    monkeypatch.setattr(gutgpt_app, "CUSTOMER_DATA_FILE", tmp_path / "customers.json")
    monkeypatch.setattr(gutgpt_app, "ASSESSMENT_DB_FILE", tmp_path / "assessments.sqlite3")
    sid = gutgpt_app.new_session()["session_id"]
    try:
        registered = gutgpt_app.register_customer(gutgpt_app.CustomerRegistrationRequest(
            session_id=sid,
            name="Assessment Test",
            age=29,
            contact="+919876543210",
            city="Delhi",
            consent=True,
        ))
        state = gutgpt_app.conversation_manager.sessions[sid].symptom_state
        state.primary_symptom = "bloating"
        state.secondary_symptoms = ["gas"]
        state.duration = "3 days"
        state.stool_form = 2

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

        with sqlite3.connect(tmp_path / "assessments.sqlite3") as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM customer_assessments").fetchall()
        assert len(rows) == 1
        record = dict(rows[0])
        assert record["customer_id"] == registered["customer_id"]
        assert record["session_id"] == sid
        assert record["diagnosis"] == "Functional constipation pattern"
        assert "bloating" in record["symptom_summary"].lower()
        assert json.loads(record["symptom_state_json"])["stool_form"] == 2
        assert json.loads(record["screening_json"])["pattern"] == "Functional constipation pattern"
    finally:
        gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.discard(sid)
        gutgpt_app.HISTORY.pop(sid, None)
        gutgpt_app.HISTORY_LAST_ACCESS.pop(sid, None)
        gutgpt_app.conversation_manager.remove(sid)
