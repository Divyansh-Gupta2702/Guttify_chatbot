"""Static regression guards for assessment-resume failure handling.

These checks deliberately do not claim to exercise PostgreSQL or a browser; those
integration tests require the configured application dependencies and a test DB.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_active_assessment_without_checkpoint_is_not_reported_as_no_active():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "LEFT JOIN assessment_state st ON st.assessment_id=a.assessment_id" in source
    assert "ASSESSMENT_CHECKPOINT_UNAVAILABLE" in source
    assert "ASSESSMENT_CHECKPOINT_INVALID" in source


def test_widget_does_not_treat_resume_failure_as_a_fresh_assessment():
    source = (ROOT / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert 'if (resumeFailed || !resume || !["RESUMED", "NO_ACTIVE_ASSESSMENT"].includes(resume.status))' in source
    assert "Your assessment has not been restarted." in source
    assert 'else if (resume.status === "NO_ACTIVE_ASSESSMENT")' in source


def test_resumed_assessment_can_restore_even_if_transcript_is_empty():
    source = (ROOT / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert 'resume.status === "RESUMED" && Array.isArray(resume.messages)' in source


def test_incompatible_active_checkpoint_is_not_reported_as_no_active():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    start = source.index("def _restore_assessment_checkpoint")
    end = source.index("def _persist_completed_assessment", start)
    restore = source[start:end]
    incompatible = restore.index("except (TypeError, ValueError) as exc:")
    branch = restore[incompatible:]
    assert "if active_assessment_found:" in branch
    assert '"status": "ASSESSMENT_CHECKPOINT_INVALID"' in branch
    assert "return None" in branch


def test_new_assessment_initial_checkpoint_is_created_in_same_transaction():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    start = source.index("def create_new_assessment_session")
    end = source.index('@app.post("/api/customer/resume")', start)
    endpoint = source[start:end]
    assessment_insert = endpoint.index("INSERT INTO customer_assessments")
    checkpoint_insert = endpoint.index("INSERT INTO assessment_state")
    transaction_start = endpoint.rfind("with conn, conn.cursor() as cur", 0, assessment_insert)
    transaction_end = endpoint.index("finally:", checkpoint_insert)
    assert transaction_start >= 0
    assert assessment_insert < checkpoint_insert < transaction_end
    assert '"state": asdict(new_state)' in endpoint
    assert '"active": True' in endpoint



def test_resume_reconciles_checkpoint_age_from_customer_profile():
    source = (ROOT / "app.py").read_text()
    start = source.index("def _restore_assessment_checkpoint")
    end = source.index("def _persist_completed_assessment", start)
    restore = source[start:end]
    assert "SELECT age FROM customers WHERE customer_id=%s" in restore
    assert "_reconcile_restored_profile_age(restored_state.symptom_state, profile_age)" in restore


def test_resume_returns_deterministic_pending_question():
    source = (ROOT / "app.py").read_text()
    start = source.index("def _restore_assessment_checkpoint")
    end = source.index("def _persist_completed_assessment", start)
    restore = source[start:end]
    assert 'pending_payload = (' in restore
    assert '"pending_question": pending_payload' in restore


def test_widget_renders_missing_pending_question_after_resume():
    source = (ROOT / "gutgpt-widget.js").read_text()
    assert "const pendingQuestion = resume.pending_question;" in source
    assert "addMessage(pendingQuestion.text, \"bot\")" in source
