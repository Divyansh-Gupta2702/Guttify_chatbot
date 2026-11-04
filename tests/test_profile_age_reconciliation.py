"""Regression tests for authoritative profile-age restoration."""
import pytest

from app import _reconcile_restored_profile_age, _validated_customer_age
from intent_parser import SymptomState


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (28, 28),
        ("28", 28),
        (1, 1),
        (120, 120),
        (None, None),
        (0, None),
        (-1, None),
        (121, None),
        ("", None),
        ("unknown", None),
        (28.0, 28),
        (28.5, None),
        ("28.5", None),
        (True, None),
    ],
)
def test_validated_customer_age(value, expected):
    assert _validated_customer_age(value) == expected


def test_valid_profile_age_overrides_null_checkpoint_age():
    state = SymptomState(age=None)
    _reconcile_restored_profile_age(state, 28)
    assert state.age == 28


def test_valid_profile_age_overrides_stale_checkpoint_age():
    state = SymptomState(age=34)
    _reconcile_restored_profile_age(state, 28)
    assert state.age == 28


def test_invalid_profile_age_preserves_valid_assessment_snapshot():
    state = SymptomState(age=34)
    _reconcile_restored_profile_age(state, 0)
    assert state.age == 34


def test_no_valid_age_remains_missing():
    state = SymptomState(age=None)
    _reconcile_restored_profile_age(state, None)
    assert state.age is None


def test_new_assessment_initialization_carries_profile_age_into_fresh_session():
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / "app.py"
    text = source.read_text(encoding="utf-8")
    assert 'profile_age = _validated_customer_age(record.get("age"))' in text
    assert 'active_new_state.symptom_state.age = profile_age' in text
    assert 'initial_checkpoint = {' in text


def test_registration_and_customer_restore_validate_profile_age_before_questionnaire():
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / "app.py"
    text = source.read_text(encoding="utf-8")
    assert 'session_state.symptom_state.age = _validated_customer_age(record.get("age"))' in text
    assert 'state.symptom_state.age = _validated_customer_age(record.get("age"))' in text



def test_profile_age_persistence_updates_only_bound_customer(monkeypatch):
    import app

    class FakeCursor:
        rowcount = 1

        def __init__(self):
            self.query = None
            self.params = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params):
            self.query = query
            self.params = params

    class FakeConnection:
        def __init__(self):
            self.cursor_instance = FakeCursor()
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return self.cursor_instance

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setitem(app.SESSION_CUSTOMER_IDS, "age-session", "customer-123")
    monkeypatch.setattr(app, "_postgres_connect", lambda: connection)

    assert app._persist_customer_profile_age("age-session", 29) is True
    assert "UPDATE customers SET age=%s" in connection.cursor_instance.query
    assert connection.cursor_instance.params == (29, "customer-123")
    assert connection.closed is True


def test_profile_age_persistence_rejects_invalid_values(monkeypatch):
    import app

    monkeypatch.setitem(app.SESSION_CUSTOMER_IDS, "age-session-invalid", "customer-123")
    monkeypatch.setattr(app, "_postgres_connect", lambda: (_ for _ in ()).throw(AssertionError("DB must not be called")))
    assert app._persist_customer_profile_age("age-session-invalid", 0) is False
    assert app._persist_customer_profile_age("age-session-invalid", 28.5) is False


def test_age_question_rejects_zero_and_out_of_range_values():
    from question_schema import resolve_against_active_question, question_has_answer
    assert resolve_against_active_question("age", "0")["status"] == "unresolved"
    assert resolve_against_active_question("age", "121")["status"] == "unresolved"
    assert resolve_against_active_question("age", "28")["values"] == {"age": 28}
    assert question_has_answer(SymptomState(age=0), "age") is False
    assert question_has_answer(SymptomState(age=28), "age") is True


def test_age_extractor_does_not_truncate_fractional_age():
    from intent_parser import extract_age
    assert extract_age("I am 28") == 28
    assert extract_age("I am 28.5") is None
    assert extract_age("28.5 years old") is None
