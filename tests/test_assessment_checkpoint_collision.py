"""Focused regression for checkpoint IDs accidentally reused across customers."""

import app
from guttify_agent import SessionState


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.result = None
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        if "SELECT customer_id FROM customer_assessments" in sql:
            self.result = {"customer_id": "owner-customer"}
        elif "SELECT status FROM customer_assessments" in sql:
            self.result = {"status": "active"}
        elif "SELECT COALESCE(MAX(sequence_no)" in sql:
            self.result = {"max_seq": 0}
        else:
            self.result = None

    def fetchone(self):
        result, self.result = self.result, None
        return result


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.fake_cursor

    def close(self):
        self.closed = True


def test_checkpoint_replaces_an_assessment_id_owned_by_another_customer(monkeypatch):
    session_id = "checkpoint-id-collision"
    old_assessment_id = "foreign-assessment-id"
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    monkeypatch.setattr(app, "_postgres_connect", lambda: connection)
    monkeypatch.setattr(app, "SESSION_CUSTOMER_IDS", {session_id: "new-customer"})
    monkeypatch.setattr(app, "SESSION_ASSESSMENT_IDS", {session_id: old_assessment_id})
    monkeypatch.setattr(app, "HISTORY", {session_id: []})
    monkeypatch.setattr(app.conversation_manager, "sessions", {session_id: SessionState()})

    app._persist_assessment_checkpoint(session_id)

    new_assessment_id = app.SESSION_ASSESSMENT_IDS[session_id]
    assert new_assessment_id != old_assessment_id
    inserted = [
        params[0] for sql, params in cursor.statements
        if "INSERT INTO customer_assessments" in sql
    ]
    assert inserted == [new_assessment_id]
    assert connection.closed
