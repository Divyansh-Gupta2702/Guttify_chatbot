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
