from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_backend_exposes_terminal_assessment_flag_for_urgent_safety_outcomes():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "assessment_complete: bool = False" in source
    assert 'status == "SAFETY_REVIEW"' in source
    assert 'get("action") == "urgent_medical_evaluation"' in source
    assert "assessment_complete=assessment_complete" in source

def test_widget_transitions_session_for_backend_confirmed_terminal_assessment():
    source = (ROOT / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert "data.assessment_complete === true" in source
    assert "await startNextAssessmentSession()" in source
